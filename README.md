# What Did I Agree To?

> A local-first tool that ingests Terms of Service documents, segments them into clauses, detects unfair clauses with an LLM, **verifies every claim against the source text deterministically**, and displays findings with clickable citations.

## Engineering Principle
**The LLM proposes; deterministic code verifies.**
No finding is ever displayed in the UI without a verified quote matching the original source text.

## North-Star Metrics
- **Grounding Rate:** $\ge 0.85$ (verified findings $\div$ proposed findings)
- **UNFAIR-ToS Benchmark F1:** (To be benchmarked in Phase 6)
- **Golden Set False Positive Count:** (To be tracked in Phase 6)

## Project Status

| Phase | Description | Status |
|---|---|---|
| **Phase 1** | Foundation & Ingestion (FastAPI, SQLite schema, PyMuPDF spans & bboxes, Pasted text) | ✅ Complete |
| **Phase 2** | Segmentation (Rule-based clause splitter with stable IDs & bounding boxes) | ✅ Complete |
| **Phase 3** | Analysis with structured output (8 UNFAIR-ToS categories, prompt from YAML, LiteLLM + dry-run) | ✅ Complete |
| **Phase 4** | Citation verifier (Exact $\rightarrow$ fuzzy $\rightarrow$ re-anchor $\rightarrow$ reject, grounding rate metrics) | ✅ Complete |
| **Phase 5** | Local LLM via Ollama (`ollama/qwen2.5:7b-instruct` default via LiteLLM adapter, $0 cost telemetry) | ✅ Complete |
| **Phase 6** | Minimal polished UI (Findings list + PDF viewer with highlight) | ⏳ Next |
| **Phase 7** | Evals & Benchmarks (UNFAIR-ToS eval runner & golden set) | ⏳ Pending |

## Evaluation Results

### Clause Segmentation Boundary Accuracy (Phase 2)
Evaluated across 6 hand-split multi-page Terms of Service benchmark documents (including adversarial edge cases):
- `cloud_service_tos.pdf` (6 clauses): **100.00%** F1
- `streaming_platform_tos.pdf` (6 clauses): **100.00%** F1
- `social_network_tos.pdf` (6 clauses): **100.00%** F1
- `ecommerce_marketplace_tos.pdf` (7 clauses): **100.00%** F1
- `saas_subscription_tos.pdf` (6 clauses): **100.00%** F1
- `hard_mode_tos.pdf` (8 clauses): **100.00%** F1 (Unnumbered preamble, inline dates/cross-references, nested sub-lists, appendix restart)
- **Overall Boundary Precision:** 100.00% (39/39)
- **Overall Boundary Recall:** 100.00% (39/39)
- **Overall Boundary F1 / Accuracy:** **100.00%**


## Quickstart

### Prerequisites
- Python 3.11+ (Tested on Python 3.13)
- Git

### Setup
```bash
# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install pinned dependencies
pip install -r requirements.txt
```

### Running Tests
```bash
pytest -v
```

### Starting the Backend
```bash
uvicorn backend.app.main:app --reload --port 8000
```

### Ingestion API Example (curl)
Upload a Terms of Service PDF (returns document metadata, spans, and segmented clauses):
```bash
curl -X POST -F "file=@backend/tests/fixtures/cloud_service_tos.pdf" http://localhost:8000/api/documents
```

Or submit pasted text:
```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"text": "1. Acceptance of Terms\nBy using this service, you agree to these terms."}' \
  http://localhost:8000/api/documents
```

### Local Model Setup (Ollama)
Run real legal analysis locally on your machine with zero cloud API keys, complete privacy, and $0 API cost using Ollama and `qwen2.5:7b-instruct` (recommended default):

1. **Pull the Model & Start Ollama:**
   ```bash
   ollama pull qwen2.5:7b-instruct
   ollama serve
   ```
   *By default, Ollama serves on `http://localhost:11434`.*
   *(Note: For resource-constrained hardware, `qwen2.5:3b-instruct` is also supported via `--model ollama/qwen2.5:3b-instruct`).*

