"""Tests for Phase 1: Foundation & Ingestion.

Covers:
- PDF span and bounding box extraction across 3 sample ToS fixtures
- Multi-page span ordering and position validity
- Heading/bold font property detection in spans
- Pasted-text ingestion with single pseudo-page and null bboxes
- SQLite schema initialization and persistence (documents, clauses, findings, analysis_runs)
- FastAPI endpoints (POST /api/documents for file & text, GET /api/documents/{id})
- 'Done when' criterion: uploading a ToS PDF returns ordered, positioned spans
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.db import (
    init_db,
    get_db_connection,
    save_document,
    get_document,
    DocumentRecord,
)
from backend.app.ingest.pdf import extract_spans_from_pdf, is_span_bold
from backend.app.ingest.text import extract_spans_from_text
from backend.app.main import app

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
PDF_FIXTURES = [
    "cloud_service_tos.pdf",
    "streaming_platform_tos.pdf",
    "social_network_tos.pdf",
]


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Use an isolated SQLite test database for each test run."""
    test_db_path = tmp_path / "test_app.db"
    monkeypatch.setenv("DATABASE_URL", str(test_db_path))
    init_db(str(test_db_path))
    yield str(test_db_path)


@pytest.fixture
def client():
    return TestClient(app)


# -----------------------------------------------------------------------------
# 1. PDF Span Extraction Tests (3 ToS Fixtures)
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("pdf_name", PDF_FIXTURES)
def test_pdf_extraction_spans_and_bboxes(pdf_name):
    """Verify each of the 3 ToS PDFs extracts ordered, positioned spans across pages."""
    pdf_path = FIXTURES_DIR / pdf_name
    assert pdf_path.exists(), f"Fixture {pdf_name} must exist"

    doc_data = extract_spans_from_pdf(pdf_path)

    assert doc_data["page_count"] == 2
    assert len(doc_data["spans"]) > 0
    assert doc_data["source_type"] == "pdf"
    assert doc_data["raw_text"] != ""

    spans = doc_data["spans"]

    # Verify pages present in spans
    pages_found = {span["page"] for span in spans}
    assert 1 in pages_found
    assert 2 in pages_found

    # Verify spans are ordered by page and y-coordinate
    for i in range(len(spans) - 1):
        curr = spans[i]
        nxt = spans[i + 1]
        assert curr["page"] <= nxt["page"], "Spans must be ordered by page"
        if curr["page"] == nxt["page"]:
            assert curr["bbox"][1] <= nxt["bbox"][1] + 1.0, "Spans must be in vertical reading order"

    # Verify bounding boxes are non-degenerate
    for span in spans:
        x0, y0, x1, y1 = span["bbox"]
        assert x0 < x1, f"Invalid width in bbox {span['bbox']}"
        assert y0 < y1, f"Invalid height in bbox {span['bbox']}"
        assert span["text"].strip() != ""
        assert span["font_size"] > 0


def test_pdf_extraction_detects_headings_by_font_size():
    """Verify titles/headings have larger font sizes than standard body spans."""
    pdf_path = FIXTURES_DIR / "cloud_service_tos.pdf"
    doc_data = extract_spans_from_pdf(pdf_path)
    spans = doc_data["spans"]

    title_spans = [s for s in spans if "CloudScale Services Terms of Service" in s["text"]]
    assert len(title_spans) > 0
    title_span = title_spans[0]

    body_spans = [s for s in spans if "By accessing or using" in s["text"]]
    assert len(body_spans) > 0
    body_span = body_spans[0]

    assert title_span["font_size"] > body_span["font_size"]
    assert title_span["is_bold"] is True or "Bold" in title_span.get("font_name", "")


def test_pdf_boldness_regression_flags_and_font_name(monkeypatch):
    """Regression test for PyMuPDF span boldness detection:

    Bit 4 (16) is bold. Bit 1 (2) is italic (not bold).
    Fixture spans:
    - flags=16 (bold, not italic) -> is_bold=True
    - flags=2 (italic, not bold)  -> is_bold=False
    - font_name='Helvetica-Bold' (flags=0) -> is_bold=True
    Asserts only the first and third spans have is_bold=True.
    """
    # 1. Direct unit verification on is_span_bold
    assert is_span_bold(flags=16, font_name="Helvetica") is True
    assert is_span_bold(flags=2, font_name="Helvetica-Oblique") is False
    assert is_span_bold(flags=0, font_name="Helvetica-Bold") is True

    # 2. End-to-end span extraction verification through extract_spans_from_pdf
    fixture_dict = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {
                        "spans": [
                            {
                                "text": "Clause 1 (Bold Flag 16)",
                                "bbox": [54.0, 54.0, 200.0, 70.0],
                                "size": 12.0,
                                "font": "Helvetica",
                                "flags": 16,
                            },
                            {
                                "text": "Clause 2 (Italic Flag 2)",
                                "bbox": [54.0, 75.0, 200.0, 90.0],
                                "size": 10.0,
                                "font": "Helvetica-Oblique",
                                "flags": 2,
                            },
                            {
                                "text": "Clause 3 (Font-Named-Bold)",
                                "bbox": [54.0, 95.0, 200.0, 110.0],
                                "size": 12.0,
                                "font": "Helvetica-Bold",
                                "flags": 0,
                            },
                        ]
                    }
                ],
            }
        ]
    }

    class MockPage:
        number = 0
        def get_text(self, opt):
            if opt == "dict":
                return fixture_dict
            return "Clause 1\nClause 2\nClause 3"

    class MockDoc:
        def __len__(self):
            return 1
        def __getitem__(self, idx):
            return MockPage()
        def close(self):
            pass

    monkeypatch.setattr("pymupdf.open", lambda *args, **kwargs: MockDoc())

    doc_data = extract_spans_from_pdf(b"%PDF-mock", filename="mock_spans.pdf")
    spans = doc_data["spans"]

    assert len(spans) == 3
    # Asserting only the first and third are is_bold=True:
    assert spans[0]["is_bold"] is True, "flags=16 must be is_bold=True"
    assert spans[1]["is_bold"] is False, "flags=2 (italic) must be is_bold=False"
    assert spans[2]["is_bold"] is True, "font_name with 'Bold' must be is_bold=True"



