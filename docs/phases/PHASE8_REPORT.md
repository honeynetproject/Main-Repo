# Phase 8 — Final Verification Report

**Date:** 2026-11-06 · **Decision: READY** (with the limitations and owner decisions in §9; none blocks a Phase 9 start, none is hidden).
Contract: `docs/MODEL_CONTRACT.md`. Evidence: `docs/phases/evidence/phase8_parity.json`, `phase8_benchmark.json`.

## 1. Requirement checklist (spec §14 acceptance criteria)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Input representation established from training code and artifacts | PASS | DistilBERT ids + mask, `CustomDistilBERTModel` (section4 cells 14–17, 35, 38); checkpoint has `distilbert.*` + `classifier.*` (102 keys), strict load OK |
| 2 | Exact preprocessing reconstructed and documented | PASS | Contract §3; tokenizer ids equal training cache (24/24 in tests, 300/300 exploratory) |
| 3 | Phase 7 cumulative text ↔ training `full_session` verified | PASS | Phase 7 builder on raw dataset rows equals training text: 500/500 (parity script), 24/24 (tests) |
| 4 | Seven labels / output order verified | PASS | `mlb.classes_` equals `LABELS` (test); order is alphabetical, differs from D-010; owner chose the model order; Phase 0 schema is name-keyed |
| 5 | Multi/single-label semantics, activation, thresholds documented | PASS (per-label thresholds explicitly *not established*) | BCEWithLogits + sigmoid, global 0.5 (section4 cell 21); sweeps in cells 41–43 are test-tuned and not adopted |
| 6 | Artifacts load in the intended Ubuntu environment on CPU | PASS on the Ubuntu host (see limitation L1 for the container) | Real-artifact tests, Ubuntu 26.04, Python 3.14.4, torch 2.14.0+cpu |
| 7 | Known reference example gives expected result via packaged path | PASS | `test_known_samples_match_original_training_evaluation_outputs` (24 TEST samples) |
| 8 | Packaged inference compared with original pipeline; discrepancies explained | PASS | 500 TEST sessions: max \|Δp\| 1.79e-7, mean 3.1e-9, 0 decision flips of 3,500. The only difference is float32 rounding from batch composition |
| 9 | CPU p50/p95 latency and memory recorded | PASS | batch 1: p50 94.8 ms / p95 118.8 ms; load 2.4 s; RSS 701 MiB after load, peak 954 MiB |
| 10 | Model loads once, not per request | PASS | `test_repeated_inference_does_not_reload` (torch.load, from_pretrained, hashing patched to raise) |
| 11 | Tests cover loading, preprocessing, shapes, labels/semantics, invalid outputs, parity | PASS | §3 |
| 12 | Regression tests pass; Phase 7 intact | PASS | 68/68 Phase 7 tests pass (see L3 about one guard test I edited) |
| 13 | Contract and report committed as documentation, no unsupported claims | PASS (committed with this report) | this file, `docs/MODEL_CONTRACT.md` |
| 14 | No unrelated architecture/Cowrie/compose/Phase 9–10 behaviour | PASS | `compose.yaml`, Dockerfile, Cowrie untouched; no router, fallback or prefix policy |

Other spec requirements: §9 loader rules 1–11 PASS (see `ai_core/classifier/loader.py`; one-time load, CPU, configurable paths, file/label/dimension validation, finite-output check, `inference_mode`, no notebook import, no fallback, no raw text in logs). §10 reference validation PASS. §11 benchmark PASS. §12 test list PASS. §13 self-review: §7 below.

## 2. Artifact inventory

See `docs/MODEL_CONTRACT.md` §1 (paths, sizes, SHA-256). Weights were never printed; only key names, shapes and `torch.equal` results were inspected.

## 3. Test results (all executed, 2026-11-06)

| Command | Result |
|---|---|
| `./.venv-ml/bin/python -m pytest -q -rs` (full suite, torch available) | **111 passed, 0 failed, 0 skipped** |
| `./.venv-ml/bin/python -m pytest -q tests/unit/test_classifier_unit.py` | 21 passed — **stub/mock tests**, no real model |
| `./.venv-ml/bin/python -m pytest -q tests/integration/test_classifier_real.py` | 22 passed — **real artifacts on CPU**; 2 of them (`…_MOCKED`) patch `torch.load` to inject corrupt weights |
| `.venv/bin/python -m pytest -q -rs` (project stdlib venv, no torch) | 68 passed, **2 skipped** (the two classifier files: `could not import 'torch'`), 0 failed |
| `python -m compileall -q ai_core scripts/phase8 tests` | OK. No linter/type-checker is configured in the repo, so none was run |

Phase 7 regression = the 68 tests that existed before (parser/normalizer 18, full-session 9, sessions 17, follower 17, replay e2e 7).

## 4. Reference comparison

- 24 fixture samples (TEST split; Discovery 23, Persistence 16, Execution 13, Harmless 3, Defense Evasion 3, Other 2, Impact 2; 18 of 24 at the 128-token cap): tokens equal training cache; probabilities within 1e-5 (observed ≤1.8e-7); identical threshold decisions.
- 500 random TEST sessions (seed 77), packaged path fed from the *raw* dataset string through Phase 7: see `phase8_parity.json`. In that sample 89.8 % of rows have predicted label set == true label set — informational only, not a Phase 8 criterion.
- Reference outputs are the original evaluation's saved probabilities (the script that made them is not in the repo; matching to 1.8e-7 shows they came from this checkpoint in fp32).
- No thresholds were tuned on these samples.

