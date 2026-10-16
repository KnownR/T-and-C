"""Comprehensive tests for Phase 4: Citation Verifier.

Covers:
- (a) Text normalization: whitespace collapse, curly/straight quotes, en/em dashes, lowercase
- (b) Exact substring match -> verified (match_score=100.0)
- (c) RapidFuzz partial_ratio >= 90 vs cited clause -> verified_fuzzy (stores match_score)
- (c) RapidFuzz near-miss just below 90 -> rejected
- (d) Quote belonging to different clause -> re-anchors to matching clause, updates clause_id
- (e) Fully fabricated quote -> rejected (never stored as finding, never returned in UI)
- (e) Real quote attached to nonexistent clause_id -> rejected without crashing
- Grounding rate calculation and persistence in analysis_runs: verified / proposed
- End-to-end proof: fabricated quote injected into analyze pipeline is rejected and NEVER appears in GET /api/documents/{id}/findings
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.analyze.analyzer import analyze_document
from backend.app.analyze.schemas import Finding
from backend.app.db import (
    ClauseRecord,
    DocumentRecord,
    get_analysis_run,
    get_findings,
    init_db,
    save_clauses,
    save_document,
)
from backend.app.ingest.pdf import extract_spans_from_pdf
from backend.app.main import app
from backend.app.segment.splitter import split_document_into_clauses
from backend.app.verify.normalizer import normalize_text
from backend.app.verify.verifier import verify_finding, verify_findings

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Use an isolated SQLite test database for each test run."""
    test_db_path = tmp_path / "test_app_verify.db"
    monkeypatch.setenv("DATABASE_URL", str(test_db_path))
    init_db(str(test_db_path))
    yield str(test_db_path)


@pytest.fixture
def client():
    return TestClient(app)


# -----------------------------------------------------------------------------
# 1. Normalization Tests
# -----------------------------------------------------------------------------

def test_normalization_whitespace_collapse():
    raw = "  This   is   a \n\n  clause  with \t irregular \r whitespace.   "
    expected = "this is a clause with irregular whitespace."
    assert normalize_text(raw) == expected


def test_normalization_quotes_unification():
    # Single curly quotes, apostrophes, backticks
    raw_single = "‘Single’ and ’Apostrophe’ and `backtick` and ´accent´"
    assert normalize_text(raw_single) == "'single' and 'apostrophe' and 'backtick' and 'accent'"

    # Double curly quotes
    raw_double = "“Double curly quotes” and „German style” and «guillemets»"
    assert '"double curly quotes"' in normalize_text(raw_double)
    assert '"german style"' in normalize_text(raw_double)


def test_normalization_dashes_unification():
    # En-dash, em-dash, minus sign, horizontal bar
    raw_dashes = "Dispute–resolution and liability—limitation and term−exclusion"
    assert normalize_text(raw_dashes) == "dispute-resolution and liability-limitation and term-exclusion"


def test_normalization_case_and_unicode_spaces():
    raw_unicode = "CLOUDSCALE\u00a0SERVICES\u200bTERMS"
    assert normalize_text(raw_unicode) == "cloudscale services terms"


# -----------------------------------------------------------------------------
# 2. Stage-by-Stage Verification Pipeline Tests
# -----------------------------------------------------------------------------

def test_verify_exact_substring_match():
    """Verify that an exact substring in the cited clause returns status 'verified' with match_score 100.0."""
    clause = ClauseRecord(
        id="C-1",
        document_id="doc_1",
        ordinal=1,
        text="By accessing or using the CloudScale Services, you agree to be bound by these Terms of Service.",
    )
    clauses_by_id = {"C-1": clause}

    finding = Finding(
        category="contract_by_using",
        severity="yellow",
        title="Contract Formed by Usage",
        explanation="Accessing service forms contract.",
        clause_id="C-1",
        quote="By accessing or using the CloudScale Services, you agree to be bound",
    )

    res = verify_finding(finding, clauses_by_id)
    assert res.status == "verified"
    assert res.clause_id == "C-1"
    assert res.match_score == 100.0
    assert "Exact substring match" in res.details


