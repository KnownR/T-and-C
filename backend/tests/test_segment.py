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
    "hard_mode_tos.pdf": [
        {"label": None, "heading": "Preamble"},
        {"label": "Section 1.", "heading": "Account Access and Security"},
        {"label": "2.", "heading": "Service Availability and Modifications"},
        {"label": "Clause 3.2", "heading": "Confidential Information"},
        {"label": "Section 4.", "heading": "Limitation of Liability"},
        {"label": "Appendix A.", "heading": "Service Level Agreement"},
        {"label": "1.", "heading": "Uptime Commitment"},
        {"label": "2.", "heading": "Service Credits"},
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


ALL_BENCHMARK_FIXTURES = [
    ("cloud_service_tos.pdf", 6),
    ("streaming_platform_tos.pdf", 6),
    ("social_network_tos.pdf", 6),
    ("ecommerce_marketplace_tos.pdf", 7),
    ("saas_subscription_tos.pdf", 6),
    ("hard_mode_tos.pdf", 8),
]


# -----------------------------------------------------------------------------
# 4. Boundary Accuracy Evaluation Across Benchmark Documents
# -----------------------------------------------------------------------------

def test_segmentation_boundary_accuracy_benchmark_documents():
    """Evaluate clause boundary precision, recall, and F1 across benchmark documents (including hard mode).

    Prints detailed per-boundary matches and records accuracy for README evals.
    """
    total_ground_truth = 0
    total_predicted = 0
    true_positive_boundaries = 0

    per_doc_metrics = {}

    print("\n=================== CLAUSE BOUNDARY EVALUATION REPORT ===================")

    for pdf_name, expected_count in ALL_BENCHMARK_FIXTURES:
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

        print(f"\nDocument: {pdf_name} (Predicted: {len(clauses)}, Ground Truth: {len(gt_clauses)})")
        doc_tp = 0

        # Check each predicted boundary against ground truth
        max_len = max(len(clauses), len(gt_clauses))
        for i in range(max_len):
            pred = clauses[i] if i < len(clauses) else None
            gt = gt_clauses[i] if i < len(gt_clauses) else None

            if pred and gt:
                label_match = pred.label == gt["label"]
                heading_match = (pred.heading or "").strip().lower() == (gt["heading"] or "").strip().lower()
                matched = label_match and heading_match
                if matched:
                    doc_tp += 1
                    status = "[MATCH]"
                else:
                    status = "[MISMATCH]"
                print(f"  Boundary {i+1} {status}:")
                print(f"    Expected : label={gt['label']!r}, heading={gt['heading']!r}")
                print(f"    Predicted: label={pred.label!r}, heading={pred.heading!r}")
            elif pred and not gt:
                print(f"  Boundary {i+1} [FALSE POSITIVE]: Predicted extra clause {pred.id} ({pred.label} {pred.heading})")
            elif gt and not pred:
                print(f"  Boundary {i+1} [FALSE NEGATIVE]: Missed expected clause ({gt['label']} {gt['heading']})")

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

    print("\n--- Summary per Document ---")
    for doc, metrics in per_doc_metrics.items():
        print(f"  {doc:32s}: Precision={metrics['precision']:.2%}, Recall={metrics['recall']:.2%}, F1={metrics['f1']:.2%}")
    print(f"\nOverall Boundary Precision : {overall_precision:.2%}")
    print(f"Overall Boundary Recall    : {overall_recall:.2%}")
    print(f"Overall Boundary F1 Score  : {overall_f1:.2%} ({true_positive_boundaries}/{total_ground_truth} boundaries matched)")
    print("========================================================================\n")

    assert overall_f1 == 1.0, f"Expected 100% boundary accuracy, got {overall_f1:.2%}"
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


# -----------------------------------------------------------------------------
# 6. Hard-Mode Adversarial Fixture & Deterministic Stability Tests
# -----------------------------------------------------------------------------

def test_hard_mode_adversarial_fixture_properties():
    """Verify all 4 adversarial properties designed to break naive splitters:

    1. Unnumbered preamble before Section 1 becomes its own clause (C-1) without merging into Section 1.
    2. Sub-list (a) ... (b) ... (c) inside Clause 3.2 body is NOT split into separate clauses.
    3. Section 1 containing inline date 'January 1, 2026' and mid-sentence 'Section 4.2' does not split.
    4. Appendix A at the end with its own numbering restarting at 1 (1. Uptime Commitment, 2. Service Credits).
    """
    pdf_path = FIXTURES_DIR / "hard_mode_tos.pdf"
    assert pdf_path.exists(), "hard_mode_tos.pdf fixture must exist"

    doc_data = extract_spans_from_pdf(pdf_path)
    clauses = split_document_into_clauses(
        spans=doc_data["spans"],
        raw_text=doc_data["raw_text"],
        document_id=doc_data["id"],
    )

    # Exactly 8 clauses expected
    assert len(clauses) == 8, f"Expected 8 clauses in hard mode, got {len(clauses)}"

    # Property 1: Unnumbered preamble is Clause 1 (C-1) and not merged with Section 1
    c1 = clauses[0]
    assert c1.id == "C-1"
    assert c1.label is None
    assert c1.heading == "Preamble"
    assert "Please read these enterprise terms carefully" in c1.text
    assert "Section 1" not in c1.text

    # Property 3: Section 1 contains inline date & mid-sentence reference without splitting
    c2 = clauses[1]
    assert c2.id == "C-2"
    assert c2.label == "Section 1."
    assert c2.heading == "Account Access and Security"
    assert "effective January 1" in c2.text
    assert "2026" in c2.text
    assert "Section 4.2 below" in c2.text



    # Clause 3: 2. Service Availability and Modifications
    c3 = clauses[2]
    assert c3.id == "C-3"
    assert c3.label == "2."
    assert c3.heading == "Service Availability and Modifications"

    # Property 2: Sub-list (a) ... (b) ... (c) is INSIDE Clause 3.2 body and NOT separate clauses
    c4 = clauses[3]
    assert c4.id == "C-4"
    assert c4.label == "Clause 3.2"
    assert c4.heading == "Confidential Information"
    assert "(a) to employees" in c4.text
    assert "with a need to know" in c4.text
    assert "(b) as required by applicable law" in c4.text
    assert "(c) with prior written consent" in c4.text


    # Clause 5: Section 4. Limitation of Liability
    c5 = clauses[4]
    assert c5.id == "C-5"
    assert c5.label == "Section 4."
    assert c5.heading == "Limitation of Liability"

    # Property 4: Appendix A and restarting numbering at 1 (C-6, C-7, C-8)
    c6 = clauses[5]
    assert c6.id == "C-6"
    assert c6.label == "Appendix A."
    assert c6.heading == "Service Level Agreement"

    c7 = clauses[6]
    assert c7.id == "C-7"
    assert c7.label == "1."
    assert c7.heading == "Uptime Commitment"
    assert "Acme guarantees 99.9% uptime" in c7.text

    c8 = clauses[7]
    assert c8.id == "C-8"
    assert c8.label == "2."
    assert c8.heading == "Service Credits"
    assert "entitled to a ten percent credit" in c8.text


def test_clause_id_deterministic_stability():
    """Verify that clause IDs and segmentation boundaries are 100% stable across repeated runs."""
    pdf_path = FIXTURES_DIR / "hard_mode_tos.pdf"
    doc_data = extract_spans_from_pdf(pdf_path)

    run_1 = split_document_into_clauses(doc_data["spans"], doc_data["raw_text"], doc_data["id"])
    run_2 = split_document_into_clauses(doc_data["spans"], doc_data["raw_text"], doc_data["id"])

    assert len(run_1) == len(run_2)

    for c1, c2 in zip(run_1, run_2):
        assert c1.id == c2.id, f"Clause ID mismatch: {c1.id} != {c2.id}"
        assert c1.label == c2.label
        assert c1.heading == c2.heading
        assert c1.text == c2.text
        assert c1.bboxes == c2.bboxes
        assert c1.char_start == c2.char_start
        assert c1.char_end == c2.char_end

