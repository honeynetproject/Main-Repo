"""Projection of a NormalizedEvent onto the Phase 0 canonical-event schema
(phase0_contracts/schemas/canonical-event.schema.json). Only verified Cowrie
event types get a specific event_type; everything else is 'other'."""
from __future__ import annotations

import ipaddress
from datetime import datetime, timezone

_TYPE_MAP = {
    "cowrie.session.connect": "session_started",
    "cowrie.session.closed": "session_closed",
    "cowrie.command.input": "command_input",
    "cowrie.command.failed": "command_failed",
    "cowrie.login.success": "auth_attempt",
    "cowrie.login.failed": "auth_attempt",
}


def to_phase0(event, ingested_at: datetime = None) -> dict:
    """Raise ValueError if the event cannot satisfy the (closed) Phase 0 schema:
    orphan events, missing/non-IPv4 source IP, unparseable timestamp."""
    if event.orphan_reason or event.session_id is None or event.timestamp_utc is None:
        raise ValueError(f"event not representable in Phase 0 schema: {event.orphan_reason}")
    if event.source_ip is None or ipaddress.ip_address(event.source_ip).version != 4:
        raise ValueError("Phase 0 schema requires an IPv4 source_ip")
    ingested = (ingested_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    raw = event.raw_event
    out = {
        "schema_version": "1.0",
        "event_uid": event.event_uid,
        "source": "cowrie",
        "source_event_type": event.source_event_type,
        "event_type": _TYPE_MAP.get(event.source_event_type, "other"),
        "event_time": event.timestamp_utc,
        "ingested_at": ingested.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "session_id": event.session_id,
        "source_ip": event.source_ip,
        "protocol": raw.get("protocol") if raw.get("protocol") in ("ssh", "telnet") else None,
        "src_port": raw.get("src_port") if isinstance(raw.get("src_port"), int) else None,
        "dst_ip": None,
        "dst_port": raw.get("dst_port") if isinstance(raw.get("dst_port"), int) else None,
        "command": event.command,
        "raw_event": raw,
    }
    dst = raw.get("dst_ip")
    try:
        if isinstance(dst, str) and ipaddress.ip_address(dst).version == 4:
            out["dst_ip"] = dst
    except ValueError:
        pass
    return out
