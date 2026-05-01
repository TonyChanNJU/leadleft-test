"""Persistent job store for document processing."""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_RECOVERABLE = "recoverable"
JOB_STATUS_READY = "ready"
JOB_STATUS_FAILED = "failed"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@contextmanager
def _connect():
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.jobs_db_path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_job_store() -> None:
    """Create the persistent job tables if they don't exist."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_jobs (
                job_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                lease_owner TEXT,
                heartbeat_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_job_progress (
                document_id TEXT PRIMARY KEY,
                total_pages INTEGER,
                parsed_pages INTEGER NOT NULL DEFAULT 0,
                ocr_candidate_pages_total INTEGER NOT NULL DEFAULT 0,
                ocr_processed_pages INTEGER NOT NULL DEFAULT 0,
                index_total_nodes INTEGER NOT NULL DEFAULT 0,
                index_done_nodes INTEGER NOT NULL DEFAULT 0,
                index_total_batches INTEGER NOT NULL DEFAULT 0,
                index_done_batches INTEGER NOT NULL DEFAULT 0,
                current_page INTEGER,
                current_batch INTEGER,
                FOREIGN KEY(document_id) REFERENCES document_jobs(document_id) ON DELETE CASCADE
            )
            """
        )
        _ensure_progress_column(conn, "index_total_nodes", "INTEGER NOT NULL DEFAULT 0")
        _ensure_progress_column(conn, "index_done_nodes", "INTEGER NOT NULL DEFAULT 0")
        _ensure_progress_column(conn, "index_total_batches", "INTEGER NOT NULL DEFAULT 0")
        _ensure_progress_column(conn, "index_done_batches", "INTEGER NOT NULL DEFAULT 0")
        _ensure_progress_column(conn, "current_batch", "INTEGER")


def _ensure_progress_column(conn: sqlite3.Connection, column_name: str, ddl: str) -> None:
    """Backfill newly added progress columns for existing SQLite files."""
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(document_job_progress)").fetchall()
    }
    if column_name in columns:
        return
    conn.execute(f"ALTER TABLE document_job_progress ADD COLUMN {column_name} {ddl}")


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _job_state_from_document(meta: dict[str, Any]) -> tuple[str, str | None]:
    processing_status = meta.get("processing_status")
    indexed = bool(meta.get("indexed"))

    if indexed or processing_status == "ready":
        return JOB_STATUS_READY, None
    if processing_status == "failed":
        return JOB_STATUS_FAILED, None
    if processing_status in {"parsing", "ocr", "indexing"}:
        return JOB_STATUS_RUNNING, processing_status
    return JOB_STATUS_QUEUED, None


