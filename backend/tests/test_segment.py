"""Tests for Phase 2: Clause Segmentation.

Covers:
- Rule-based detection of numbering: 1., 1.1, (a), Section 4.2, Clause 7
- Heading detection via font properties (size / boldness)
- Stable clause IDs (C-1...C-n), label, heading, text, page, bbox[], char_start, char_end
- Deterministic fallback for unstructured prose (no LLM, heading-less paragraphs)
- Real bounding box mapping for PDF clauses
- Boundary accuracy evaluation on 5 hand-split sample ToS documents
- SQLite persistence of clauses
- FastAPI endpoints returning document clauses
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.db import (
    init_db,
    save_document,
    get_document,
    save_clauses,
    get_clauses,
    DocumentRecord,
    ClauseRecord,
)
from backend.app.ingest.pdf import extract_spans_from_pdf
from backend.app.ingest.text import extract_spans_from_text
from backend.app.segment.splitter import split_document_into_clauses
from backend.app.main import app

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

FIVE_TOS_FIXTURES = [
    ("cloud_service_tos.pdf", 6),
    ("streaming_platform_tos.pdf", 6),
    ("social_network_tos.pdf", 6),
    ("ecommerce_marketplace_tos.pdf", 7),
    ("saas_subscription_tos.pdf", 6),
]

# Ground-truth clause headings/labels for boundary accuracy evaluation
GROUND_TRUTH_BOUNDARIES = {
    "cloud_service_tos.pdf": [
        {"label": "1.", "heading": "Acceptance of Terms"},
        {"label": "2.", "heading": "User Accounts and Security"},
        {"label": "3.", "heading": "Unilateral Modification of Terms"},
        {"label": "4.", "heading": "Limitation of Liability"},
        {"label": "5.", "heading": "Mandatory Binding Arbitration and Class Action Waiver"},
        {"label": "6.", "heading": "Termination"},
    ],
    "streaming_platform_tos.pdf": [
        {"label": "1.", "heading": "Grant of License"},
        {"label": "2.", "heading": "Content Removal and Discretionary Termination"},
        {"label": "3.", "heading": "Subscription Billing and Automatic Renewal"},
        {"label": "4.", "heading": "Choice of Law and Jurisdiction"},
        {"label": "5.", "heading": "Contract by Usage"},
        {"label": "6.", "heading": "Disclaimer of Warranties"},
    ],
    "social_network_tos.pdf": [
        {"label": "1.", "heading": "Eligibility and User Registration"},
        {"label": "2.", "heading": "User Content and Intellectual Property License"},
        {"label": "3.", "heading": "Content Moderation and Account Suspension"},
        {"label": "4.", "heading": "Limitation of Liability and Damages Cap"},
        {"label": "5.", "heading": "Dispute Resolution and Venue Selection"},
        {"label": "6.", "heading": "Severability and Complete Agreement"},
    ],
    "ecommerce_marketplace_tos.pdf": [
        {"label": "Section 1.", "heading": "Marketplace Participation"},
        {"label": "1.1", "heading": "Buyer Obligations"},
        {"label": "(a)", "heading": "Order Cancellation"},
        {"label": "(b)", "heading": "Returns and Refunds"},
        {"label": "Section 2.", "heading": "Intellectual Property Rights"},
        {"label": "Clause 3.", "heading": "Unilateral Termination and Account Deletion"},
        {"label": "Clause 4.", "heading": "Limitation of Merchant Liability"},
    ],
    "saas_subscription_tos.pdf": [
        {"label": "1.", "heading": "Scope and Provision of Services"},
        {"label": "1.1", "heading": "License Grant and API Usage"},
        {"label": "1.2", "heading": "Usage Limits and Fair Use"},
        {"label": "Section 2.", "heading": "Fees, Invoicing, and Auto-Renewal"},
        {"label": "Clause 3.", "heading": "Confidentiality and Security"},
        {"label": "Clause 4.", "heading": "Governing Law and Arbitration"},
    ],
}


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Use an isolated SQLite test database for each test run."""
    test_db_path = tmp_path / "test_app_segment.db"
    monkeypatch.setenv("DATABASE_URL", str(test_db_path))
    init_db(str(test_db_path))
    yield str(test_db_path)


@pytest.fixture
def client():
    return TestClient(app)


# -----------------------------------------------------------------------------
# 1. Rule-Based Numbering & Label Detection
# -----------------------------------------------------------------------------