2. **Environment Configuration (Optional):**
   - `OLLAMA_BASE_URL`: Base URL for Ollama daemon (defaults to `http://localhost:11434`).
   - `ANALYZE_MODEL`: Default model string (defaults to `ollama/qwen2.5:7b-instruct`).
   - `ANALYZE_MAX_TOKENS`: Maximum output tokens ceiling (defaults to `8192` for Ollama).
   - `ANALYZE_DEBUG_RAW`: Write model raw output per call to `debug_logs/raw_{run_id}.log` (defaults to disabled; or use `--debug-raw`).

3. **Run Real Analysis via CLI:**
   ```bash
   python -m backend.app.analyze --file backend/tests/fixtures/cloud_service_tos.pdf
   ```
   You can override the model on the fly using `--model`:
   ```bash
   python -m backend.app.analyze --file backend/tests/fixtures/cloud_service_tos.pdf --model ollama/qwen2.5:7b-instruct
   ```
   Enable raw response debug logging if needed:
   ```bash
   python -m backend.app.analyze --file backend/tests/fixtures/cloud_service_tos.pdf --debug-raw
   ```

4. **Graceful Failure & Offline Mode:**
   - If Ollama is not running or unreachable, the CLI clearly fails fast with:
     `[Error] Analysis failed: Ollama not reachable at http://localhost:11434 — run ollama serve and ensure qwen2.5:7b-instruct is pulled`
   - Use `--dry-run` to run fully offline with zero network calls and no Ollama daemon required:
     ```bash
     python -m backend.app.analyze --file backend/tests/fixtures/cloud_service_tos.pdf --dry-run
     ```

### Local Model Comparison: 3B vs 7B on `cloud_service_tos.pdf` (Phase 5)

Comprehensive benchmark telemetry and operational behavior comparing local Ollama models on the standard 6-clause fixture `backend/tests/fixtures/cloud_service_tos.pdf`:

| Metric | Qwen 2.5 3B (`ollama/qwen2.5:3b-instruct`) | Qwen 2.5 7B (`ollama/qwen2.5:7b-instruct`) [Default] |
|---|---|---|
| **Parameters** | 3.09B | 7.61B |
| **Proposed Findings** | 1 | **4** |
| **Verified Findings** | 1 | **4** |
| **Rejected Findings** | 0 | 0 |
| **Grounding Rate** | 100.0% (1/1) | **100.0%** (4/4) |
| **Categories Detected** | `unilateral_termination` | `arbitration`, `unilateral_change`, `limitation_of_liability`, `unilateral_termination` |
| **Tokens In** | 3,261 *(accumulated across 2 attempts)* | **1,232** *(single pass)* |
| **Tokens Out** | 4,207 – 8,291 *(verbose / truncated)* | **~469** |
| **Generation Stability** | ⚠️ Truncation-prone, retry loop triggered | ✅ Clean single-shot execution, zero retries |
| **Consistency Across Runs** | Variable; prone to output ceiling blowout | **Rock-solid & stable across N runs** |
| **Latency** | ~75.8s | **~69s** |
| **API Cost** | **$0.0000** | **$0.0000** |

#### Verified Finding Details (7B Model, 4 Findings)
1. **[RED] [VERIFIED] Mandatory Arbitration & Class Action Waiver (`arbitration`) - Clause C-5**
   - **Match Score:** 100.0%
   - **Quote:** `"Any dispute, controversy, or claim arising out of or relating to this agreement shall be settled exclusively by confidential binding arbitration in Wilmington, Delaware"`
   - **Explanation:** Forces consumer disputes into private binding arbitration and waives class action litigation rights.
2. **[RED] [VERIFIED] Unilateral Modification of Terms (`unilateral_change`) - Clause C-3**
   - **Match Score:** 100.0%
   - **Quote:** `"CloudScale reserves the right to modify, amend, or replace these Terms at any time at its sole discretion without prior notice to you."`
   - **Explanation:** The provider reserves discretion to amend terms, pricing, or features without advance bilateral agreement.
3. **[RED] [VERIFIED] Limitation of Liability and Damages Cap (`limitation_of_liability`) - Clause C-4**
   - **Match Score:** 100.0%
   - **Quote:** `"in no event shall CloudScale, its affiliates, or directors be liable for any indirect, incidental, punitive, or consequential damages"`
   - **Explanation:** Disclaims consequential and incidental damages and imposes an unreasonably low liability ceiling.