def test_verify_whitespace_quote_dash_variants():
    """Verify that quote variations with smart quotes, dashes, or irregular spacing match as 'verified'."""
    clause = ClauseRecord(
        id="C-4",
        document_id="doc_1",
        ordinal=4,
        text='In no event shall CloudScale—its affiliates—be liable for "consequential" damages.',
    )
    clauses_by_id = {"C-4": clause}

    # Quote uses straight hyphens, curly double quotes, different case and extra spacing
    finding = Finding(
        category="limitation_of_liability",
        severity="red",
        title="Liability Cap",
        explanation="Excludes damages.",
        clause_id="C-4",
        quote='IN NO EVENT SHALL CLOUDSCALE - ITS AFFILIATES - BE LIABLE FOR   “CONSEQUENTIAL”   DAMAGES.',
    )

    res = verify_finding(finding, clauses_by_id)
    assert res.status == "verified"
    assert res.clause_id == "C-4"
    assert res.match_score == 100.0


def test_verify_fuzzy_near_miss_above_and_below_threshold():
    """Verify that rapidfuzz partial_ratio >= 90 is verified_fuzzy, but < 90 is rejected."""
    clause = ClauseRecord(
        id="C-5",
        document_id="doc_1",
        ordinal=5,
        text="Dispute shall be settled by confidential arbitration in Wilmington.",
    )
    clauses_by_id = {"C-5": clause}

    # Near miss just ABOVE 90 threshold (minor typo: 'arbitraton' instead of 'arbitration', ratio ~97%)
    finding_above = Finding(
        category="arbitration",
        severity="red",
        title="Arbitration",
        explanation="Test",
        clause_id="C-5",
        quote="Dispute shall be settled by confidential arbitraton in Wilmington.",
    )
    res_above = verify_finding(finding_above, clauses_by_id)
    assert res_above.status == "verified_fuzzy"
    assert res_above.match_score is not None
    assert res_above.match_score >= 90.0

    # Near miss just BELOW 90 threshold (multiple altered words: ratio ~85-89%)
    finding_below = Finding(
        category="arbitration",
        severity="red",
        title="Arbitration",
        explanation="Test",
        clause_id="C-5",
        quote="Disputes will be handled through private arbitraton in Wilmington town.",
    )
    res_below = verify_finding(finding_below, clauses_by_id)
    assert res_below.status == "rejected"
    assert res_below.match_score is not None
    assert res_below.match_score < 90.0


def test_verify_reanchors_quote_belonging_to_different_clause():
    """Verify that a quote that does not match cited clause C-1 but matches C-5 is re-anchored to C-5."""
    clause_1 = ClauseRecord(
        id="C-1",
        document_id="doc_1",
        ordinal=1,
        text="Welcome to the service. Read terms carefully.",
    )
    clause_5 = ClauseRecord(
        id="C-5",
        document_id="doc_1",
        ordinal=5,
        text="Any dispute, controversy, or claim shall be settled exclusively by confidential binding arbitration.",
    )
    clauses_by_id = {"C-1": clause_1, "C-5": clause_5}

    # Finding incorrectly cites C-1 instead of C-5
    misattributed_finding = Finding(
        category="arbitration",
        severity="red",
        title="Arbitration Clause",
        explanation="Disputes go to binding arbitration.",
        clause_id="C-1",  # Wrong clause
        quote="settled exclusively by confidential binding arbitration",
    )

    res = verify_finding(misattributed_finding, clauses_by_id)
    assert res.status == "reanchored"
    assert res.clause_id == "C-5"  # Updated to real clause
    assert res.original_clause_id == "C-1"
    assert res.match_score == 100.0
    assert "Re-anchored from C-1 to C-5" in res.details


