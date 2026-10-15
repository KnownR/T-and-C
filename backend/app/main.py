"""FastAPI application for What Did I Agree To."""

from contextlib import asynccontextmanager
from typing import Any, Optional
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.db import (
    DocumentRecord,
    get_document,
    init_db,
    save_document,
)
from backend.app.ingest.pdf import extract_spans_from_pdf
from backend.app.ingest.text import extract_spans_from_text


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database tables exist on startup
    init_db()
    yield


app = FastAPI(
    title="What Did I Agree To? API",
    description="Local-first Terms of Service analyzer with deterministic verified citations.",
    version="0.1.0",
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


class DocumentResponse(BaseModel):
    id: str
    filename: Optional[str] = None
    source_type: str
    sha256: Optional[str] = None
    page_count: int
    raw_text: str
    spans: list[SpanModel] = Field(default_factory=list)
    status: str
    created_at: str


@app.get("/api/health")
def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": "what-did-i-agree-to",
        "phase": 1,
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
    """Upload a document (PDF file or pasted text) for ingestion and span extraction."""
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

    record = DocumentRecord(**parsed)
    saved = save_document(record)
    return DocumentResponse(**saved.model_dump())


@app.get("/api/documents/{doc_id}", response_model=DocumentResponse)
def get_document_endpoint(doc_id: str) -> DocumentResponse:
    """Retrieve document metadata and extracted spans by ID."""
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Document with ID '{doc_id}' not found.",
        )
    return DocumentResponse(**doc.model_dump())
