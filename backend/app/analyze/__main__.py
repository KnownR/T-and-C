"""CLI entrypoint for running legal analysis from terminal."""

import argparse
from pathlib import Path
from backend.app.analyze.analyzer import analyze_document
from backend.app.db import DocumentRecord, init_db, save_clauses, save_document
from backend.app.ingest.pdf import extract_spans_from_pdf
from backend.app.ingest.text import extract_spans_from_text
from backend.app.segment.splitter import split_document_into_clauses


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Terms of Service documents.")
    parser.add_argument("--file", "-f", required=True, help="Path to PDF or text file to analyze.")
    parser.add_argument("--dry-run", action="store_true", help="Run with offline stubbed model at zero API cost.")
    parser.add_argument("--lens", default="tos", help="Lens configuration to use (default: tos).")
    parser.add_argument("--model", default=None, help="LiteLLM model identifier.")
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

    run, findings = analyze_document(
        document=doc_record,
        clauses=clauses,
        lens_id=args.lens,
        dry_run=args.dry_run,
        model=args.model,
    )

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
    print(f"\n--- Verified Findings ({len(findings)}) ---")
    for idx, f in enumerate(findings, 1):
        print(f"\n[{idx}] [{f.severity.upper()}] [{f.verification_status.upper()}] {f.title} ({f.category}) - Clause {f.clause_id}")
        if f.match_score is not None:
            print(f"    Match Score: {f.match_score:.1f}%")
        print(f"    Quote:       \"{f.quote}\"")
        print(f"    Explanation: {f.explanation}")



if __name__ == "__main__":
    main()