## 5. Performance evidence

Table in `docs/MODEL_CONTRACT.md` §6; raw JSON in `docs/phases/evidence/phase8_benchmark.json`. Single run on a shared machine; the playbook has no latency target, so no pass/fail is claimed. p50 is dominated by 128-token sessions (90 % of the sample).

## 6. Changed files

| Path | Reason |
|---|---|
| `ai_core/classifier/{__init__,contract,errors,loader}.py` | Packaged loader and contract constants |
| `ai_core/requirements-classifier.txt`, `.env.example` (`MODEL_SHA256`), `.gitignore` and `.dockerignore` (`.venv-ml/`) | Pinned runtime versions, checkpoint hash pin, keep the 1+ GB venv out of Git and Docker context |
| `scripts/phase8/{build_reference,parity_report,benchmark,_testdata,_dump_texts}.py` | Reference-set generation, parity evidence, benchmark |
| `tests/unit/test_classifier_unit.py`, `tests/integration/test_classifier_real.py`, `tests/fixtures/model/reference_samples.jsonl` | Tests and the 24-sample reference set (115 KB) |
| `tests/integration/test_replay_e2e.py` | Phase 7 guard test now skips only `ai_core/classifier/` and additionally forbids other modules importing the classifier package (L3) |
| `docs/MODEL_CONTRACT.md`, `docs/phases/PHASE8_REPORT.md`, `docs/phases/evidence/*.json`, `docs/DECISIONS.md` (D-013, D-010, D-062, D-063), `docs/phases/PHASE8_SPECIFICATION.md` (status line) | Documentation |

Not changed: `compose.yaml`, `ai_core/Dockerfile`, Cowrie config, Phase 7 modules. The pre-existing deletions of `README.md` / `README_PHASE4.md` in the working tree are not mine.

## 7. Self-review (spec §13)

Diff and files inspected for: duplicated preprocessing (none: reuses `ai_core.sessions.fullsession`), hard-coded paths (none; env-configurable, tests use repo-relative defaults), label-order mistakes (test against `mlb.pkl`), accidental refit (none, no TF-IDF), per-request reload (tested), GPU assumptions (none; CPU asserted), unsafe logging (only version/timing logged; tested), unrelated changes (see §6). Defects found and fixed during review: wrong expected values in two of my own tests; a noisy tokenizer warning on over-length inputs (`verbose=False`); a benchmark whose "before load" memory included dataset-loading memory (sampling moved to a separate process); a Phase 7 guard test that the new package legitimately violated (L3). Final test and parity runs were repeated after the last code change.

## 8. Commands executed (essential)

```bash
python3 -m venv .venv-ml && .venv-ml/bin/pip install torch-2.14.0+cpu-cp314…whl numpy==2.5.2 transformers==5.16.1 tokenizers==0.23.2 safetensors==0.8.0 scikit-learn==1.9.0 pyarrow pytest
./.venv-ml/bin/python scripts/phase8/build_reference.py
./.venv-ml/bin/python scripts/phase8/parity_report.py --n 500 --out docs/phases/evidence/phase8_parity.json
./.venv-ml/bin/python scripts/phase8/benchmark.py --out docs/phases/evidence/phase8_benchmark.json
./.venv-ml/bin/python -m pytest -q -rs ; .venv/bin/python -m pytest -q -rs
```

Committed locally on `main`; not pushed.

## 9. Known limitations and owner decisions

- **L1 — Container:** the `ai-core` image has no torch; the classifier was verified on the Ubuntu host (same Python 3.14 line as the image base), not inside the container. An image change (large wheel, size and attack surface) needs its own approval.
- **L2 — Per-label thresholds and model confidence (D-024)** are not established; only the training evaluation's global 0.5 is used.
- **L3 — Phase 7 test edit (owner proceeded with it):** `test_phase7_does_not_import_classifier_rl_or_controller` scanned all of `ai_core/`; it now excludes `ai_core/classifier/` and adds a stricter import check for the rest. Please confirm this is acceptable.
- **L4 — Removed files (closed):** the owner deleted `final_model.pth`, `checkpoint.pth` and the Windows `venv` as no longer needed (2026-11-06). They were never compared with the deployed checkpoint, and `RESCUED_checkpoint.pth` is the single source of truth. The checkpoint SHA-256 is pinned as `MODEL_SHA256` in `.env.example`.
- **L5 — Live-data equivalence:** Phase 7 ↔ training equivalence was proven on dataset raw strings; live Cowrie command strings are not in that dataset (equivalence there holds by using the same functions). Phase 7's trailing-`echo` fallback differs from the training code (which raises).
- **L6 — Class support:** TEST split has 2 Impact / 67 Other positives; quality for those labels is unmeasured.
- **L7 — Fixture content:** the reference fixture contains attacker command strings from the public dataset (e.g. `passwd` usage); no credentials of this project.
- **L8 — Timing** is one run on a loaded 4-core laptop CPU.
