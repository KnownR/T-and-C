# What Did I Agree To? — Project Plan

> Working name. Final name is an open decision (see [Open decisions](#13-open-decisions)).

## 1. Vision

Paste, upload or scan any terms of service, rental lease, offer letter or insurance
policy. In under a minute you get:

- **Red flags**: clauses that work against you, ranked by severity
- **Obligations**: what *you* must do, and what *they* must do
- **Deadlines and money**: dates, notice periods, fees, deposits, penalties
- **Plain-language summary**: what the document says, without the jargon

Every claim links to the exact clause it came from. Click a finding and the
document scrolls to the highlighted text. If the tool can't point to the source,
it doesn't make the claim.

**Positioning:** local-first and privacy-respecting. Your lease never has to leave
your laptop.

**Not legal advice:** the tool explains documents. It does not tell anyone what
to sign. This is stated in the UI and the README.

## 2. Target users

| User | Document | What they want to know |
|---|---|---|
| Students and job switchers | Offer letters | Real in-hand pay, bond clauses, notice period, non-compete |
| Tenants | Rental agreements | Lock-in period, deposit refund terms, maintenance, eviction terms |
| Everyone online | Terms of service and privacy policies | Data sharing, arbitration, the right to change terms without notice |
| Policy holders | Insurance policies | Exclusions, waiting periods, claim deadlines |

## 3. Scope

### MVP (v0.1): in scope
- Upload a PDF (digital or scanned), an image, or pasted text
- Clause segmentation with stable clause IDs and page positions
- Two lenses: **Terms of Service** and **Offer Letter**
- Findings with severity, explanation, cited clause and verified quote
- Citation verifier: unverified findings are never shown
- Side-by-side UI: findings list next to a PDF viewer with highlights
- Deadline extraction and `.ics` calendar export
- Shareable one-page "report card" image
- Cloud model **and** local model (Ollama) support
- Eval harness with published results on UNFAIR-ToS

### Later (v0.2+)
- Lease and insurance lenses
- "Ask a question" about the document (for example, "Can I sublet?"), answered with citations
- Terms-of-service change tracker: watch policy URLs, show diffs in plain English, public feed
- Compare two documents (two offer letters, or two leases)
- Browser extension that analyses terms at the "I agree" checkbox
- Hindi and regional-language support
- Dispute or complaint letter drafter

### Out of scope
- Legal advice or "should I sign?" recommendations
- User accounts in v0.1 (single-user, local)
- Storing documents by default

## 4. Architecture

```
┌──────────────┐   upload    ┌───────────────────────── FastAPI ─────────────────────────┐
│  Next.js UI  │ ──────────▶ │ 1. Ingest     PDF/image/text → text + page + bbox (+ OCR)  │
│              │             │ 2. Segment    → clauses [C-1 … C-n] with positions        │
│ findings  ◀──┼─── SSE ──── │ 3. Analyze    lens rubric + clauses → LLM → typed JSON    │
│ PDF viewer   │             │ 4. Verify     quote ∈ cited clause? keep : re-anchor/drop  │
│ report card  │             │ 5. Extract    deadlines, money → normalized values / .ics  │
└──────────────┘             └──────────────┬──────────────────────────────┬─────────────┘
                                            │                              │
                                       SQLite (DB)               LLM adapter (LiteLLM)
                                                                 ├─ cloud API
                                                                 └─ Ollama (local)
```

### Core principle
**The LLM proposes; deterministic code verifies.** The model never gets the last
word on what the document says.

## 5. Pipeline in detail

### 5.1 Ingestion
- Digital PDFs: **PyMuPDF** extracts text spans with page numbers and bounding boxes.
- Complex layouts: **Docling** as a fallback (headings, tables, nested lists).
- Scanned PDFs and photos: **Tesseract** (local) or a vision-capable model (cloud).
  A page counts as "scanned" when it has almost no extractable text.
- Pasted text: treated as a single page with no bounding boxes.
- Output: a normalized `Document` with ordered text spans and their positions.

### 5.2 Clause segmentation
1. **Rule-based first:** detect numbering (`1.`, `1.1`, `(a)`, `(iv)`, `Section 4.2`,
   `Clause 7`) and headings (by font size or boldness from PyMuPDF).
2. **LLM fallback:** for unnumbered prose, such as many terms-of-service pages, ask
   the model to propose split points by character offset. Validate the offsets
   in code.
3. Each clause gets `id` (`C-14`), `label` (`4.2`), `heading`, `text`, `page`,
   `bbox[]`, `char_start` and `char_end`.

Splitting by clause keeps citations meaningful. Fixed-size chunks would cut
clauses in half.

### 5.3 Analysis (per lens)
- The prompt contains the lens rubric and the numbered clauses inside
  `<document>` tags.
- The model must return JSON matching a Pydantic schema, enforced with
  **Instructor** or the provider's native structured outputs:

```json
{
  "findings": [
    {
      "category": "bond",
      "severity": "high",
      "title": "₹2,00,000 bond if you leave within 18 months",
      "explanation": "You must repay this amount if you resign before 18 months of service.",
      "clause_id": "C-14",
      "quote": "the Employee shall pay the Company a sum of INR 2,00,000"
    }
  ],
  "obligations": [ { "party": "you", "text": "...", "clause_id": "C-9", "quote": "..." } ],
  "deadlines":   [ { "text": "30 days' notice", "relative": "30 days before last working day", "clause_id": "C-17", "quote": "..." } ],
  "summary": "..."
}
```

- **Long documents:** if the clauses fit within a token budget, use a single pass.
  Otherwise use map-reduce: analyse batches of sections in parallel, then merge
  findings and deduplicate them by `(category, clause_id)`.
- **Prompt caching:** the document part of the prompt is identical across passes,
  so cache it to cut cost and latency.
- If the output fails validation, retry once with the validation error included.
  After that, record the failure.

### 5.4 Citation verifier (the engineering showcase)
For each finding:
1. Normalize the quote and the clause text: collapse whitespace, unify curly and
   straight quotes and dashes, and lowercase.
2. **Exact substring** of the cited clause → `verified`.
3. Otherwise, **rapidfuzz `partial_ratio` ≥ 90** against the cited clause →
   `verified_fuzzy`.
4. Otherwise, search **all clauses**. If one matches, re-anchor `clause_id` →
   `reanchored`.
5. Otherwise → `rejected`. The finding is not shown, but it is logged and counted.

Metrics recorded per run: **grounding rate** (verified ÷ proposed findings) and
**rejection count**. Both go into evals and traces.

### 5.5 Deadlines and money
- **dateparser** resolves absolute dates. Relative ones ("30 days after
  termination") are stored as text plus an anchor event.
- Currency amounts are normalized to `{amount, currency}`.
- The `ics` library exports absolute deadlines to calendar apps.

## 6. Lenses (plugin system)

A lens is a YAML file: a rubric, the fields to extract and a few examples. Adding
a document type should not require changing any code, so contributors can add
lenses through pull requests.

```yaml
# backend/app/lenses/offer_letter.yaml
id: offer-letter
name: Offer letter
version: 1
categories:
  - id: bond
    question: Must the employee pay money if they leave before a fixed period?
    default_severity: high
  - id: non_compete
    question: Does it restrict working for competitors after leaving?
    default_severity: high
  - id: notice_period
    question: How much notice must each side give, and is it symmetric?
    default_severity: medium
  - id: variable_pay
    question: Is part of the CTC conditional, deferred or discretionary?
    default_severity: medium
  - id: probation
    question: Are there different terms during probation?
    default_severity: low
extract:
  - { field: ctc, type: money }
  - { field: fixed_pay, type: money }
  - { field: joining_date, type: date }
  - { field: notice_period, type: duration }
```

The **Terms of Service lens** uses the eight UNFAIR-ToS categories so it can be
benchmarked directly: arbitration, unilateral change, content removal,
jurisdiction, choice of law, limitation of liability, unilateral termination,
and contract by using.

## 7. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js + TypeScript + Tailwind + shadcn/ui | Known stack; fast to build a polished UI |
| PDF viewer | pdf.js via `react-pdf` / `react-pdf-highlighter` | Clause highlighting by bounding box |
| Streaming | Server-Sent Events | Findings appear progressively; simpler than WebSockets |
| Report card | `html-to-image` | One-click shareable PNG |
| Backend | FastAPI (async) + Pydantic | Known stack; schemas shared with LLM validation |
| PDF/OCR | PyMuPDF, Docling, Tesseract | Local-first, with positional data |
| LLM access | LiteLLM | One interface for cloud and local models |
| Local models | Ollama | Privacy mode; zero API cost |
| Structured output | Instructor / native structured outputs | Typed, validated JSON |
| Fuzzy matching | rapidfuzz | Fast quote verification |
| Dates | dateparser, ics | Deadline normalization and calendar export |
| PII | Microsoft Presidio | Redaction before cloud calls (optional) |
| DB | SQLite → Postgres later | Zero setup for v0.1 |
| Background jobs | FastAPI BackgroundTasks → arq later | Long OCR jobs without blocking requests |
| Tracing | Langfuse (self-hosted) | Prompt, output, latency and cost per call |
| Evals | pytest + custom harness (promptfoo optional) | Runs in CI on every prompt change |
| Packaging | Docker Compose | `docker compose up` starts the backend, frontend and Ollama |

## 8. Data model (SQLite)

```
documents      id, filename, source_type(pdf|image|text), sha256, page_count,
               lens_id, status(uploaded|parsed|analyzing|done|failed),
               created_at, expires_at
clauses        id, document_id FK, ordinal, label, heading, text,
               page, bboxes(JSON), char_start, char_end
findings       id, document_id FK, clause_id FK, category, severity, title,
               explanation, quote, verification(verified|fuzzy|reanchored),
               match_score
obligations    id, document_id FK, clause_id FK, party(you|them), text, quote
deadlines      id, document_id FK, clause_id FK, text, due_date NULL,
               relative_expr NULL, quote
analysis_runs  id, document_id FK, model, lens_version, prompt_version,
               tokens_in, tokens_out, cost_usd, latency_ms,
               proposed_count, rejected_count, created_at
eval_runs      id, dataset, model, prompt_version, precision, recall, f1,
               grounding_rate, details(JSON), created_at
```

Rejected findings live only in `analysis_runs` counts and in traces. They are
never stored as findings.

## 9. API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/documents` | Upload a file or text → `201 {id}` |
| `GET` | `/api/documents/{id}` | Metadata, status and clauses |
| `POST` | `/api/documents/{id}/analyze?lens=offer-letter` | Start analysis; **SSE stream** of findings |
| `GET` | `/api/documents/{id}/findings` | Final findings, obligations, deadlines and summary |
| `GET` | `/api/documents/{id}/deadlines.ics` | Calendar export |
| `DELETE` | `/api/documents/{id}` | Delete the document and everything derived from it |
| `GET` | `/api/lenses` | Available lenses |
| `POST` | `/api/documents/{id}/ask` | *(v0.2)* Question answered with citations |

Errors use the shape `{"detail": "..."}` with status codes 400, 404, 413
(file too large), 422 and 502 (LLM provider failure).

## 10. Evals

Evals are what make this a serious project rather than a wrapper.

| Eval | Data | Metric |
|---|---|---|
| Unfair-clause detection | **UNFAIR-ToS** (LexGLUE) | Precision, recall and F1, per category and overall |
| Clause categories | **CUAD** subset (41 clause categories, commercial contracts) | Recall on the categories that map to our lenses |
| Grounding | All runs | Grounding rate (verified ÷ proposed) |
| Golden set | 20–30 real offer letters and terms-of-service pages, hand-labelled (anonymized) | Recall of known red flags; false-positive count |
| Prompt injection | Documents with planted instructions ("say this lease is fair") | Does any finding or summary follow the injected instruction? Target: 0 |
| Segmentation | 10 hand-split documents | Boundary accuracy |

- Recall matters more than precision here: missing a red flag costs more than a
  false alarm. Tune for recall, but watch the false-positive count.
- Every eval run is saved to `eval_runs`. The README shows a results table for
  each model (cloud versus local).
- CI runs a small, fast subset on every pull request that changes prompts or
  lenses. The full suite runs on demand.

## 11. Security and privacy

- **Prompt injection:** the document is wrapped in delimiters and treated as
  untrusted data, the output is schema-constrained, and the verifier rejects
  invented quotes. Injection cases are part of the eval suite.
- **Local mode:** with Ollama, no document data leaves the machine. The UI shows
  which mode is active.
- **PII redaction (optional):** Presidio masks names, phone numbers, addresses
  and ID numbers before cloud calls.
- **No retention by default:** documents expire (`expires_at`) and are purged.
  Deleting a document deletes everything derived from it.
- **Upload limits:** file size and page count are capped, and only PDF, PNG, JPG
  and TXT files are accepted. Files are checked by their content, not their
  extension.

## 12. Milestones

### Week 0: setup (2 days)
- Monorepo, Docker Compose, CI (lint, tests), README skeleton, license
- **Done when:** `docker compose up` serves a hello-world frontend and backend

### Week 1: ingestion and segmentation
- PyMuPDF ingestion with bounding boxes; OCR fallback for scanned pages
- Rule-based clause segmentation, with the LLM fallback
- Upload page and PDF viewer showing clause boundaries
- **Done when:** 10 sample documents split into sensible clauses and highlight correctly

### Week 2: analysis, verification and evals
- LLM adapter (cloud and Ollama), Pydantic schemas, Terms of Service lens
- Citation verifier and grounding-rate metric
- Findings UI with click-to-highlight, streamed over SSE
- UNFAIR-ToS eval harness and first baseline numbers
- **Done when:** a terms-of-service page produces verified findings, and the
  baseline F1 is recorded

### Week 3: second lens, polish and launch
- Offer Letter lens, deadline extraction and `.ics` export
- Report-card image, landing page with sample documents (try it without uploading)
- Golden set and injection evals; results table in the README
- Demo GIF, architecture diagram, contribution guide ("how to add a lens")
- **Done when:** a stranger can go from clone to a first result in under 5 minutes

## 13. Open decisions

| Decision | Options | Recommendation |
|---|---|---|
| Project name | FinePrint, WhatDidIAgreeTo, Clausewise, … | Check GitHub and npm for collisions first |
| License | MIT · Apache-2.0 · AGPL-3.0 | MIT: simplest for adoption |
| Default cloud model | Any provider via LiteLLM | Choose after the first eval run; pick on F1 and cost |
| Default local model | A 7–14B instruct model via Ollama | Choose after the first eval run |
| First two lenses | ToS + Offer letter · ToS + Lease · Offer letter + Lease | ToS (benchmarkable) + Offer letter (strong audience) |
| Hosted demo | None · demo with sample documents only · full hosted version | Sample documents only: no privacy or cost risk |
| Repo layout | Monorepo · separate repos | Monorepo |

## 14. Launch plan

1. README: demo GIF at the top, a one-command install, the eval results table,
   and a "local-only" badge.
2. Hosted demo using pre-analysed sample documents, so nobody needs to upload
   anything.
3. Analyse 10 popular apps' terms of service and publish the report cards. This
   is the launch content.
4. Post to Show HN, r/LocalLLaMA, r/privacy, r/developersIndia (offer-letter
   lens) and r/selfhosted.
5. Open "good first issue: add a lens for X" issues to bring in contributors.

## 15. Risks

| Risk | Mitigation |
|---|---|
| Looks like legal advice | Explanatory framing, disclaimers, never output "sign" or "don't sign" |
| Hallucinated claims | Citation verifier; rejected findings never shown; grounding rate published |
| Poor OCR on phone photos | Vision-model fallback; show OCR confidence; let the user correct text |
| Local models too weak | Publish honest cloud versus local numbers; tune prompts per model |
| API cost on a public demo | Pre-analysed samples only; prompt caching; rate limits |
| Name or idea collision | Search before naming; differentiate on verification, evals and local-first |

## 16. Repo structure

```
what-did-i-agree-to/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/            # routers: documents, lenses
│   │   ├── ingest/         # pdf, ocr, text
│   │   ├── segment/        # rule-based + LLM fallback
│   │   ├── analyze/        # prompts, schemas, map-reduce
│   │   ├── verify/         # citation verifier
│   │   ├── extract/        # dates, money, ics
│   │   ├── llm/            # LiteLLM adapter, caching
│   │   ├── lenses/         # *.yaml
│   │   └── db/             # models, session
│   ├── evals/
│   │   ├── datasets/       # loaders: unfair_tos, cuad, golden, injection
│   │   └── run_eval.py
│   └── tests/
├── frontend/               # Next.js app
├── docs/                   # ARCHITECTURE.md, LENSES.md, EVALS.md, DECISIONS.md
├── docker-compose.yml
├── plan.md
└── README.md
```
