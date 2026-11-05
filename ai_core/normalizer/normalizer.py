"""Canonical event conversion, identity and fingerprints (Phase 7 spec 6-9)."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Union

from .parser import parse_line
from .schemas import NormalizationError, NormalizedEvent, SourceRef, UID_VERSION

COMMAND_INPUT_EVENT = "cowrie.command.input"

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})?$"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_timestamp(value) -> Optional[Tuple[str, int]]:
    """Return (UTC ISO-8601 with microseconds and Z, integer microseconds since
    epoch), or None when the value is not a timezone-aware timestamp. A naive
    timestamp is rejected rather than assumed to be UTC (no invented data)."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m or not m.group(8):
        return None
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    frac = (m.group(7) or "").ljust(6, "0")[:6]
    tz = m.group(8)
    if tz == "Z":
        off = timedelta(0)
    else:
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        off = sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    try:
        dt = datetime(y, mo, d, h, mi, s, int(frac), tzinfo=timezone(off))
    except ValueError:
        return None
    utc = dt.astimezone(timezone.utc)
    us = (utc - _EPOCH) // timedelta(microseconds=1)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), us


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_raw_fingerprint(raw_event: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(raw_event)).hexdigest()


def compute_event_uid(log_file_id: str, byte_offset: int, raw_line: bytes) -> str:
    h = hashlib.sha256()
    h.update(UID_VERSION.encode() + b"\0")
    h.update(log_file_id.encode() + b"\0")
    h.update(str(byte_offset).encode() + b"\0")
    h.update(raw_line)
    return "sha256:" + h.hexdigest()


def _opt_str(obj: dict, key: str, errors: list) -> Optional[str]:
    v = obj.get(key)
    if v is None:
        return None
    if isinstance(v, str):
        return v
    errors.append(f"invalid_{key}")
    return None


def normalize_object(obj: dict, raw_line: bytes, src: SourceRef) -> NormalizedEvent:
    errors: list = []

    etype = obj.get("eventid")
    if not isinstance(etype, str) or not etype:
        errors.append("missing_event_type")
        etype = None

    ts_original = obj.get("timestamp")
    parsed = parse_timestamp(ts_original)
    if parsed is None:
        errors.append("missing_timestamp" if ts_original is None else "invalid_timestamp")
    ts_utc, ts_us = parsed if parsed else (None, None)

    sid = obj.get("session")
    if not isinstance(sid, str) or not sid.strip():
        errors.append("missing_session" if sid is None else "invalid_session")
        sid = None

    ip = obj.get("src_ip")
    if ip is None:
        errors.append("missing_src_ip")
        ip = None
    else:
        try:
            ip = str(ipaddress.ip_address(ip)) if isinstance(ip, str) else None
        except ValueError:
            ip = None
        if ip is None:
            errors.append("invalid_src_ip")

    is_cmd = etype == COMMAND_INPUT_EVENT
    command = None
    if is_cmd:
        raw_cmd = obj.get("input")
        if isinstance(raw_cmd, str):
            command = raw_cmd
        else:
            errors.append("missing_command_text" if raw_cmd is None else "invalid_command_text")

    # An event may update a session only if it has a usable session and a
    # timestamp that can order it. Otherwise it is stored as an orphan.
    orphan = None
    if sid is None:
        orphan = "missing_session"
    elif ts_us is None:
        orphan = "unorderable_timestamp"

    return NormalizedEvent(
        event_uid=compute_event_uid(src.log_file_id, src.byte_offset_start, raw_line),
        raw_fingerprint=compute_raw_fingerprint(obj),
        source="cowrie",
        source_event_type=etype,
        timestamp_original=ts_original,
        timestamp_utc=ts_utc,
        timestamp_us=ts_us,
        session_id=sid,
        source_ip=ip,
        username=_opt_str(obj, "username", errors),
        message=_opt_str(obj, "message", errors),
        command=command,
        is_command_input=is_cmd and command is not None,
        orphan_reason=orphan,
        validation_errors=errors,
        raw_event=obj,
        raw_line=raw_line.decode("utf-8", errors="replace"),
        log_file_id=src.log_file_id,
        file_seq=src.file_seq,
        byte_offset_start=src.byte_offset_start,
        byte_offset_end=src.byte_offset_end,
    )


def normalize_line(raw_line: bytes, src: SourceRef) -> Union[NormalizedEvent, NormalizationError]:
    """Normalize one complete line (without its trailing newline)."""
    obj, err = parse_line(raw_line)
    if err is not None:
        return NormalizationError(
            error_type=err[0], error_detail=err[1],
            raw_line=raw_line.decode("utf-8", errors="replace"),
            log_file_id=src.log_file_id, byte_offset=src.byte_offset_start,
        )
    return normalize_object(obj, raw_line, src)
