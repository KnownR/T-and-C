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
| **Phase 3** | Analysis with structured output (8 UNFAIR-ToS categories) | ⏳ Next |
| **Phase 4** | Citation verifier (Exact $\rightarrow$ fuzzy $\rightarrow$ re-anchor $\rightarrow$ reject) | ⏳ Pending |
| **Phase 5** | Minimal polished UI (Findings list + PDF viewer with highlight) | ⏳ Pending |
| **Phase 6** | Evals & Benchmarks (UNFAIR-ToS eval runner & golden set) | ⏳ Pending |

## Evaluation Results

### Clause Segmentation Boundary Accuracy (Phase 2)
Evaluated across 5 hand-split multi-page Terms of Service benchmark documents:
- `cloud_service_tos.pdf` (6 clauses): **100.00%** F1
- `streaming_platform_tos.pdf` (6 clauses): **100.00%** F1
- `social_network_tos.pdf` (6 clauses): **100.00%** F1
- `ecommerce_marketplace_tos.pdf` (7 clauses): **100.00%** F1
- `saas_subscription_tos.pdf` (6 clauses): **100.00%** F1
- **Overall Boundary Precision:** 100.00% (31/31)
- **Overall Boundary Recall:** 100.00% (31/31)
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

## Decisions & Architecture
1. **Span Bounding Boxes:** PyMuPDF extracts character and word spans directly with `bbox: [x0, y0, x1, y1]`, font size, and font weight/bold flags (checked via bit 16 and font name). Spans are ordered in deterministic reading order ($page \rightarrow y_0 \rightarrow x_0$).
2. **Deterministic Clause Segmentation:** Regex rules detect `1.`, `1.1`, `(a)`, `Section 4.2`, `Clause 7`, and `Article I`, alongside font size/boldness styling. Stable IDs (`C-1`...`C-n`) and bounding box regions are attached to each clause.
3. **Zero-LLM Fallback:** If a document lacks numbering or headings, segmentation deterministically falls back to heading-less paragraphs as clauses.
4. **Known Layout Limitations:**
   - **Multi-column layouts & tables:** Multi-column text flow is currently ingested sequentially in top-to-bottom reading order. Complex magazine-style multi-column text flows and nested HTML/PDF tables are treated as sequential paragraphs rather than performing full geometric 2D column de-warping.
5. **Database Schema:** SQLite stores `documents`, `clauses`, `findings`, and `analysis_runs` with foreign key enforcement enabled (`PRAGMA foreign_keys = ON`).

