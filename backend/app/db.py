"""Database models and SQLite connection management for What Did I Agree To."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "what_did_i_agree_to.db"


def get_db_path() -> str:
    return os.environ.get("DATABASE_URL", str(DEFAULT_DB_PATH))


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT,
    source_type TEXT NOT NULL,
    sha256 TEXT,
    page_count INTEGER NOT NULL DEFAULT 1,
    raw_text TEXT NOT NULL,
    spans TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clauses (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    label TEXT,
    heading TEXT,
    text TEXT NOT NULL,
    page INTEGER,
    bboxes TEXT,
    char_start INTEGER,
    char_end INTEGER,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    model TEXT,
    lens TEXT NOT NULL DEFAULT 'tos',
    total_clauses INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    proposed_count INTEGER NOT NULL DEFAULT 0,
    verified_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    grounding_rate REAL NOT NULL DEFAULT 0.0,
    latency_ms REAL NOT NULL DEFAULT 0.0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    analysis_run_id TEXT,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    explanation TEXT NOT NULL,
    clause_id TEXT NOT NULL,
    quote TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    verification_details TEXT,
    match_score REAL,
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs (id) ON DELETE CASCADE,
    FOREIGN KEY (clause_id) REFERENCES clauses (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    dataset TEXT NOT NULL,
    split TEXT NOT NULL DEFAULT 'test',
    model TEXT NOT NULL,
    lens_id TEXT NOT NULL DEFAULT 'tos',
    lens_version INTEGER NOT NULL DEFAULT 1,
    sample_id INTEGER NOT NULL,
    sentence TEXT NOT NULL,
    ground_truth TEXT NOT NULL,
    predicted TEXT NOT NULL,
    findings_json TEXT NOT NULL DEFAULT '[]',
    verified_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    grounding_rate REAL NOT NULL DEFAULT 1.0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    UNIQUE(dataset, split, model, lens_id, lens_version, sample_id)
);

CREATE TABLE IF NOT EXISTS eval_summaries (
    id TEXT PRIMARY KEY,
    dataset TEXT NOT NULL,
    split TEXT NOT NULL DEFAULT 'test',
    model TEXT NOT NULL,
    lens_id TEXT NOT NULL DEFAULT 'tos',
    lens_version INTEGER NOT NULL DEFAULT 1,
    limit_n INTEGER NOT NULL DEFAULT 0,
    sample_count INTEGER NOT NULL,
    macro_f1 REAL NOT NULL DEFAULT 0.0,
    micro_f1 REAL NOT NULL DEFAULT 0.0,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""



def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables according to schema and migrate columns if needed."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA_SQL)
            # Lightweight schema migration for existing SQLite databases
            cur = conn.execute("PRAGMA table_info(analysis_runs);")
            columns = {row["name"] for row in cur.fetchall()}
            if columns and "tokens_in" not in columns:
                conn.execute(
                    "ALTER TABLE analysis_runs ADD COLUMN tokens_in INTEGER NOT NULL DEFAULT 0;"
                )
            if columns and "tokens_out" not in columns:
                conn.execute(
                    "ALTER TABLE analysis_runs ADD COLUMN tokens_out INTEGER NOT NULL DEFAULT 0;"
                )
    finally:
        conn.close()


class DocumentRecord(BaseModel):
    id: str
    filename: Optional[str] = None
    source_type: str = "pdf"
    sha256: Optional[str] = None
    page_count: int = 1
    raw_text: str = ""
    spans: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "parsed"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def save_document(record: DocumentRecord, db_path: Optional[str] = None) -> DocumentRecord:
    """Insert or update a document record without triggering foreign key cascade deletion."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO documents (
                    id, filename, source_type, sha256, page_count, raw_text, spans, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    filename = excluded.filename,
                    source_type = excluded.source_type,
                    sha256 = excluded.sha256,
                    page_count = excluded.page_count,
                    raw_text = excluded.raw_text,
                    spans = excluded.spans,
                    status = excluded.status,
                    created_at = excluded.created_at
                """,
                (
                    record.id,
                    record.filename,
                    record.source_type,
                    record.sha256,
                    record.page_count,
                    record.raw_text,
                    json.dumps(record.spans),
                    record.status,
                    record.created_at,
                ),
            )
        return record
    finally:
        conn.close()


def update_document_status(doc_id: str, status: str, db_path: Optional[str] = None) -> None:
    """Update document processing status without touching other fields."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute("UPDATE documents SET status = ? WHERE id = ?", (status, doc_id))
    finally:
        conn.close()


