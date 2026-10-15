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
"""


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables according to schema."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA_SQL)
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
    """Insert or replace a document record."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO documents (
                    id, filename, source_type, sha256, page_count, raw_text, spans, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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

