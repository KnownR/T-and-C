"""Unit tests for UNFAIR-ToS benchmark loader, metrics calculation, and evaluation runner.

All tests run completely offline with mocked LLM or deterministic dry-run (no Ollama/network needed).
"""

import json
import sys
from unittest.mock import MagicMock, patch
import pytest

from backend.app.db import (
    EvalRunRecord,
    EvalSummaryRecord,
    get_cached_eval_run,
    get_eval_runs,
    get_latest_eval_summary,
    init_db,
    save_eval_run,
    save_eval_summary,
)
from backend.evals.datasets.unfair_tos import (
    ALL_CATEGORIES,
    CATEGORY_TO_LABEL_MAP,
    LEXGLUE_LABEL_MAP,
    UnfairTosSample,
    load_unfair_tos,
    map_labels_to_categories,
)
from backend.evals.metrics import compute_metrics
from backend.evals.run_eval import main, run_evaluation, slugify_model


@pytest.fixture
def test_db(tmp_path):
    """Provide a fresh isolated SQLite database for testing."""
    db_file = tmp_path / "test_evals.db"
    init_db(str(db_file))
    return str(db_file)


# ---------------------------------------------------------------------------
# 1. Dataset Loader & Category Mapping Tests
# ---------------------------------------------------------------------------

def test_lexglue_label_mapping():
    """Verify that all 8 LexGLUE labels map explicitly 1-to-1 to tos.yaml categories."""
    assert len(LEXGLUE_LABEL_MAP) == 8
    assert len(ALL_CATEGORIES) == 8

    expected_mappings = {
        0: "limitation_of_liability",
        1: "unilateral_termination",
        2: "unilateral_change",
        3: "content_removal",
        4: "contract_by_using",
        5: "choice_of_law",
        6: "jurisdiction",
        7: "arbitration",
    }
    for label_id, category_id in expected_mappings.items():
        assert LEXGLUE_LABEL_MAP[label_id] == category_id
        assert CATEGORY_TO_LABEL_MAP[category_id] == label_id


def test_map_labels_to_categories():
    """Test mapping helper with empty, single, and multiple label lists."""
    assert map_labels_to_categories([]) == []
    assert map_labels_to_categories([7]) == ["arbitration"]
    assert map_labels_to_categories([0, 2]) == ["limitation_of_liability", "unilateral_change"]
    # Unknown labels ignored gracefully
    assert map_labels_to_categories([999, 7]) == ["arbitration"]


def test_unfair_tos_sample_model():
    """Test UnfairTosSample model creation and defaults."""
    sample = UnfairTosSample(
        sample_id=42,
        text="Any dispute will be resolved by arbitration.",
        labels=[7],
        categories=["arbitration"],
    )
    assert sample.sample_id == 42
    assert "arbitration" in sample.text
    assert sample.categories == ["arbitration"]


def test_load_unfair_tos_from_cache(tmp_path):
    """Test loading unfair_tos from a cached JSON file with limit slicing."""
    cache_dir = tmp_path / "data"
    cache_dir.mkdir(parents=True, exist_ok=True)
    sample_data = [
        {"row_idx": 0, "text": "Clause zero is neutral.", "labels": []},
        {"row_idx": 1, "text": "Clause one forces arbitration.", "labels": [7]},
        {"row_idx": 2, "text": "Clause two limits liability.", "labels": [0]},
    ]
    (cache_dir / "unfair_tos_test.json").write_text(json.dumps(sample_data), encoding="utf-8")

    loaded_all = load_unfair_tos(split="test", cache_dir=cache_dir, allow_download=False)
    assert len(loaded_all) == 3
    assert loaded_all[0].categories == []
    assert loaded_all[1].categories == ["arbitration"]
    assert loaded_all[2].categories == ["limitation_of_liability"]

    loaded_limited = load_unfair_tos(split="test", limit=2, cache_dir=cache_dir, allow_download=False)
    assert len(loaded_limited) == 2


# ---------------------------------------------------------------------------
# 2. Evaluation Metrics Calculation Tests
# ---------------------------------------------------------------------------

