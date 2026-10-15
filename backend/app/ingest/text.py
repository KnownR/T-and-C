"""Pasted-text ingestion and span creation."""

import hashlib
import uuid
from typing import Any


def extract_spans_from_text(
    raw_text: str,
    filename: str = "pasted_text.txt",
) -> dict[str, Any]:
    """Process raw pasted text into a document with a single pseudo-page and null bboxes.

    Returns:
        dict containing:
            - id: generated document UUID
            - filename: display name
            - source_type: 'text'
            - sha256: sha256 hex digest of the string
            - page_count: 1 (pseudo-page)
            - raw_text: unmodified raw text
            - spans: list of spans with page=1, bbox=None
            - status: 'parsed'
    """
    text_bytes = raw_text.encode("utf-8")
    sha256 = hashlib.sha256(text_bytes).hexdigest()
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"

    spans: list[dict[str, Any]] = []
    lines = raw_text.splitlines()

    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        spans.append(
            {
                "text": cleaned,
                "page": 1,
                "bbox": None,
                "font_size": 12.0,
                "font_name": "monospace",
                "is_bold": False,
            }
        )

    # In case there were only empty lines
    if not spans and raw_text.strip():
        spans.append(
            {
                "text": raw_text.strip(),
                "page": 1,
                "bbox": None,
                "font_size": 12.0,
                "font_name": "monospace",
                "is_bold": False,
            }
        )

    return {
        "id": doc_id,
        "filename": filename,
        "source_type": "text",
        "sha256": sha256,
        "page_count": 1,
        "raw_text": raw_text,
        "spans": spans,
        "status": "parsed",
    }
