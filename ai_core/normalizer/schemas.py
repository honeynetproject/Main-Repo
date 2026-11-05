"""Typed contracts for the Phase 7 normalizer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

SCHEMA_VERSION = 1
UID_VERSION = "cdp-uid-v1"


@dataclass(frozen=True)
class SourceRef:
    """Where a raw line came from (provenance)."""
    log_file_id: str          # stable identity of the file generation
    file_seq: int             # order in which file generations were first seen
    byte_offset_start: int    # offset of the first byte of the line
    byte_offset_end: int      # offset just past the line's newline


@dataclass
class NormalizedEvent:
    event_uid: str
    raw_fingerprint: str
    source: str
    source_event_type: Optional[str]
    timestamp_original: Any
    timestamp_utc: Optional[str]
    timestamp_us: Optional[int]
    session_id: Optional[str]
    source_ip: Optional[str]
    username: Optional[str]
    message: Optional[str]
    command: Optional[str]
    is_command_input: bool
    orphan_reason: Optional[str]          # None when the event may update a session
    validation_errors: list = field(default_factory=list)
    raw_event: dict = field(default_factory=dict)
    raw_line: str = ""
    log_file_id: str = ""
    file_seq: int = 0
    byte_offset_start: int = 0
    byte_offset_end: int = 0
    schema_version: int = SCHEMA_VERSION
    uid_version: str = UID_VERSION


@dataclass
class NormalizationError:
    """A complete line that could not become an event (dead-letter record)."""
    error_type: str           # decode_error | malformed_json | non_object_json
    error_detail: str
    raw_line: str             # decoded with replacement, for diagnosis
    log_file_id: str
    byte_offset: int
