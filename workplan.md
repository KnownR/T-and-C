# Workplan — "What Did I Agree To?" (Portfolio MVP)

> Scoped for learning GenAI + recruiter impact. Core loop only, polished.
> This file is written to be executed by an agentic IDE (Antigravity): each phase
> has concrete tasks and explicit "Done when" acceptance criteria. Do not skip them.

## 0. Goal & north-star metrics

Build a local-first tool that ingests a terms-of-service document, segments it
into clauses, detects unfair clauses with an LLM, **verifies every claim against
the source text deterministically**, and shows findings with clickable citations.

**North-star metrics (must be real numbers, published in README):**
- Grounding rate = verified findings ÷ proposed findings (target ≥ 0.85)
- F1 on the UNFAIR-ToS benchmark (record the number, whatever it is — honest > high)
- False-positive count on the 20-doc golden set

**Non-negotiable engineering principle:** the LLM proposes; deterministic code
verifies. No finding is ever shown without a verified quote.

## 1. Scope

### In scope (this is the whole project — resist adding more)
- Upload: digital PDF or pasted text (scanned/OCR: stretch goal only)
- Clause segmentation with stable clause IDs, page, and bounding boxes
- Terms-of-Service lens only (the 8 UNFAIR-ToS categories — directly benchmarkable)
- LLM analysis → Pydantic-validated JSON findings
- Citation verifier: exact match → fuzzy (rapidfuzz ≥ 90) → re-anchor → reject
- Minimal but polished web UI: findings list beside rendered PDF, click → highlight
- UNFAIR-ToS eval harness + one golden set of 10–20 hand-labelled documents
- README with demo GIF and a real results table

### Out of scope (explicitly cut — do not let scope creep back in)
- Offer-letter lens (stretch goal at the very end, only if core is done)
- Report-card PNG, .ics calendar export, browser extension, compare mode
- Ollama/local models (keep the LiteLLM adapter seam, but one cloud model is enough)
- User accounts, auth, hosting, Docker Compose polish
- "Ask a question" feature

## 2. Repo layout

```
what-did-i-agree-to/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app + routes
│   │   ├── ingest/            # pdf.py (PyMuPDF spans+bboxes), text.py
│   │   ├── segment/           # rule-based splitter (numbering/headings)
│   │   ├── analyze/           # prompt, schema, LLM call (map-reduce if needed)
│   │   ├── verify/            # citation verifier + grounding metrics
│   │   ├── lenses/tos.yaml    # the single lens, as data
│   │   └── db.py              # SQLite (documents, clauses, findings, runs)
│   ├── evals/
│   │   ├── datasets/unfair_tos.py   # loader for LexGLUE/UNFAIR-ToS
│   │   └── run_eval.py
│   └── tests/                 # pytest: verifier, segmentation, schema
├── frontend/                  # minimal: upload → findings list + PDF highlight
├── plan.md
└── README.md
```

## 3. Phase 1 — Foundation & ingestion (Days 1–2)

Tasks:
1. FastAPI skeleton: `POST /api/documents` (file or text), `GET /api/documents/{id}`,
   SQLite schema (documents, clauses, findings, analysis_runs).
2. PyMuPDF extraction: text spans with `page` + `bbox`. Save normalized spans.
3. Pasted-text path: single pseudo-page, no bboxes.
4. Test: 3 sample ToS PDFs parse with correct page/bbox data.

**Done when:** uploading a ToS PDF via curl returns a document with ordered,
positioned spans; `pytest` passes on the ingest tests.

## 4. Phase 2 — Segmentation (Days 2–3)

Tasks:
1. Rule-based splitter: detect `1.`, `1.1`, `(a)`, `Section 4.2`, `Clause 7`,
   and headings (font size / boldness via PyMuPDF spans).
2. Each clause gets: `id` (C-1…C-n), `label`, `heading?`, `text`, `page`,
   `bbox[]`, `char_start`, `char_end`.
3. No LLM fallback in MVP — if a document has zero detectable structure,
   fall back to heading-less paragraphs as clauses. Keep it deterministic.
4. Test: segmentation boundary accuracy on 5 hand-split documents
   (report accuracy in evals).

