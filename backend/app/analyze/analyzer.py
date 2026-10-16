"""Analysis engine with structured output enforcement via LiteLLM and Pydantic.

Rules:
- Schema enforcement for findings: {category, severity, title, explanation, clause_id, quote}
- The lens prompt is constructed dynamically from YAML (no rubric hardcoded in Python).
- The document is passed inside <document> tags marked as untrusted data.
- Strict instructions that every quote must be a verbatim substring of its cited clause.
- Schema validation failure: retry ONCE feeding back the error; on 2nd failure record failure in analysis_runs.
- Record per run: model, tokens in/out, cost, latency, proposed/rejected counts.
- Dry-run mode using a stubbed model for offline $0 cost execution in tests.
- Deduplication of findings by (category, clause_id).
"""

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")
load_dotenv()

import litellm
from pydantic import ValidationError


from backend.app.analyze.lens import load_lens
from backend.app.analyze.prompt import build_analysis_prompt
from backend.app.analyze.schemas import AnalysisOutput, Finding
from backend.app.db import (
    AnalysisRunRecord,
    ClauseRecord,
    DocumentRecord,
    FindingRecord,
    save_analysis_run,
    save_findings,
)
from backend.app.verify import verify_findings

# Single configuration location for default analysis model
DEFAULT_ANALYSIS_MODEL = "gemini/gemini-2.5-flash"

# Dry-run pattern definitions mapping category -> list of regex patterns and metadata
DRY_RUN_CATEGORY_RULES = [

    {
        "category": "arbitration",
        "patterns": [
            r"settled exclusively by confidential binding arbitration[^.]*",
            r"resolved exclusively through individual binding arbitration[^.]*",
            r"decided by binding arbitration[^.]*",
            r"waive any right to participate as a member in any class action[^.]*",
            r"waive the right to trial by jury and class proceedings[^.]*",
            r"[^.]*\b(?:binding arbitration|class action)\b[^.]*",
        ],
        "title": "Mandatory Arbitration & Class Action Waiver",
        "explanation": "Forces consumer disputes into private binding arbitration and waives class action litigation rights.",
    },
    {
        "category": "unilateral_change",
        "patterns": [
            r"reserves the right to modify, amend, or replace these Terms at any time[^.]*",
            r"modify API features with thirty days prior notice[^.]*",
            r"[^.]*\breserves the right to modify\b[^.]*",
            r"[^.]*\bwithout prior notice to you\b[^.]*",
        ],
        "title": "Unilateral Modification of Terms",
        "explanation": "The provider reserves discretion to amend terms, pricing, or features without advance bilateral agreement.",
    },
    {
        "category": "limitation_of_liability",
        "patterns": [
            r"in no event shall CloudScale's total aggregate liability exceed[^.]*",
            r"in no event shall either party's aggregate liability exceed[^.]*",
            r"Total liability of Nexus for any claim hereunder shall be capped at[^.]*",
            r"liability to any merchant or buyer exceed[^.]*",
            r"[^.]*\bin no event shall (?:CloudScale|Nexus|MarketHub|either party)[^.]*be liable for any indirect[^.]*",
            r"[^.]*\blimitation of liability\b[^.]*",
        ],
        "title": "Limitation of Liability and Damages Cap",
        "explanation": "Disclaims consequential and incidental damages and imposes an unreasonably low liability ceiling.",
    },
    {
        "category": "unilateral_termination",
        "patterns": [
            r"may suspend or terminate your access to the Services immediately[^.]*",
            r"terminate any user account at its sole discretion[^.]*",
            r"may suspend, restrict, or terminate your merchant or buyer account at any time[^.]*",
            r"[^.]*\bterminate your access[^.]*without prior notice\b[^.]*",
        ],
        "title": "Unilateral Account Termination",
        "explanation": "Grants the service provider unilateral authority to terminate or suspend user access immediately without cause or notice.",
    },
    {
        "category": "content_removal",
        "patterns": [
            r"reserves the absolute right to remove, edit, or block any content[^.]*",
            r"may screen, monitor, or remove any user content without notice[^.]*",
            r"[^.]*\bremove, edit, or block any content\b[^.]*",
        ],
        "title": "Discretionary Content Removal",
        "explanation": "Allows the provider to remove or alter user-submitted content without prior notice, justification, or appeal.",
    },
    {
        "category": "jurisdiction",
        "patterns": [
            r"instituted exclusively in state or federal courts in New York County[^.]*",
            r"exclusive jurisdiction of the state and federal courts located in New Castle County[^.]*",
            r"[^.]*\bexclusively in state or federal courts\b[^.]*",
        ],
        "title": "Exclusive Forum Selection",
        "explanation": "Requires users to litigate any disputes in an inconvenient remote court forum.",
    },
    {
        "category": "choice_of_law",
        "patterns": [
            r"governed by and construed in accordance with the laws of the State of New York[^.]*",
            r"governed by the laws of California[^.]*",
            r"[^.]*\bgoverned by and construed in accordance with the laws of\b[^.]*",
        ],
        "title": "Choice of Governing Law",
        "explanation": "Designates governing jurisdiction law which may limit user rights under local consumer protection statutes.",
    },
    {
        "category": "contract_by_using",
        "patterns": [
            r"By browsing, downloading, streaming, or otherwise accessing any portion of the StreamVerse service[^.]*",
            r"By accessing or using the CloudScale Services, you agree to be bound[^.]*",
            r"By accessing or using the services, you agree to be bound[^.]*",
            r"[^.]*\bcontract is formed\b[^.]*",
        ],
        "title": "Contract Formed by Mere Usage",
        "explanation": "Asserts that browsing, downloading, or merely visiting the website binds the user to legal terms.",
    },
]