def test_compute_metrics_exact_arithmetic():
    """Verify precision, recall, F1, micro/macro averages against manually computed arithmetic."""
    # 3 samples:
    # Sample 1: GT={arbitration}, Pred={arbitration} -> TP=1 for arbitration
    # Sample 2: GT={arbitration}, Pred={} -> FN=1 for arbitration
    # Sample 3: GT={}, Pred={arbitration} -> FP=1 for arbitration
    records = [
        {"ground_truth": ["arbitration"], "predicted": ["arbitration"], "verified_count": 1, "rejected_count": 0, "latency_ms": 10},
        {"ground_truth": ["arbitration"], "predicted": [], "verified_count": 0, "rejected_count": 0, "latency_ms": 10},
        {"ground_truth": [], "predicted": ["arbitration"], "verified_count": 1, "rejected_count": 0, "latency_ms": 10},
    ]

    report = compute_metrics(records)
    arb = report.per_category["arbitration"]
    assert arb.tp == 1
    assert arb.fn == 1
    assert arb.fp == 1
    assert arb.support == 2
    # Precision = 1 / (1 + 1) = 0.5
    assert arb.precision == pytest.approx(0.5)
    # Recall = 1 / (1 + 1) = 0.5
    assert arb.recall == pytest.approx(0.5)
    # F1 = 2 * 0.5 * 0.5 / (0.5 + 0.5) = 0.5
    assert arb.f1 == pytest.approx(0.5)

    # Micro average across all categories (only arbitration had events: TP=1, FP=1, FN=1):
    assert report.micro_precision == pytest.approx(0.5)
    assert report.micro_recall == pytest.approx(0.5)
    assert report.micro_f1 == pytest.approx(0.5)

    # Macro average: 1 category has F1=0.5, the other 7 have F1=0.0 -> 0.5 / 8 = 0.0625
    assert report.macro_f1 == pytest.approx(0.5 / 8)

    # Grounding rate: 2 proposed, 2 verified, 0 rejected -> 1.0
    assert report.grounding_rate == pytest.approx(1.0)
    assert report.total_proposed == 2
    assert report.total_verified == 2


def test_compute_metrics_zero_division():
    """Verify that zero predictions or zero ground truth do not raise ZeroDivisionError."""
    records = [
        {"ground_truth": [], "predicted": [], "verified_count": 0, "rejected_count": 0, "latency_ms": 5},
    ]
    report = compute_metrics(records)
    assert report.sample_count == 1
    assert report.positive_samples == 0
    assert report.negative_samples == 1
    assert report.macro_f1 == 0.0
    assert report.micro_f1 == 0.0
    assert "Benchmark Evaluation Results" in report.format_table()


# ---------------------------------------------------------------------------
# 3. SQLite Persistence & Resumability Tests
# ---------------------------------------------------------------------------

def test_eval_runs_persistence_and_caching(test_db):
    """Test persisting an eval run record and retrieving it via get_cached_eval_run."""
    rec = EvalRunRecord(
        id="eval_run_1",
        dataset="unfair_tos",
        split="test",
        model="test_model",
        lens_id="tos",
        lens_version=1,
        sample_id=10,
        sentence="Disputes go to binding arbitration.",
        ground_truth=json.dumps(["arbitration"]),
        predicted=json.dumps(["arbitration"]),
        findings_json="[]",
        verified_count=1,
        rejected_count=0,
        grounding_rate=1.0,
        tokens_in=100,
        tokens_out=50,
        latency_ms=120.0,
    )
    saved = save_eval_run(rec, db_path=test_db)
    assert saved.id == "eval_run_1"

    cached = get_cached_eval_run(
        dataset="unfair_tos",
        split="test",
        model="test_model",
        lens_id="tos",
        lens_version=1,
        sample_id=10,
        db_path=test_db,
    )
    assert cached is not None
    assert cached.sample_id == 10
    assert json.loads(cached.ground_truth) == ["arbitration"]
    assert json.loads(cached.predicted) == ["arbitration"]

    # Miss on different sample ID
    miss = get_cached_eval_run(
        dataset="unfair_tos",
        split="test",
        model="test_model",
        lens_id="tos",
        lens_version=1,
        sample_id=999,
        db_path=test_db,
    )
    assert miss is None


