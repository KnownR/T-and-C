"""PDF ingestion and span extraction using PyMuPDF (fitz)."""

import hashlib
import uuid
from pathlib import Path
from typing import Any, Union
import pymupdf


def extract_spans_from_pdf(
    file_or_bytes: Union[str, Path, bytes],
    filename: str = "document.pdf",
) -> dict[str, Any]:
    """Extract ordered, positioned text spans and bounding boxes from a PDF.

    Returns:
        dict containing:
            - id: generated document UUID
            - filename: original filename
            - source_type: 'pdf'
            - sha256: sha256 hex digest of the raw bytes
            - page_count: total pages
            - raw_text: full reconstructed text
            - spans: list of ordered spans with {text, page, bbox, font_size, font_name, is_bold}
            - status: 'parsed'
    """
    if isinstance(file_or_bytes, (str, Path)):
        path = Path(file_or_bytes)
        filename = path.name
        with open(path, "rb") as f:
            pdf_bytes = f.read()
    else:
        pdf_bytes = file_or_bytes

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page_count = len(doc)

    all_spans: list[dict[str, Any]] = []
    page_texts: list[str] = []

    for page_idx in range(page_count):
        page = doc[page_idx]
        page_num = page_idx + 1
        page_dict = page.get_text("dict")
        page_spans: list[dict[str, Any]] = []

        blocks = page_dict.get("blocks", [])
        for block in blocks:
            # Type 0 is text
            if block.get("type") != 0:
                continue

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    clean_text = span_text.strip()
                    if not clean_text:
                        continue

                    raw_bbox = span.get("bbox", [0.0, 0.0, 0.0, 0.0])
                    bbox = [round(float(c), 2) for c in raw_bbox]
                    font_size = round(float(span.get("size", 0.0)), 2)
                    font_name = str(span.get("font", ""))
                    flags = int(span.get("flags", 0))
                    is_bold = bool(flags & 2) or ("bold" in font_name.lower())

                    page_spans.append(
                        {
                            "text": clean_text,
                            "page": page_num,
                            "bbox": bbox,
                            "font_size": font_size,
                            "font_name": font_name,
                            "is_bold": is_bold,
                        }
                    )

        # Sort spans in top-to-bottom reading order (y0, then x0)
        page_spans.sort(key=lambda s: (round(s["bbox"][1], 1), round(s["bbox"][0], 1)))
        all_spans.extend(page_spans)

        # Also get page plain text for raw_text reconstruction
        page_plain = page.get_text("text").strip()
        if page_plain:
            page_texts.append(page_plain)

    doc.close()

    raw_text = "\n\n".join(page_texts) if page_texts else " ".join(s["text"] for s in all_spans)

    return {
        "id": doc_id,
        "filename": filename,
        "source_type": "pdf",
        "sha256": sha256,
        "page_count": page_count,
        "raw_text": raw_text,
        "spans": all_spans,
        "status": "parsed",
    }