def _run_dry_run_analysis(
    lens_data: dict[str, Any], clauses: list[ClauseRecord]
) -> list[Finding]:
    """Deterministic offline analyzer matching rubric rules to clauses with verbatim quotes."""
    findings: list[Finding] = []
    category_meta = {c["id"]: c for c in lens_data.get("categories", [])}

    for clause in clauses:
        clause_text = clause.text
        for rule in DRY_RUN_CATEGORY_RULES:
            cat_id = rule["category"]
            if cat_id not in category_meta:
                continue
            meta = category_meta[cat_id]
            default_sev = meta.get("default_severity", "yellow")

            matched_quote: Optional[str] = None
            for pat in rule["patterns"]:
                match = re.search(pat, clause_text, re.IGNORECASE)
                if match:
                    # Clean and ensure the extracted quote is a verbatim substring of clause_text
                    raw_matched = match.group(0).strip()
                    if raw_matched in clause_text:
                        matched_quote = raw_matched
                        break

            if matched_quote:
                finding = Finding(
                    category=cat_id,
                    severity=default_sev,
                    title=rule["title"],
                    explanation=rule["explanation"],
                    clause_id=clause.id,
                    quote=matched_quote,
                )
                findings.append(finding)

    return findings


def analyze_document(
    document: DocumentRecord,
    clauses: list[ClauseRecord],
    lens_id: str = "tos",
    dry_run: bool = False,
    max_retries: int = 1,
    model: Optional[str] = None,
    db_path: Optional[str] = None,
) -> tuple[AnalysisRunRecord, list[FindingRecord]]:
    """Perform structured legal analysis on a document's clauses.

    Args:
        document: The DocumentRecord to analyze.
        clauses: List of ClauseRecord items segmented from the document.
        lens_id: The lens configuration file identifier (default 'tos').
        dry_run: If True, uses stubbed offline analysis without network API calls.
        max_retries: Number of retries on schema validation failure (default 1).
        model: Model name for LiteLLM completion (env ANALYSIS_MODEL if None).
        db_path: Optional SQLite DB path.

    Returns:
        tuple[AnalysisRunRecord, list[FindingRecord]]
    """
    t0 = time.perf_counter()
    lens_data = load_lens(lens_id)
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    if dry_run:
        # Dry-run stubbed mode: offline, no API key required, zero API cost
        findings_raw = _run_dry_run_analysis(lens_data, clauses)
        model_name = "dry-run-stub"
        latency_ms = max(1.0, (time.perf_counter() - t0) * 1000)
        tokens_in = max(50, len(document.raw_text) // 4)
        tokens_out = max(20, sum(len(f.quote) + len(f.explanation) for f in findings_raw) // 4)
        cost_usd = 0.0

        # Deduplicate by (category, clause_id)
        seen = set()
        deduped: list[Finding] = []
        for f in findings_raw:
            key = (f.category, f.clause_id)
            if key not in seen:
                seen.add(key)
                deduped.append(f)

        # Verify findings deterministically
        verified_records, verified_count, rejected_count, grounding_rate = verify_findings(
            findings=deduped,
            clauses=clauses,
            document_id=document.id,
            analysis_run_id=run_id,
        )

        run = AnalysisRunRecord(
            id=run_id,
            document_id=document.id,
            model=model_name,
            lens=lens_id,
            total_clauses=len(clauses),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            proposed_count=len(deduped),
            verified_count=verified_count,
            rejected_count=rejected_count,
            grounding_rate=grounding_rate,
        )
        save_analysis_run(run, db_path=db_path)
        save_findings(verified_records, db_path=db_path)
        return run, verified_records


    # Non-dry-run mode: invoke LiteLLM
    model_name = model or os.environ.get("ANALYSIS_MODEL", DEFAULT_ANALYSIS_MODEL)
    system_prompt, user_prompt = build_analysis_prompt(lens_data, clauses)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0
    attempts = 0
    max_attempts = 1 + max_retries
    parsed_output: Optional[AnalysisOutput] = None

    while attempts < max_attempts:
        attempts += 1
        resp = litellm.completion(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
        )

        if hasattr(resp, "usage") and resp.usage:
            total_tokens_in += getattr(resp.usage, "prompt_tokens", 0) or 0
            total_tokens_out += getattr(resp.usage, "completion_tokens", 0) or 0

        try:
            cost = litellm.completion_cost(completion_response=resp)
            if cost is not None:
                total_cost += float(cost)
        except Exception:
            pass

        raw_content = ""
        if hasattr(resp, "choices") and resp.choices:
            raw_content = resp.choices[0].message.content or ""

        try:
            parsed_output = AnalysisOutput.model_validate_json(raw_content)
            # Schema validation succeeded
            break
        except (ValidationError, json.JSONDecodeError) as err:
            if attempts < max_attempts:
                # Retry ONCE, feeding back the validation error
                messages.append({"role": "assistant", "content": raw_content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Schema validation failed: {err}\n"
                            "Please correct your response to strictly adhere to the required JSON format:\n"
                            '{"findings": [{"category": ..., "severity": ..., "title": ..., "explanation": ..., "clause_id": ..., "quote": ...}]}'
                        ),
                    }
                )
            else:
                # Max retries reached; do not retry infinitely
                parsed_output = None
                break

    latency_ms = max(1.0, (time.perf_counter() - t0) * 1000)

    # If parsing completely failed after retries, record failure in analysis_runs and move on
    if parsed_output is None:
        run = AnalysisRunRecord(
            id=run_id,
            document_id=document.id,
            model=model_name,
            lens=lens_id,
            total_clauses=len(clauses),
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost_usd=total_cost,
            latency_ms=latency_ms,
            proposed_count=0,
            verified_count=0,
            rejected_count=0,
        )
        save_analysis_run(run, db_path=db_path)
        return run, []

    # Deduplicate findings by (category, clause_id)
    seen = set()
    deduped = []
    for f in parsed_output.findings:
        key = (f.category, f.clause_id)
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    # Verify findings deterministically
    verified_records, verified_count, rejected_count, grounding_rate = verify_findings(
        findings=deduped,
        clauses=clauses,
        document_id=document.id,
        analysis_run_id=run_id,
    )

    run = AnalysisRunRecord(
        id=run_id,
        document_id=document.id,
        model=model_name,
        lens=lens_id,
        total_clauses=len(clauses),
        tokens_in=total_tokens_in,
        tokens_out=total_tokens_out,
        cost_usd=total_cost,
        latency_ms=latency_ms,
        proposed_count=len(deduped),
        verified_count=verified_count,
        rejected_count=rejected_count,
        grounding_rate=grounding_rate,
    )
    save_analysis_run(run, db_path=db_path)
    save_findings(verified_records, db_path=db_path)
    return run, verified_records



if __name__ == "__main__":
    from backend.app.analyze.__main__ import main

    main()


