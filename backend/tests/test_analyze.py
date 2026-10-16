"""Tests for Phase 3: Analysis with Structured Output.

Covers:
- Pydantic schema validation for findings ({category, severity, title, explanation, clause_id, quote})
- Lens YAML loading and prompt construction (dynamic rubric, <document> untrusted tags, verbatim quote rules)
- Single-retry recovery on schema validation failure
- Failure recording in analysis_runs when retry fails (no infinite retries)
- Deduplication of findings by (category, clause_id)
- Dry-run mock analysis mode on sample ToS documents without API cost
- Acceptance 'Done when': running analysis returns typed findings all carrying clause_id and quote
- API endpoints: POST /api/documents/{id}/analyze and GET /api/documents/{id}/findings
"""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from backend.app.db import (
    init_db,
    save_document,
    save_clauses,
    get_analysis_run,
    get_findings,
    DocumentRecord,
    ClauseRecord,
)
from backend.app.ingest.pdf import extract_spans_from_pdf
from backend.app.segment.splitter import split_document_into_clauses
from backend.app.analyze.schemas import Finding, AnalysisOutput
from backend.app.analyze.lens import load_lens, build_rubric_prompt
from backend.app.analyze.prompt import build_analysis_prompt, format_document_for_prompt
from backend.app.analyze.analyzer import analyze_document
from backend.app.main import app

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Use an isolated SQLite test database for each test run."""
    test_db_path = tmp_path / "test_app_analyze.db"
    monkeypatch.setenv("DATABASE_URL", str(test_db_path))
    init_db(str(test_db_path))
    yield str(test_db_path)


@pytest.fixture
def client():
    return TestClient(app)


# -----------------------------------------------------------------------------
# 1. Pydantic Schema Validation Tests
# -----------------------------------------------------------------------------

def test_finding_schema_valid():
    """Verify valid finding matches all required fields."""
    valid_data = {
        "category": "unilateral_change",
        "severity": "red",
        "title": "Unilateral modification without notice",
        "explanation": "The provider reserves the right to change terms at any time without prior notice.",
        "clause_id": "C-3",
        "quote": "CloudScale reserves the right to modify, amend, or replace these Terms at any time",
    }
    finding = Finding(**valid_data)
    assert finding.category == "unilateral_change"
    assert finding.severity == "red"
    assert finding.clause_id == "C-3"
    assert finding.quote != ""


def test_finding_schema_invalid_category_or_missing_fields():
    """Verify schema rejects invalid categories or missing mandatory fields."""
    # Invalid category
    with pytest.raises(ValidationError):
        Finding(
            category="not_a_valid_unfair_tos_category",
            severity="red",
            title="Invalid",
            explanation="Test",
            clause_id="C-1",
            quote="Quote",
        )

    # Missing quote
    with pytest.raises(ValidationError):
        Finding(
            category="arbitration",
            severity="red",
            title="Arbitration",
            explanation="Test",
            clause_id="C-1",
            quote="",  # Empty quote prohibited
        )


# -----------------------------------------------------------------------------
# 2. Lens YAML Loading & Prompt Construction Tests
# -----------------------------------------------------------------------------

def test_lens_yaml_contains_all_eight_unfair_tos_categories():
    """Verify lenses/tos.yaml defines the 8 UNFAIR-ToS benchmark categories."""
    lens = load_lens("tos")
    assert lens["id"] == "tos"
    categories = lens["categories"]
    assert len(categories) == 8

    category_ids = {c["id"] for c in categories}
    expected_categories = {
        "arbitration",
        "unilateral_change",
        "content_removal",
        "jurisdiction",
        "choice_of_law",
        "limitation_of_liability",
        "unilateral_termination",
        "contract_by_using",
    }
    assert category_ids == expected_categories

    for cat in categories:
        assert "question" in cat and cat["question"] != ""
        assert cat["default_severity"] in ("red", "yellow", "info")


def test_prompt_built_from_yaml_with_untrusted_tags_and_quote_instructions():
    """Verify prompt is generated from YAML rubric and includes untrusted <document> tags."""
    lens = load_lens("tos")
    rubric = build_rubric_prompt(lens)

    # Ensure all 8 categories are rendered in rubric
    assert "unilateral_change" in rubric
    assert "limitation_of_liability" in rubric
    assert "arbitration" in rubric

    clauses = [
        ClauseRecord(
            id="C-1",
            document_id="doc_1",
            ordinal=1,
            label="1.",
            heading="Terms",
            text="By using the service you agree.",
            page=1,
        )
    ]
    formatted_doc = format_document_for_prompt(clauses)
    assert "<document>" in formatted_doc
    assert "</document>" in formatted_doc
    assert "[C-1]" in formatted_doc

    system_prompt, user_prompt = build_analysis_prompt(lens, clauses)
    assert "verbatim substring" in system_prompt.lower()
    assert "untrusted" in system_prompt.lower() or "untrusted" in user_prompt.lower()


# -----------------------------------------------------------------------------
# 3. Retry on Schema Validation Failure
# -----------------------------------------------------------------------------

def test_validation_retry_once_recovers_valid_output(monkeypatch):
    """Verify that when the LLM returns invalid JSON or schema on attempt 1,

    it retries ONCE with feedback and succeeds on attempt 2.
    """
    call_count = 0

    def mock_completion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        mock_resp.usage.prompt_tokens = 250
        mock_resp.usage.completion_tokens = 80

        if call_count == 1:
            # First attempt returns invalid category that fails Pydantic validation
            mock_resp.choices = [
                MagicMock(
                    message=MagicMock(
                        content='{"findings": [{"category": "bogus_category", "severity": "red", "title": "Bad", "explanation": "x", "clause_id": "C-1", "quote": "Agree"}]}'
                    )
                )
            ]
        else:
            # Second attempt fixes the schema
            mock_resp.choices = [
                MagicMock(
                    message=MagicMock(
                        content='{"findings": [{"category": "unilateral_change", "severity": "red", "title": "Valid", "explanation": "x", "clause_id": "C-1", "quote": "Agree"}]}'
                    )
                )
            ]
        return mock_resp

    monkeypatch.setattr("litellm.completion", mock_completion)

    doc = DocumentRecord(id="doc_retry", source_type="text", raw_text="Agree to terms.")
    save_document(doc)
    clauses = [
        ClauseRecord(
            id="C-1",
            document_id="doc_retry",
            ordinal=1,
            text="Agree to terms.",
            page=1,
        )
    ]
    save_clauses(clauses)

    run, findings = analyze_document(doc, clauses, dry_run=False, max_retries=1)

    assert call_count == 2, "Must retry exactly once on validation failure"
    assert len(findings) == 1
    assert findings[0].category == "unilateral_change"
    assert run.proposed_count == 1
    assert run.tokens_in == 500
    assert run.tokens_out == 160
    assert run.latency_ms > 0


def test_validation_failure_recorded_in_runs_after_max_retries(monkeypatch):
    """Verify that if retry fails as well, the failure is recorded in analysis_runs without looping infinitely."""
    call_count = 0

    def mock_failing_completion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        mock_resp.usage.prompt_tokens = 100
        mock_resp.usage.completion_tokens = 20
        # Consistently invalid JSON
        mock_resp.choices = [MagicMock(message=MagicMock(content="Invalid non-json output"))]
        return mock_resp

    monkeypatch.setattr("litellm.completion", mock_failing_completion)

    doc = DocumentRecord(id="doc_fail", source_type="text", raw_text="Sample text.")
    save_document(doc)
    clauses = [ClauseRecord(id="C-1", document_id="doc_fail", ordinal=1, text="Sample text.", page=1)]
    save_clauses(clauses)

    run, findings = analyze_document(doc, clauses, dry_run=False, max_retries=1)

    assert call_count == 2, "Must attempt initial call + 1 retry, then stop"
    assert len(findings) == 0
    assert run.proposed_count == 0
    assert run.tokens_in == 200
    assert run.tokens_out == 40
    assert run.latency_ms > 0

    # Ensure run is persisted in SQLite
    saved_run = get_analysis_run(run.id)
    assert saved_run is not None
    assert saved_run.proposed_count == 0
    assert saved_run.tokens_in == 200
    assert saved_run.tokens_out == 40


# -----------------------------------------------------------------------------
# 4. Deduplication by (category, clause_id)
# -----------------------------------------------------------------------------

def test_findings_deduplicated_by_category_and_clause_id(monkeypatch):
    """Verify multiple proposed findings with the same (category, clause_id) are deduplicated."""
    mock_resp = MagicMock()
    mock_resp.usage.prompt_tokens = 150
    mock_resp.usage.completion_tokens = 100
    mock_resp.choices = [
        MagicMock(
            message=MagicMock(
                content="""{
            "findings": [
                {
                    "category": "arbitration",
                    "severity": "red",
                    "title": "Mandatory Arbitration Clause",
                    "explanation": "Short explanation",
                    "clause_id": "C-5",
                    "quote": "settled exclusively by confidential binding arbitration"
                },
                {
                    "category": "arbitration",
                    "severity": "red",
                    "title": "Class Action Waiver / Arbitration",
                    "explanation": "More detailed explanation of the arbitration clause",
                    "clause_id": "C-5",
                    "quote": "settled exclusively by confidential binding arbitration in Wilmington"
                }
            ]
        }"""
            )
        )
    ]
    monkeypatch.setattr("litellm.completion", lambda *args, **kwargs: mock_resp)

    raw_text = (
        "Any dispute, claim or controversy shall be settled exclusively by "
        "confidential binding arbitration in Wilmington, Delaware."
    )
    doc = DocumentRecord(id="doc_dedupe", source_type="text", raw_text=raw_text)
    save_document(doc)
    clauses = [ClauseRecord(id="C-5", document_id="doc_dedupe", ordinal=5, text=raw_text, page=1)]
    save_clauses(clauses)

    run, findings = analyze_document(doc, clauses, dry_run=False)

    # Exactly 1 finding kept after deduplication
    assert len(findings) == 1
    assert findings[0].category == "arbitration"
    assert findings[0].clause_id == "C-5"


# -----------------------------------------------------------------------------
# 5. Acceptance 'Done when' & Dry-Run Mode Tests
# -----------------------------------------------------------------------------

def test_done_when_analysis_returns_typed_findings_with_clause_id_and_quote():
    """'Done when' acceptance criterion:

    Running analysis on a sample ToS returns typed findings that all carry a clause_id and quote.
    """
    pdf_path = FIXTURES_DIR / "cloud_service_tos.pdf"
    doc_data = extract_spans_from_pdf(pdf_path)
    doc_record = save_document(DocumentRecord(**doc_data))

    clauses = split_document_into_clauses(doc_data["spans"], doc_data["raw_text"], doc_record.id)
    save_clauses(clauses)

    # Run in dry_run mode (fully offline, no API key needed, zero API cost)
    run, findings = analyze_document(doc_record, clauses, dry_run=True)

    assert run.document_id == doc_record.id
    assert run.model is not None
    assert run.latency_ms > 0
    assert run.tokens_in > 0
    assert run.tokens_out > 0
    assert run.cost_usd == 0.0
    assert run.proposed_count == len(findings)
    assert len(findings) > 0, "Dry-run analysis on ToS document must detect unfair clauses"

    clause_id_map = {c.id: c.text for c in clauses}

    for finding in findings:
        # 1. Typed fields
        assert finding.category in [
            "arbitration",
            "unilateral_change",
            "content_removal",
            "jurisdiction",
            "choice_of_law",
            "limitation_of_liability",
            "unilateral_termination",
            "contract_by_using",
        ]
        assert finding.severity in ("red", "yellow", "info")
        assert finding.title != ""
        assert finding.explanation != ""

        # 2. Every finding carries clause_id and quote
        assert finding.clause_id in clause_id_map, f"Clause ID {finding.clause_id} must be in document"
        assert finding.quote != "", "Quote must not be empty"
        assert finding.quote in clause_id_map[finding.clause_id], "Quote must be an exact verbatim substring of cited clause"


# -----------------------------------------------------------------------------
# 6. API Endpoints Integration Test
# -----------------------------------------------------------------------------

def test_api_analyze_and_findings_endpoints(client):
    """Test POST /api/documents/{id}/analyze?dry_run=true and GET /api/documents/{id}/findings."""
    pdf_path = FIXTURES_DIR / "cloud_service_tos.pdf"
    with open(pdf_path, "rb") as f:
        upload_resp = client.post(
            "/api/documents",
            files={"file": ("cloud_service_tos.pdf", f, "application/pdf")},
        )
    doc_id = upload_resp.json()["id"]

    # Trigger analysis in dry_run mode
    analyze_resp = client.post(f"/api/documents/{doc_id}/analyze?dry_run=true")
    assert analyze_resp.status_code == 200
    analysis_data = analyze_resp.json()

    assert "run" in analysis_data
    assert "findings" in analysis_data
    assert analysis_data["run"]["proposed_count"] > 0
    assert len(analysis_data["findings"]) > 0

    # Retrieve findings via GET
    get_findings_resp = client.get(f"/api/documents/{doc_id}/findings")
    assert get_findings_resp.status_code == 200
    retrieved = get_findings_resp.json()
    assert len(retrieved) == len(analysis_data["findings"])
    assert retrieved[0]["clause_id"].startswith("C-")
    assert retrieved[0]["quote"] != ""


def test_app_starts_and_analyzes_without_any_api_keys_present(client, monkeypatch):
    """Verify that the FastAPI app starts and performs complete analysis in dry-run mode

    even when NO API keys (GEMINI_API_KEY, GOOGLE_API_KEY, OPENAI_API_KEY, etc.) exist in the environment,
    ensuring missing keys never break the test suite or local analysis.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # 1. Health check works and reports key not configured
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["status"] == "ok"
    assert health_data["gemini_api_key_configured"] is False

    # 2. Upload document
    pdf_path = FIXTURES_DIR / "cloud_service_tos.pdf"
    with open(pdf_path, "rb") as f:
        upload_resp = client.post(
            "/api/documents",
            files={"file": ("cloud_service_tos.pdf", f, "application/pdf")},
        )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["id"]

    # 3. Dry-run analysis runs without API keys
    analyze_resp = client.post(f"/api/documents/{doc_id}/analyze?dry_run=true")
    assert analyze_resp.status_code == 200
    data = analyze_resp.json()
    assert data["run"]["model"] == "dry-run-stub"
    assert data["run"]["proposed_count"] > 0
    assert data["run"]["verified_count"] > 0
    assert len(data["findings"]) > 0

    # 4. Retrieve findings
    findings_resp = client.get(f"/api/documents/{doc_id}/findings")
    assert findings_resp.status_code == 200
    assert len(findings_resp.json()) == len(data["findings"])


