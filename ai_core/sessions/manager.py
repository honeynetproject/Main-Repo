"""Session Manager: idempotent event insertion and deterministic session
snapshots. Sessions are keyed ONLY by Cowrie's session id.

Session aggregates are recomputed from the stored events/commands in a stable
order (timestamp, file generation sequence, byte offset), so late-arriving
events, replays and restarts all converge to the same snapshot."""
from __future__ import annotations

import json
from typing import Iterable, Optional, Set

from ai_core.normalizer.schemas import NormalizedEvent

from .fullsession import RULE_ID, build_full_session

SESSION_CLOSED_EVENT = "cowrie.session.closed"  # verified in captured Phase 5/6 data
_ORDER = "timestamp_us, file_seq, byte_offset_start"


def insert_event(conn, ev: NormalizedEvent) -> bool:
    """INSERT OR IGNORE by event_uid. True if newly inserted, False if duplicate."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO events(event_uid,raw_fingerprint,schema_version,uid_version,source,source_event_type,"
        "timestamp_original,timestamp_utc,timestamp_us,session_id,source_ip,username,message,command,is_command_input,"
        "orphan_reason,validation_errors,raw_event,raw_line,log_file_id,file_seq,byte_offset_start,byte_offset_end)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ev.event_uid, ev.raw_fingerprint, ev.schema_version, ev.uid_version, ev.source, ev.source_event_type,
         None if ev.timestamp_original is None else str(ev.timestamp_original),
         ev.timestamp_utc, ev.timestamp_us, ev.session_id, ev.source_ip, ev.username, ev.message, ev.command,
         int(ev.is_command_input), ev.orphan_reason,
         json.dumps(ev.validation_errors), json.dumps(ev.raw_event, ensure_ascii=False), ev.raw_line,
         ev.log_file_id, ev.file_seq, ev.byte_offset_start, ev.byte_offset_end))
    return cur.rowcount == 1


def apply_event(conn, ev: NormalizedEvent, touched: Optional[Set[str]] = None) -> bool:
    """Persist one event and its command record. Returns False for a duplicate
    event_uid (nothing else is touched). Call recompute_sessions() on `touched`
    before committing."""
    if not insert_event(conn, ev):
        return False
    if ev.orphan_reason is None:
        conn.execute("INSERT OR IGNORE INTO sessions(session_id) VALUES(?)", (ev.session_id,))
        if ev.is_command_input:
            conn.execute(
                "INSERT OR IGNORE INTO commands(event_uid,session_id,command_text,is_empty,timestamp_utc,timestamp_us,"
                "file_seq,byte_offset_start) VALUES(?,?,?,?,?,?,?,?)",
                (ev.event_uid, ev.session_id, ev.command, int(ev.command.strip() == ""),
                 ev.timestamp_utc, ev.timestamp_us, ev.file_seq, ev.byte_offset_start))
        if touched is not None:
            touched.add(ev.session_id)
    return True


def ingest_event(conn, ev: NormalizedEvent) -> bool:
    """Convenience for tests/single events: apply + recompute (caller owns the transaction)."""
    touched: Set[str] = set()
    inserted = apply_event(conn, ev, touched)
    recompute_sessions(conn, touched)
    return inserted


def recompute_sessions(conn, session_ids: Iterable[str]) -> None:
    for sid in sorted(set(session_ids)):
        recompute_session(conn, sid)


def recompute_session(conn, sid: str) -> None:
    applied = "session_id=? AND orphan_reason IS NULL"
    first = conn.execute(f"SELECT timestamp_utc FROM events WHERE {applied} ORDER BY {_ORDER} LIMIT 1", (sid,)).fetchone()
    last = conn.execute(f"SELECT timestamp_utc FROM events WHERE {applied} ORDER BY timestamp_us DESC, file_seq DESC, "
                        "byte_offset_start DESC LIMIT 1", (sid,)).fetchone()
    n_events = conn.execute(f"SELECT COUNT(*) AS n FROM events WHERE {applied}", (sid,)).fetchone()["n"]
    ip = conn.execute(f"SELECT source_ip FROM events WHERE {applied} AND source_ip IS NOT NULL ORDER BY {_ORDER} LIMIT 1",
                      (sid,)).fetchone()
    cmds = conn.execute(f"SELECT command_text, is_empty FROM commands WHERE session_id=? ORDER BY {_ORDER}", (sid,)).fetchall()
    texts = [r["command_text"] for r in cmds]
    nonempty = [r["command_text"] for r in cmds if not r["is_empty"]]
    close = conn.execute(f"SELECT timestamp_utc, raw_event FROM events WHERE {applied} AND source_event_type=? "
                         f"ORDER BY {_ORDER} LIMIT 1", (sid, SESSION_CLOSED_EVENT)).fetchone()
    duration = None
    if close:
        d = json.loads(close["raw_event"]).get("duration_ms")
        duration = d if isinstance(d, int) and not isinstance(d, bool) else None
    conn.execute(
        "UPDATE sessions SET source_ip=?, started_at_utc=?, last_activity_at_utc=?, event_count=?, command_count=?,"
        " unique_command_count=?, full_session=?, full_session_rule=?, status=?, closure_reason=?, closed_at_utc=?,"
        " duration_ms=?, is_complete=? WHERE session_id=?",
        (ip["source_ip"] if ip else None, first["timestamp_utc"] if first else None,
         last["timestamp_utc"] if last else None, n_events, len(nonempty), len(set(nonempty)),
         build_full_session(texts), RULE_ID, "closed" if close else "active",
         SESSION_CLOSED_EVENT if close else None, close["timestamp_utc"] if close else None,
         duration, int(bool(close)), sid))


def get_session(conn, sid: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (sid,)).fetchone()
    return dict(row) if row else None


def get_commands(conn, sid: str):
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM commands WHERE session_id=? ORDER BY {_ORDER}", (sid,))]
