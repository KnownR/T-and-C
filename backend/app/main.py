"""FastAPI application for What Did I Agree To."""

from contextlib import asynccontextmanager
from typing import Any, Optional
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.db import (
    ClauseRecord,
    DocumentRecord,
    get_clauses,
    get_document,
    init_db,
    save_clauses,
    save_document,
)
from backend.app.ingest.pdf import extract_spans_from_pdf
from backend.app.ingest.text import extract_spans_from_text
from backend.app.segment.splitter import split_document_into_clauses


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database tables exist on startup
    init_db()
    yield


app = FastAPI(
    title="What Did I Agree To? API",
    description="Local-first Terms of Service analyzer with deterministic verified citations.",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS setup for future frontend UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SpanModel(BaseModel):
    text: str
    page: int
    bbox: Optional[list[float]] = None
    font_size: Optional[float] = None
    font_name: Optional[str] = None
    is_bold: bool = False


class ClauseModel(BaseModel):
    id: str
    document_id: str
    ordinal: int
    label: Optional[str] = None
    heading: Optional[str] = None
    text: str
    page: Optional[int] = 1
    bboxes: list[list[float]] = Field(default_factory=list)
    char_start: Optional[int] = None
    char_end: Optional[int] = None


class DocumentResponse(BaseModel):
    id: str
    filename: Optional[str] = None
    source_type: str
    sha256: Optional[str] = None
    page_count: int
    raw_text: str
    spans: list[SpanModel] = Field(default_factory=list)
    clauses: list[ClauseModel] = Field(default_factory=list)
    status: str
    created_at: str


@app.get("/api/health")
def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": "what-did-i-agree-to",
        "phase": 2,
    }


@app.post(
    "/api/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentResponse,
)
async def create_document(
    request: Request,
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    filename: Optional[str] = Form(None),
) -> DocumentResponse:
    """Upload a document (PDF file or pasted text) for ingestion, span extraction, and clause segmentation."""
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Malformed JSON payload.")
        raw_text = body.get("text", "")
        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="Field 'text' cannot be empty.")
        doc_name = body.get("filename", "pasted_text.txt")
        parsed = extract_spans_from_text(raw_text, filename=doc_name)

    elif file is not None:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        doc_name = file.filename or "uploaded.pdf"
        if doc_name.lower().endswith(".pdf") or file.content_type == "application/pdf":
            parsed = extract_spans_from_pdf(file_bytes, filename=doc_name)
        else:
            decoded_text = file_bytes.decode("utf-8", errors="replace")
            parsed = extract_spans_from_text(decoded_text, filename=doc_name)

    elif text is not None and text.strip():
        parsed = extract_spans_from_text(text, filename=filename or "pasted_text.txt")

    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either a file upload ('file') or text content ('text').",
        )

    # 1. Save document record
    record = DocumentRecord(**parsed)
    saved_doc = save_document(record)

    # 2. Segment document into clauses deterministically
    clauses = split_document_into_clauses(
        spans=record.spans,
        raw_text=record.raw_text,
        document_id=record.id,
    )
    saved_clauses = save_clauses(clauses)

    doc_data = saved_doc.model_dump()
    doc_data["clauses"] = [c.model_dump() for c in saved_clauses]
    return DocumentResponse(**doc_data)


@app.get("/api/documents/{doc_id}", response_model=DocumentResponse)
def get_document_endpoint(doc_id: str) -> DocumentResponse:
    """Retrieve document metadata, extracted spans, and segmented clauses by ID."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document with ID '{doc_id}' not found.",
        )
    clauses = get_clauses(doc_id)
    doc_data = doc.model_dump()
    doc_data["clauses"] = [c.model_dump() for c in clauses]
    return DocumentResponse(**doc_data)


@app.get("/api/documents/{doc_id}/clauses", response_model=list[ClauseModel])
def get_document_clauses_endpoint(doc_id: str) -> list[ClauseModel]:
    """Retrieve only the segmented clauses for a document."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document with ID '{doc_id}' not found.",
        )
    clauses = get_clauses(doc_id)
    return [ClauseModel(**c.model_dump()) for c in clauses]
