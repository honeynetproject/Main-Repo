"""End-to-end replay against the sanitized Phase 5/6 Cowrie capture."""
import hashlib
import json
import re
import shutil
from pathlib import Path

from ai_core import ingest
from ai_core.normalizer.follower import LogFollower
from ai_core.persistence import connect, init_schema
from ai_core.sessions.fullsession import build_full_session
from ai_core.sessions.manager import get_commands, get_session

ROOT = Path(__file__).resolve().parents[2]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_expected(path):
    rows = [json.loads(l) for l in open(path, "rb") if l.strip()]
    by = {}
    for r in rows:
        by.setdefault(r["session"], []).append(r)
    return rows, by


def test_fixture_replay_matches_captured_log(conn, cowrie_fixture_path, tmp_path):
    log = tmp_path / "cowrie.json"
    shutil.copy(cowrie_fixture_path, log)
    before = sha(log)
    stats = LogFollower(conn, log).replay()
    rows, by = load_expected(log)

    assert sha(log) == before                                   # source evidence never modified
    assert stats.events_inserted == len(rows) == 156 and stats.errors == 0
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 156
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == len(by) == 14
    assert conn.execute("SELECT COUNT(DISTINCT source_ip) FROM sessions").fetchone()[0] == 1   # 14 sessions, one IP
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE status='closed' AND is_complete=1").fetchone()[0] == 14

    total_nonempty = 0
    for sid, evs in by.items():
        inputs = [e["input"] for e in evs if e["eventid"] == "cowrie.command.input"]
        s = get_session(conn, sid)
        assert s["command_count"] == len([i for i in inputs if i.strip()])
        assert s["unique_command_count"] == len({i for i in inputs if i.strip()})
        assert s["full_session"] == build_full_session(inputs)
        assert [c["command_text"] for c in get_commands(conn, sid)] == inputs      # exact order, exact text
        assert s["started_at_utc"] == evs[0]["timestamp"] and s["last_activity_at_utc"] == evs[-1]["timestamp"]
        total_nonempty += s["command_count"]
    assert total_nonempty == 38                                 # 39 command inputs, 1 empty
    assert conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 39

    # command.failed events are retained as events but never become commands
    assert conn.execute("SELECT COUNT(*) FROM events WHERE source_event_type='cowrie.command.failed'").fetchone()[0] == 3
    # raw JSON preserved verbatim
    for r in conn.execute("SELECT raw_event, raw_line FROM events"):
        assert json.loads(r["raw_event"]) == json.loads(r["raw_line"])


def test_known_sessions_from_phase6(conn, cowrie_fixture_path, tmp_path):
    shutil.copy(cowrie_fixture_path, tmp_path / "cowrie.json")
    LogFollower(conn, tmp_path / "cowrie.json").replay()
    assert get_session(conn, "df4e2975db2d")["full_session"] == "id uname -a pwd ls -la cat /etc/os-release whoami exit"
    assert get_session(conn, "ce7a2ea57fdd")["full_session"] == "hello exit"
    assert get_session(conn, "666d224be5a1")["full_session"] == "python -c printPHASE6EXECUTIONMARKER"
    assert get_session(conn, "a0e08a2f3685")["full_session"] == "crontab -l systemctl list-unit-files --type exit"
    s = get_session(conn, "a4f790093695")
    assert s["command_count"] == 6 and len(get_commands(conn, "a4f790093695")) == 7   # includes the empty Enter


def test_replaying_capture_twice_does_not_double_count(conn, cowrie_fixture_path, tmp_path):
    log = tmp_path / "cowrie.json"
    shutil.copy(cowrie_fixture_path, log)
    LogFollower(conn, log).replay()
    snap = {r["session_id"]: dict(r) for r in conn.execute("SELECT * FROM sessions")}
    conn.execute("DELETE FROM follower_cursors")
    s2 = LogFollower(conn, log).replay()
    assert s2.events_inserted == 0 and s2.duplicates == 156
    assert {r["session_id"]: dict(r) for r in conn.execute("SELECT * FROM sessions")} == snap
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 156


def test_cli_replay_with_env(monkeypatch, cowrie_fixture_path, tmp_path, capsys):
    logdir, dbdir = tmp_path / "logs", tmp_path / "db"
    logdir.mkdir()
    shutil.copy(cowrie_fixture_path, logdir / "cowrie.json")
    monkeypatch.setenv("COWRIE_LOG_DIR", str(logdir))
    monkeypatch.setenv("DATABASE_DIR", str(dbdir))
    assert ingest.main(["--replay"]) == 0
    c = connect(dbdir / "platform.sqlite3")
    assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 14


def test_fixture_has_no_credentials():
    text = (ROOT / "tests/fixtures/cowrie/phase5_6_sanitized.jsonl").read_text()
    assert set(re.findall(r'"password": "([^"]*)"', text)) == {"REDACTED"}
    assert "Cowire100" not in text


def test_phase7_code_grants_no_shell_or_firewall_access():
    banned = re.compile(r"\b(subprocess|os\.system|os\.popen|pty|socket|docker|iptables|nft|ufw)\b")
    for p in (ROOT / "ai_core").rglob("*.py"):
        code = "\n".join(l for l in p.read_text().splitlines() if not l.lstrip().startswith(("#", '"""')))
        hits = [m.group(0) for m in banned.finditer(code) if "firewall" not in m.group(0)]
        assert not hits, f"{p}: {hits}"


def test_phase7_does_not_import_classifier_rl_or_controller():
    # Phase 7 ingestion must stay stdlib-only. ai_core/classifier/ is the separate Phase 8 package (it
    # legitimately needs torch); everything else under ai_core/ must not import ML libraries, RL, the
    # controller, or the classifier package itself.
    for p in (ROOT / "ai_core").rglob("*.py"):
        if "classifier" in p.relative_to(ROOT / "ai_core").parts:
            continue
        text = p.read_text()
        for bad in ("torch", "transformers", "sklearn", "distilbert", "q_learning", "controller"):
            assert not re.search(rf"^\s*(import|from)\s+{bad}", text, re.M), (p, bad)
        assert not re.search(r"^\s*(import|from)\s+(ai_core\.classifier|\.+classifier)", text, re.M), p