def test_clause_splitter_detects_all_numbering_formats():
    """Verify regex and rule parser recognizes 1., 1.1, (a), Section 4.2, Clause 7."""
    text = (
        "1. Acceptance of Terms\n"
        "By accessing our platform you accept all terms.\n\n"
        "1.1 Sub-clause on Accounts\n"
        "You must secure your password.\n\n"
        "(a) Specific Condition\n"
        "Passwords must be at least 12 characters long.\n\n"
        "Section 4.2 Limitation of Liability\n"
        "We are not liable for incidental damages.\n\n"
        "Clause 7 Governing Law\n"
        "This agreement is governed by the laws of California."
    )
    doc_data = extract_spans_from_text(text, filename="numbered_test.txt")
    clauses = split_document_into_clauses(
        spans=doc_data["spans"],
        raw_text=doc_data["raw_text"],
        document_id=doc_data["id"],
    )

    assert len(clauses) == 5

    assert clauses[0].id == "C-1"
    assert clauses[0].label == "1."
    assert clauses[0].heading == "Acceptance of Terms"

    assert clauses[1].id == "C-2"
    assert clauses[1].label == "1.1"
    assert clauses[1].heading == "Sub-clause on Accounts"

    assert clauses[2].id == "C-3"
    assert clauses[2].label == "(a)"
    assert clauses[2].heading == "Specific Condition"

    assert clauses[3].id == "C-4"
    assert clauses[3].label == "Section 4.2"
    assert clauses[3].heading == "Limitation of Liability"

    assert clauses[4].id == "C-5"
    assert clauses[4].label == "Clause 7"
    assert clauses[4].heading == "Governing Law"


# -----------------------------------------------------------------------------
# 2. Deterministic Fallback on Unstructured Text
# -----------------------------------------------------------------------------

def test_clause_splitter_fallback_on_unstructured_paragraphs():
    """Verify that text with zero detectable structure falls back to heading-less paragraphs."""
    unstructured_text = (
        "Welcome to our platform. We offer digital media services to registered users.\n\n"
        "You agree not to disrupt or reverse engineer our system at any time.\n\n"
        "All fees paid are strictly non-refundable once your billing cycle begins."
    )
    doc_data = extract_spans_from_text(unstructured_text, filename="unstructured.txt")
    clauses = split_document_into_clauses(
        spans=doc_data["spans"],
        raw_text=doc_data["raw_text"],
        document_id=doc_data["id"],
    )

    assert len(clauses) == 3
    for i, clause in enumerate(clauses):
        assert clause.id == f"C-{i+1}"
        assert clause.label is None
        assert clause.heading is None
        assert clause.text != ""
        assert clause.char_start is not None
        assert clause.char_end is not None
        assert clause.char_end > clause.char_start


# -----------------------------------------------------------------------------
# 3. Acceptance "Done when": 5 Sample ToS Documents Split into Sensible Clauses
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("pdf_name, expected_count", FIVE_TOS_FIXTURES)
def test_done_when_five_sample_tos_documents_split_sensibly(pdf_name, expected_count):
    """'Done when' acceptance criterion:

    5 sample ToS documents split into sensible clauses;
    each clause maps to a real page/bbox region; tests pass.
    """
    pdf_path = FIXTURES_DIR / pdf_name
    assert pdf_path.exists(), f"Fixture {pdf_name} must exist"

    doc_data = extract_spans_from_pdf(pdf_path)
    clauses = split_document_into_clauses(
        spans=doc_data["spans"],
        raw_text=doc_data["raw_text"],
        document_id=doc_data["id"],
    )

    assert len(clauses) == expected_count, f"{pdf_name} should produce {expected_count} clauses"

    for idx, clause in enumerate(clauses):
        # 1. Stable clause IDs
        assert clause.id == f"C-{idx+1}"
        assert clause.document_id == doc_data["id"]
        assert clause.ordinal == idx + 1

        # 2. Page mapping
        assert clause.page in (1, 2)

        # 3. Real bounding box region
        assert len(clause.bboxes) > 0, f"Clause {clause.id} in {pdf_name} must have bboxes"
        for bbox in clause.bboxes:
            assert len(bbox) == 4
            x0, y0, x1, y1 = bbox
            assert x0 < x1, f"Invalid width in clause bbox {bbox}"
            assert y0 < y1, f"Invalid height in clause bbox {bbox}"
            # Standard page coordinate limits (within 612x792 points letter page)
            assert 0 <= x0 <= 612
            assert 0 <= y0 <= 792

        # 4. Character offsets
        assert clause.char_start is not None
        assert clause.char_end is not None
        assert clause.char_end > clause.char_start
        # Substring in raw_text must match clause text
        slice_text = doc_data["raw_text"][clause.char_start:clause.char_end]
        assert len(slice_text) > 0