def ensure_document_job(meta: dict[str, Any]) -> dict[str, Any]:
    """Create or update the persistent job row for one document."""
    ensure_job_store()
    now = _utcnow()
    status, stage = _job_state_from_document(meta)
    document_id = meta["doc_id"]

    with _connect() as conn:
        existing = conn.execute(
            "SELECT job_id, attempt_count, created_at FROM document_jobs WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if existing is None:
            job_id = str(uuid.uuid4())
            attempt_count = 0
            created_at = now
            conn.execute(
                """
                INSERT INTO document_jobs (
                    job_id, document_id, filename, file_path, status, stage,
                    attempt_count, lease_owner, heartbeat_at, last_error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                """,
                (
                    job_id,
                    document_id,
                    meta["filename"],
                    meta["file_path"],
                    status,
                    stage,
                    attempt_count,
                    meta.get("processing_error"),
                    created_at,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO document_job_progress (
                    document_id, total_pages, parsed_pages, ocr_candidate_pages_total,
                    ocr_processed_pages, index_total_nodes, index_done_nodes,
                    index_total_batches, index_done_batches,
                    current_page, current_batch
                )
                VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?, NULL)
                """,
                (
                    document_id,
                    meta.get("total_pages"),
                    meta.get("processed_pages", 0),
                    meta.get("ocr_candidate_pages_total", 0),
                    meta.get("ocr_processed_pages", 0),
                    meta.get("current_page"),
                ),
            )
        else:
            job_id = existing["job_id"]
            attempt_count = existing["attempt_count"]
            created_at = existing["created_at"]
            conn.execute(
                """
                UPDATE document_jobs
                SET filename = ?, file_path = ?, status = ?, stage = ?, last_error = ?, updated_at = ?
                WHERE document_id = ?
                """,
                (
                    meta["filename"],
                    meta["file_path"],
                    status,
                    stage,
                    meta.get("processing_error"),
                    now,
                    document_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO document_job_progress (
                    document_id, total_pages, parsed_pages, ocr_candidate_pages_total,
                    ocr_processed_pages, index_total_nodes, index_done_nodes,
                    index_total_batches, index_done_batches,
                    current_page, current_batch
                )
                VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?, NULL)
                ON CONFLICT(document_id) DO UPDATE SET
                    total_pages = excluded.total_pages,
                    parsed_pages = excluded.parsed_pages,
                    ocr_candidate_pages_total = excluded.ocr_candidate_pages_total,
                    ocr_processed_pages = excluded.ocr_processed_pages,
                    current_page = excluded.current_page
                """,
                (
                    document_id,
                    meta.get("total_pages"),
                    meta.get("processed_pages", 0),
                    meta.get("ocr_candidate_pages_total", 0),
                    meta.get("ocr_processed_pages", 0),
                    meta.get("current_page"),
                ),
            )

        row = conn.execute(
            """
            SELECT
                j.job_id,
                j.document_id,
                j.filename,
                j.file_path,
                j.status,
                j.stage,
                j.attempt_count,
                j.lease_owner,
                j.heartbeat_at,
                j.last_error,
                j.created_at,
                j.updated_at,
                p.total_pages,
                p.parsed_pages,
                p.ocr_candidate_pages_total,
                p.ocr_processed_pages,
                p.index_total_nodes,
                p.index_done_nodes,
                p.index_total_batches,
                p.index_done_batches,
                p.current_page,
                p.current_batch
            FROM document_jobs j
            LEFT JOIN document_job_progress p ON p.document_id = j.document_id
            WHERE j.document_id = ?
            """,
            (document_id,),
        ).fetchone()
    return _row_to_dict(row) or {
        "job_id": job_id,
        "document_id": document_id,
        "filename": meta["filename"],
        "file_path": meta["file_path"],
        "status": status,
        "stage": stage,
        "attempt_count": attempt_count,
        "created_at": created_at,
        "updated_at": now,
    }


def touch_job_progress(document_id: str, **fields: Any) -> None:
    """Update durable progress counters for one job."""
    if not fields:
        return
    ensure_job_store()
    allowed = {
        "total_pages",
        "parsed_pages",
        "ocr_candidate_pages_total",
        "ocr_processed_pages",
        "index_total_nodes",
        "index_done_nodes",
        "index_total_batches",
        "index_done_batches",
        "current_page",
        "current_batch",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return

    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values())
    values.append(document_id)

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO document_job_progress (document_id)
            VALUES (?)
            ON CONFLICT(document_id) DO NOTHING
            """,
            (document_id,),
        )
        conn.execute(
            f"UPDATE document_job_progress SET {assignments} WHERE document_id = ?",
            values,
        )
        conn.execute(
            "UPDATE document_jobs SET updated_at = ? WHERE document_id = ?",
            (_utcnow(), document_id),
        )


def start_job_attempt(document_id: str, stage: str, lease_owner: str) -> None:
    """Start one end-to-end processing attempt for a job."""
    ensure_job_store()
    now = _utcnow()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE document_jobs
            SET status = ?, stage = ?, attempt_count = attempt_count + 1,
                lease_owner = ?, heartbeat_at = ?, last_error = NULL, updated_at = ?
            WHERE document_id = ?
            """,
            (JOB_STATUS_RUNNING, stage, lease_owner, now, now, document_id),
        )


def set_job_stage(document_id: str, stage: str, lease_owner: str | None = None) -> bool:
    """Update the current running stage without bumping attempt_count."""
    ensure_job_store()
    with _connect() as conn:
        params: list[Any] = [JOB_STATUS_RUNNING, stage, _utcnow(), _utcnow(), document_id]
        where_clause = "document_id = ?"
        if lease_owner is not None:
            where_clause += " AND lease_owner = ?"
            params.append(lease_owner)
        cursor = conn.execute(
            f"""
            UPDATE document_jobs
            SET status = ?, stage = ?, heartbeat_at = ?, updated_at = ?
            WHERE {where_clause}
            """,
            params,
        )
    return bool(cursor.rowcount)


def renew_job_heartbeat(document_id: str, lease_owner: str) -> bool:
    """Refresh one running job heartbeat if the lease owner still matches."""
    ensure_job_store()
    now = _utcnow()
    with _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE document_jobs
            SET heartbeat_at = ?, updated_at = ?
            WHERE document_id = ? AND lease_owner = ?
            """,
            (now, now, document_id, lease_owner),
        )
    return bool(cursor.rowcount)


def job_lease_matches(document_id: str, lease_owner: str) -> bool:
    """Return whether the stored lease owner still matches the caller."""
    ensure_job_store()
    with _connect() as conn:
        row = conn.execute(
            "SELECT lease_owner FROM document_jobs WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    if row is None:
        return False
    return row["lease_owner"] == lease_owner


def complete_job(document_id: str) -> None:
    """Mark a job as finished successfully."""
    ensure_job_store()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE document_jobs
            SET status = ?, stage = NULL, lease_owner = NULL,
                heartbeat_at = ?, last_error = NULL, updated_at = ?
            WHERE document_id = ?
            """,
            (JOB_STATUS_READY, _utcnow(), _utcnow(), document_id),
        )


