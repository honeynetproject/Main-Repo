import json
from pathlib import Path

from ai_core.sessions.fullsession import (RULE_ID, build_full_session, clean_full_session,
                                          decode_session, full_session_tokens, raw_session_string)

PARITY = Path(__file__).resolve().parents[1] / "fixtures" / "training" / "fullsession_parity.jsonl"


def _rows():
    return [json.loads(l) for l in PARITY.read_text().splitlines()]


def test_parity_fixture_shape():
    rows = _rows()
    assert len(rows) == 20 and sum(r["base64_decoded"] for r in rows) == 6


def test_live_builder_matches_training_tokens_exactly():
    """Raw dataset sessions -> builder must equal the training decoded tokens."""
    for r in _rows():
        assert clean_full_session(decode_session(r["raw"])) == r["tokens"], r["session_id"]


def test_commands_roundtrip_through_raw_format():
    """Per-command inputs joined the dataset way produce the same tokens as the
    dataset raw string split on ';' (the dataset raw is cmd ; cmd ; ... ;)."""
    for r in _rows():
        cmds = [c.strip() for c in r["raw"].split(";") if c.strip()]
        assert full_session_tokens(cmds) == r["tokens"], r["session_id"]


def test_join_is_single_space_of_tokens():
    r = _rows()[0]
    assert build_full_session([c for c in r["raw"].split(";") if c.strip()]) == " ".join(r["tokens"])


def test_known_examples_no_arbitrary_splitting():
    assert build_full_session(["uname -a"]) == "uname -a"
    assert build_full_session(["id", "uname -a", "pwd", "ls -la", "cat /etc/os-release", "whoami"]) == \
        "id uname -a pwd ls -la cat /etc/os-release whoami"
    # '=' values and trailing digits are removed exactly as in training
    assert full_session_tokens(["dd bs=52 count=1 if=.s"]) == ["dd", "bs", "count", "if"]
    assert full_session_tokens(["python3 -c 'print(1)'"]) == ["python", "-c", "print"]


def test_empty_and_whitespace_commands_add_no_tokens():
    assert full_session_tokens([]) == []
    assert full_session_tokens(["", "  "]) == []
    assert build_full_session(["id", "", "pwd"]) == "id pwd"


def test_case_is_preserved():
    assert build_full_session(["cat SAEMW"]) == "cat SAEMW"


def test_trailing_echo_does_not_crash_ingestion():
    cmds = ["echo", "x base64 --decode echo"]
    assert isinstance(build_full_session(cmds), str)


def test_rule_id_declared():
    assert RULE_ID == "section0-v1"
