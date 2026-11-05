import json
import os
import shutil
import threading
import time

import pytest

from ai_core.normalizer import follower as follower_mod
from ai_core.normalizer.follower import LogFollower
from ai_core.persistence import connect, init_schema
from ai_core.sessions.manager import get_session
from tests.conftest import line, make_event


def name(n):
    # letters, not digits: the training cleaning rule strips trailing digits (cmd1 -> cmd)
    return "cmd" + chr(96 + n)


def cmd(sid, n, text=None):
    return make_event(session=sid, ts=f"2026-11-04T10:00:{n:02d}.000000Z", input=text or name(n))


def count(conn, table="events"):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.fixture
def log(tmp_path):
    return tmp_path / "cowrie.json"


def append(path, *chunks):
    with open(path, "ab") as f:
        for c in chunks:
            f.write(c if isinstance(c, bytes) else line(c))


def cursor(conn):
    return conn.execute("SELECT * FROM follower_cursors WHERE is_current=1").fetchone()


def test_reads_only_new_complete_lines_incrementally(conn, log):
    f = LogFollower(conn, log)
    assert f.poll_once().lines == 0                       # file missing: no crash
    append(log, cmd("A", 1), cmd("A", 2))
    s = f.poll_once()
    assert s.events_inserted == 2 and count(conn) == 2
    assert cursor(conn)["committed_offset"] == os.path.getsize(log)
    append(log, cmd("A", 3))
    s = f.poll_once()
    assert s.lines == 1 and s.events_inserted == 1 and count(conn) == 3   # not re-reading old lines
    assert f.poll_once().lines == 0


def test_partial_line_buffered_until_newline(conn, log):
    full = line(cmd("A", 2))
    append(log, cmd("A", 1), full[:20])
    f = LogFollower(conn, log)
    assert f.poll_once().events_inserted == 1
    first_len = len(line(cmd("A", 1)))
    assert cursor(conn)["committed_offset"] == first_len        # cursor stops at the line start
    assert count(conn) == 1 and count(conn, "normalization_errors") == 0   # partial is NOT a malformed record
    append(log, full[20:])
    assert f.poll_once().events_inserted == 1
    assert get_session(conn, "A")["full_session"] == "cmda cmdb"


def test_buffered_partial_line_survives_restart(tmp_path, log):
    dbp = tmp_path / "x.sqlite3"
    full = line(cmd("A", 2))
    append(log, cmd("A", 1), full[:15])
    c1 = connect(dbp); init_schema(c1)
    LogFollower(c1, log).poll_once(); c1.close()               # "process dies" with a partial line pending
    append(log, full[15:])
    c2 = connect(dbp); init_schema(c2)
    s = LogFollower(c2, log).poll_once()                       # new process
    assert s.events_inserted == 1 and count(c2) == 2
    assert get_session(c2, "A")["command_count"] == 2


def test_malformed_complete_line_recorded_and_next_line_processed(conn, log):
    append(log, cmd("A", 1), b'{"broken": \n', b"[1,2]\n", cmd("A", 2))
    s = LogFollower(conn, log).poll_once()
    assert s.events_inserted == 2 and s.errors == 2
    kinds = sorted(r[0] for r in conn.execute("SELECT error_type FROM normalization_errors"))
    assert kinds == ["malformed_json", "non_object_json"]
    assert cursor(conn)["committed_offset"] == os.path.getsize(log)


def test_replaying_same_file_does_not_duplicate(conn, log):
    append(log, *[cmd("A", i) for i in range(1, 6)], make_event(session="A", eventid="cowrie.session.closed",
                                                                  ts="2026-11-04T10:00:30.000000Z", duration_ms=1))
    LogFollower(conn, log).replay()
    snap = get_session(conn, "A")
    assert count(conn) == 6 and snap["command_count"] == 5
    conn.execute("DELETE FROM follower_cursors")                # lose the cursor -> full re-read
    s = LogFollower(conn, log).replay()
    assert s.events_inserted == 0 and s.duplicates == 6
    assert count(conn) == 6 and count(conn, "commands") == 5 and get_session(conn, "A") == snap


