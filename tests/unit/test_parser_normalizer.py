import json
from datetime import datetime, timedelta, timezone

from ai_core.normalizer import NormalizationError, NormalizedEvent, SourceRef, normalize_line
from ai_core.normalizer.normalizer import compute_event_uid, compute_raw_fingerprint, parse_timestamp
from ai_core.normalizer.phase0 import to_phase0
from tests.conftest import make_event

SRC = SourceRef(log_file_id="sha256:f1", file_seq=1, byte_offset_start=0, byte_offset_end=100)


def norm(d, src=SRC):
    raw = json.dumps(d).encode()
    return normalize_line(raw, src)


def test_valid_event_maps_to_canonical_fields():
    d = make_event(session="abc123", ts="2026-11-04T03:41:50.395330Z", input="uname -a",
                   message="CMD: uname -a", username="root")
    ev = norm(d)
    assert isinstance(ev, NormalizedEvent)
    assert ev.source == "cowrie" and ev.session_id == "abc123"
    assert ev.source_ip == "10.77.10.20" and ev.command == "uname -a" and ev.is_command_input
    assert ev.message == "CMD: uname -a" and ev.username == "root"
    assert ev.raw_event == d and ev.validation_errors == [] and ev.orphan_reason is None


def test_eventid_is_source_event_type_not_uid():
    ev = norm(make_event(eventid="cowrie.session.connect"))
    assert ev.source_event_type == "cowrie.session.connect"
    assert ev.event_uid.startswith("sha256:") and ev.event_uid != ev.source_event_type
    assert ev.event_uid != ev.raw_fingerprint


def test_timestamp_original_preserved_and_utc_normalized():
    ev = norm(make_event(ts="2026-11-04T03:41:50.395330Z"))
    assert ev.timestamp_original == "2026-11-04T03:41:50.395330Z"
    assert ev.timestamp_utc == "2026-11-04T03:41:50.395330Z"
    ev2 = norm(make_event(ts="2026-11-04T06:41:50+03:00"))
    assert ev2.timestamp_utc == "2026-11-04T03:41:50.000000Z" and ev2.timestamp_original == "2026-11-04T06:41:50+03:00"
    expected = (datetime(2026, 11, 4, 3, 41, 50, 395330, tzinfo=timezone.utc)
                - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(microseconds=1)
    assert ev.timestamp_us == expected


def test_naive_or_garbage_timestamp_is_not_invented():
    for bad in ("2026-11-04T03:41:50", "yesterday", 12345, None):
        ev = norm(make_event(ts=bad))
        assert ev.timestamp_utc is None and ev.timestamp_us is None
        assert ev.orphan_reason == "unorderable_timestamp"
        assert any("timestamp" in e for e in ev.validation_errors)


def test_ip_validation_ipv4_ipv6_invalid():
    assert norm(make_event(src_ip="10.77.10.20")).source_ip == "10.77.10.20"
    assert norm(make_event(src_ip="2001:db8::1")).source_ip == "2001:db8::1"
    bad = norm(make_event(src_ip="999.1.1.1"))
    assert bad.source_ip is None and "invalid_src_ip" in bad.validation_errors


def test_missing_optional_fields_are_null_with_note():
    d = make_event(eventid="cowrie.session.connect")
    del d["src_ip"]
    ev = norm(d)
    assert ev.source_ip is None and ev.message is None and ev.username is None
    assert "missing_src_ip" in ev.validation_errors


def test_missing_or_invalid_session_is_orphan_not_invented():
    d = make_event()
    del d["session"]
    ev = norm(d)
    assert ev.session_id is None and ev.orphan_reason == "missing_session"
    assert norm(make_event(session="")).orphan_reason == "missing_session"
    assert norm(make_event(session=123)).session_id is None


def test_unknown_event_type_retained():
    ev = norm(make_event(eventid="cowrie.something.new"))
    assert isinstance(ev, NormalizedEvent) and ev.source_event_type == "cowrie.something.new"
    assert not ev.is_command_input and ev.command is None


def test_missing_event_type_retained_with_note():
    d = make_event()
    del d["eventid"]
    ev = norm(d)
    assert ev.source_event_type is None and "missing_event_type" in ev.validation_errors


def test_command_input_exact_text_preserved():
    for text in ("ls  -la ", "  padded", "a;b && c | d", ""):
        ev = norm(make_event(input=text))
        assert ev.command == text and ev.is_command_input


def test_command_failed_is_not_command_input():
    ev = norm(make_event(eventid="cowrie.command.failed", input="eit "))
    assert ev.command is None and not ev.is_command_input


def test_invalid_command_text_flagged():
    ev = norm(make_event(input=123))
    assert ev.command is None and not ev.is_command_input and "invalid_command_text" in ev.validation_errors


def test_malformed_and_non_object_json_return_errors():
    for raw, kind in ((b'{"a": 1', "malformed_json"), (b"not json", "malformed_json"),
                      (b"[1,2,3]", "non_object_json"), (b'"str"', "non_object_json"),
                      (b"\xff\xfe{}", "decode_error")):
        r = normalize_line(raw, SRC)
        assert isinstance(r, NormalizationError) and r.error_type == kind


def test_event_uid_depends_on_location_and_bytes():
    raw = b'{"a":1}'
    u1 = compute_event_uid("f1", 0, raw)
    assert u1 == compute_event_uid("f1", 0, raw)           # deterministic
    assert u1 != compute_event_uid("f1", 10, raw)          # offset
    assert u1 != compute_event_uid("f2", 0, raw)           # file generation
    assert u1 != compute_event_uid("f1", 0, b'{"a":2}')    # bytes


def test_identical_content_distinct_uid_same_fingerprint():
    d = make_event(input="pwd")
    a = normalize_line(json.dumps(d).encode(), SourceRef("f1", 1, 0, 50))
    b = normalize_line(json.dumps(d).encode(), SourceRef("f1", 1, 50, 100))
    assert a.raw_fingerprint == b.raw_fingerprint and a.event_uid != b.event_uid


def test_raw_fingerprint_key_order_independent():
    assert compute_raw_fingerprint({"a": 1, "b": 2}) == compute_raw_fingerprint({"b": 2, "a": 1})


def test_parse_timestamp_fractions_and_offsets():
    assert parse_timestamp("2026-11-04T03:41:50.1Z")[0] == "2026-11-04T03:41:50.100000Z"
    assert parse_timestamp("2026-11-04T03:41:50Z")[0] == "2026-11-04T03:41:50.000000Z"
    assert parse_timestamp("2026-13-04T03:41:50Z") is None


def test_phase0_projection_and_rejections():
    ev = norm(make_event(session="s9", input="id", protocol="ssh", src_port=1234, dst_ip="172.18.0.2", dst_port=2222))
    out = to_phase0(ev, datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert out["event_type"] == "command_input" and out["event_time"] == ev.timestamp_utc
    assert out["session_id"] == "s9" and out["command"] == "id" and out["dst_ip"] == "172.18.0.2"
    import pytest
    with pytest.raises(ValueError):
        to_phase0(norm(make_event(session="")))
    with pytest.raises(ValueError):
        to_phase0(norm(make_event(src_ip="2001:db8::1")))
