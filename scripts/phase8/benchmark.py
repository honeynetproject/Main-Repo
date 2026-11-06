"""CPU latency / memory benchmark for the packaged classifier. Writes machine-readable JSON.

  python scripts/phase8/benchmark.py --out docs/phases/evidence/phase8_benchmark.json

Method: model load is timed separately. RSS is read from /proc/self/status (VmRSS now, VmHWM peak)
before load, after load, and after the measured runs. Latency = tokenisation + forward + sigmoid
for ONE session per call (batch size 1), using real TEST-split sessions; also batch size 8.
"""
import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _status(key):  # defined first so RSS can be sampled before heavy imports
    for line in open("/proc/self/status"):
        if line.startswith(key + ":"):
            return int(line.split()[1]) / 1024.0  # MiB
    return None


def pct(vals, q):
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def run(texts, warmup=20, runs=300, batch=8, clf=None, cfg=None, rss_start=None):
    from ai_core.classifier.loader import SessionClassifier, ClassifierConfig
    import torch
    mem = {"rss_at_process_start_mib": rss_start, "rss_before_load_mib": _status("VmRSS")}  # before = after imports
    t0 = time.perf_counter()
    clf = clf or SessionClassifier.load(cfg or ClassifierConfig.from_env())
    load_s = time.perf_counter() - t0
    mem["rss_after_load_mib"] = _status("VmRSS")
    for i in range(warmup):
        clf.predict(texts[i % len(texts)])
    lat, toks = [], []
    for i in range(runs):
        t = time.perf_counter()
        p = clf.predict(texts[i % len(texts)])
        lat.append((time.perf_counter() - t) * 1000.0)
        toks.append(p.token_count)
    blat = []
    for i in range(max(runs // 4, 10)):
        chunk = [texts[(i * batch + j) % len(texts)] for j in range(batch)]
        t = time.perf_counter()
        clf.predict_batch(chunk)
        blat.append((time.perf_counter() - t) * 1000.0)
    mem["rss_after_inference_mib"] = _status("VmRSS")
    mem["peak_rss_mib"] = _status("VmHWM")
    cpu = ""
    for line in open("/proc/cpuinfo"):
        if line.startswith("model name"):
            cpu = line.split(":", 1)[1].strip()
            break
    return {
        "model_version": clf.model_version,
        "load_time_s": round(load_s, 3),
        "includes_tokenization": True,
        "warmup_runs": warmup,
        "measured_runs_batch1": runs,
        "batch1_ms": {"p50": round(pct(lat, .5), 2), "p95": round(pct(lat, .95), 2),
                      "mean": round(statistics.fmean(lat), 2), "min": round(min(lat), 2), "max": round(max(lat), 2)},
        "measured_runs_batch%d" % batch: len(blat),
        "batch%d_ms_per_call" % batch: {"p50": round(pct(blat, .5), 2), "p95": round(pct(blat, .95), 2)},
        "batch%d_ms_per_session_p50" % batch: round(pct(blat, .5) / batch, 2),
        "token_count": {"p50": pct(toks, .5), "p95": pct(toks, .95), "max": max(toks),
                        "share_at_128": round(sum(t == 128 for t in toks) / len(toks), 3)},
        "memory": {k: (round(v, 1) if v is not None else None) for k, v in mem.items()},
        "memory_method": "/proc/self/status VmRSS (current) and VmHWM (peak resident), MiB",
        "environment": {"cpu": cpu, "python": platform.python_version(), "torch": torch.__version__,
                        "torch_threads": torch.get_num_threads(), "platform": platform.platform()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--sessions", type=int, default=300)
    ap.add_argument("--runs", type=int, default=300)
    ap.add_argument("--warmup", type=int, default=20)
    a = ap.parse_args()
    rss_start = _status("VmRSS")
    # Sample the sessions in a SEPARATE process so pyarrow/sklearn/dataset memory never enters this one.
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as td:
        tf = Path(td) / "texts.json"
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "_dump_texts.py"),
                        str(a.sessions), "2024", str(tf)], check=True)
        texts = json.loads(tf.read_text())
    res = run(texts, warmup=a.warmup, runs=a.runs, rss_start=rss_start)
    res["input_set"] = f"{a.sessions} random TEST-split training texts (seed 2024)"
    out = json.dumps(res, indent=2)
    print(out)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(out + "\n")


if __name__ == "__main__":
    main()
