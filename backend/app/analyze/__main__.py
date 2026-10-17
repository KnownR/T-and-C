"""CLI entrypoint for running legal analysis from terminal."""

import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file at startup before reading environment variables
ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")
load_dotenv()

from backend.app.analyze.analyzer import DEFAULT_ANALYSIS_MODEL, analyze_document
from backend.app.db import DocumentRecord, init_db, save_clauses, save_document
from backend.app.ingest.pdf import extract_spans_from_pdf
from backend.app.ingest.text import extract_spans_from_text
from backend.app.segment.splitter import split_document_into_clauses



def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Terms of Service documents.")
    parser.add_argument("--file", "-f", required=True, help="Path to PDF or text file to analyze.")
    parser.add_argument("--dry-run", action="store_true", help="Run with offline stubbed model at zero API cost.")
    parser.add_argument("--lens", default="tos", help="Lens configuration to use (default: tos).")
    default_model = (
        os.environ.get("ANALYZE_MODEL")
        or os.environ.get("ANALYSIS_MODEL")
        or DEFAULT_ANALYSIS_MODEL
    )
    parser.add_argument(
        "--model",
        default=default_model,
        help=f"LiteLLM model identifier (default: env ANALYZE_MODEL or {DEFAULT_ANALYSIS_MODEL}).",
    )
    parser.add_argument(
        "--debug-raw",
        action="store_true",
        help="Write raw model response per call to a debug log file tied to the run ID.",
    )
    args = parser.parse_args()

    init_db()
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: file not found: {file_path}")
        raise SystemExit(1)

    if file_path.suffix.lower() == ".pdf":
        doc_data = extract_spans_from_pdf(file_path)
    else:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        doc_data = extract_spans_from_text(text, filename=file_path.name)

    doc_record = save_document(DocumentRecord(**doc_data))
    clauses = split_document_into_clauses(doc_data["spans"], doc_data["raw_text"], doc_record.id)
    save_clauses(clauses)

    try:
        run, findings = analyze_document(
            document=doc_record,
            clauses=clauses,
            lens_id=args.lens,
            dry_run=args.dry_run,
            model=args.model,
            debug_raw=args.debug_raw,
        )
    except Exception as exc:
        print(f"\n[Error] Analysis failed: {exc}")
        raise SystemExit(1)

    print(f"\n--- Analysis & Verification Summary ---")
    print(f"Run ID:          {run.id}")
    print(f"Model:           {run.model}")
    print(f"Lens:            {run.lens}")
    print(f"Total Clauses:   {run.total_clauses}")
    print(f"Proposed:        {run.proposed_count}")
    print(f"Verified:        {run.verified_count}")
    print(f"Rejected:        {run.rejected_count}")
    print(f"Grounding Rate:  {run.grounding_rate * 100:.1f}%")
    print(f"Tokens In/Out:   {run.tokens_in} / {run.tokens_out}")
    print(f"Cost (USD):      ${run.cost_usd:.4f}")
    print(f"Latency:         {run.latency_ms:.1f} ms")
    is_debug_raw = (
        args.debug_raw
        or os.environ.get("ANALYZE_DEBUG_RAW", "").lower() in ("1", "true", "yes")
        or os.environ.get("DEBUG_RAW", "").lower() in ("1", "true", "yes")
    )
    if is_debug_raw and not args.dry_run:
        debug_dir = os.environ.get("ANALYZE_DEBUG_DIR", "debug_logs")
        print(f"Debug Raw Log:   {debug_dir}/raw_{run.id}.log")
    print(f"\n--- Verified Findings ({len(findings)}) ---")
    for idx, f in enumerate(findings, 1):
        print(f"\n[{idx}] [{f.severity.upper()}] [{f.verification_status.upper()}] {f.title} ({f.category}) - Clause {f.clause_id}")
        if f.match_score is not None:
            print(f"    Match Score: {f.match_score:.1f}%")
        print(f"    Quote:       \"{f.quote}\"")
        print(f"    Explanation: {f.explanation}")



if __name__ == "__main__":
    main()