def get_document(doc_id: str, db_path: Optional[str] = None) -> Optional[DocumentRecord]:
    """Retrieve a document record by ID."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute(
            """
            SELECT id, filename, source_type, sha256, page_count, raw_text, spans, status, created_at
            FROM documents WHERE id = ?
            """,
            (doc_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return DocumentRecord(
            id=row["id"],
            filename=row["filename"],
            source_type=row["source_type"],
            sha256=row["sha256"],
            page_count=row["page_count"],
            raw_text=row["raw_text"],
            spans=json.loads(row["spans"]),
            status=row["status"],
            created_at=row["created_at"],
        )
    finally:
        conn.close()


class ClauseRecord(BaseModel):
    id: str
    document_id: str
    ordinal: int
    label: Optional[str] = None
    heading: Optional[str] = None
    text: str
    page: Optional[int] = 1
    bboxes: list[list[float]] = Field(default_factory=list)
    char_start: Optional[int] = None
    char_end: Optional[int] = None


def save_clauses(
    clauses: list[ClauseRecord], db_path: Optional[str] = None
) -> list[ClauseRecord]:
    """Save or update a list of clause records in SQLite."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO clauses (
                    id, document_id, ordinal, label, heading, text, page, bboxes, char_start, char_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        c.id,
                        c.document_id,
                        c.ordinal,
                        c.label,
                        c.heading,
                        c.text,
                        c.page,
                        json.dumps(c.bboxes),
                        c.char_start,
                        c.char_end,
                    )
                    for c in clauses
                ],
            )
        return clauses
    finally:
        conn.close()


def get_clauses(
    document_id: str, db_path: Optional[str] = None
) -> list[ClauseRecord]:
    """Retrieve all clauses for a given document ordered by ordinal."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute(
            """
            SELECT id, document_id, ordinal, label, heading, text, page, bboxes, char_start, char_end
            FROM clauses WHERE document_id = ? ORDER BY ordinal ASC
            """,
            (document_id,),
        )
        rows = cur.fetchall()
        return [
            ClauseRecord(
                id=row["id"],
                document_id=row["document_id"],
                ordinal=row["ordinal"],
                label=row["label"],
                heading=row["heading"],
                text=row["text"],
                page=row["page"],
                bboxes=json.loads(row["bboxes"] or "[]"),
                char_start=row["char_start"],
                char_end=row["char_end"],
            )
            for row in rows
        ]
    finally:
        conn.close()


class AnalysisRunRecord(BaseModel):
    id: str
    document_id: str
    model: Optional[str] = None
    lens: str = "tos"
    total_clauses: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    proposed_count: int = 0
    verified_count: int = 0
    rejected_count: int = 0
    grounding_rate: float = 0.0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def save_analysis_run(
    run: AnalysisRunRecord, db_path: Optional[str] = None
) -> AnalysisRunRecord:
    """Save an analysis run record to SQLite."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analysis_runs (
                    id, document_id, model, lens, total_clauses,
                    tokens_in, tokens_out, proposed_count, verified_count,
                    rejected_count, grounding_rate, latency_ms, cost_usd, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.document_id,
                    run.model,
                    run.lens,
                    run.total_clauses,
                    run.tokens_in,
                    run.tokens_out,
                    run.proposed_count,
                    run.verified_count,
                    run.rejected_count,
                    run.grounding_rate,
                    run.latency_ms,
                    run.cost_usd,
                    run.created_at,
                ),
            )
        return run
    finally:
        conn.close()