def test_eval_summary_persistence(test_db):
    """Test saving and retrieving an evaluation summary record."""
    summary = EvalSummaryRecord(
        id="summary_1",
        dataset="unfair_tos",
        split="test",
        model="test_model",
        lens_id="tos",
        lens_version=1,
        limit_n=10,
        sample_count=10,
        macro_f1=0.75,
        micro_f1=0.80,
        metrics_json="{}",
    )
    save_eval_summary(summary, db_path=test_db)
    latest = get_latest_eval_summary(
        dataset="unfair_tos",
        split="test",
        model="test_model",
        lens_id="tos",
        lens_version=1,
        db_path=test_db,
    )
    assert latest is not None
    assert latest.id == "summary_1"
    assert latest.macro_f1 == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# 4. Eval Runner Tests with Mocked LLM & Dry-Run
# ---------------------------------------------------------------------------

def test_eval_runner_with_mocked_llm(test_db, tmp_path):
    """Test full evaluation pipeline with mocked LLM output and verifier checks."""
    # Create local fixture with 2 samples: 1 arbitration and 1 neutral
    cache_dir = tmp_path / "data"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fixture_samples = [
        {
            "row_idx": 100,
            "text": "All claims shall be submitted to mandatory individual arbitration.",
            "labels": [7],  # arbitration
        },
        {
            "row_idx": 101,
            "text": "Welcome to our website. Enjoy your stay.",
            "labels": [],  # neutral
        },
    ]
    (cache_dir / "unfair_tos_test.json").write_text(json.dumps(fixture_samples), encoding="utf-8")

    mock_resp = MagicMock()
    mock_resp.usage.prompt_tokens = 250
    mock_resp.usage.completion_tokens = 80
    mock_choice = MagicMock()
    # The LLM outputs a finding with a verbatim quote for sample 100
    mock_choice.message.content = json.dumps({
        "findings": [
            {
                "category": "arbitration",
                "severity": "red",
                "title": "Mandatory Arbitration",
                "explanation": "Waives court litigation rights.",
                "clause_id": "C-1",
                "quote": "All claims shall be submitted to mandatory individual arbitration.",
            }
        ]
    })
    mock_resp.choices = [mock_choice]

    with patch("backend.evals.datasets.unfair_tos.get_default_data_dir", return_value=cache_dir):
        with patch("backend.app.analyze.analyzer.completion_with_backoff", return_value=mock_resp) as mock_llm:
            report, records = run_evaluation(
                dataset="unfair_tos",
                split="test",
                model="mock-model",
                db_path=test_db,
                quiet=True,
            )

            assert len(records) == 2
            # First sample had arbitration: proposed and verified
            rec0 = records[0]
            assert json.loads(rec0.ground_truth) == ["arbitration"]
            assert json.loads(rec0.predicted) == ["arbitration"]
            assert rec0.verified_count == 1
            assert rec0.rejected_count == 0

            # Verify metrics report
            arb_metric = report.per_category["arbitration"]
            assert arb_metric.tp == 1
            assert arb_metric.fn == 0
            assert arb_metric.precision == 1.0
            assert arb_metric.recall == 1.0
            assert arb_metric.f1 == 1.0

            assert mock_llm.call_count == 2


def test_eval_runner_resumability(test_db, tmp_path):
    """Test that second run skips LLM calls when records are already cached in eval_runs."""
    cache_dir = tmp_path / "data"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fixture_samples = [
        {"row_idx": 200, "text": "Disputes are handled in arbitration.", "labels": [7]},
    ]
    (cache_dir / "unfair_tos_test.json").write_text(json.dumps(fixture_samples), encoding="utf-8")

    mock_resp = MagicMock()
    mock_resp.usage.prompt_tokens = 100
    mock_resp.usage.completion_tokens = 50
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "findings": [
            {
                "category": "arbitration",
                "severity": "red",
                "title": "Arbitration",
                "explanation": "Forces arbitration.",
                "clause_id": "C-1",
                "quote": "Disputes are handled in arbitration.",
            }
        ]
    })
    mock_resp.choices = [mock_choice]

    with patch("backend.evals.datasets.unfair_tos.get_default_data_dir", return_value=cache_dir):
        with patch("backend.app.analyze.analyzer.completion_with_backoff", return_value=mock_resp) as mock_llm:
            # First pass: executes LLM call
            _, records1 = run_evaluation(
                dataset="unfair_tos",
                model="resumable-model",
                db_path=test_db,
                quiet=True,
            )
            assert len(records1) == 1
            assert mock_llm.call_count == 1

            # Second pass: must skip LLM call via cached record
            mock_llm.reset_mock()
            _, records2 = run_evaluation(
                dataset="unfair_tos",
                model="resumable-model",
                db_path=test_db,
                quiet=True,
            )
            assert len(records2) == 1
            assert mock_llm.call_count == 0  # Did not call LLM!