def fail_job(document_id: str, error: str) -> None:
    """Mark a job as failed."""
    ensure_job_store()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE document_jobs
            SET status = ?, stage = NULL, lease_owner = NULL,
                heartbeat_at = ?, last_error = ?, updated_at = ?
            WHERE document_id = ?
            """,
            (JOB_STATUS_FAILED, _utcnow(), error, _utcnow(), document_id),
        )


def queue_job(document_id: str) -> None:
    """Mark a job as waiting to be processed."""
    ensure_job_store()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE document_jobs
            SET status = ?, stage = NULL, lease_owner = NULL, updated_at = ?
            WHERE document_id = ?
            """,
            (JOB_STATUS_QUEUED, _utcnow(), document_id),
        )


def mark_job_recoverable(document_id: str, reason: str | None = None) -> None:
    """Mark a job recoverable and release its lease."""
    ensure_job_store()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE document_jobs
            SET status = ?, lease_owner = NULL, last_error = COALESCE(?, last_error), updated_at = ?
            WHERE document_id = ?
            """,
            (JOB_STATUS_RECOVERABLE, reason, _utcnow(), document_id),
        )


def reclaim_stale_running_jobs(timeout_seconds: int) -> list[dict[str, Any]]:
    """Mark stale running jobs as recoverable and return their job rows."""
    ensure_job_store()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    reclaimed_ids: list[str] = []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT document_id, heartbeat_at
            FROM document_jobs
            WHERE status = ?
            """,
            (JOB_STATUS_RUNNING,),
        ).fetchall()
        for row in rows:
            heartbeat = _parse_utc(row["heartbeat_at"])
            if heartbeat is None or heartbeat <= cutoff:
                reclaimed_ids.append(row["document_id"])
        if reclaimed_ids:
            placeholders = ", ".join(["?"] * len(reclaimed_ids))
            conn.execute(
                f"""
                UPDATE document_jobs
                SET status = ?, lease_owner = NULL, updated_at = ?
                WHERE document_id IN ({placeholders})
                """,
                [JOB_STATUS_RECOVERABLE, _utcnow(), *reclaimed_ids],
            )

    return [job for job in list_recoverable_jobs() if job["document_id"] in reclaimed_ids]


def reclaim_orphaned_running_jobs() -> list[dict[str, Any]]:
    """Mark all running jobs recoverable during backend startup."""
    ensure_job_store()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE document_jobs
            SET status = ?, lease_owner = NULL, updated_at = ?
            WHERE status = ?
            """,
            (JOB_STATUS_RECOVERABLE, _utcnow(), JOB_STATUS_RUNNING),
        )
    return list_recoverable_jobs()


def list_recoverable_jobs() -> list[dict[str, Any]]:
    """Return jobs that should be retried on startup."""
    ensure_job_store()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                j.job_id,
                j.document_id,
                j.filename,
                j.file_path,
                j.status,
                j.stage,
                j.attempt_count,
                j.last_error,
                p.total_pages,
                p.parsed_pages,
                p.ocr_candidate_pages_total,
                p.ocr_processed_pages,
                p.current_page
            FROM document_jobs j
            LEFT JOIN document_job_progress p ON p.document_id = j.document_id
            WHERE j.status IN (?, ?, ?)
            ORDER BY j.created_at ASC
            """,
            (JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, JOB_STATUS_RECOVERABLE),
        ).fetchall()
    return [dict(row) for row in rows]


def get_job(document_id: str) -> dict[str, Any] | None:
    """Fetch one job with progress details."""
    ensure_job_store()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                j.job_id,
                j.document_id,
                j.filename,
                j.file_path,
                j.status,
                j.stage,
                j.attempt_count,
                j.lease_owner,
                j.heartbeat_at,
                j.last_error,
                j.created_at,
                j.updated_at,
                p.total_pages,
                p.parsed_pages,
                p.ocr_candidate_pages_total,
                p.ocr_processed_pages,
                p.index_total_nodes,
                p.index_done_nodes,
                p.index_total_batches,
                p.index_done_batches,
                p.current_page,
                p.current_batch
            FROM document_jobs j
            LEFT JOIN document_job_progress p ON p.document_id = j.document_id
            WHERE j.document_id = ?
            """,
            (document_id,),
        ).fetchone()
    return _row_to_dict(row)


def delete_job(document_id: str) -> None:
    """Delete one document job."""
    ensure_job_store()
    with _connect() as conn:
        conn.execute("DELETE FROM document_jobs WHERE document_id = ?", (document_id,))
    shutil.rmtree(get_document_job_dir(document_id), ignore_errors=True)


def clear_jobs() -> None:
    """Delete all persistent document jobs."""
    if os.path.exists(settings.jobs_db_path):
        ensure_job_store()
        with _connect() as conn:
            conn.execute("DELETE FROM document_jobs")
    shutil.rmtree(settings.job_artifacts_dir, ignore_errors=True)
    os.makedirs(settings.job_artifacts_dir, exist_ok=True)


def get_document_job_dir(document_id: str) -> str:
    """Return the artifact directory for one document's processing job."""
    return os.path.join(settings.job_artifacts_dir, document_id)


def get_document_page_checkpoint_dir(document_id: str) -> str:
    """Return the page-checkpoint directory for one document."""
    return os.path.join(get_document_job_dir(document_id), "pages")
