"""SQLite persistence for Phase 7. One AI Core writer process owns the DB."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS events (
    event_uid          TEXT PRIMARY KEY,
    raw_fingerprint    TEXT NOT NULL,
    schema_version     INTEGER NOT NULL,
    uid_version        TEXT NOT NULL,
    source             TEXT NOT NULL,
    source_event_type  TEXT,
    timestamp_original TEXT,
    timestamp_utc      TEXT,
    timestamp_us       INTEGER,
    session_id         TEXT,
    source_ip          TEXT,
    username           TEXT,
    message            TEXT,
    command            TEXT,
    is_command_input   INTEGER NOT NULL,
    orphan_reason      TEXT,
    validation_errors  TEXT NOT NULL,
    raw_event          TEXT NOT NULL,
    raw_line           TEXT NOT NULL,
    log_file_id        TEXT NOT NULL,
    file_seq           INTEGER NOT NULL,
    byte_offset_start  INTEGER NOT NULL,
    byte_offset_end    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, timestamp_us);
CREATE INDEX IF NOT EXISTS idx_events_fingerprint ON events(raw_fingerprint);

CREATE TABLE IF NOT EXISTS sessions (
    session_id            TEXT PRIMARY KEY,
    source_ip             TEXT,
    started_at_utc        TEXT,
    last_activity_at_utc  TEXT,
    event_count           INTEGER NOT NULL DEFAULT 0,
    command_count         INTEGER NOT NULL DEFAULT 0,
    unique_command_count  INTEGER NOT NULL DEFAULT 0,
    full_session          TEXT,
    full_session_rule     TEXT,
    status                TEXT NOT NULL DEFAULT 'active',
    closure_reason        TEXT,
    closed_at_utc         TEXT,
    duration_ms           INTEGER,
    has_downloads         INTEGER,
    download_count        INTEGER,
    is_complete           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS commands (
    event_uid          TEXT PRIMARY KEY REFERENCES events(event_uid),
    session_id         TEXT NOT NULL REFERENCES sessions(session_id),
    command_text       TEXT NOT NULL,
    is_empty           INTEGER NOT NULL,
    timestamp_utc      TEXT NOT NULL,
    timestamp_us       INTEGER NOT NULL,
    file_seq           INTEGER NOT NULL,
    byte_offset_start  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commands_order
    ON commands(session_id, timestamp_us, file_seq, byte_offset_start);

CREATE TABLE IF NOT EXISTS follower_cursors (
    log_file_id       TEXT PRIMARY KEY,
    file_seq          INTEGER NOT NULL UNIQUE,
    inode             INTEGER,
    path              TEXT,
    committed_offset  INTEGER NOT NULL,
    last_size         INTEGER NOT NULL DEFAULT 0,
    is_current        INTEGER NOT NULL,
    finished          INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS normalization_errors (
    error_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    log_file_id  TEXT NOT NULL,
    byte_offset  INTEGER NOT NULL,
    error_type   TEXT NOT NULL,
    error_detail TEXT NOT NULL,
    raw_line     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE (log_file_id, byte_offset, error_type)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect(path) -> sqlite3.Connection:
    """Open the DB in autocommit mode; transactions are explicit."""
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# ---- cursor helpers -------------------------------------------------------

def get_cursor(conn, log_file_id: str):
    return conn.execute("SELECT * FROM follower_cursors WHERE log_file_id=?", (log_file_id,)).fetchone()


def get_current_cursor(conn):
    return conn.execute(
        "SELECT * FROM follower_cursors WHERE is_current=1 ORDER BY file_seq DESC LIMIT 1").fetchone()


def next_file_seq(conn) -> int:
    row = conn.execute("SELECT COALESCE(MAX(file_seq),0)+1 AS n FROM follower_cursors").fetchone()
    return int(row["n"])


def create_cursor(conn, log_file_id: str, inode, path: str, size: int) -> int:
    seq = next_file_seq(conn)
    conn.execute(
        "INSERT INTO follower_cursors(log_file_id,file_seq,inode,path,committed_offset,last_size,is_current,finished,updated_at)"
        " VALUES(?,?,?,?,0,?,1,0,?)", (log_file_id, seq, inode, path, size, now_iso()))
    return seq


def set_cursor_offset(conn, log_file_id: str, offset: int, size: int) -> None:
    conn.execute("UPDATE follower_cursors SET committed_offset=?, last_size=?, updated_at=? WHERE log_file_id=?",
                 (offset, size, now_iso(), log_file_id))


def finish_cursor(conn, log_file_id: str) -> None:
    conn.execute("UPDATE follower_cursors SET is_current=0, finished=1, updated_at=? WHERE log_file_id=?",
                 (now_iso(), log_file_id))


def record_error(conn, log_file_id: str, byte_offset: int, error_type: str, detail: str, raw_line: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO normalization_errors(log_file_id,byte_offset,error_type,error_detail,raw_line,created_at)"
        " VALUES(?,?,?,?,?,?)", (log_file_id, byte_offset, error_type, detail, raw_line, now_iso()))
