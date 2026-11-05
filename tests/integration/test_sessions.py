from ai_core.normalizer import SourceRef, normalize_line
from ai_core.persistence import connect, init_schema, transaction
from ai_core.sessions.manager import apply_event, get_commands, get_session, ingest_event, recompute_sessions
from tests.conftest import ingest_dicts, make_event
import json


def cmd(sid, ts, text, **kw):
    return make_event(session=sid, ts=ts, input=text, **kw)


def test_events_with_same_session_update_one_session(conn):
    ingest_dicts(conn, [make_event(session="A", eventid="cowrie.session.connect", ts="2026-11-04T10:00:00.000000Z"),
                        cmd("A", "2026-11-04T10:00:01.000000Z", "id"),
                        cmd("A", "2026-11-04T10:00:02.000000Z", "pwd")])
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    s = get_session(conn, "A")
    assert s["command_count"] == 2 and s["event_count"] == 3


def test_two_sessions_same_ip_stay_separate(conn):
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:01.000000Z", "id", src_ip="10.77.10.20"),
                        cmd("B", "2026-11-04T10:00:02.000000Z", "pwd", src_ip="10.77.10.20")])
    a, b = get_session(conn, "A"), get_session(conn, "B")
    assert a["full_session"] == "id" and b["full_session"] == "pwd"
    assert a["source_ip"] == b["source_ip"] == "10.77.10.20"


def test_duplicate_event_uid_does_not_double_count(conn):
    evs = [cmd("A", "2026-11-04T10:00:01.000000Z", "id"), cmd("A", "2026-11-04T10:00:02.000000Z", "pwd")]
    assert ingest_dicts(conn, evs) == [True, True]
    assert ingest_dicts(conn, evs) == [False, False]       # same file id + offsets -> replay
    s = get_session(conn, "A")
    assert s["command_count"] == 2 and s["event_count"] == 2
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 2


def test_identical_commands_at_different_offsets_are_both_kept(conn):
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:01.000000Z", "pwd"), cmd("A", "2026-11-04T10:00:01.000000Z", "pwd")])
    s = get_session(conn, "A")
    assert s["command_count"] == 2 and s["unique_command_count"] == 1 and s["full_session"] == "pwd pwd"


def test_commands_reconstructed_in_timestamp_order_with_tiebreak(conn):
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:03.000000Z", "third"),
                        cmd("A", "2026-11-04T10:00:01.000000Z", "first"),
                        cmd("A", "2026-11-04T10:00:02.000000Z", "second-a"),
                        cmd("A", "2026-11-04T10:00:02.000000Z", "second-b")])
    assert [c["command_text"] for c in get_commands(conn, "A")] == ["first", "second-a", "second-b", "third"]
    assert get_session(conn, "A")["full_session"] == "first second-a second-b third"


def test_late_arriving_older_event_is_ordered_correctly(conn):
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:05.000000Z", "late-newer")], start=0)
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:01.000000Z", "arrived-late-but-older")], start=1000)
    s = get_session(conn, "A")
    assert s["full_session"] == "arrived-late-but-older late-newer"
    assert s["started_at_utc"] == "2026-11-04T10:00:01.000000Z"
    assert s["last_activity_at_utc"] == "2026-11-04T10:00:05.000000Z"   # never moves backwards


def test_started_earliest_last_latest(conn):
    ingest_dicts(conn, [make_event(session="A", eventid="cowrie.session.connect", ts="2026-11-04T10:00:00.000000Z"),
                        cmd("A", "2026-11-04T10:09:00.000000Z", "x"),
                        cmd("A", "2026-11-04T10:05:00.000000Z", "y")])
    s = get_session(conn, "A")
    assert s["started_at_utc"] == "2026-11-04T10:00:00.000000Z" and s["last_activity_at_utc"] == "2026-11-04T10:09:00.000000Z"


def test_counts_unique_and_empty_commands(conn):
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:01.000000Z", "id"), cmd("A", "2026-11-04T10:00:02.000000Z", ""),
                        cmd("A", "2026-11-04T10:00:03.000000Z", "id"), cmd("A", "2026-11-04T10:00:04.000000Z", "ls -la")])
    s = get_session(conn, "A")
    assert s["command_count"] == 3 and s["unique_command_count"] == 2          # empty excluded from counts
    assert len(get_commands(conn, "A")) == 4                                   # but preserved as a record
    assert s["full_session"] == "id id ls -la"