def test_default_model_is_gemini_3_8_flash_and_overridable(monkeypatch):
    """Verify default model is gemini/gemini-3.8-flash with gemini/ prefix, and overridable via ANALYSIS_MODEL."""
    from backend.app.analyze import DEFAULT_ANALYSIS_MODEL

    assert DEFAULT_ANALYSIS_MODEL == "gemini/gemini-3.8-flash"
    assert DEFAULT_ANALYSIS_MODEL.startswith("gemini/")

    captured_model = None

    def mock_completion(*args, **kwargs):
        nonlocal captured_model
        captured_model = kwargs.get("model")
        mock_resp = MagicMock()
        mock_resp.usage.prompt_tokens = 50
        mock_resp.usage.completion_tokens = 10
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"findings": []}'))]
        return mock_resp

    monkeypatch.setattr("litellm.completion", mock_completion)

    # 1. Without env override, defaults to gemini/gemini-3.8-flash
    monkeypatch.delenv("ANALYSIS_MODEL", raising=False)
    doc = DocumentRecord(id="doc_m1", source_type="text", raw_text="Sample terms.")
    save_document(doc)
    clauses = [ClauseRecord(id="C-1", document_id="doc_m1", ordinal=1, text="Sample terms.", page=1)]
    save_clauses(clauses)
    analyze_document(doc, clauses, dry_run=False)
    assert captured_model == "gemini/gemini-3.8-flash"

    # 2. With ANALYSIS_MODEL override
    monkeypatch.setenv("ANALYSIS_MODEL", "gemini/gemini-2.0-flash")
    analyze_document(doc, clauses, dry_run=False)
    assert captured_model == "gemini/gemini-2.0-flash"




