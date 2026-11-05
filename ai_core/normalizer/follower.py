"""Incremental Cowrie JSONL follower with a restart-safe cursor.

Guarantees (Phase 7 spec 7):
  * only newline-terminated lines are processed; a trailing partial line is kept
    out of the durable state (the cursor only ever points at a line start);
  * a malformed complete line is written to normalization_errors in the same
    transaction as the cursor advance;
  * the cursor moves in the SAME transaction as the event inserts and session
    updates, so a persistence failure leaves the cursor behind and the lines are
    simply retried;
  * file generations are identified by a hash of their first complete line, not
    by path or inode alone; rename- and copy-truncate rotation drain the old
    generation first, and anything that cannot be drained is recorded visibly.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from ai_core.persistence import db
from ai_core.persistence.db import transaction
from ai_core.sessions.manager import apply_event, recompute_sessions

from .normalizer import normalize_line
from .schemas import NormalizationError, SourceRef

log = logging.getLogger("ai_core.follower")

IDENT_LIMIT = 1 << 20  # max bytes scanned for the first newline when identifying a file


@dataclass
class PollStats:
    lines: int = 0
    events_inserted: int = 0
    duplicates: int = 0
    errors: int = 0
    rotations: int = 0

    def add(self, other: "PollStats") -> None:
        for k in self.__dict__:
            setattr(self, k, getattr(self, k) + getattr(other, k))

    @property
    def progressed(self) -> bool:
        return bool(self.lines or self.rotations)


class LogFollower:
    def __init__(self, conn: sqlite3.Connection, log_path, batch_lines: int = 500,
                 read_chunk: int = 1 << 20, max_line_bytes: int = 16 << 20):
        self.conn = conn
        self.path = Path(log_path)
        self.batch_lines = max(1, batch_lines)
        self.read_chunk = read_chunk
        self.max_line_bytes = max_line_bytes

    # ---- identity ---------------------------------------------------------
    @staticmethod
    def identify(path: Path) -> Optional[Tuple[str, int, int]]:
        """(log_file_id, size, inode) once the file has a complete first line, else None."""
        with open(path, "rb") as f:
            st = os.fstat(f.fileno())
            data = b""
            while b"\n" not in data and len(data) < IDENT_LIMIT:
                chunk = f.read(8192)
                if not chunk:
                    break
                data += chunk
        idx = data.find(b"\n")
        if idx < 0:
            return None
        return "sha256:" + hashlib.sha256(data[:idx]).hexdigest(), st.st_size, st.st_ino

    # ---- public API -------------------------------------------------------
    def poll_once(self) -> PollStats:
        stats = PollStats()
        try:
            ident = self.identify(self.path)
        except FileNotFoundError:
            return stats
        if ident is None:
            return stats  # empty file or only a partial first line: nothing complete yet
        file_id, size, inode = ident

        cursor = db.get_cursor(self.conn, file_id)
        if cursor is None:
            prev = db.get_current_cursor(self.conn)
            if prev is not None:
                stats.add(self._drain_previous(prev))
                stats.rotations += 1
            with transaction(self.conn):
                db.create_cursor(self.conn, file_id, inode, str(self.path), size)
            cursor = db.get_cursor(self.conn, file_id)
        elif not cursor["is_current"] and not cursor["finished"]:
            pass
        if size < cursor["committed_offset"]:
            msg = f"file shrank: size={size} < committed_offset={cursor['committed_offset']}; restarting generation at 0"
            log.error("truncation_detected file=%s offset=%d detail=%s", self.path, cursor["committed_offset"], msg)
            with transaction(self.conn):
                db.record_error(self.conn, file_id, cursor["committed_offset"], "truncation_detected", msg, "")
                db.set_cursor_offset(self.conn, file_id, 0, size)
            cursor = db.get_cursor(self.conn, file_id)
            stats.errors += 1
        stats.add(self._process(self.path, cursor, final=False))
        return stats

    def replay(self) -> PollStats:
        """Deterministic one-shot: poll until no more progress (used by tests/tools)."""
        total = PollStats()
        while True:
            s = self.poll_once()
            total.add(s)
            if not s.progressed:
                return total

    def run(self, stop: threading.Event, interval: float = 1.0) -> None:
        """Follow mode. Stops cleanly when `stop` is set; anything not committed is re-read on restart."""
        while not stop.is_set():
            try:
                progressed = self.poll_once().progressed
            except (OSError, sqlite3.Error) as exc:
                log.error("poll_failed file=%s category=%s detail=%s", self.path, type(exc).__name__, exc)
                progressed = False
            if not progressed:
                stop.wait(interval)

    # ---- rotation ---------------------------------------------------------
    def _find_generation(self, file_id: str) -> Optional[Path]:
        parent = self.path.parent
        try:
            names = sorted(os.listdir(parent))
        except OSError:
            return None
        for name in names:
            cand = parent / name
            if cand == self.path or not name.startswith(self.path.name) or not cand.is_file():
                continue
            try:
                ident = self.identify(cand)
            except OSError:
                continue
            if ident and ident[0] == file_id:
                return cand
        return None

    def _drain_previous(self, prev) -> PollStats:
        stats = PollStats()
        old = self._find_generation(prev["log_file_id"])
        if old is None:
            detail = (f"previous generation (last_size={prev['last_size']}, committed={prev['committed_offset']}) "
                      "not found after rotation; unread bytes may be lost")
            log.error("rotation_source_missing file=%s offset=%d", self.path, prev["committed_offset"])
            with transaction(self.conn):
                db.record_error(self.conn, prev["log_file_id"], prev["committed_offset"],
                                "rotation_source_missing", detail, "")
                db.finish_cursor(self.conn, prev["log_file_id"])
            stats.errors += 1
            return stats
        stats.add(self._process(old, prev, final=True))
        with transaction(self.conn):
            db.finish_cursor(self.conn, prev["log_file_id"])
        log.info("rotation_drained old=%s new=%s", old, self.path)
        return stats

    # ---- reading ----------------------------------------------------------
    def _process(self, path: Path, cursor, final: bool) -> PollStats:
        stats = PollStats()
        file_id, file_seq = cursor["log_file_id"], cursor["file_seq"]
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            offset = cursor["committed_offset"]
            f.seek(offset)
            buf, base = b"", offset
            while True:
                chunk = f.read(self.read_chunk)
                if not chunk:
                    break
                buf += chunk
                lines: List[Tuple[int, bytes]] = []
                pos = 0
                while True:
                    nl = buf.find(b"\n", pos)
                    if nl < 0:
                        break
                    lines.append((base + pos, buf[pos:nl]))
                    pos = nl + 1
                for i in range(0, len(lines), self.batch_lines):
                    stats.add(self._commit_batch(file_id, file_seq, lines[i:i + self.batch_lines], size))
                base += pos
                buf = buf[pos:]
                if len(buf) > self.max_line_bytes:
                    with transaction(self.conn):
                        db.record_error(self.conn, file_id, base, "oversize_partial_line",
                                        f"{len(buf)} bytes without newline", "")
                    stats.errors += 1
                    return stats
            if buf and final:
                # a rotated file will never grow again: its trailing partial line is
                # recorded (not silently dropped) and the generation is finished.
                with transaction(self.conn):
                    db.record_error(self.conn, file_id, base, "partial_final_line_on_rotation",
                                    f"{len(buf)} unterminated bytes at end of rotated file",
                                    buf.decode("utf-8", errors="replace"))
                    db.set_cursor_offset(self.conn, file_id, base, size)
                stats.errors += 1
        return stats

    def _commit_batch(self, file_id: str, file_seq: int, lines, size: int) -> PollStats:
        stats = PollStats()
        touched = set()
        with transaction(self.conn):
            for off, raw in lines:
                stats.lines += 1
                if not raw.strip():
                    continue  # blank line: nothing to record
                src = SourceRef(file_id, file_seq, off, off + len(raw) + 1)
                res = normalize_line(raw, src)
                if isinstance(res, NormalizationError):
                    db.record_error(self.conn, file_id, off, res.error_type, res.error_detail, res.raw_line)
                    stats.errors += 1
                    log.warning("normalization_error file=%s offset=%d category=%s", self.path, off, res.error_type)
                elif apply_event(self.conn, res, touched):
                    stats.events_inserted += 1
                else:
                    stats.duplicates += 1
            last_off, last_raw = lines[-1]
            recompute_sessions(self.conn, touched)
            db.set_cursor_offset(self.conn, file_id, last_off + len(last_raw) + 1, size)
        return stats
