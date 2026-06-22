from __future__ import annotations

import os
import sqlite3
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "storage" / "cases.db"


def get_db_path() -> Path:
    configured = os.getenv("CASES_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_DB_PATH


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: Path | None = None) -> Path:
    path = db_path or get_db_path()
    with get_connection(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                patient_code TEXT,
                status TEXT,
                payload TEXT,
                final_result TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        _ensure_case_columns(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS queue_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_version INTEGER,
                event_type TEXT NOT NULL,
                case_id TEXT,
                affected_case_ids TEXT,
                simulation_tick INTEGER,
                details TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        _ensure_queue_event_columns(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS queue_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_tick INTEGER NOT NULL DEFAULT 0,
                arrival_seq INTEGER NOT NULL DEFAULT 0,
                queue_version INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO queue_state (
                id,
                current_tick,
                arrival_seq,
                queue_version
            ) VALUES (1, 0, 0, 0)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cases_status_queue_rank
            ON cases (status, queue_rank, created_at, case_id)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_queue_events_version
            ON queue_events (queue_version, created_at)
            """
        )
        connection.commit()
    return path


def _ensure_case_columns(connection: sqlite3.Connection) -> None:
    required_columns = [
        ("priority_score", "REAL"),
        ("queue_rank", "INTEGER"),
        ("previous_rank", "INTEGER"),
        ("rank_change", "INTEGER"),
        ("queue_version", "INTEGER"),
        ("arrival_seq", "INTEGER"),
        ("enqueue_tick", "INTEGER"),
        ("start_tick", "INTEGER"),
        ("completion_tick", "INTEGER"),
        ("manual_priority_override", "REAL"),
        ("human_packet", "TEXT"),
        ("human_status", "TEXT"),
        ("human_due_at", "TEXT"),
        ("human_decision", "TEXT"),
        ("human_decision_notes", "TEXT"),
        ("human_decided_at", "TEXT"),
    ]
    for column_name, column_type in required_columns:
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(cases)").fetchall()
        }
        if column_name in existing_columns:
            continue
        connection.execute(
            f"ALTER TABLE cases ADD COLUMN {column_name} {column_type}"
        )


def _ensure_queue_event_columns(connection: sqlite3.Connection) -> None:
    required_columns = [
        ("affected_case_ids", "TEXT"),
        ("simulation_tick", "INTEGER"),
    ]
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(queue_events)").fetchall()
    }
    for column_name, column_type in required_columns:
        if column_name in existing_columns:
            continue
        connection.execute(
            f"ALTER TABLE queue_events ADD COLUMN {column_name} {column_type}"
        )