def test_rename_create_rotation_drains_old_file_then_new(conn, log, tmp_path):
    append(log, cmd("A", 1), cmd("A", 2))
    f = LogFollower(conn, log)
    f.poll_once()
    append(log, cmd("A", 3), cmd("A", 4))                       # written but not yet polled
    os.rename(log, tmp_path / "cowrie.json.2026-11-04")         # rotate
    append(log, cmd("B", 5), cmd("B", 6))                       # new generation
    s = f.poll_once()
    assert s.rotations == 1 and count(conn) == 6
    assert get_session(conn, "A")["full_session"] == "cmda cmdb cmdc cmdd"
    assert get_session(conn, "B")["full_session"] == "cmde cmdf"
    assert count(conn, "normalization_errors") == 0
    assert conn.execute("SELECT COUNT(*) FROM follower_cursors WHERE finished=1").fetchone()[0] == 1
    append(log, cmd("B", 7))
    assert f.poll_once().events_inserted == 1


def test_rotation_with_partial_final_line_is_recorded_not_lost_silently(conn, log, tmp_path):
    append(log, cmd("A", 1))
    f = LogFollower(conn, log); f.poll_once()
    append(log, cmd("A", 2), line(cmd("A", 3))[:25])
    os.rename(log, tmp_path / "cowrie.json.1")
    append(log, cmd("B", 4))
    f.poll_once()
    assert get_session(conn, "A")["full_session"] == "cmda cmdb" and get_session(conn, "B")["command_count"] == 1
    row = conn.execute("SELECT error_type FROM normalization_errors").fetchall()
    assert [r[0] for r in row] == ["partial_final_line_on_rotation"]


def test_copy_truncate_rotation_without_skipping_data(conn, log, tmp_path):
    append(log, cmd("A", 1), cmd("A", 2))
    f = LogFollower(conn, log); f.poll_once()
    append(log, cmd("A", 3))                                    # unread at rotation time
    shutil.copy(log, tmp_path / "cowrie.json.1")                # copy ...
    with open(log, "wb"):
        pass                                                    # ... then truncate (size < committed offset)
    assert f.poll_once().lines == 0                             # empty file: wait, do nothing destructive
    append(log, cmd("B", 4), cmd("B", 5))
    s = f.poll_once()
    assert s.rotations == 1
    assert get_session(conn, "A")["full_session"] == "cmda cmdb cmdc"
    assert get_session(conn, "B")["full_session"] == "cmdd cmde"
    assert count(conn) == 5 and count(conn, "normalization_errors") == 0


def test_truncate_without_copy_fails_visibly(conn, log):
    append(log, cmd("A", 1), cmd("A", 2))
    f = LogFollower(conn, log); f.poll_once()
    with open(log, "wb"):
        pass
    append(log, cmd("B", 3))
    f.poll_once()
    kinds = [r[0] for r in conn.execute("SELECT error_type FROM normalization_errors")]
    assert kinds == ["rotation_source_missing"]
    assert get_session(conn, "B")["command_count"] == 1


def test_same_first_line_but_shrunk_is_detected(conn, log):
    first = cmd("A", 1)
    append(log, first, cmd("A", 2), cmd("A", 3))
    f = LogFollower(conn, log); f.poll_once()
    with open(log, "wb") as fh:                                  # rewritten, identical first line, shorter
        fh.write(line(first))
    f.poll_once()
    kinds = [r[0] for r in conn.execute("SELECT error_type FROM normalization_errors")]
    assert "truncation_detected" in kinds and count(conn) == 3   # nothing double counted