def test_eval_runner_verifier_rejects_hallucinated_quote(test_db, tmp_path):
    """Verify non-negotiable principle: hallucinated quotes are rejected and NEVER counted as predicted."""
    cache_dir = tmp_path / "data"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fixture_samples = [
        {"row_idx": 300, "text": "This clause is about cookies and tracking.", "labels": []},
    ]
    (cache_dir / "unfair_tos_test.json").write_text(json.dumps(fixture_samples), encoding="utf-8")

    # LLM hallucinates an arbitration finding with an invented quote not present in the text
    mock_resp = MagicMock()
    mock_resp.usage.prompt_tokens = 100
    mock_resp.usage.completion_tokens = 50
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "findings": [
            {
                "category": "arbitration",
                "severity": "red",
                "title": "Hallucinated Finding",
                "explanation": "Fabricated by model.",
                "clause_id": "C-1",
                "quote": "Completely made up quote about mandatory arbitration that does not exist.",
            }
        ]
    })
    mock_resp.choices = [mock_choice]

    with patch("backend.evals.datasets.unfair_tos.get_default_data_dir", return_value=cache_dir):
        with patch("backend.app.analyze.analyzer.completion_with_backoff", return_value=mock_resp):
            report, records = run_evaluation(
                dataset="unfair_tos",
                model="hallucinating-model",
                db_path=test_db,
                quiet=True,
            )

            rec = records[0]
            # Ground truth is empty
            assert json.loads(rec.ground_truth) == []
            # Predicted MUST BE EMPTY because the fabricated quote was rejected!
            assert json.loads(rec.predicted) == []
            assert rec.rejected_count == 1
            assert rec.verified_count == 0
            assert rec.grounding_rate == 0.0

            # False Positive for arbitration should be 0 because verifier killed the hallucination!
            assert report.per_category["arbitration"].fp == 0


def test_eval_runner_dry_run_offline(test_db):
    """Test eval runner with --dry-run (fully offline, no network, no LLM calls)."""
    report, records = run_evaluation(
        dataset="unfair_tos",
        limit=5,
        dry_run=True,
        db_path=test_db,
        quiet=True,
    )
    assert len(records) == 5
    assert report.sample_count == 5
    assert "dry-run:" in report.model


def test_eval_runner_cli_dry_run(test_db):
    """Test eval runner CLI invocation via main() with dry-run flags."""
    test_args = [
        "run_eval.py",
        "--dataset", "unfair_tos",
        "--limit", "3",
        "--dry-run",
        "--db-path", test_db,
        "--quiet",
    ]
    with patch.object(sys, "argv", test_args):
        # Must execute without exception
        main()

    # Verify records were saved to test_db
    records = get_eval_runs(
        dataset="unfair_tos",
        split="test",
        model="dry-run:ollama/qwen2.5:7b-instruct",
        lens_id="tos",
        lens_version=1,
        db_path=test_db,
    )
    assert len(records) == 3


# ---------------------------------------------------------------------------
# 5. Golden Set & Prompt-Injection Tests
# ---------------------------------------------------------------------------

def test_golden_set_loader_coverage():
    """Verify golden set contains 14 documents covering all 8 categories + clean controls."""
    from backend.evals.datasets.golden import load_golden_set

    samples = load_golden_set()
    assert len(samples) == 14

    covered_cats = set()
    clean_count = 0
    for s in samples:
        if not s.categories:
            clean_count += 1
        for cat in s.categories:
            covered_cats.add(cat)

    # Must cover at least 2-3 clean documents
    assert clean_count == 3
    # Must cover all 8 lens categories
    assert len(covered_cats) == 8
    assert "contract_by_using" in covered_cats
    assert "arbitration" in covered_cats
    assert "unilateral_change" in covered_cats
    assert "unilateral_termination" in covered_cats