def get_analysis_run(
    run_id: str, db_path: Optional[str] = None
) -> Optional[AnalysisRunRecord]:
    """Retrieve an analysis run record by ID."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute(
            """
            SELECT id, document_id, model, lens, total_clauses,
                   tokens_in, tokens_out, proposed_count, verified_count,
                   rejected_count, grounding_rate, latency_ms, cost_usd, created_at
            FROM analysis_runs WHERE id = ?
            """,
            (run_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return AnalysisRunRecord(
            id=row["id"],
            document_id=row["document_id"],
            model=row["model"],
            lens=row["lens"],
            total_clauses=row["total_clauses"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            proposed_count=row["proposed_count"],
            verified_count=row["verified_count"],
            rejected_count=row["rejected_count"],
            grounding_rate=row["grounding_rate"],
            latency_ms=row["latency_ms"],
            cost_usd=row["cost_usd"],
            created_at=row["created_at"],
        )
    finally:
        conn.close()


class FindingRecord(BaseModel):
    id: str
    document_id: str
    analysis_run_id: Optional[str] = None
    category: str
    severity: str
    title: str
    explanation: str
    clause_id: str
    quote: str
    verification_status: str = "proposed"
    verification_details: Optional[str] = None
    match_score: Optional[float] = None


def save_findings(
    findings: list[FindingRecord], db_path: Optional[str] = None
) -> list[FindingRecord]:
    """Save a list of findings to SQLite."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO findings (
                    id, document_id, analysis_run_id, category, severity,
                    title, explanation, clause_id, quote,
                    verification_status, verification_details, match_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f.id,
                        f.document_id,
                        f.analysis_run_id,
                        f.category,
                        f.severity,
                        f.title,
                        f.explanation,
                        f.clause_id,
                        f.quote,
                        f.verification_status,
                        f.verification_details,
                        f.match_score,
                    )
                    for f in findings
                ],
            )
        return findings
    finally:
        conn.close()