def test_persistence_failure_does_not_advance_cursor_and_is_retried(conn, log, monkeypatch):
    append(log, cmd("A", 1), cmd("A", 2), cmd("A", 3))
    real = follower_mod.apply_event
    calls = {"n": 0}

    def flaky(c, ev, touched=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise sqlite_error()
        return real(c, ev, touched)

    def sqlite_error():
        import sqlite3
        return sqlite3.OperationalError("disk I/O error (simulated)")

    monkeypatch.setattr(follower_mod, "apply_event", flaky)
    f = LogFollower(conn, log)
    with pytest.raises(Exception):
        f.poll_once()
    assert count(conn) == 0                                      # whole batch rolled back
    cur = conn.execute("SELECT committed_offset FROM follower_cursors").fetchone()
    assert cur["committed_offset"] == 0                          # cursor NOT advanced
    monkeypatch.setattr(follower_mod, "apply_event", real)
    assert f.poll_once().events_inserted == 3
    assert count(conn) == 3 and get_session(conn, "A")["command_count"] == 3


def test_small_batches_commit_progressively(conn, log):
    append(log, *[cmd("A", i) for i in range(1, 8)])
    f = LogFollower(conn, log, batch_lines=3, read_chunk=64)
    assert f.replay().events_inserted == 7
    assert get_session(conn, "A")["full_session"] == " ".join(name(i) for i in range(1, 8))


def test_blank_lines_are_skipped_without_errors(conn, log):
    append(log, cmd("A", 1), b"\n", b"   \n", cmd("A", 2))
    LogFollower(conn, log).poll_once()
    assert count(conn) == 2 and count(conn, "normalization_errors") == 0


def _run_in_thread(dbp, log, stop):
    c = connect(dbp)                       # sqlite connections are per-thread
    try:
        LogFollower(c, log).run(stop, 0.02)
    finally:
        c.close()


def test_follow_mode_runs_and_stops_cleanly(conn, log, tmp_path):
    dbp = tmp_path / "thread.sqlite3"
    c = connect(dbp); init_schema(c); c.close()
    stop = threading.Event()
    t = threading.Thread(target=_run_in_thread, args=(dbp, log, stop)); t.start()
    try:
        append(log, cmd("A", 1)); time.sleep(0.3)
        append(log, cmd("A", 2)); time.sleep(0.3)
    finally:
        stop.set(); t.join(timeout=5)
    assert not t.is_alive()
    r = connect(dbp)
    assert count(r) == 2


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_permission_error_surfaces_and_run_loop_survives(conn, log, caplog):
    append(log, cmd("A", 1))
    os.chmod(log, 0)
    f = LogFollower(conn, log)
    with pytest.raises(PermissionError):
        f.poll_once()
    dbp = conn.execute("PRAGMA database_list").fetchone()["file"]
    stop = threading.Event()
    t = threading.Thread(target=_run_in_thread, args=(dbp, log, stop)); t.start()
    time.sleep(0.2)
    os.chmod(log, 0o644)
    time.sleep(0.4)
    stop.set(); t.join(timeout=5)
    assert count(conn) == 1


def test_oversize_unterminated_line_is_reported(conn, log):
    append(log, cmd("A", 1), b"x" * 5000)
    f = LogFollower(conn, log, max_line_bytes=1000, read_chunk=512)
    f.poll_once()
    kinds = [r[0] for r in conn.execute("SELECT error_type FROM normalization_errors")]
    assert kinds == ["oversize_partial_line"] and count(conn) == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_works_when_log_directory_is_read_only(tmp_path, cowrie_fixture_path):
    """Mirrors the container: Cowrie logs are mounted :ro, only the DB dir is writable."""
    logdir = tmp_path / "ro"
    logdir.mkdir()
    shutil.copy(cowrie_fixture_path, logdir / "cowrie.json")
    os.chmod(logdir / "cowrie.json", 0o444)
    os.chmod(logdir, 0o555)
    try:
        c = connect(tmp_path / "db.sqlite3"); init_schema(c)
        assert LogFollower(c, logdir / "cowrie.json").replay().events_inserted == 156
        c.close()
    finally:
        os.chmod(logdir, 0o755)
