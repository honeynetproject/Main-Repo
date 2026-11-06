# Model Contract — DistilBERT session classifier (Phase 8)

**Contract version:** 1.0 · **Date:** 2026-11-06 · **Status:** verified on CPU against the real artifacts (evidence in `docs/phases/evidence/` and `docs/phases/PHASE8_REPORT.md`).
Nothing below is inferred from the proposal text alone; each row cites the training notebook or an artifact.

## 1. Identity and artifacts

| Field | Value |
|---|---|
| Model | Custom `CustomDistilBERTModel`: `DistilBertModel` (from `distilbert-base-uncased`, 6 layers, dim 768) + `Linear(768, 7)` on the first-token (`[CLS]`) output. Not `DistilBertForSequenceClassification`. |
| Deployed checkpoint | `models/models/RESCUED_checkpoint.pth` — SHA-256 `d2087f59d336150ac07d4a10903862a0467d53f56b6699d21d4199a261bb9ee1`, 796,546,585 B, keys `model_state_dict` (102 tensors), `optimizer_state_dict` (training-only), `train_loss_list`, `val_loss_list`, `epochs_completed=4`, `num_labels=7`. Selected by the project owner on 2026-11-06. |
| Equivalent weights | `RESCUED_model_state.pth` (SHA-256 `f2f8c647…89e6`) holds tensors identical to the checkpoint's `model_state_dict` (checked with `torch.equal`). `RESCUED_model_state_BACKUP.pth` has the same SHA-256 prefix. |
| Tokenizer / base config | `models/models/distilbert-base-uncased/` — `vocab.txt` (30,522 lines, SHA-256 `07eced37…38a3`), `config.json` (`0ed7ac6b…a363`), `tokenizer_config.json` (`6a4cfee8…ecb7`). Supplied by the project owner; `tokenizer.model` and `tokenizer.json` are not used (`tokenizer.model` is byte-identical to `vocab.txt`). |
| Label encoder | `models/data/processed/mlb.pkl` (`5f122412…e6a3`), `MultiLabelBinarizer.classes_`. |
| Original evaluation outputs | `models/models/eval/y_pred_probs.npy` (`280c250e…214a`), `y_true.npy` (`a7a5d9de…4913`), `metrics.json`; shape (46607, 7) = the notebook's TEST split. |
| Not required at inference | `optimizer.pth`, `model_evaluation.pkl`, the optimizer state inside the checkpoint, `*_encodings.pt`, datasets, `tokenizer.model`. |
| Not present | `final_model.pth` and `checkpoint.pth` (listed in the notebook) were deleted by the owner as no longer needed; they were never compared with the deployed checkpoint. `eval_distilbert.py` (the script that produced `eval/*.npy`) is not in the repo. |

## 2. Runtime

| Field | Value |
|---|---|
| Verified with | Ubuntu 26.04.1 LTS, Python 3.14.4, `torch 2.14.0+cpu`, `transformers 5.16.1`, `tokenizers 0.23.2`, `safetensors 0.8.0`, `numpy 2.5.2` (pins in `ai_core/requirements-classifier.txt`; local environment `.venv-ml/`, git-ignored; they equal the versions in the notebook's own venv). Training Python was 3.12.3. |
| Device | CPU only (`torch.set_num_threads` optional via `MODEL_TORCH_THREADS`); no GPU code path. |
| Loading | Offline, `local_files_only=True`; checkpoint read with `torch.load(weights_only=True, mmap=True)`; **strict** state-dict load (the notebook used `strict=False`; all 102 keys match, so strictness changes nothing but protects against silent mismatch). |
| Interface | `ai_core.classifier.loader.SessionClassifier.load(ClassifierConfig.from_env())`, then `.predict(text)` / `.predict_batch(texts)`. Env: `MODEL_DIR` (compose already sets `/app/models`), `MODEL_CHECKPOINT`, `MODEL_TOKENIZER_DIR`, `MODEL_SHA256` (optional pin), `MODEL_TORCH_THREADS`. |
| Container | **Not yet in the `ai-core` image** (stdlib-only; torch is not installed there and `compose.yaml` was deliberately not changed). Running the classifier inside the container needs a later, approved image change. |

## 3. Input

| Field | Value |
|---|---|
| Source field | Phase 7 `sessions.full_session` (text) — built by `ai_core/sessions/fullsession.py`, rule `section0-v1`. |
| Representation | Case A: DistilBERT WordPiece token ids + attention mask. No TF-IDF. |
| Preprocessing (ordered) | 1) Phase 7 builds raw `cmd ; cmd ; … ;`; 2) per `;` chunk, Base64 `echo … | base64 --decode` payloads are decoded; 3) split on `[;\s\n\t]+`; 4) per token keep `#!/bin/bash` as is, else keep only `a-zA-Z0-9/=-.`, drop everything after `=`, strip trailing digits, drop empties; 5) join with single spaces (training text); 6) `DistilBertTokenizer` (uncased) → ids. |
| Sequence handling | `max_length=128`, `truncation=True` (head kept; `[SEP]` re-appended), special tokens `[CLS]`/`[SEP]`, **no fixed padding**: training padded dynamically to the longest row in each batch (right side, id 0, mask 0). Single-session inference therefore uses no padding. |
| Input schema | `input_ids` and `attention_mask`, `torch.long`, shape `(batch, ≤128)`. |
| Empty / invalid | Empty or whitespace-only text, non-`str`, or empty batch → `InvalidInputError`. Phase 7 produces `""` for a session with no tokens; it must not be classified. |
| Verified | `full_session` text built from the raw dataset by the Phase 7 functions equals the training text for 500/500 random TEST rows (`scripts/phase8/parity_report.py`) and 24/24 fixtures (tests); tokenizer ids equal the cached training ids (`test_encodings.pt`) for 24/24 fixtures (tests) and 300/300 in an exploratory run with a scratch script that is not committed. |

