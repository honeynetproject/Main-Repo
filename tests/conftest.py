import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def make_event(session="s1", eventid="cowrie.command.input", ts="2026-11-04T10:00:00.000000Z",
               src_ip="10.77.10.20", **extra):
    d = {"session": session, "eventid": eventid, "timestamp": ts, "src_ip": src_ip}
    if eventid == "cowrie.command.input" and "input" not in extra:
        extra["input"] = "id"
    d.update(extra)
    return d


def line(d) -> bytes:
    return (json.dumps(d) + "\n").encode()


@pytest.fixture
def cowrie_fixture_path():
    return FIXTURES / "cowrie" / "phase5_6_sanitized.jsonl"


from ai_core.normalizer import SourceRef, normalize_line  # noqa: E402
from ai_core.persistence import connect, init_schema, transaction  # noqa: E402
from ai_core.sessions.manager import apply_event, recompute_sessions  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.sqlite3")
    init_schema(c)
    yield c
    c.close()


def ingest_dicts(conn, dicts, file_id="sha256:f1", file_seq=1, start=0):
    """Normalize+apply dicts as consecutive lines of one file generation, in one txn."""
    touched, off, results = set(), start, []
    with transaction(conn):
        for d in dicts:
            raw = json.dumps(d).encode()
            src = SourceRef(file_id, file_seq, off, off + len(raw) + 1)
            ev = normalize_line(raw, src)
            results.append(apply_event(conn, ev, touched))
            off = src.byte_offset_end
        recompute_sessions(conn, touched)
    return results
