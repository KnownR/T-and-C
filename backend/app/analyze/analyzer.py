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
from typing import Any, Callable, Optional, Union
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")
load_dotenv()

import random
import litellm
import litellm.exceptions
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
DEFAULT_ANALYSIS_MODEL = "ollama/qwen2.5:7b-instruct"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_NUM_CTX = 8192
DEFAULT_OLLAMA_MAX_TOKENS = 8192
DEFAULT_MAX_TOKENS = 4096


def get_default_max_tokens(model: str) -> int:
    """Get the default max_tokens generation cap for a model.

    Configurable via ANALYZE_MAX_TOKENS env var (default 8192 for ollama models, 4096 otherwise).
    """
    env_tokens = os.environ.get("ANALYZE_MAX_TOKENS")
    if env_tokens is not None:
        try:
            return int(env_tokens)
        except ValueError:
            pass
    if is_ollama_model(model):
        return DEFAULT_OLLAMA_MAX_TOKENS
    return DEFAULT_MAX_TOKENS


def is_ollama_model(model: str) -> bool:
    """Check if model string targets local Ollama."""
    return model.startswith("ollama/") or model.startswith("ollama")


def is_ollama_connection_error(exc: Exception) -> bool:
    """Check if exception represents an unreachable or connection refused Ollama server."""
    if isinstance(exc, litellm.exceptions.APIConnectionError):
        return True
    exc_str = str(exc).lower()
    keywords = [
        "actively refused",
        "connection refused",
        "failed to connect",
        "connecterror",
        "ollama not reachable",
        "ollamaexception",
        "winerror 10061",
        "errno 111",
        "connection error",
    ]
    return any(kw in exc_str for kw in keywords)


def is_num_ctx_rejected_error(exc: Exception) -> bool:
    """Check if exception was caused by a model/server rejecting num_ctx."""
    if is_ollama_connection_error(exc):
        return False
    exc_str = str(exc).lower()
    keywords = [
        "num_ctx",
        "unrecognized option",
        "unknown option",
        "invalid option",
        "unknown parameter",
        "invalid parameter",
        "extra_body",
        "context length",
        "context window",
        "not supported",
    ]
    if any(kw in exc_str for kw in keywords):
        return True
    return isinstance(
        exc,
        (
            litellm.exceptions.BadRequestError,
            litellm.exceptions.InvalidRequestError,
            litellm.exceptions.UnprocessableEntityError,
        ),
    )


def is_transient_error(exc: Exception) -> bool:
    """Classify whether an exception is transient (e.g. 503, 429, 408, network timeouts) vs permanent."""
    # Definite permanent LiteLLM exceptions: never retry
    permanent_types = (
        litellm.exceptions.AuthenticationError,
        litellm.exceptions.PermissionDeniedError,
        litellm.exceptions.NotFoundError,
        litellm.exceptions.BadRequestError,
        litellm.exceptions.InvalidRequestError,
        litellm.exceptions.UnprocessableEntityError,
        litellm.exceptions.ContextWindowExceededError,
    )
    if isinstance(exc, permanent_types):
        return False

    status_code = (
        getattr(exc, "status_code", None)
        or getattr(exc, "http_status", None)
        or getattr(exc, "code", None)
    )
    if status_code in (400, 401, 403, 404, 422):
        return False

    # Definite transient LiteLLM exceptions
    transient_types = (
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.RateLimitError,
        litellm.exceptions.Timeout,
        litellm.exceptions.APIConnectionError,
        litellm.exceptions.InternalServerError,
        litellm.exceptions.BadGatewayError,
    )
    if isinstance(exc, transient_types):
        return True

    if status_code in (408, 429, 500, 502, 503, 504):
        return True

    # Check error message strings for known transient indicators
    err_str = str(exc).lower()
    transient_keywords = [
        "503",
        "429",
        "408",
        "high demand",
        "spikes in demand",
        "temporarily unavailable",
        "rate limit",
        "resource exhausted",
        "resource_exhausted",
        "connection error",
        "timeout",
        "timed out",
        "try again later",
    ]
    return any(kw in err_str for kw in transient_keywords)