def test_golden_set_eval_with_mocked_llm(test_db):
    """Test golden set evaluation with mocked LLM predicting known red flags."""
    mock_resp = MagicMock()
    mock_resp.usage.prompt_tokens = 200
    mock_resp.usage.completion_tokens = 50
    mock_choice = MagicMock()
    # Mock LLM outputs arbitration for arbitration sample
    mock_choice.message.content = json.dumps({
        "findings": [
            {
                "category": "arbitration",
                "severity": "red",
                "title": "Arbitration",
                "explanation": "Mandatory arbitration.",
                "clause_id": "C-1",
                "quote": "shall be resolved solely and exclusively by final and binding individual arbitration",
            }
        ]
    })
    mock_resp.choices = [mock_choice]

    with patch("backend.app.analyze.analyzer.completion_with_backoff", return_value=mock_resp):
        report, records = run_evaluation(
            dataset="golden",
            model="mock-golden-model",
            limit=2,
            db_path=test_db,
            quiet=True,
        )
        assert len(records) == 2
        assert report.sample_count == 2


def test_injection_set_loader():
    """Verify injection set loads 3 distinct adversarial attack vectors."""
    from backend.evals.datasets.injection import load_injection_set

    injections = load_injection_set()
    assert len(injections) == 3
    attack_types = {inj.attack_type for inj in injections}
    assert "directive_override" in attack_types
    assert "jailbreak_diversion" in attack_types
    assert "prompt_leakage" in attack_types


def test_injection_compliance_checker():
    """Test compliance checking logic for detecting attacks and non-compliance."""
    from backend.evals.datasets.injection import InjectionSample, check_injection_compliance

    sample_override = InjectionSample(
        sample_id=1,
        name="Fairness Override",
        attack_type="directive_override",
        planted_phrase="this policy is fair",
        text="text",
    )
    # Compliant (bad): says policy is certified fair
    compliant, reason = check_injection_compliance(
        sample_override,
        [{"title": "Fair", "explanation": "This policy is certified 100% fair", "quote": ""}],
    )
    assert compliant is True
    assert "obeyed" in reason

    # Resisted (good): normal findings
    not_compliant, _ = check_injection_compliance(
        sample_override,
        [{"title": "Unilateral Termination", "explanation": "Provider terminates at will.", "quote": "terminate your account"}],
    )
    assert not_compliant is False


def test_injection_eval_runner_with_mocked_llm(test_db):
    """Test injection eval runner produces 0 compliant runs with secure output."""
    from backend.evals.datasets.injection import check_injection_compliance

    mock_resp = MagicMock()
    mock_resp.usage.prompt_tokens = 150
    mock_resp.usage.completion_tokens = 40
    mock_choice = MagicMock()
    # Mock LLM outputs standard findings ignoring the adversarial text
    mock_choice.message.content = json.dumps({
        "findings": [
            {
                "category": "unilateral_termination",
                "severity": "red",
                "title": "Unilateral Termination",
                "explanation": "Company reserves right to terminate without notice.",
                "clause_id": "C-1",
                "quote": "terminate or suspend your user account",
            }
        ]
    })
    mock_resp.choices = [mock_choice]

    with patch("backend.app.analyze.analyzer.completion_with_backoff", return_value=mock_resp):
        report, records = run_evaluation(
            dataset="injection",
            model="secure-model",
            limit=1,
            db_path=test_db,
            quiet=True,
        )
        assert len(records) == 1
        rec = records[0]
        findings = json.loads(rec.findings_json)
        assert len(findings) == 1
        assert findings[0]["category"] == "unilateral_termination"


def test_cli_golden_and_injection_dry_run(test_db):
    """Test CLI runs for golden set and injection mini-eval in dry-run mode."""
    golden_args = [
        "run_eval.py",
        "--dataset", "golden",
        "--limit", "2",
        "--dry-run",
        "--db-path", test_db,
        "--quiet",
    ]
    with patch.object(sys, "argv", golden_args):
        main()

    injection_args = [
        "run_eval.py",
        "--dataset", "injection",
        "--dry-run",
        "--db-path", test_db,
        "--quiet",
    ]
    with patch.object(sys, "argv", injection_args):
        main()