def test_verify_fully_fabricated_quote_rejected():
    """Verify that a hallucinated quote not present in any clause is rejected."""
    clause_1 = ClauseRecord(id="C-1", document_id="doc_1", ordinal=1, text="Acceptance of terms.")
    clause_2 = ClauseRecord(id="C-2", document_id="doc_1", ordinal=2, text="User credentials and security.")
    clauses_by_id = {"C-1": clause_1, "C-2": clause_2}

    fabricated_finding = Finding(
        category="unilateral_termination",
        severity="red",
        title="Immediate Termination",
        explanation="Service can terminate immediately.",
        clause_id="C-1",
        quote="The company may terminate user accounts at will without reason or notification.",
    )

    res = verify_finding(fabricated_finding, clauses_by_id)
    assert res.status == "rejected"
    assert res.clause_id == "C-1"


def test_verify_real_quote_attached_to_nonexistent_clause_id_rejected():
    """Verify that a real quote attached to a nonexistent clause_id (e.g. C-999) is rejected and does NOT crash."""
    clause_1 = ClauseRecord(id="C-1", document_id="doc_1", ordinal=1, text="CloudScale reserves the right to modify.")
    clauses_by_id = {"C-1": clause_1}

    finding_nonexistent_clause = Finding(
        category="unilateral_change",
        severity="red",
        title="Unilateral Change",
        explanation="Modification of terms.",
        clause_id="C-999",  # Does NOT exist in document
        quote="CloudScale reserves the right to modify",
    )

    # Must NOT raise KeyError, must return rejected status
    res = verify_finding(finding_nonexistent_clause, clauses_by_id)
    assert res.status == "rejected"
    assert res.clause_id == "C-999"
    assert "does not exist in document" in res.details


# -----------------------------------------------------------------------------
# 3. Grounding Rate Calculation & Batch Verification
# -----------------------------------------------------------------------------

def test_grounding_rate_computation_and_persistence():
    """Verify that grounding_rate = verified / proposed is accurately computed and persisted."""
    clauses = [
        ClauseRecord(id="C-1", document_id="doc_test", ordinal=1, text="You agree to binding arbitration in New York."),
        ClauseRecord(id="C-2", document_id="doc_test", ordinal=2, text="We may modify fees with notice."),
    ]

    proposed_findings = [
        # Finding 1: Exact match in C-1 -> verified
        Finding(
            category="arbitration",
            severity="red",
            title="Arbitration",
            explanation="Test",
            clause_id="C-1",
            quote="binding arbitration in New York",
        ),
        # Finding 2: Re-anchor from C-2 to C-1 -> reanchored (counts as verified)
        Finding(
            category="arbitration",
            severity="red",
            title="Arbitration 2",
            explanation="Test",
            clause_id="C-2",
            quote="agree to binding arbitration",
        ),
        # Finding 3: Fabricated quote -> rejected
        Finding(
            category="unilateral_termination",
            severity="red",
            title="Termination",
            explanation="Test",
            clause_id="C-1",
            quote="Fabricated text that does not exist anywhere in document.",
        ),
        # Finding 4: Attached to nonexistent clause_id -> rejected
        Finding(
            category="unilateral_change",
            severity="red",
            title="Fees",
            explanation="Test",
            clause_id="C-99",
            quote="modify fees",
        ),
    ]

    verified_records, verified_count, rejected_count, grounding_rate = verify_findings(
        findings=proposed_findings,
        clauses=clauses,
        document_id="doc_test",
        analysis_run_id="run_test",
    )

    assert verified_count == 2
    assert rejected_count == 2
    assert len(verified_records) == 2  # Only verified findings returned
    assert grounding_rate == 0.50  # 2 / 4 = 0.50

    # Ensure rejected findings are excluded from verified_records
    for rec in verified_records:
        assert rec.verification_status in ("verified", "verified_fuzzy", "reanchored")
        assert "Fabricated" not in rec.quote