4. **[RED] [VERIFIED] Unilateral Account Termination (`unilateral_termination`) - Clause C-6**
   - **Match Score:** 100.0%
   - **Quote:** `"CloudScale may suspend or terminate your access to the Services immediately, with or without cause, and without prior notice or liability."`
   - **Explanation:** Grants the service provider unilateral authority to terminate or suspend user access immediately without cause or notice.

#### Consistency Across Runs Note
- **7B (`qwen2.5:7b-instruct`):** Evaluated across multiple identical runs. Produces consistent results every time: exactly the same 4 findings, 100% citation grounding, concise explanations (~469 tokens out), no retry triggers, and ~69s execution latency.
- **3B (`qwen2.5:3b-instruct`):** Even after prompt tightening (e.g. limiting explanations to 2 sentences and forbidding prose/markdown fences), the 3B model is verbose and prone to repeating output patterns, exceeding token caps and forcing the validation retry path to fire, which yields only a single finding.

#### Honest Accounting: `tokens_in` Discrepancy (1,232 vs ~3,261)
Why did the 7B report `1,232` tokens in, while the 3B reported `~3,261` for the exact same document?
1. **Base Prompt Length:** The actual single-pass prompt (system instructions + 8-category YAML rubric + segmented document clauses) is ~1,232 tokens. On the 7B, the model produces valid structured output on Attempt 1, so `tokens_in = 1,232`.
2. **Retry Path Accumulation on 3B:** When the 3B run truncated and failed schema validation, the analysis engine automatically retried. The retry request fed back the conversation context (including the prior assistant output and validation error), and the telemetry counter accumulated tokens across both attempts (`1,232 + 2,029 = 3,261`).
3. **Ollama Prompt Caching (KV Reuse):** Ollama's `prompt_eval_count` metric reports tokens actively evaluated by the inference engine. On warm repeated runs with shared prefix context, Ollama reuses KV cache states, while cold runs evaluate the entire prompt.

#### Known Limitation & Honest Evaluation: Browsewrap Blindness (`contract_by_using`)
- **Observed Behavior:** While the 7B model successfully extracts 4 critical unfair clauses (`arbitration`, `unilateral_change`, `limitation_of_liability`, `unilateral_termination`), it does **not** flag `contract_by_using` (browsewrap) on Clause C-1 (`"By accessing or using the CloudScale Services, you agree to be bound by these Terms of Service..."`), which our deterministic dry-run heuristic flags.
- **Root Cause:** Likely **low-salience blindness** — standard introductory agreement-by-use statements are often interpreted by instruction-tuned general LLMs as routine preamble rather than an aggressive unfair clause unless prompted explicitly.
- **Measurement Plan:** We intentionally avoid ad-hoc prompt hacking or one-off workarounds on this single fixture. Instead, per-category recall will be systematically evaluated across the full UNFAIR-ToS benchmark in **Phase 6** before adjusting prompt instructions.

#### Privacy Guarantee: Raw Debug Logs
- Running with `--debug-raw` (or `ANALYZE_DEBUG_RAW=1`) dumps the exact raw model response per call attempt into `debug_logs/raw_{run_id}.log`.
- Because raw LLM responses contain unredacted contract document text, `debug_logs/` and `*.log` are strictly added to `.gitignore`.
- This ensures a privacy-first guarantee: untrusted contract texts and raw LLM traces remain strictly local on the user's filesystem and are never committed to git.



### Analysis CLI (Dry-Run Mode)
Analyze any Terms of Service document offline at zero cost using deterministic rubric pattern matching:
```bash
python -m backend.app.analyze --file backend/tests/fixtures/cloud_service_tos.pdf --dry-run
```

Or trigger analysis via the FastAPI endpoint:
```bash
curl -X POST "http://localhost:8000/api/documents/{doc_id}/analyze?dry_run=true"
curl -X GET "http://localhost:8000/api/documents/{doc_id}/findings"
```

