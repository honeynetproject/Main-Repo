"""Runtime configuration read from the environment variables already defined
for the ai-core service in compose.yaml (COWRIE_LOG_DIR, DATABASE_DIR)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    cowrie_log_dir: Path
    cowrie_log_name: str
    database_path: Path
    poll_interval_s: float
    batch_lines: int

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        env = os.environ if env is None else env
        db_dir = Path(env.get("DATABASE_DIR", "data/app/db"))
        return cls(
            cowrie_log_dir=Path(env.get("COWRIE_LOG_DIR", "data/cowrie/var/log/cowrie")),
            cowrie_log_name=env.get("COWRIE_LOG_NAME", "cowrie.json"),
            database_path=db_dir / env.get("DATABASE_FILE", "platform.sqlite3"),
            poll_interval_s=float(env.get("FOLLOW_POLL_INTERVAL_S", "1.0")),
            batch_lines=int(env.get("FOLLOW_BATCH_LINES", "500")),
        )

    @property
    def log_path(self) -> Path:
        return self.cowrie_log_dir / self.cowrie_log_name
