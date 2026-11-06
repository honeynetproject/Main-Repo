"""Build tests/fixtures/model/reference_samples.jsonl from the held-out TEST split.

Reproduces the notebook split (train_test_split random_state=42, 0.2), selects a small
deterministic, class-stratified sample, and stores the *training-side* expectations:
the cached token ids (test_encodings.pt) and the original evaluation probabilities
(models/models/eval/y_pred_probs.npy). Needs pyarrow, numpy, torch, scikit-learn.
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import torch
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "models" / "data"
M = ROOT / "models" / "models"
N_TOTAL = 233035
MAX_RAW_CHARS = 8000
HARD_MAX_RAW_CHARS = 60000


def main(out: Path):
    mlb = pickle.load(open(D / "processed/mlb.pkl", "rb"))
    labels = list(mlb.classes_)
    _, te = train_test_split(np.arange(N_TOTAL), test_size=0.2, random_state=42)
    tl = np.load(D / "processed/test_labels.npy")
    yp = np.load(M / "eval/y_pred_probs.npy")
    enc = torch.load(D / "processed/test_encodings.pt", weights_only=False)
    rng = np.random.default_rng(8)
    rawlen = np.array([len(x) for x in pq.read_table(D / "raw/ssh_attacks.parquet", columns=["full_session"])
                       .take(te.tolist()).column(0).to_pylist()])
    chosen = []
    for ci, name in enumerate(labels):            # up to 3 compact positives per class
        pos = np.where((tl[:, ci] == 1) & (rawlen <= MAX_RAW_CHARS))[0]
        chosen += list(rng.choice(pos, size=min(3, len(pos)), replace=False))
    big = np.where((tl[:, labels.index("Other")] == 1) & (rawlen > MAX_RAW_CHARS))[0]
    chosen.append(int(rng.choice(big)))            # one very long 'Other' session (truncation + size)
    lens = np.array([len(x) for x in enc["input_ids"]])
    ok = rawlen <= MAX_RAW_CHARS
    chosen += list(rng.choice(np.where((lens >= 128) & ok)[0], 3, replace=False))   # truncated rows
    chosen += list(rng.choice(np.where((lens < 12) & ok)[0], 2, replace=False))     # very short rows
    chosen = sorted(set(int(c) for c in chosen))
    rows = te[chosen].tolist()
    tbl = {n: pq.read_table(D / p, columns=["session_id", "full_session", "Set_Fingerprint"]).take(rows).to_pylist()
           for n, p in (("raw", "raw/ssh_attacks.parquet"), ("dec", "processed/ssh_attacks_decoded.parquet"))}
    n_out = 0
    with open(out, "w") as f:
        for k, j in enumerate(chosen):
            r, d = tbl["raw"][k], tbl["dec"][k]
            assert r["session_id"] == d["session_id"]
            if len(r["full_session"]) > HARD_MAX_RAW_CHARS:
                continue
            f.write(json.dumps({
                "sample_id": r["session_id"], "split": "test", "test_index": j,
                "raw_session": r["full_session"],
                "training_text": " ".join(d["full_session"]),
                "expected_input_ids": [int(x) for x in enc["input_ids"][j]],
                "true_labels": [labels[i] for i in np.where(tl[j] == 1)[0]],
                "expected_probs": [float(x) for x in yp[j]],
            }) + "\n")
            n_out += 1
    print(f"wrote {n_out} samples to {out}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests/fixtures/model/reference_samples.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    main(out)