def completion_with_backoff(
    *,
    model: str,
    messages: list[dict[str, str]],
    response_format: Optional[dict[str, Any]] = None,
    temperature: Optional[float] = 0.0,
    max_tokens: Optional[int] = None,
    api_base: Optional[str] = None,
    extra_body: Optional[dict[str, Any]] = None,
    max_transient_retries: Optional[int] = None,
    base_delay: Optional[float] = None,
    max_delay: Optional[float] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
) -> Any:
    """Execute litellm.completion with bounded exponential backoff and jitter for transient errors.

    Prevents nested retries by disabling internal LiteLLM retries (num_retries=0).
    Fails immediately without retries for permanent errors (401, 403, 404, 400)
    and provides clear graceful errors if local Ollama is unreachable.
    Passes num_ctx=8192 and max_tokens=8192 for ollama/* models with graceful fallback if rejected.
    """
    if max_transient_retries is None:
        max_transient_retries = int(os.environ.get("ANALYSIS_MAX_TRANSIENT_RETRIES", "4"))
    if base_delay is None:
        base_delay = float(os.environ.get("ANALYSIS_BASE_BACKOFF", "1.5"))
    if max_delay is None:
        max_delay = float(os.environ.get("ANALYSIS_MAX_BACKOFF", "12.0"))
    if sleep_fn is None:
        sleep_fn = time.sleep

    total_attempts = 1 + max(0, max_transient_retries)

    effective_max_tokens = (
        max_tokens if max_tokens is not None else get_default_max_tokens(model)
    )

    effective_api_base = api_base
    if effective_api_base is None and is_ollama_model(model):
        effective_api_base = os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)

    effective_extra_body = dict(extra_body) if extra_body is not None else {}
    if is_ollama_model(model) and "num_ctx" not in effective_extra_body:
        effective_extra_body["num_ctx"] = DEFAULT_OLLAMA_NUM_CTX

    for attempt in range(1, total_attempts + 1):
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "num_retries": 0,  # Ensure no hidden nested LiteLLM retries
            }
            if response_format is not None:
                kwargs["response_format"] = response_format
            if temperature is not None:
                kwargs["temperature"] = temperature
            if effective_max_tokens is not None:
                kwargs["max_tokens"] = effective_max_tokens
            if effective_api_base is not None:
                kwargs["api_base"] = effective_api_base
            if effective_extra_body:
                kwargs["extra_body"] = dict(effective_extra_body)

            try:
                return litellm.completion(**kwargs)
            except Exception as call_exc:
                if (
                    "extra_body" in kwargs
                    and "num_ctx" in kwargs["extra_body"]
                    and is_num_ctx_rejected_error(call_exc)
                ):
                    fallback_kwargs = dict(kwargs)
                    fallback_extra_body = dict(kwargs["extra_body"])
                    fallback_extra_body.pop("num_ctx", None)
                    if fallback_extra_body:
                        fallback_kwargs["extra_body"] = fallback_extra_body
                    else:
                        fallback_kwargs.pop("extra_body", None)
                    effective_extra_body = fallback_extra_body
                    return litellm.completion(**fallback_kwargs)
                raise

        except Exception as exc:
            if is_ollama_model(model) and is_ollama_connection_error(exc):
                ollama_url = (
                    effective_api_base
                    or os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
                )
                model_tag = model.split("/", 1)[1] if "/" in model else model
                raise RuntimeError(
                    f"Ollama not reachable at {ollama_url} — run ollama serve and ensure {model_tag} is pulled"
                ) from exc

            if not is_transient_error(exc):
                status_val = getattr(exc, "status_code", "permanent")
                print(
                    f"\n[Model API] Error: Non-retryable error ({status_val}) from model '{model}': {exc}"
                )
                raise

            if attempt < total_attempts:
                # Exponential backoff with jitter
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                jitter = random.uniform(0.1, max(0.2, 0.4 * delay))
                sleep_time = min(max_delay, delay + jitter)
                status_val = getattr(exc, "status_code", "503")
                print(
                    f"[Model API] Warning: Upstream transient error ({status_val}) from {model}. "
                    f"Retrying in {sleep_time:.2f}s (retry {attempt}/{max_transient_retries})..."
                )
                sleep_fn(sleep_time)
            else:
                status_val = getattr(exc, "status_code", "503")
                print(
                    f"\n[Model API] Error: Bounded transient retries exhausted ({total_attempts} attempts) "
                    f"for model '{model}' (HTTP {status_val})."
                )
                raise

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
    max_transient_retries: Optional[int] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
    temperature: Optional[float] = 0.0,
    max_tokens: Optional[int] = None,
    api_base: Optional[str] = None,
    extra_body: Optional[dict[str, Any]] = None,
    debug_raw: bool = False,
    debug_dir: Optional[Union[str, Path]] = None,
) -> tuple[AnalysisRunRecord, list[FindingRecord]]:
    """Perform structured legal analysis on a document's clauses.

    Args:
        document: The DocumentRecord to analyze.
        clauses: List of ClauseRecord items segmented from the document.
        lens_id: The lens configuration file identifier (default 'tos').
        dry_run: If True, uses stubbed offline analysis without network API calls.
        max_retries: Number of retries on schema validation failure (default 1).
        model: Model name for LiteLLM completion (env ANALYZE_MODEL or ANALYSIS_MODEL if None).
        db_path: Optional SQLite DB path.
        max_transient_retries: Number of retries on transient errors (HTTP 503, 429, etc.).
        sleep_fn: Optional sleep function for backoff delays (default time.sleep).
        temperature: Temperature for deterministic quoting (default 0.0).
        max_tokens: Token generation limit (default 8192 for ollama, 4096 otherwise; env ANALYZE_MAX_TOKENS).
        api_base: Optional base URL for Ollama or custom endpoint.
        extra_body: Optional extra payload options passed to LiteLLM (e.g. num_ctx=8192).
        debug_raw: If True, writes raw model responses per call to a log file tied to the run ID.
        debug_dir: Optional directory for raw debug output (default env ANALYZE_DEBUG_DIR or 'debug_logs').

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


    # Non-dry-run mode: invoke LiteLLM with transient retry wrapper
    model_name = (
        model
        or os.environ.get("ANALYZE_MODEL")
        or os.environ.get("ANALYSIS_MODEL")
        or DEFAULT_ANALYSIS_MODEL
    )
    is_ollama = is_ollama_model(model_name)
    effective_api_base = api_base or (
        os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL) if is_ollama else None
    )

    effective_max_tokens = (
        max_tokens if max_tokens is not None else get_default_max_tokens(model_name)
    )

    is_debug_raw = (
        debug_raw
        or os.environ.get("ANALYZE_DEBUG_RAW", "").lower() in ("1", "true", "yes")
        or os.environ.get("DEBUG_RAW", "").lower() in ("1", "true", "yes")
    )
    raw_log_path: Optional[Path] = None
    if is_debug_raw:
        resolved_debug_dir = (
            Path(debug_dir)
            if debug_dir
            else Path(os.environ.get("ANALYZE_DEBUG_DIR", "debug_logs"))
        )
        resolved_debug_dir.mkdir(parents=True, exist_ok=True)
        raw_log_path = resolved_debug_dir / f"raw_{run_id}.log"

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
        resp = completion_with_backoff(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=effective_max_tokens,
            api_base=effective_api_base,
            extra_body=extra_body,
            max_transient_retries=max_transient_retries,
            sleep_fn=sleep_fn,
        )

        if hasattr(resp, "usage") and resp.usage:
            # Note on tokens_in: LiteLLM maps Ollama's prompt_eval_count to prompt_tokens.
            # In single-attempt clean runs (e.g. 7B single-pass), tokens_in is ~1,232 for cloud_service_tos.pdf.
            # When validation retries fire (as observed on 3B truncation), total_tokens_in accumulates
            # prompt tokens across both attempts (1,232 + 2,029 = ~3,261 tokens).
            # Additionally, Ollama prompt caching (KV reuse) reports only evaluated tokens on warm cache hits.
            total_tokens_in += getattr(resp.usage, "prompt_tokens", 0) or 0
            total_tokens_out += getattr(resp.usage, "completion_tokens", 0) or 0

        if is_ollama:
            total_cost = 0.0
        else:
            try:
                cost = litellm.completion_cost(completion_response=resp)
                if cost is not None:
                    total_cost += float(cost)
            except Exception:
                pass

        raw_content = ""
        if hasattr(resp, "choices") and resp.choices:
            raw_content = resp.choices[0].message.content or ""

        if is_debug_raw and raw_log_path is not None:
            with open(raw_log_path, "a", encoding="utf-8") as f:
                f.write(
                    f"=== Call Attempt {attempts} | Run: {run_id} | Model: {model_name} ===\n"
                )
                f.write(raw_content)
                f.write("\n\n")

        # Clean potential markdown code blocks
        clean_content = raw_content.strip()
        if clean_content.startswith("```"):
            clean_content = re.sub(r"^```(?:json)?\s*", "", clean_content, flags=re.IGNORECASE)
            clean_content = re.sub(r"\s*```$", "", clean_content)

        try:
            parsed_output = AnalysisOutput.model_validate_json(clean_content)
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
                            '{"findings": [{"category": ..., "severity": ..., "title": ..., "explanation": ..., "clause_id": ..., "quote": ...}]}\n'
                            "Explanations: maximum 2 sentences each. Output only the JSON, no prose, no markdown fences."
                        ),
                    }
                )
            else:
                # Max retries reached; do not retry infinitely
                parsed_output = None
                break

    latency_ms = max(1.0, (time.perf_counter() - t0) * 1000)
    run_cost = 0.0 if is_ollama else total_cost

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
            cost_usd=run_cost,
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
        cost_usd=run_cost,
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