# -----------------------------------------------------------------------------
# 4. End-to-End Proof Test: Fabricated Quotes Never Reach Findings / UI
# -----------------------------------------------------------------------------

def test_e2e_proof_fabricated_quotes_never_stored_nor_in_api(client, monkeypatch):
    """End-to-end proof test:

    Inject a fabricated finding alongside valid findings.
    Assert:
    1. The fabricated finding is rejected by the verification pipeline.
    2. The rejected count is recorded in analysis_runs.
    3. The fabricated finding NEVER appears in the GET /findings response.
    4. Grounding rate correctly reflects the verified vs proposed ratio.
    """
    pdf_path = FIXTURES_DIR / "cloud_service_tos.pdf"
    with open(pdf_path, "rb") as f:
        upload_resp = client.post(
            "/api/documents",
            files={"file": ("cloud_service_tos.pdf", f, "application/pdf")},
        )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    # Mock LiteLLM completion returning 2 real findings + 1 completely fabricated hallucination
    mock_resp = {
        "findings": [
            {
                "category": "arbitration",
                "severity": "red",
                "title": "Mandatory Arbitration",
                "explanation": "Forces arbitration.",
                "clause_id": "C-5",
                "quote": "settled exclusively by confidential binding arbitration in Wilmington",
            },
            {
                "category": "unilateral_change",
                "severity": "red",
                "title": "Unilateral Change",
                "explanation": "Can modify terms.",
                "clause_id": "C-3",
                "quote": "reserves the right to modify, amend, or replace these Terms at any time",
            },
            {
                "category": "unilateral_termination",
                "severity": "red",
                "title": "Hallucinated Finding",
                "explanation": "This finding contains a fabricated quote invented by an LLM.",
                "clause_id": "C-1",
                "quote": "The user forfeits all rights to seek any legal counsel whatsoever under penalty of perjury.",
            },
        ]
    }

    import json
    from unittest.mock import MagicMock

    resp_mock = MagicMock()
    resp_mock.usage.prompt_tokens = 300
    resp_mock.usage.completion_tokens = 120
    resp_mock.choices = [MagicMock(message=MagicMock(content=json.dumps(mock_resp)))]
    monkeypatch.setattr("litellm.completion", lambda *args, **kwargs: resp_mock)

    # Run analysis via API endpoint
    analyze_resp = client.post(f"/api/documents/{doc_id}/analyze?dry_run=false")
    assert analyze_resp.status_code == 200
    data = analyze_resp.json()

    run_data = data["run"]
    findings_data = data["findings"]

    # Assert 3 proposed, 2 verified, 1 rejected
    assert run_data["proposed_count"] == 3
    assert run_data["verified_count"] == 2
    assert run_data["rejected_count"] == 1
    assert run_data["grounding_rate"] == round(2 / 3, 4)

    # Exactly 2 findings returned (the fabricated one was rejected)
    assert len(findings_data) == 2
    for f in findings_data:
        assert "forfeits all rights" not in f["quote"]
        assert f["verification_status"] in ("verified", "verified_fuzzy", "reanchored")

    # Verify GET /api/documents/{id}/findings
    get_resp = client.get(f"/api/documents/{doc_id}/findings")
    assert get_resp.status_code == 200
    stored_findings = get_resp.json()

    assert len(stored_findings) == 2
    stored_quotes = [f["quote"] for f in stored_findings]
    assert not any("forfeits all rights" in q for q in stored_quotes)

    # Verify SQLite analysis_runs table record
    persisted_run = get_analysis_run(run_data["id"])
    assert persisted_run is not None
    assert persisted_run.proposed_count == 3
    assert persisted_run.verified_count == 2
    assert persisted_run.rejected_count == 1
    assert persisted_run.grounding_rate == round(2 / 3, 4)