def get_findings(
    document_id: str,
    analysis_run_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[FindingRecord]:
    """Retrieve findings for a document, optionally filtered by analysis_run_id."""
    conn = get_db_connection(db_path)
    try:
        if analysis_run_id:
            cur = conn.execute(
                """
                SELECT id, document_id, analysis_run_id, category, severity,
                       title, explanation, clause_id, quote,
                       verification_status, verification_details, match_score
                FROM findings WHERE document_id = ? AND analysis_run_id = ?
                """,
                (document_id, analysis_run_id),
            )
        else:
            cur = conn.execute(
                """
                SELECT id, document_id, analysis_run_id, category, severity,
                       title, explanation, clause_id, quote,
                       verification_status, verification_details, match_score
                FROM findings WHERE document_id = ?
                """,
                (document_id,),
            )
        rows = cur.fetchall()
        return [
            FindingRecord(
                id=row["id"],
                document_id=row["document_id"],
                analysis_run_id=row["analysis_run_id"],
                category=row["category"],
                severity=row["severity"],
                title=row["title"],
                explanation=row["explanation"],
                clause_id=row["clause_id"],
                quote=row["quote"],
                verification_status=row["verification_status"],
                verification_details=row["verification_details"],
                match_score=row["match_score"],
            )
            for row in rows
        ]
    finally:
        conn.close()


class EvalRunRecord(BaseModel):
    id: str
    dataset: str
    split: str = "test"
    model: str
    lens_id: str = "tos"
    lens_version: int = 1
    sample_id: int
    sentence: str
    ground_truth: str  # JSON list of category IDs e.g. '["arbitration"]'
    predicted: str  # JSON list of verified category IDs e.g. '["arbitration"]'
    findings_json: str = "[]"
    verified_count: int = 0
    rejected_count: int = 0
    grounding_rate: float = 1.0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def save_eval_run(
    record: EvalRunRecord, db_path: Optional[str] = None
) -> EvalRunRecord:
    """Insert or replace an evaluation sample run record."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_runs (
                    id, dataset, split, model, lens_id, lens_version,
                    sample_id, sentence, ground_truth, predicted,
                    findings_json, verified_count, rejected_count,
                    grounding_rate, tokens_in, tokens_out, latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.dataset,
                    record.split,
                    record.model,
                    record.lens_id,
                    record.lens_version,
                    record.sample_id,
                    record.sentence,
                    record.ground_truth,
                    record.predicted,
                    record.findings_json,
                    record.verified_count,
                    record.rejected_count,
                    record.grounding_rate,
                    record.tokens_in,
                    record.tokens_out,
                    record.latency_ms,
                    record.created_at,
                ),
            )
        return record
    finally:
        conn.close()


def get_cached_eval_run(
    dataset: str,
    split: str,
    model: str,
    lens_id: str,
    lens_version: int,
    sample_id: int,
    db_path: Optional[str] = None,
) -> Optional[EvalRunRecord]:
    """Retrieve an evaluation run for a sample if already executed with identical parameters."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute(
            """
            SELECT id, dataset, split, model, lens_id, lens_version,
                   sample_id, sentence, ground_truth, predicted,
                   findings_json, verified_count, rejected_count,
                   grounding_rate, tokens_in, tokens_out, latency_ms, created_at
            FROM eval_runs
            WHERE dataset = ? AND split = ? AND model = ? AND lens_id = ? AND lens_version = ? AND sample_id = ?
            """,
            (dataset, split, model, lens_id, lens_version, sample_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return EvalRunRecord(
            id=row["id"],
            dataset=row["dataset"],
            split=row["split"],
            model=row["model"],
            lens_id=row["lens_id"],
            lens_version=row["lens_version"],
            sample_id=row["sample_id"],
            sentence=row["sentence"],
            ground_truth=row["ground_truth"],
            predicted=row["predicted"],
            findings_json=row["findings_json"],
            verified_count=row["verified_count"],
            rejected_count=row["rejected_count"],
            grounding_rate=row["grounding_rate"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            latency_ms=row["latency_ms"],
            created_at=row["created_at"],
        )
    finally:
        conn.close()


def get_eval_runs(
    dataset: str,
    split: str,
    model: str,
    lens_id: str,
    lens_version: int,
    db_path: Optional[str] = None,
) -> list[EvalRunRecord]:
    """Retrieve all evaluation sample runs for a dataset/split/model/lens combination."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute(
            """
            SELECT id, dataset, split, model, lens_id, lens_version,
                   sample_id, sentence, ground_truth, predicted,
                   findings_json, verified_count, rejected_count,
                   grounding_rate, tokens_in, tokens_out, latency_ms, created_at
            FROM eval_runs
            WHERE dataset = ? AND split = ? AND model = ? AND lens_id = ? AND lens_version = ?
            ORDER BY sample_id ASC
            """,
            (dataset, split, model, lens_id, lens_version),
        )
        rows = cur.fetchall()
        return [
            EvalRunRecord(
                id=row["id"],
                dataset=row["dataset"],
                split=row["split"],
                model=row["model"],
                lens_id=row["lens_id"],
                lens_version=row["lens_version"],
                sample_id=row["sample_id"],
                sentence=row["sentence"],
                ground_truth=row["ground_truth"],
                predicted=row["predicted"],
                findings_json=row["findings_json"],
                verified_count=row["verified_count"],
                rejected_count=row["rejected_count"],
                grounding_rate=row["grounding_rate"],
                tokens_in=row["tokens_in"],
                tokens_out=row["tokens_out"],
                latency_ms=row["latency_ms"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
    finally:
        conn.close()


class EvalSummaryRecord(BaseModel):
    id: str
    dataset: str
    split: str = "test"
    model: str
    lens_id: str = "tos"
    lens_version: int = 1
    limit_n: int = 0
    sample_count: int
    macro_f1: float = 0.0
    micro_f1: float = 0.0
    metrics_json: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def save_eval_summary(
    record: EvalSummaryRecord, db_path: Optional[str] = None
) -> EvalSummaryRecord:
    """Insert or replace an evaluation summary record."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_summaries (
                    id, dataset, split, model, lens_id, lens_version,
                    limit_n, sample_count, macro_f1, micro_f1, metrics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.dataset,
                    record.split,
                    record.model,
                    record.lens_id,
                    record.lens_version,
                    record.limit_n,
                    record.sample_count,
                    record.macro_f1,
                    record.micro_f1,
                    record.metrics_json,
                    record.created_at,
                ),
            )
        return record
    finally:
        conn.close()


def get_latest_eval_summary(
    dataset: str,
    split: str,
    model: str,
    lens_id: str = "tos",
    lens_version: int = 1,
    db_path: Optional[str] = None,
) -> Optional[EvalSummaryRecord]:
    """Retrieve the most recent evaluation summary for a dataset/model combination."""
    conn = get_db_connection(db_path)
    try:
        cur = conn.execute(
            """
            SELECT id, dataset, split, model, lens_id, lens_version,
                   limit_n, sample_count, macro_f1, micro_f1, metrics_json, created_at
            FROM eval_summaries
            WHERE dataset = ? AND split = ? AND model = ? AND lens_id = ? AND lens_version = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (dataset, split, model, lens_id, lens_version),
        )
        row = cur.fetchone()
        if not row:
            return None
        return EvalSummaryRecord(
            id=row["id"],
            dataset=row["dataset"],
            split=row["split"],
            model=row["model"],
            lens_id=row["lens_id"],
            lens_version=row["lens_version"],
            limit_n=row["limit_n"],
            sample_count=row["sample_count"],
            macro_f1=row["macro_f1"],
            micro_f1=row["micro_f1"],
            metrics_json=row["metrics_json"],
            created_at=row["created_at"],
        )
    finally:
        conn.close()