# -----------------------------------------------------------------------------
# 2. Pasted-Text Extraction Tests
# -----------------------------------------------------------------------------

def test_pasted_text_extraction():
    """Verify pasted text creates a single pseudo-page without bounding boxes."""
    sample_text = (
        "1. Acceptance of Terms\n\n"
        "By accessing this site you agree to these terms.\n\n"
        "2. Modification\n"
        "We may change these terms without prior notice."
    )

    doc_data = extract_spans_from_text(sample_text, filename="pasted.txt")

    assert doc_data["source_type"] == "text"
    assert doc_data["page_count"] == 1
    assert len(doc_data["spans"]) >= 4

    for span in doc_data["spans"]:
        assert span["page"] == 1
        assert span["bbox"] is None
        assert span["text"] != ""


# -----------------------------------------------------------------------------
# 3. SQLite Database Schema & Persistence Tests
# -----------------------------------------------------------------------------

def test_sqlite_schema_and_persistence(setup_test_db):
    """Verify database schema creation and document persistence with spans."""
    db_path = setup_test_db

    # Check that tables exist
    with get_db_connection(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "documents" in tables
    assert "clauses" in tables
    assert "findings" in tables
    assert "analysis_runs" in tables

    # Insert a document record
    doc_record = DocumentRecord(
        id="doc-test-123",
        filename="test.pdf",
        source_type="pdf",
        sha256="abcdef123456",
        page_count=2,
        raw_text="Sample raw text",
        spans=[
            {
                "text": "1. Section",
                "page": 1,
                "bbox": [54.0, 54.0, 200.0, 70.0],
                "font_size": 12.0,
                "is_bold": True,
            }
        ],
        status="parsed",
    )
    save_document(doc_record, db_path)

    retrieved = get_document("doc-test-123", db_path)
    assert retrieved is not None
    assert retrieved.id == "doc-test-123"
    assert retrieved.filename == "test.pdf"
    assert retrieved.page_count == 2
    assert len(retrieved.spans) == 1
    assert retrieved.spans[0]["text"] == "1. Section"
    assert retrieved.spans[0]["bbox"] == [54.0, 54.0, 200.0, 70.0]


# -----------------------------------------------------------------------------
# 4. FastAPI Endpoints & "Done when" Acceptance Tests
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("pdf_name", PDF_FIXTURES)
def test_done_when_uploading_tos_pdf_returns_ordered_positioned_spans(client, pdf_name):
    """'Done when' acceptance criterion:

    Uploading a ToS PDF returns a document with ordered, positioned spans.
    Verified against all 3 realistic ToS fixtures.
    """
    pdf_path = FIXTURES_DIR / pdf_name
    with open(pdf_path, "rb") as f:
        response = client.post(
            "/api/documents",
            files={"file": (pdf_name, f, "application/pdf")},
        )

    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["filename"] == pdf_name
    assert data["source_type"] == "pdf"
    assert data["page_count"] == 2

    spans = data["spans"]
    assert len(spans) > 0

    # Verify spans are ordered
    for i in range(len(spans) - 1):
        s1 = spans[i]
        s2 = spans[i + 1]
        assert s1["page"] <= s2["page"]
        if s1["page"] == s2["page"]:
            assert s1["bbox"][1] <= s2["bbox"][1] + 1.0

    # Verify spans are positioned
    for s in spans:
        assert s["bbox"] is not None
        assert len(s["bbox"]) == 4
        x0, y0, x1, y1 = s["bbox"]
        assert x0 < x1
        assert y0 < y1
        assert s["page"] in (1, 2)


def test_post_document_pasted_text(client):
    """Test POST /api/documents with pasted text input."""
    payload = {"text": "1. Intro\nWelcome to our terms of service."}
    response = client.post("/api/documents", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["source_type"] == "text"
    assert data["page_count"] == 1
    assert len(data["spans"]) >= 1
    assert data["spans"][0]["bbox"] is None


def test_get_document_by_id(client):
    """Test GET /api/documents/{id} returns full document metadata and spans."""
    pdf_path = FIXTURES_DIR / "streaming_platform_tos.pdf"
    with open(pdf_path, "rb") as f:
        upload_resp = client.post(
            "/api/documents",
            files={"file": ("streaming_platform_tos.pdf", f, "application/pdf")},
        )
    doc_id = upload_resp.json()["id"]

    get_resp = client.get(f"/api/documents/{doc_id}")
    assert get_resp.status_code == 200
    doc_data = get_resp.json()
    assert doc_data["id"] == doc_id
    assert doc_data["filename"] == "streaming_platform_tos.pdf"
    assert len(doc_data["spans"]) > 0
    assert doc_data["status"] == "parsed"


def test_get_document_not_found(client):
    """Test GET /api/documents/{id} returns 404 for non-existent document."""
    resp = client.get("/api/documents/non-existent-id")
    assert resp.status_code == 404


def test_health_check(client):
    """Test GET /api/health."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