## 4. Output

| Field | Value |
|---|---|
| Output | 7 raw logits per session; training loss `BCEWithLogitsLoss(pos_weight)`; **multi-label**, independent `sigmoid` per label (never softmax). |
| Label order (model output index 0→6) | `Defense Evasion, Discovery, Execution, Harmless, Impact, Other, Persistence` — equals `mlb.classes_` (test `test_label_order_matches_saved_training_label_encoder`). **This differs from the order listed in D-010/Phase 0 schema.** Resolved 2026-11-06 by the owner: the model's alphabetical order is the frozen model order. Consumers must use the `scores` mapping **by label name**; the Phase 0 `classification-result` schema is keyed by name and is therefore compatible. |
| Threshold | Global `0.5`, rule `probability >= threshold` (section4 `test_model`, and the notebook's live-inference cells). Per-label thresholds: **not established** — the notebook's per-class sweeps (cells 41–43) were tuned on the TEST data and are not adopted. D-024's `0.7` is a separate, still-undefined "confidence" concept and is not applied here. |
| Prediction object | `scores{label→p}`, `predicted_labels`, `threshold`, `token_count`, `truncated`, `model_version` (`RESCUED_checkpoint.pth@sha256:d2087f59d336150a`), `preprocessing_version` (`section0-v1`), `latency_ms`. Maps onto Phase 0 `classification-result` (`scores`, `predicted_labels`, `model_version`, `preprocessing_version`, `latency_ms`); `method`, `status`, ids and fallback are Phase 9. |
| Invalid output | NaN/Inf logits, wrong shape, or probability outside [0,1] → `InvalidOutputError`; never converted to a prediction. |

## 5. Validation

- **Reference set:** `tests/fixtures/model/reference_samples.jsonl` — 24 sessions, all from the held-out **TEST** split (random_state 42, 20%), class-stratified (all 7 classes; Impact has only 2 positives in the whole test split), with training token ids and the original evaluation probabilities. Generated by `scripts/phase8/build_reference.py`. They were not used to choose any threshold.
- **Tolerance:** `|Δp| < 1e-5`. Observed maximum 1.79e-7 (float32 CPU, different batch composition), i.e. ~56× margin and 5 orders below any decision-relevant difference.
- **Broader comparison:** 500 random TEST sessions, packaged path vs `eval/y_pred_probs.npy`: max |Δp| 1.79e-7, 0 threshold-decision flips in 3,500 decisions (`docs/phases/evidence/phase8_parity.json`).
- **Not independent evidence of model quality:** parity shows the packaged path reproduces the saved evaluation, not that the model is accurate on live Cowrie traffic.

## 6. Performance (CPU, measured)

Environment: Intel i7-10850H, 4 threads, Ubuntu 26.04, Python 3.14.4, torch 2.14.0+cpu, other desktop/Docker workloads running (load average ≈1.3). Procedure: 20 warm-ups, 300 measured calls, batch size 1, 300 random TEST sessions (90 % reach the 128-token cap), latency **includes tokenisation**, model load timed separately, RSS from `/proc/self/status`.

| Metric | Value |
|---|---|
| Load time | 2.4 s (once per process) |
| Latency, batch 1 | p50 94.8 ms · p95 118.8 ms (min 22 ms for short sessions, max 233 ms) |
| Latency, batch 8 | p50 612 ms per call (76 ms/session) · p95 680 ms |
| Memory (RSS) | 17 MiB at process start → 429 MiB after importing torch/transformers → 701 MiB after load → 721 MiB after inference; peak 954 MiB (during load) |

Raw output: `docs/phases/evidence/phase8_benchmark.json`. The playbook sets no latency target; the figures are reported for the owner to judge. Reproduce with `scripts/phase8/benchmark.py`.

## 7. Open items / owner decisions

1. Per-label thresholds and the model-confidence definition (D-024) are not established.
2. The trained model was fitted on whole sessions; behaviour on 5-command prefixes is Phase 10's question.
3. Test split class support is very uneven (Impact 2, Other 67, Harmless 458 of 46,607), so per-class quality for those labels cannot be judged from it.
4. Phase 7's fallback for a chunk ending in `echo` (cleans without Base64 instead of raising) deviates from the training code, which would raise; it affects only inputs the training pipeline could not process.
5. The `ai-core` image does not yet contain torch/transformers.

## 8. Provenance

`models/section4_language_model_exploration.ipynb` (cells 12–18 split/tokenisation/model/loss, 21 evaluation, 29/24 checkpoint export, 35/38 checkpoint loading), `models/section0_data_preprocessing_and_cleaning.ipynb` (decode/clean), `models/data/processed/mlb.pkl`, `models/models/eval/*`, Phase 7 `ai_core/sessions/fullsession.py`.