def test_incremental_snapshots_update_after_each_command(conn):
    seen, off = [], 0
    for i, text in enumerate(["id", "uname -a", "pwd"]):
        d = cmd("A", f"2026-11-04T10:00:0{i+1}.000000Z", text)
        ingest_dicts(conn, [d], start=off)
        off += 1000
        seen.append(get_session(conn, "A")["full_session"])
    assert seen == ["id", "id uname -a", "id uname -a pwd"]
    assert get_session(conn, "A")["status"] == "active" and get_session(conn, "A")["is_complete"] == 0


def test_close_event_closes_correct_session_only(conn):
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:01.000000Z", "id"), cmd("B", "2026-11-04T10:00:01.500000Z", "id"),
                        make_event(session="A", eventid="cowrie.session.closed", ts="2026-11-04T10:00:09.000000Z",
                                   duration_ms=9000, message="Connection lost after 9000 milliseconds")])
    a, b = get_session(conn, "A"), get_session(conn, "B")
    assert a["status"] == "closed" and a["is_complete"] == 1 and a["closure_reason"] == "cowrie.session.closed"
    assert a["closed_at_utc"] == "2026-11-04T10:00:09.000000Z" and a["duration_ms"] == 9000
    assert b["status"] == "active" and b["is_complete"] == 0


def test_late_command_does_not_reopen_closed_session(conn):
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:01.000000Z", "id"),
                        make_event(session="A", eventid="cowrie.session.closed", ts="2026-11-04T10:00:09.000000Z", duration_ms=8000)])
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:05.000000Z", "late-before-close")], start=5000)
    s = get_session(conn, "A")
    assert s["status"] == "closed" and s["closed_at_utc"] == "2026-11-04T10:00:09.000000Z"
    assert s["full_session"] == "id late-before-close" and s["command_count"] == 2


def test_active_session_not_complete_without_close(conn):
    ingest_dicts(conn, [cmd("A", "2020-01-01T00:00:00.000000Z", "id")])    # ancient, no close -> still active
    assert get_session(conn, "A")["status"] == "active"


def test_orphan_events_stored_but_update_no_session(conn):
    d = make_event(); del d["session"]
    bad_ts = cmd("A", "garbage", "id")
    ingest_dicts(conn, [d, bad_ts])
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
    reasons = sorted(r[0] for r in conn.execute("SELECT orphan_reason FROM events"))
    assert reasons == ["missing_session", "unorderable_timestamp"]


def test_ip_is_never_a_session_key(conn):
    d = make_event(); del d["session"]
    ingest_dicts(conn, [d])
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_downloads_unknown_not_invented(conn):
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:01.000000Z", "wget http://x/y")])
    s = get_session(conn, "A")
    assert s["has_downloads"] is None and s["download_count"] is None


def test_restart_reconstructs_same_snapshot_without_duplicates(tmp_path):
    path = tmp_path / "r.sqlite3"
    evs = [cmd("A", "2026-11-04T10:00:01.000000Z", "id"), cmd("A", "2026-11-04T10:00:02.000000Z", "uname -a"),
           make_event(session="A", eventid="cowrie.session.closed", ts="2026-11-04T10:00:03.000000Z", duration_ms=3000)]
    c1 = connect(path); init_schema(c1); ingest_dicts(c1, evs); snap1 = get_session(c1, "A"); c1.close()
    c2 = connect(path); init_schema(c2)
    assert ingest_dicts(c2, evs) == [False, False, False]
    assert get_session(c2, "A") == snap1
    # a full recompute from stored rows yields the identical snapshot too
    with transaction(c2):
        recompute_sessions(c2, ["A"])
    assert get_session(c2, "A") == snap1
    c2.close()


def test_persistence_failure_rolls_back_whole_batch(conn):
    import pytest
    ingest_dicts(conn, [cmd("A", "2026-11-04T10:00:01.000000Z", "id")])
    before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    with pytest.raises(RuntimeError):
        with transaction(conn):
            raw = json.dumps(cmd("A", "2026-11-04T10:00:02.000000Z", "pwd")).encode()
            ev = normalize_line(raw, SourceRef("sha256:f1", 1, 9000, 9100))
            apply_event(conn, ev, set())
            raise RuntimeError("simulated failure")
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before
    assert get_session(conn, "A")["command_count"] == 1
