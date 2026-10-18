"""UNFAIR-ToS and Terms of Service benchmark runner and evaluation metrics reporter.

Usage:
    # UNFAIR-ToS Benchmark
    python -m backend.evals.run_eval --dataset unfair_tos --limit 100 --model ollama/qwen2.5:3b-instruct

    # Golden Set Evaluation (14 real ToS clauses / clean controls)
    python -m backend.evals.run_eval --dataset golden --model ollama/qwen2.5:3b-instruct
    python -m backend.evals.run_eval --dataset golden --model ollama/qwen2.5:7b-instruct

    # Prompt-Injection Mini-Eval (3 adversarial prompt injections)
    python -m backend.evals.run_eval --dataset injection --model ollama/qwen2.5:3b-instruct

    # Offline Dry-Run
    python -m backend.evals.run_eval --dataset golden --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
load_dotenv()

from backend.app.analyze.analyzer import DEFAULT_ANALYSIS_MODEL, analyze_document
from backend.app.analyze.lens import load_lens
from backend.app.db import (
    ClauseRecord,
    DocumentRecord,
    EvalRunRecord,
    EvalSummaryRecord,
    get_cached_eval_run,
    init_db,
    save_clauses,
    save_document,
    save_eval_run,
    save_eval_summary,
)
from backend.evals.datasets.golden import GoldenSample, load_golden_set
from backend.evals.datasets.injection import (
    InjectionSample,
    check_injection_compliance,
    load_injection_set,
)
from backend.evals.datasets.unfair_tos import UnfairTosSample, load_unfair_tos
from backend.evals.metrics import EvalMetricsReport, compute_metrics


def slugify_model(model: str) -> str:
    """Create a safe filesystem/identifier slug from a model name."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", model)


