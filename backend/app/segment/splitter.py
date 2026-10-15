"""Rule-based, deterministic clause segmentation for terms of service documents.

Detects:
- Numbering patterns: '1.', '1.1', '(a)', 'Section 4.2', 'Clause 7', 'Article I'
- Section headings via font size / boldness from PyMuPDF span data
- Fallback for unformatted prose: deterministic paragraph splitting (no LLM)
Produces stable ClauseRecord objects with id (C-1...C-n), label, heading, text, page, bbox[], char_start, char_end.
"""

import re
from typing import Any, Optional
from statistics import median
from backend.app.db import ClauseRecord

NUMBERING_PATTERNS = [
    # Section 4.2 / Section 1 / Section IV
    re.compile(r"^(Section\s+[0-9a-zA-Z\.\-]+[:\.]?)(\s+(.*))?$", re.IGNORECASE),
    # Clause 7 / Clause 1.2
    re.compile(r"^(Clause\s+[0-9a-zA-Z\.\-]+[:\.]?)(\s+(.*))?$", re.IGNORECASE),
    # Article I / Article 3
    re.compile(r"^(Article\s+[0-9a-zA-Z\.\-]+[:\.]?)(\s+(.*))?$", re.IGNORECASE),
    # Sub-numbering: 1.1, 1.1.2, 4.2
    re.compile(r"^(\d{1,3}(?:\.\d{1,3})+[\.:]?)(\s+(.*))?$"),
    # Top-level numbered list: 1., 2., 10.
    re.compile(r"^(\d{1,3}\.)(\s+(.*))?$"),
    # Parenthetical letters/numbers: (a), (b), (iv), (1)
    re.compile(r"^(\([0-9a-zA-Z]{1,4}\))(\s+(.*))?$"),
]


def match_numbering_pattern(text: str) -> Optional[tuple[str, Optional[str]]]:
    """Test if text starts with a recognized clause numbering pattern.

    Returns (label, remaining_heading) if matched, or None.
    """
    clean = text.strip()
    for pattern in NUMBERING_PATTERNS:
        match = pattern.match(clean)
        if match:
            label = match.group(1).strip()
            rest = match.group(3).strip() if match.group(3) else None
            return label, rest
    return None


def is_document_title_span(span: dict[str, Any], max_font_size: float, median_font_size: float) -> bool:
    """Check if span on page 1 is the main document title rather than a clause heading."""
    if span.get("page", 1) != 1:
        return False
    font_size = span.get("font_size", 0.0)
    text = span.get("text", "").lower()
    is_prominent = font_size >= max_font_size and font_size > (median_font_size * 1.3)
    title_phrases = ["terms of service", "terms of use", "service agreement", "privacy policy", "agreement"]
    has_title_phrase = any(phrase in text for phrase in title_phrases) and (font_size > median_font_size * 1.2)
    return is_prominent or has_title_phrase


def is_heading_span(span: dict[str, Any], median_font_size: float) -> bool:
    """Detect if a span has styling typical of a section heading."""
    font_size = span.get("font_size", 0.0)
    is_bold = span.get("is_bold", False)
    text = span.get("text", "").strip()

    # Headings are concise, not long paragraphs
    if len(text) > 120 or not text:
        return False

    has_enlarged_font = font_size >= (median_font_size * 1.15)
    return is_bold or has_enlarged_font