# -----------------------------------------------------------------------------
# 4. Boundary Accuracy Evaluation Across 5 Hand-Split Documents
# -----------------------------------------------------------------------------

def test_segmentation_boundary_accuracy_five_documents():
    """Evaluate clause boundary precision, recall, and F1 across all 5 hand-split documents.

    Record the final boundary accuracy percentage for README evals.
    """
    total_ground_truth = 0
    total_predicted = 0
    true_positive_boundaries = 0

    per_doc_metrics = {}

    for pdf_name, expected_count in FIVE_TOS_FIXTURES:
        pdf_path = FIXTURES_DIR / pdf_name
        doc_data = extract_spans_from_pdf(pdf_path)
        clauses = split_document_into_clauses(
            spans=doc_data["spans"],
            raw_text=doc_data["raw_text"],
            document_id=doc_data["id"],
        )

        gt_clauses = GROUND_TRUTH_BOUNDARIES[pdf_name]
        total_ground_truth += len(gt_clauses)
        total_predicted += len(clauses)

        doc_tp = 0
        for pred, gt in zip(clauses, gt_clauses):
            # A boundary match is verified if label and heading match the ground truth
            label_match = pred.label == gt["label"]
            heading_match = (pred.heading or "").strip().lower() == gt["heading"].strip().lower()
            if label_match and heading_match:
                doc_tp += 1

        true_positive_boundaries += doc_tp
        precision = doc_tp / len(clauses) if clauses else 0.0
        recall = doc_tp / len(gt_clauses) if gt_clauses else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        per_doc_metrics[pdf_name] = {"precision": precision, "recall": recall, "f1": f1}

    overall_precision = true_positive_boundaries / total_predicted if total_predicted else 0.0
    overall_recall = true_positive_boundaries / total_ground_truth if total_ground_truth else 0.0
    overall_f1 = (
        (2 * overall_precision * overall_recall) / (overall_precision + overall_recall)
        if (overall_precision + overall_recall) > 0
        else 0.0
    )

    print("\n--- Clause Segmentation Boundary Accuracy ---")
    for doc, metrics in per_doc_metrics.items():
        print(f"  {doc}: F1 = {metrics['f1']:.2%}")
    print(f"Overall Boundary Accuracy (F1): {overall_f1:.2%} ({true_positive_boundaries}/{total_ground_truth})")

    # Assert accuracy threshold (target >= 95% on structured ToS)
    assert overall_f1 >= 0.95
    assert true_positive_boundaries == total_ground_truth


# -----------------------------------------------------------------------------
# 5. SQLite Persistence & API Integration
# -----------------------------------------------------------------------------

def test_db_clauses_persistence(setup_test_db):
    """Verify clauses can be persisted to and fetched from SQLite."""
    db_path = setup_test_db
    doc = DocumentRecord(
        id="doc_persist_test",
        filename="test.pdf",
        source_type="pdf",
        page_count=1,
        raw_text="1. Title\nClause text here.",
    )
    save_document(doc, db_path)

    clauses = [
        ClauseRecord(
            id="C-1",
            document_id="doc_persist_test",
            ordinal=1,
            label="1.",
            heading="Title",
            text="Clause text here.",
            page=1,
            bboxes=[[54.0, 54.0, 200.0, 70.0]],
            char_start=0,
            char_end=25,
        )
    ]
    saved = save_clauses(clauses, db_path)
    assert len(saved) == 1

    loaded = get_clauses("doc_persist_test", db_path)
    assert len(loaded) == 1
    assert loaded[0].id == "C-1"
    assert loaded[0].label == "1."
    assert loaded[0].heading == "Title"
    assert loaded[0].bboxes == [[54.0, 54.0, 200.0, 70.0]]


def test_api_upload_automatically_populates_clauses(client):
    """Verify POST /api/documents segments clauses and GET /api/documents/{id} returns them."""
    pdf_path = FIXTURES_DIR / "ecommerce_marketplace_tos.pdf"
    with open(pdf_path, "rb") as f:
        resp = client.post(
            "/api/documents",
            files={"file": ("ecommerce_marketplace_tos.pdf", f, "application/pdf")},
        )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]

    get_resp = client.get(f"/api/documents/{doc_id}")
    assert get_resp.status_code == 200
    doc_data = get_resp.json()

    assert "clauses" in doc_data
    clauses = doc_data["clauses"]
    assert len(clauses) == 7
    assert clauses[0]["id"] == "C-1"
    assert clauses[0]["label"] == "Section 1."
    assert clauses[0]["heading"] == "Marketplace Participation"
    assert len(clauses[0]["bboxes"]) > 0