## Decisions & Architecture
1. **Span Bounding Boxes:** PyMuPDF extracts character and word spans directly with `bbox: [x0, y0, x1, y1]`, font size, and font weight/bold flags (checked via bit 16 and font name). Spans are ordered in deterministic reading order ($page \rightarrow y_0 \rightarrow x_0$).
2. **Deterministic Clause Segmentation:** Regex rules detect `1.`, `1.1`, `(a)`, `Section 4.2`, `Clause 7`, and `Article I`, alongside font size/boldness styling. Stable IDs (`C-1`...`C-n`) and bounding box regions are attached to each clause.
3. **Zero-LLM Fallback:** If a document lacks numbering or headings, segmentation deterministically falls back to heading-less paragraphs as clauses.
4. **Structured Output & Dynamic Rubric:** Findings schema enforces `{category, severity, title, explanation, clause_id, quote}`. The rubric is built entirely from `lenses/tos.yaml` (8 UNFAIR-ToS categories: arbitration, unilateral change, content removal, jurisdiction, choice of law, limitation of liability, unilateral termination, contract by using); no categories are hardcoded in Python.
5. **Prompt Grounding & Untrusted Input:** The document clauses are wrapped in `<document>` tags explicitly flagged as untrusted user data. Prompts strictly instruct the model that every quote must be an exact verbatim substring of its cited clause.
6. **Robust Validation Recovery:** On schema validation failure, the system retries exactly ONCE with the error message fed back. On repeated failure, it logs the failure in `analysis_runs` with `proposed_count=0` and moves on without infinite loops.
7. **Per-Run Telemetry & Dry-Run Mode:** Every run records model, tokens in/out, cost USD, latency ms, and proposed/rejected counts. The `--dry-run` stubbed mode enables full end-to-end testing without cloud API keys or costs.
8. **Deterministic Citation Verification Pipeline (Phase 4 centerpiece):**
   - **Normalization:** Collapses whitespace, unifies curly quotes (`“` `”` `‘` `’` `‵` `′` $\rightarrow$ `"` `'`), unifies all Unicode dashes (`–` `—` `−` `―` $\rightarrow$ `-`), strips surrounding spaces around hyphens, and lowercases.
   - **Stage 1 (Exact Substring):** If normalized quote is an exact substring of the cited clause $\rightarrow$ status `verified` (`match_score = 100.0`).
   - **Stage 2 (Fuzzy Near-Miss):** If `rapidfuzz.fuzz.partial_ratio >= 90.0` against the cited clause $\rightarrow$ status `verified_fuzzy` (persisting exact `match_score`).
   - **Stage 3 (Re-Anchoring):** If the quote is not in the cited clause, searches ALL other clauses. If found $\rightarrow$ updates `clause_id` to the matching clause and marks status `reanchored`.
   - **Stage 4 (Rejection & Grounding Guarantee):** Else $\rightarrow$ marks `rejected`. **Rejected findings are NEVER stored in the database and NEVER returned in the API / UI.** Nonexistent clause IDs are safely rejected without crashing.
   - **Grounding Rate Telemetry:** Every run computes and persists `grounding_rate = verified_count / proposed_count` along with `proposed_count`, `verified_count`, and `rejected_count` in `analysis_runs`.
9. **Known Layout Limitations:**
   - **Multi-column layouts & tables:** Multi-column text flow is currently ingested sequentially in top-to-bottom reading order. Complex magazine-style multi-column text flows and nested HTML/PDF tables are treated as sequential paragraphs rather than performing full geometric 2D column de-warping.
10. **Database Schema:** SQLite stores `documents`, `clauses`, `findings`, and `analysis_runs` with foreign key enforcement enabled (`PRAGMA foreign_keys = ON`).
11. **Local LLM via Ollama & LiteLLM Seam (Phase 5):**
    - Analysis pipeline defaults to `ollama/qwen2.5:7b-instruct` communicating over LiteLLM to local Ollama (`http://localhost:11434`, overridable via `OLLAMA_BASE_URL`).
    - Model selection is dynamically configurable via `--model` CLI flag or `ANALYZE_MODEL` environment variable.
    - Zero cost ($0.0000) telemetry automatically enforced for all `ollama/*` models.
    - Deterministic parameters: `temperature=0.0` and a default `max_tokens=8192` ceiling for Ollama models (configurable via `ANALYZE_MAX_TOKENS`).
    - Raw debug logging: `--debug-raw` flag writes exact verbatim model responses per call to `debug_logs/raw_{run_id}.log` (strictly ignored by `.gitignore`).
    - Graceful failure: if the local Ollama daemon is down, an explicit actionable error informs the user to run `ollama serve` and pull the model.
    - Full offline independence: `--dry-run` retains 100% offline functionality without touching the network or requiring Ollama.