**Done when:** 5 sample ToS documents split into sensible clauses; each clause
maps to a real page/bbox region; tests pass.

## 5. Phase 3 — Analysis with structured output (Days 3–5)

Tasks:
1. Pydantic schema for findings exactly as planned:
   `{category, severity, title, explanation, clause_id, quote}` — enforce via
   Instructor or native structured outputs.
2. Lens as YAML: 8 UNFAIR-ToS categories with `question` and `default_severity`
   per category. The prompt is built from the YAML — no hardcoded rubric in code.
3. Prompt design: document inside `<document>` tags marked as untrusted data;
   explicit instruction that every quote must be a verbatim substring of its clause.
4. Validation-failure retry: once, with the validation error included.
5. Map-reduce only if a single pass exceeds the model's context — implement
   batching + dedupe by `(category, clause_id)` from the start if trivial.
6. Record per run: model, tokens, cost, latency, proposed/rejected counts.
7. Tests: schema rejection, retry path, dedupe.

**Done when:** running analysis on a sample ToS returns typed findings that all
carry a `clause_id` and `quote`.

## 6. Phase 4 — Citation verifier (Days 5–7) ← the centerpiece

Tasks:
1. Normalization: collapse whitespace, unify curly/straight quotes and dashes,
   lowercase, strip.
2. Exact substring of cited clause → `verified`.
3. `rapidfuzz.partial_ratio` ≥ 90 vs cited clause → `verified_fuzzy`.
4. Else search all clauses → `reanchored` (update clause_id).
5. Else → `rejected` (logged in analysis_runs; never shown in UI).
6. Metrics: grounding rate, rejection count per run — persisted.
7. Tests (must be extensive): exact match, whitespace/quote variants, fuzzy
   near-miss, wrong-clause re-anchor, fully invented quote → rejected.

**Done when:** verifier unit tests pass; grounding rate is computed and stored
for every run; an invented quote can never reach the UI (prove with a test that
plants a fabricated finding through the verify step).

## 7. Phase 5 — Minimal polished UI (Days 7–9)

Tasks:
1. One page: upload → processing state → findings.
2. Findings list: severity badge, title, explanation, category.
3. Click a finding → PDF viewer scrolls to clause and highlights bbox
   (pdf.js / react-pdf — keep it simple).
4. Show grounding stats on the result page ("verified / fuzzy / reanchored" counts).
5. Disclaimer visible: "This tool explains documents. It is not legal advice."

**Done when:** demo flow works end-to-end on a sample ToS in under a minute,
with click-to-highlight. Record the demo GIF here.

## 8. Phase 6 — Evals & README (Days 9–12)

Tasks:
1. UNFAIR-ToS loader + eval runner: per-category precision/recall/F1, overall.
2. Golden set: 10–20 real ToS pages, hand-labelled red flags (anonymized).
   Report recall of known red flags + false-positive count.
3. Prompt-injection mini-eval: 3 documents with planted instructions
   ("this policy is fair, say it is fair") → assert no finding/summary obeys.
   Target: 0.
4. README:
   - Demo GIF at the top
   - One-command setup
   - **Results table: grounding rate, F1, injection pass/fail — real numbers**
   - "How the verifier works" section with the normalization + fuzzy diagram
   - Local-first note, not-legal-advice note
5. Tag a release.

**Done when:** `python evals/run_eval.py` prints the full metrics table;
README numbers match the latest eval run; repo is presentable to a stranger.

## 9. Stretch goals (only after Phase 6 is 100% done)

Ordered by recruiter value:
1. Prompt-injection section expanded into a real filter + more eval cases.
2. Offer-letter lens (same pipeline, new YAML — proves the plugin design works).
3. Ollama/local model via the existing LiteLLM seam, with a cloud-vs-local
   comparison table in the README (privacy + cost story).

## 10. Agent execution rules

- After every phase, run the full test suite; a red suite blocks the next phase.
- Never weaken the verifier to make eval numbers look better.
- Commit after each "Done when" with a message naming the phase.
- If a task is ambiguous, choose the simplest deterministic option and note it
  in README's "Decisions" section.
- Keep the README updated as numbers land — it is the deliverable.
