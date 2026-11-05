"""Raw line -> JSON object, with explicit failure categories."""
from __future__ import annotations

import json
from typing import Optional, Tuple


def parse_line(raw: bytes) -> Tuple[Optional[dict], Optional[Tuple[str, str]]]:
    """Return (obj, None) or (None, (error_type, detail)). Never raises."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, ("decode_error", f"utf-8 decode failed at byte {exc.start}")
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError) as exc:
        return None, ("malformed_json", str(exc)[:200])
    if not isinstance(obj, dict):
        return None, ("non_object_json", f"top-level JSON is {type(obj).__name__}")
    return obj, None
