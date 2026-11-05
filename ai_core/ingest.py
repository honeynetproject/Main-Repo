"""CLI: ``python -m ai_core.ingest --replay`` (one-shot) or ``--follow``.
Reads COWRIE_LOG_DIR / DATABASE_DIR from the environment (see config.py)."""
from __future__ import annotations

import argparse
import logging
import signal
import threading

from ai_core.config import Settings
from ai_core.normalizer.follower import LogFollower
from ai_core.persistence import connect, init_schema


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Phase 7 Cowrie log ingestion")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replay", action="store_true", help="ingest everything currently complete, then exit")
    mode.add_argument("--follow", action="store_true", help="keep following the log until SIGINT/SIGTERM")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = Settings.from_env()
    s.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(s.database_path)
    init_schema(conn)
    follower = LogFollower(conn, s.log_path, batch_lines=s.batch_lines)
    if args.replay:
        print(follower.replay())
        return 0
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    follower.run(stop, s.poll_interval_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
