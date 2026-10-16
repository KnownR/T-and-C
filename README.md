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
| **Phase 5** | Minimal polished UI (Findings list + PDF viewer with highlight) | ⏳ Next |
| **Phase 6** | Evals & Benchmarks (UNFAIR-ToS eval runner & golden set) | ⏳ Pending |

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



