"""Shared helper: deterministic samples of the held-out TEST split (needs pyarrow, numpy, scikit-learn)."""
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "models" / "data"
M = ROOT / "models" / "models"
N_TOTAL = 233035


def test_indices():
    _, te = train_test_split(np.arange(N_TOTAL), test_size=0.2, random_state=42)
    return te


def sample_test_sessions(n, seed):
    """Return (positions_in_test_split, raw_session_strings, training_texts) for n random test rows."""
    te = test_indices()
    pick = np.sort(np.random.default_rng(seed).choice(len(te), n, replace=False))
    rows = te[pick].tolist()
    raw = pq.read_table(D / "raw/ssh_attacks.parquet", columns=["full_session"]).take(rows).column(0).to_pylist()
    dec = pq.read_table(D / "processed/ssh_attacks_decoded.parquet", columns=["full_session"]).take(rows).column(0).to_pylist()
    return pick, raw, [" ".join(t) for t in dec]
