"""Training-compatible ``full_session`` builder.

Reproduces, verbatim, the preprocessing in
models/section0_data_preprocessing_and_cleaning.ipynb (``decode_session`` then
``clean_full_session``) and the training notebook's join
(``" ".join(tokens)``; models/section4_language_model_exploration.ipynb).

Verified against the dataset: 15,000 / 15,000 sampled rows matched.
Do NOT change the behaviour here without re-verifying against training data.
"""
from __future__ import annotations

import base64
import re
from typing import Iterable, List

RULE_ID = "section0-v1"


def _decode_base64(word: str):
    try:
        return base64.b64decode(word).decode()
    except Exception:
        return None


def decode_session(full_session: str) -> str:
    out = []
    for chunk in full_session.split(";"):
        if "base64 --decode" in chunk and "echo" in chunk:
            parts = chunk.split()
            b64 = None
            for i in range(len(parts)):
                if parts[i] == "echo":
                    b64 = parts[i + 1].strip("\"")  # same IndexError behaviour as training
                    break
            if b64:
                decoded = _decode_base64(b64)
                if decoded:
                    out.append("; ".join(list(filter(None, decoded.split("\n")))).strip())
                else:
                    out.append(chunk.strip())
            else:
                out.append(chunk.strip())
        else:
            out.append(chunk.strip())
    return "; ".join(out)


def clean_full_session(session: str) -> List[str]:
    cleaned = []
    for cmd in re.split(r"[;\s\n\t]+", session):
        if "#!/bin/bash" in cmd:
            cleaned.append(cmd)
            continue
        cmd = cmd.strip()
        cmd = re.sub(r"[^a-zA-Z0-9\/=\-\.]+", "", cmd)
        if "=" in cmd:
            cmd = cmd.split("=")[0]
        cmd = re.sub(r"\d+$", "", cmd)
        if cmd:
            cleaned.append(cmd)
    return cleaned


def raw_session_string(commands: Iterable[str]) -> str:
    """Dataset raw format: commands joined by ' ; ' with a trailing ' ;'."""
    return " ; ".join(commands) + " ;"


def full_session_tokens(commands: Iterable[str]) -> List[str]:
    cmds = list(commands)
    if not cmds:
        return []
    try:
        return clean_full_session(decode_session(raw_session_string(cmds)))
    except IndexError:
        # 'echo' as the last word of a chunk: the training code would raise.
        # Fall back to cleaning without the base64 step rather than crash ingestion.
        return clean_full_session(raw_session_string(cmds))


def build_full_session(commands: Iterable[str]) -> str:
    """Text that is fed to the tokenizer: tokens joined by single spaces."""
    return " ".join(full_session_tokens(commands))