def split_document_into_clauses(
    spans: list[dict[str, Any]],
    raw_text: str,
    document_id: str,
) -> list[ClauseRecord]:
    """Deterministically segment a document's spans into clauses with stable IDs.

    Args:
        spans: Ordered list of spans with {text, page, bbox, font_size, is_bold}.
        raw_text: Full reconstructed text of the document.
        document_id: ID of the parent document.

    Returns:
        List of ClauseRecord models with id (C-1...C-n), label, heading, text, page, bboxes, char_start, char_end.
    """
    if not spans:
        return []

    # Calculate font metrics for heading detection
    font_sizes = [s.get("font_size", 10.0) for s in spans if s.get("font_size")]
    median_size = median(font_sizes) if font_sizes else 10.0
    max_size = max(font_sizes) if font_sizes else 10.0

    # Step 1: Scan spans and identify clause boundary indices
    # Each boundary is (span_index, label, heading)
    boundaries: list[tuple[int, Optional[str], Optional[str]]] = []

    for i, span in enumerate(spans):
        text = span.get("text", "").strip()
        if not text:
            continue

        # Skip document title on page 1
        if i == 0 and is_document_title_span(span, max_size, median_size):
            continue

        # Check explicit numbering pattern
        matched = match_numbering_pattern(text)
        if matched:
            label, rest_heading = matched
            # If rest_heading is empty and next span on same line is bold/heading, take it
            heading = rest_heading
            boundaries.append((i, label, heading))
            continue

        # Check unnumbered bold/large font heading
        if is_heading_span(span, median_size):
            # Verify it is not preceded by another span on the same clause line
            boundaries.append((i, None, text))

    # Step 2: Fallback if zero structure detected (pure unstructured prose)
    if not boundaries:
        return _fallback_paragraph_segmentation(spans, raw_text, document_id)

    # Step 3: Group spans between boundaries into clauses
    clauses: list[ClauseRecord] = []
    total_spans = len(spans)

    for b_idx, (start_span_idx, label, heading) in enumerate(boundaries):
        end_span_idx = (
            boundaries[b_idx + 1][0] if b_idx + 1 < len(boundaries) else total_spans
        )

        clause_spans = spans[start_span_idx:end_span_idx]
        if not clause_spans:
            continue

        ordinal = len(clauses) + 1
        clause_id = f"C-{ordinal}"
        clause_page = clause_spans[0].get("page", 1)

        # Collect bboxes
        bboxes = [
            s["bbox"] for s in clause_spans if s.get("bbox") is not None
        ]

        # Assemble clause text
        clause_span_texts = [s.get("text", "").strip() for s in clause_spans if s.get("text", "").strip()]
        full_clause_text = "\n".join(clause_span_texts)

        clauses.append(
            ClauseRecord(
                id=clause_id,
                document_id=document_id,
                ordinal=ordinal,
                label=label,
                heading=heading,
                text=full_clause_text,
                page=clause_page,
                bboxes=bboxes,
                char_start=0,
                char_end=0,
            )
        )

    # Step 4: Deterministically assign char_start and char_end within raw_text
    _assign_character_offsets(clauses, raw_text)

    return clauses


def _fallback_paragraph_segmentation(
    spans: list[dict[str, Any]],
    raw_text: str,
    document_id: str,
) -> list[ClauseRecord]:
    """Fallback segmentation for unstructured text: splits by double newline paragraphs."""
    # Split raw_text into distinct paragraph chunks
    raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw_text) if p.strip()]

    if not raw_paragraphs:
        raw_paragraphs = [s.get("text", "").strip() for s in spans if s.get("text", "").strip()]

    clauses: list[ClauseRecord] = []
    curr_offset = 0

    for i, para in enumerate(raw_paragraphs):
        ordinal = i + 1
        clause_id = f"C-{ordinal}"

        # Find offsets in raw_text
        found_idx = raw_text.find(para, curr_offset)
        if found_idx != -1:
            char_start = found_idx
            char_end = found_idx + len(para)
            curr_offset = char_end
        else:
            char_start = curr_offset
            char_end = curr_offset + len(para)
            curr_offset = char_end

        # Match relevant spans
        clause_spans = [
            s for s in spans if s.get("text", "").strip() in para
        ]
        page = clause_spans[0].get("page", 1) if clause_spans else 1
        bboxes = [s["bbox"] for s in clause_spans if s.get("bbox") is not None]

        clauses.append(
            ClauseRecord(
                id=clause_id,
                document_id=document_id,
                ordinal=ordinal,
                label=None,
                heading=None,
                text=para,
                page=page,
                bboxes=bboxes,
                char_start=char_start,
                char_end=char_end,
            )
        )

    return clauses


def _assign_character_offsets(clauses: list[ClauseRecord], raw_text: str) -> None:
    """Calculate character offsets [char_start, char_end] in raw_text for each clause."""
    curr_search_pos = 0
    total_len = len(raw_text)

    for i, clause in enumerate(clauses):
        # Determine candidate search anchor: first line or heading or first 30 chars
        search_target = clause.text.split("\n")[0].strip()
        if len(search_target) > 50:
            search_target = search_target[:50]

        found_pos = raw_text.find(search_target, curr_search_pos)
        if found_pos != -1:
            char_start = found_pos
        else:
            char_start = curr_search_pos

        # The end of this clause is either the start of the next clause or the end of raw_text
        if i + 1 < len(clauses):
            next_target = clauses[i + 1].text.split("\n")[0].strip()
            if len(next_target) > 50:
                next_target = next_target[:50]
            next_pos = raw_text.find(next_target, char_start + 1)
            if next_pos != -1:
                char_end = next_pos
            else:
                char_end = min(char_start + len(clause.text), total_len)
        else:
            char_end = total_len

        clause.char_start = char_start
        clause.char_end = max(char_start + 1, char_end)
        curr_search_pos = clause.char_end
