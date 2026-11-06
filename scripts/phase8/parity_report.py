"""Compare the packaged classifier with the ORIGINAL evaluation outputs on the held-out TEST split.

Reference = models/models/eval/y_pred_probs.npy (the probabilities the training pipeline produced for the
full test split, 46,607 rows). For N random test rows we rebuild the text from the raw dataset with the
Phase 7 builder, run the packaged path, and compare probabilities and threshold decisions.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--out", default=None)
    ap.add_argument("--batch", type=int, default=16)
    a = ap.parse_args()
    from _testdata import sample_test_sessions, M
    from ai_core.classifier.contract import LABELS
    from ai_core.classifier.loader import SessionClassifier, ClassifierConfig
    from ai_core.sessions.fullsession import clean_full_session, decode_session
    pick, raw, train_text = sample_test_sessions(a.n, seed=77)
    ref = np.load(M / "eval/y_pred_probs.npy")[pick]
    ytrue = np.load(M / "eval/y_true.npy")[pick]
    phase7_text = [" ".join(clean_full_session(decode_session(r))) for r in raw]
    text_equal = sum(p == t for p, t in zip(phase7_text, train_text))
    clf = SessionClassifier.load(ClassifierConfig.from_env())
    got = []
    for i in range(0, a.n, a.batch):                       # same batch size as the original DataLoader (16)
        got += [[p.scores[l] for l in LABELS] for p in clf.predict_batch(phase7_text[i:i + a.batch])]
    got = np.array(got)
    diff = np.abs(got - ref)
    flips = int(((got >= 0.5) != (ref >= 0.5)).sum())
    res = {
        "n_sessions": a.n, "split": "test (held out)", "reference": "models/models/eval/y_pred_probs.npy",
        "model_version": clf.model_version,
        "phase7_text_equals_training_text": f"{text_equal}/{a.n}",
        "max_abs_prob_diff": float(diff.max()), "mean_abs_prob_diff": float(diff.mean()),
        "p99_abs_prob_diff": float(np.quantile(diff, .99)),
        "decision_flips_at_0.5": flips, "decisions_compared": int(diff.size),
        "rows_with_label_set_difference": int((((got >= 0.5) != (ref >= 0.5)).any(1)).sum()),
        "true_label_set_agreement_with_packaged": float((((got >= 0.5) == (ytrue == 1)).all(1)).mean()),
        "worst_row_position_in_test_split": int(pick[int(diff.max(1).argmax())]),
    }
    out = json.dumps(res, indent=2)
    print(out)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(out + "\n")


if __name__ == "__main__":
    main()