def run_evaluation(
    dataset: str = "unfair_tos",
    split: str = "test",
    model: Optional[str] = None,
    limit: Optional[int] = None,
    lens_id: str = "tos",
    dry_run: bool = False,
    force_rerun: bool = False,
    db_path: Optional[str] = None,
    debug_raw: bool = False,
    quiet: bool = False,
) -> tuple[EvalMetricsReport, list[EvalRunRecord]]:
    """Execute evaluation over a dataset and return metrics and run records.

    Treats each clause/document through the normal analysis path.
    Results are cached in the eval_runs table; cached combinations skip the LLM call.

    Args:
        dataset: Dataset identifier ('unfair_tos', 'golden', or 'injection').
        split: Dataset split ('test', 'validation', 'train'). Default 'test'.
        model: Model identifier. Defaults to env ANALYZE_MODEL or DEFAULT_ANALYSIS_MODEL.
        limit: Optional maximum number of samples to evaluate.
        lens_id: Lens configuration to use (default 'tos').
        dry_run: If True, uses offline deterministic analyzer.
        force_rerun: If True, bypasses cache and re-analyzes all samples.
        db_path: Optional SQLite database path.
        debug_raw: If True, writes raw LLM outputs to debug logs.
        quiet: If True, suppresses per-sample console logging.

    Returns:
        tuple[EvalMetricsReport, list[EvalRunRecord]]
    """
    init_db(db_path=db_path)

    effective_model = (
        model
        or os.environ.get("ANALYZE_MODEL")
        or os.environ.get("ANALYSIS_MODEL")
        or DEFAULT_ANALYSIS_MODEL
    )
    if dry_run:
        effective_model = f"dry-run:{effective_model}"

    lens_data = load_lens(lens_id)
    lens_version = lens_data.get("version", 1)
    model_slug = slugify_model(effective_model)

    dataset_lower = dataset.lower()
    if dataset_lower == "unfair_tos":
        raw_samples = load_unfair_tos(split=split, limit=limit)
        samples = [
            {
                "sample_id": s.sample_id,
                "name": f"Sample {s.sample_id}",
                "text": s.text,
                "categories": s.categories,
            }
            for s in raw_samples
        ]
    elif dataset_lower in ("golden", "golden_set"):
        dataset = "golden"
        raw_samples = load_golden_set(limit=limit)
        samples = [
            {
                "sample_id": s.sample_id,
                "name": s.name,
                "text": s.text,
                "categories": s.categories,
            }
            for s in raw_samples
        ]
    elif dataset_lower in ("injection", "prompt_injection"):
        dataset = "injection"
        raw_samples = load_injection_set()
        samples = [
            {
                "sample_id": s.sample_id,
                "name": s.name,
                "text": s.text,
                "categories": s.real_unfair_categories,
                "_injection_sample": s,
            }
            for s in raw_samples
        ]
        if limit is not None and limit > 0:
            samples = samples[:limit]
    else:
        raise ValueError(
            f"Unsupported dataset: {dataset}. Supported datasets: ['unfair_tos', 'golden', 'injection']"
        )

    total_samples = len(samples)
    if not quiet:
        print(f"\n=======================================================")
        print(f" Starting Evaluation: {dataset} ({split})")
        print(f" Model:               {effective_model}")
        print(f" Lens:                {lens_id} (version {lens_version})")
        print(f" Samples to Evaluate: {total_samples}")
        print(f" Mode:                {'DRY RUN (offline)' if dry_run else 'LIVE LLM'}")
        print(f" Cache:               {'BYPASSED (--force-rerun)' if force_rerun else 'ENABLED (resumable)'}")
        print(f"=======================================================\n")

    eval_records: list[EvalRunRecord] = []
    cached_count = 0
    executed_count = 0
    injection_results: list[dict[str, Any]] = []

    t_eval_start = time.perf_counter()

    for idx, s in enumerate(samples, 1):
        sample_id = s["sample_id"]
        sample_text = s["text"].strip()
        expected_cats = s["categories"]
        sample_name = s.get("name", f"Sample {sample_id}")

        cached_rec: Optional[EvalRunRecord] = None
        if not force_rerun:
            cached_rec = get_cached_eval_run(
                dataset=dataset,
                split=split,
                model=effective_model,
                lens_id=lens_id,
                lens_version=lens_version,
                sample_id=sample_id,
                db_path=db_path,
            )

        if cached_rec is not None:
            cached_count += 1
            eval_records.append(cached_rec)
            pred_cats = json.loads(cached_rec.predicted)

            if dataset == "injection" and "_injection_sample" in s:
                inj_sample: InjectionSample = s["_injection_sample"]
                findings_data = json.loads(cached_rec.findings_json)
                complied, reason = check_injection_compliance(inj_sample, findings_data)
                injection_results.append(
                    {
                        "sample_id": sample_id,
                        "name": sample_name,
                        "complied": complied,
                        "reason": reason,
                    }
                )

            if not quiet:
                print(
                    f"[{idx:2d}/{total_samples:2d}] [CACHED] ID {sample_id:>2d} ({sample_name[:28]:<28}) | "
                    f"GT: {str(expected_cats):<24} | Pred: {str(pred_cats):<24}"
                )
            continue

        doc_id = f"eval-{dataset}-{split}-{sample_id}"
        doc_record = DocumentRecord(
            id=doc_id,
            filename=f"{dataset}_{sample_id}.txt",
            source_type="text",
            raw_text=sample_text,
            page_count=1,
        )
        clause_record = ClauseRecord(
            id="C-1",
            document_id=doc_id,
            ordinal=1,
            label="Clause 1",
            heading=None,
            text=sample_text,
            page=1,
            char_start=0,
            char_end=len(sample_text),
            bboxes=[],
        )

        save_document(doc_record, db_path=db_path)
        save_clauses([clause_record], db_path=db_path)

        t0 = time.perf_counter()
        run, verified_findings = analyze_document(
            document=doc_record,
            clauses=[clause_record],
            lens_id=lens_id,
            dry_run=dry_run,
            model=effective_model.replace("dry-run:", "") if dry_run else effective_model,
            db_path=db_path,
            debug_raw=debug_raw,
        )
        latency_ms = max(1.0, (time.perf_counter() - t0) * 1000)

        pred_categories = sorted(list({f.category for f in verified_findings}))

        rec_id = f"eval_{dataset}_{split}_{model_slug}_{lens_id}_v{lens_version}_{sample_id}"
        eval_rec = EvalRunRecord(
            id=rec_id,
            dataset=dataset,
            split=split,
            model=effective_model,
            lens_id=lens_id,
            lens_version=lens_version,
            sample_id=sample_id,
            sentence=sample_text,
            ground_truth=json.dumps(expected_cats),
            predicted=json.dumps(pred_categories),
            findings_json=json.dumps([f.model_dump() for f in verified_findings]),
            verified_count=run.verified_count,
            rejected_count=run.rejected_count,
            grounding_rate=run.grounding_rate,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            latency_ms=latency_ms,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        save_eval_run(eval_rec, db_path=db_path)
        eval_records.append(eval_rec)
        executed_count += 1

        if dataset == "injection" and "_injection_sample" in s:
            inj_sample = s["_injection_sample"]
            complied, reason = check_injection_compliance(
                inj_sample, [f.model_dump() for f in verified_findings]
            )
            injection_results.append(
                {
                    "sample_id": sample_id,
                    "name": sample_name,
                    "complied": complied,
                    "reason": reason,
                }
            )

        if not quiet:
            print(
                f"[{idx:2d}/{total_samples:2d}] [RUN]    ID {sample_id:>2d} ({sample_name[:28]:<28}) | "
                f"GT: {str(expected_cats):<24} | Pred: {str(pred_categories):<24} | "
                f"Verified: {run.verified_count}/{run.proposed_count} | {latency_ms:.0f} ms"
            )

    report = compute_metrics(
        records=eval_records,
        dataset=dataset,
        split=split,
        model=effective_model,
        lens_id=lens_id,
        lens_version=lens_version,
    )

    summary_id = f"summary_{dataset}_{split}_{model_slug}_{lens_id}_v{lens_version}_{int(time.time())}"
    summary_rec = EvalSummaryRecord(
        id=summary_id,
        dataset=dataset,
        split=split,
        model=effective_model,
        lens_id=lens_id,
        lens_version=lens_version,
        limit_n=total_samples,
        sample_count=total_samples,
        macro_f1=report.macro_f1,
        micro_f1=report.micro_f1,
        metrics_json=json.dumps(report.model_dump()),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    save_eval_summary(summary_rec, db_path=db_path)

    if not quiet:
        elapsed_total = time.perf_counter() - t_eval_start
        print(f"\nEvaluation completed in {elapsed_total:.1f}s ({cached_count} cached, {executed_count} executed).")
        print(report.format_table())

        if dataset == "golden":
            # Golden Set specialized metrics: recall of known red flags and false-positive counts
            total_known_red_flags = sum(len(s["categories"]) for s in samples)
            detected_known_red_flags = sum(m.tp for m in report.per_category.values())
            overall_fp_count = sum(m.fp for m in report.per_category.values())
            clean_samples = [s for s in samples if not s["categories"]]
            clean_fp_count = 0
            for rec in eval_records:
                if json.loads(rec.ground_truth) == []:
                    clean_fp_count += len(json.loads(rec.predicted))

            recall_rate = (
                (detected_known_red_flags / total_known_red_flags * 100)
                if total_known_red_flags > 0
                else 0.0
            )
            print(f"=========================================================================================")
            print(f" GOLDEN SET SUMMARY ({effective_model})")
            print(f" Total Documents:              {total_samples} (11 Unfair clauses, 3 Clean controls)")
            print(f" Total Known Red Flags:        {total_known_red_flags}")
            print(f" Detected Known Red Flags:     {detected_known_red_flags}")
            print(f" Red Flag Recall:              {recall_rate:.1f}% ({detected_known_red_flags}/{total_known_red_flags})")
            print(f" Total False Positives:        {overall_fp_count}")
            print(f" Clean Controls False Positives: {clean_fp_count} (out of {len(clean_samples)} clean documents)")
            print(f" Grounding Rate:               {report.grounding_rate * 100:.1f}%")
            print(f"=========================================================================================\n")

        elif dataset == "injection":
            compliant_count = sum(1 for r in injection_results if r["complied"])
            resisted_count = len(injection_results) - compliant_count
            print(f"=========================================================================================")
            print(f" PROMPT-INJECTION MINI-EVAL SUMMARY ({effective_model})")
            print(f" Total Attack Vectors:         {len(injection_results)}")
            print(f" Attacks Resisted (PASS):      {resisted_count}/{len(injection_results)}")
            print(f" Attacks Complied (FAIL):      {compliant_count} (Target: 0)")
            print(f" Security Pass Rate:           {(resisted_count / len(injection_results)) * 100:.1f}%")
            print(f"-----------------------------------------------------------------------------------------")
            for r in injection_results:
                status = "FAIL (Complied)" if r["complied"] else "PASS (Resisted)"
                print(f" [{status}] Sample {r['sample_id']}: {r['name']} — {r['reason']}")
            print(f"=========================================================================================\n")

    return report, eval_records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run benchmark evaluations for Terms of Service fairness detection."
    )
    parser.add_argument(
        "--dataset",
        "-d",
        default="unfair_tos",
        choices=["unfair_tos", "golden", "injection"],
        help="Evaluation dataset to run ('unfair_tos', 'golden', or 'injection').",
    )
    parser.add_argument(
        "--split",
        "-s",
        default="test",
        help="Dataset split: 'test', 'validation', or 'train' (default: test).",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Maximum number of sentences/clauses to evaluate.",
    )
    default_model = (
        os.environ.get("ANALYZE_MODEL")
        or os.environ.get("ANALYSIS_MODEL")
        or DEFAULT_ANALYSIS_MODEL
    )
    parser.add_argument(
        "--model",
        "-m",
        default=default_model,
        help=f"Model identifier (default: env ANALYZE_MODEL or {DEFAULT_ANALYSIS_MODEL}).",
    )
    parser.add_argument(
        "--lens",
        default="tos",
        help="Lens configuration name (default: tos).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run offline deterministic analyzer without LLM API calls.",
    )
    parser.add_argument(
        "--force-rerun",
        action="store_true",
        help="Ignore cached results in eval_runs and re-execute all samples.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional custom SQLite database path.",
    )
    parser.add_argument(
        "--debug-raw",
        action="store_true",
        help="Log raw model outputs to debug directory.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress per-sample output lines.",
    )

    args = parser.parse_args()

    run_evaluation(
        dataset=args.dataset,
        split=args.split,
        model=args.model,
        limit=args.limit,
        lens_id=args.lens,
        dry_run=args.dry_run,
        force_rerun=args.force_rerun,
        db_path=args.db_path,
        debug_raw=args.debug_raw,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
