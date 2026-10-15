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
| **Phase 2** | Segmentation (Rule-based clause splitter with stable IDs & bounding boxes) | ⏳ Next |
| **Phase 3** | Analysis with structured output (8 UNFAIR-ToS categories) | ⏳ Pending |
| **Phase 4** | Citation verifier (Exact $\rightarrow$ fuzzy $\rightarrow$ re-anchor $\rightarrow$ reject) | ⏳ Pending |
| **Phase 5** | Minimal polished UI (Findings list + PDF viewer with highlight) | ⏳ Pending |
| **Phase 6** | Evals & Benchmarks (UNFAIR-ToS eval runner & golden set) | ⏳ Pending |

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
Upload a Terms of Service PDF:
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
1. **Span Bounding Boxes:** PyMuPDF (`fitz`) extracts character and word spans directly with `bbox: [x0, y0, x1, y1]`, font size, and font weight/bold flags. Spans are ordered in deterministic reading order (page ascending, vertical $y_0$ ascending, horizontal $x_0$ ascending).
2. **Deterministic Fallback:** Pasted text is assigned to a single pseudo-page (`page=1`) with `bbox=None`.
3. **Database Schema:** SQLite stores `documents`, `clauses`, `findings`, and `analysis_runs` with foreign key enforcement enabled (`PRAGMA foreign_keys = ON`).
