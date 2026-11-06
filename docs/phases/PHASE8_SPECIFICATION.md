# Phase 8 — Audit and Package the Trained Model for Inference

**Project:** Autonomous Cyber Deception Platform Using Reinforcement Learning for Adaptive Honeynet Orchestration  
**Phase:** 8  
**Part:** DistilBERT, fallback and five-command policy  
**Primary owner:** Member B; review by Member E  
**Depends on:** Phase 7 event/session schema is frozen; trained model weights and all required training artifacts are available.  
**Suggested effort in the implementation playbook:** 2–4 days  
**Status:** Verified 2026-11-06 — see `docs/phases/PHASE8_REPORT.md` (evidence-based)

---

## 1. Purpose

Ensure that live inference uses exactly the input representation, preprocessing, label mapping, output semantics, and decision thresholds used during model training.

The project already has a trained model. This phase is primarily an **artifact audit, inference-compatibility verification, and inference packaging task**. Do not automatically retrain the model. Retraining is outside this phase unless the audit proves that the available artifacts are unusable or incompatible and the project owner explicitly approves a separate corrective task.

The result of this phase is a versioned **Model Contract** and a repeatable CPU inference path that can be used by the ClassifierRouter in Phase 9.

## 2. Governing references and precedence

Read these project documents before implementation:

1. `CLAUDE.md`
2. `docs/PROJECT_CONTEXT.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DECISIONS.md`
5. `docs/IMPLEMENTATION_PLAYBOOK.docx` (the master implementation playbook)
6. `docs/phases/PHASE8_SPECIFICATION.md` (this file)
7. The Phase 7 schema/specification and the actual Phase 7 implementation/tests.

The master implementation playbook remains the governing project reference. This phase specification makes its Phase 8 requirements actionable; it does not authorize changing the project architecture or model-training design.

If the playbook, this specification, the actual training notebook/code, and the saved artifacts appear to conflict, do not guess or silently reconcile them. Record the exact conflict, supporting evidence, and the decision needed from the project owner. A verified training artifact and its training code are the evidence for what the model actually accepts; descriptive proposal text alone is not sufficient.

## 3. Scope

### In scope

- Locate and inventory the existing trained model and its associated artifacts.
- Inspect the final training code/notebook and checkpoint-loading code.
- Establish whether inference consumes DistilBERT token IDs and attention masks, TF-IDF features, or a documented custom/hybrid input.
- Reconstruct and document the exact preprocessing pipeline.
- Freeze the seven-label mapping and actual output semantics.
- Identify and document maximum sequence length, truncation/padding behavior, thresholds, and other inference parameters.
- Load the saved artifact offline on the Ubuntu VM or in the intended AI Core runtime.
- Compare known validation examples against the existing training notebook/pipeline.
- Measure CPU memory use and p50/p95 inference latency.
- Package or adapt a minimal, repeatable inference loader/wrapper if needed for Phase 9.
- Add automated tests and evidence proving the model contract is correct.

### Out of scope

- Retraining or fine-tuning the model as a routine step.
- Implementing the Phase 9 `ClassifierRouter` or rule-based fallback.
- Implementing five-command prefix policy evaluation (Phase 10).
- Implementing the Observation Builder, Q-learning agent, RL policy, or controller.
- Changing the seven project labels, model architecture, training strategy, or model checkpoint without explicit approval.
- Replacing DistilBERT with another model or adding a new ML model because it is more convenient.
- Refactoring unrelated repository modules, changing Cowrie, or changing Docker Compose unless a demonstrated Phase 8 runtime requirement makes a narrowly scoped change unavoidable and it is approved.

## 4. Project label contract

The project has exactly these seven project labels, in this order unless the actual training label encoder and approved project records demonstrate a different frozen order that must be reconciled with the owner:

1. `Persistence`
2. `Discovery`
3. `Defense Evasion`
4. `Execution`
5. `Impact`
6. `Other`
7. `Harmless`

`Other` and `Harmless` are project classes; they are not MITRE ATT&CK tactics.

Claude must inspect the training label encoder, saved label map, model output dimension, and training/evaluation code. Do not infer the class order from alphabetical sorting, a folder listing, or a model output shape. Do not reorder labels merely to match the list above. If the actual model's order differs, document the discrepancy and stop for owner review before changing the mapping or artifact.

The project has described the task as multi-label classification. Nevertheless, verify the saved model's actual training and inference semantics before implementation. In particular, establish whether the model produces:

- independent per-label logits/probabilities (typically a sigmoid-based multi-label setup), or
- mutually exclusive class scores (typically a softmax-based single-label setup), or
- another documented output representation.

Never apply sigmoid, softmax, or a thresholding strategy based only on assumption. Match the training code and checkpoint contract exactly.

## 5. Mandatory repository and artifact audit

Before changing files, inspect the repository and report:

1. Where the model weights/checkpoint are stored.
2. Where the tokenizer, vocabulary, config, label encoder/map, fitted vectorizer, estimator, or other required preprocessing artifacts are stored.
3. Which files are required at inference time and which are training-only outputs, logs, plots, or caches.
4. The training notebook/script and the final training cell or equivalent checkpoint-export code.
5. The checkpoint-loading code and the exact library/framework versions used, where discoverable.
6. The model's expected input tensor/features, dimensions, dtypes, batch shape, and required metadata.
7. Whether the currently available artifacts are complete and loadable without reaching out to the training environment or downloading an unpinned dependency at runtime.
8. Whether the model can be loaded on CPU in the Ubuntu environment intended for AI Core.
9. The current repository integration points, if any, that can be reused without creating duplicate loaders or preprocessing implementations.

Do not dump model weights or large dataset contents into the terminal, Claude context, or logs. Inspect metadata and targeted examples. Do not copy large model files unnecessarily. Keep raw data, credentials, and secrets out of Git.

If the model artifact directory or its required companion artifacts are missing, stop and report the exact missing path/files. Do not create fake placeholder model files or claim an inference test passed using a substitute model.

## 6. Determine the true model input pipeline

Use the actual training code and saved artifacts to answer this question conclusively:

**What exact representation does the deployed classifier consume?**

Possible cases include:

### Case A — Standard DistilBERT text-classification input

If the checkpoint uses a standard transformer text-classification path:

- Load the matching saved tokenizer and model configuration.
- Reconstruct the same text that was passed to the tokenizer during training.
- Apply the same cleaning, normalization, special-token handling, padding, truncation, and maximum sequence length.
- Pass the expected token IDs and attention masks, with the correct tensor names, shapes, and dtypes.
- Do not pass TF-IDF vectors into the transformer.

### Case B — TF-IDF plus a fitted estimator

If the deployed classifier actually uses TF-IDF features and a fitted estimator:

- Load the saved fitted vectorizer and estimator.
- Apply the same text preparation that was used before vectorization.
- Call the fitted vectorizer's `transform()` method on live input.
- Never call `fit()` or `fit_transform()` on live session data.
- Verify feature count, vocabulary, estimator input shape, class order, and probability/score semantics.
- Do not describe this path as a standard DistilBERT inference path unless the actual implementation demonstrates that design.

### Case C — Custom or hybrid input

If the training pipeline uses a custom or hybrid representation:

- Trace every transformation from raw training text to the model input.
- Identify every required artifact and dependency.
- Record exact ordering, tensor/feature names, dimensions, dtypes, and preprocessing steps.
- Implement no guessed simplification. Reproduce the training pipeline and prove equivalence with reference examples.

If the input path cannot be established from the available code and artifacts, Phase 8 is **blocked**, not ready.

## 7. Exact preprocessing and `full_session` compatibility

The Phase 7 Session Manager builds cumulative command history. Phase 8 must document how that history is converted into the model's true input.

Inspect the training pipeline and establish:

- Whether `full_session` was built by joining command strings, using separators, adding event/context fields, or another process.
- Whether whitespace, case, punctuation, shell prompts, timestamps, or special characters were normalized.
- Whether empty commands, duplicate commands, unknown tokens, or non-command events were filtered.
- Whether there was a maximum number of commands or a maximum text/token length.
- Whether truncation kept the beginning, end, or another window of the session.
- Whether padding was applied and how attention masks were formed.
- Whether the text was tokenized once per session or per command before aggregation.
- Whether any tokenizer/vectorizer state was fitted and saved during training.

The live inference path must reproduce the training behavior. Do not split commands on arbitrary spaces or semicolons, invent separators, strip meaningful characters, or apply new normalization unless the original training implementation did so.

Phase 8 must not redesign Phase 7's event schema. If the existing `full_session` field cannot faithfully represent the training input, document the mismatch and request a schema decision before modifying either phase.

## 8. Model Contract deliverable

Create a concise, version-controlled model contract at an appropriate existing documentation location (recommended: `docs/MODEL_CONTRACT.md`). Do not create duplicate contract documents if an equivalent authoritative contract already exists; update the existing one after inspection.

The contract must document at least:

| Contract field | Required content |
|---|---|
| Model identity | Model name/family, checkpoint/artifact path, artifact version or hash |
| Runtime | Framework/library versions and supported execution device; CPU must be tested |
| Input source | The session field(s) supplied by Phase 7 |
| Representation | Transformer tokens, TF-IDF features, or custom/hybrid representation |
| Text preprocessing | Exact ordered steps, including cleaning and tokenization/vectorization |
| Sequence handling | Maximum sequence length, padding, truncation side/strategy, special tokens |
| Input schema | Required keys, tensor/feature names, shapes, dtypes, batch behavior |
| Label mapping | Exact seven labels in actual model output order |
| Output semantics | Multi-label or single-label, logits vs probabilities, activation/score conversion |
| Decision thresholds | Exact values and whether global or per-label; source/justification; or explicitly `not established` |
| Runtime behavior | Model load timing, inference call contract, empty/invalid input behavior |
| Validation | Reference sample IDs, expected outputs, tolerances, and test evidence |
| Performance | CPU environment, warm-up/repetition procedure, p50/p95 latency, memory measurement |
| Provenance | Training notebook/script and artifact files used to derive the contract |

Do not invent missing values to make the table look complete. Use `unknown`, `not present in artifact`, or `requires owner decision`, and explain the impact. A missing label map, unknown output semantics, or unknown preprocessing is a readiness blocker.

## 9. Checkpoint loading and inference packaging

Implement or reuse a small deterministic inference loader/adapter only after the audit has established the true input/output contract.

Requirements:

1. Load the checkpoint and all required preprocessing artifacts once at process startup or explicit initialization. Do not reload the model for every command or session inference.
2. Support CPU execution in the intended Ubuntu runtime.
3. Put model loading behind a clear function or class interface that Phase 9 can reuse.
4. Keep artifact paths configurable; do not hard-code a developer-specific absolute path.
5. Validate that all required files exist and are readable before declaring the model available.
6. Validate label count/order and output dimensions before returning a prediction.
7. Reject or explicitly handle empty input, malformed input, invalid tensor dimensions, non-finite scores, and incompatible artifacts. Do not silently return fabricated predictions.
8. Use inference/evaluation mode and disable gradient computation where appropriate for the selected framework.
9. Keep inference code separate from training code. Do not import a notebook as a runtime dependency.
10. Do not add the Phase 9 fallback router or rules here. Model load/inference errors should be explicit and testable so Phase 9 can route them to fallback later.
11. Do not expose raw session text in routine logs. Log safe identifiers, status, timing, and structured error information; avoid credentials or sensitive raw command dumps.

If an inference wrapper already exists, evaluate and test it before creating another. Prefer a small, well-tested change over a parallel implementation.

## 10. Reference validation against the training pipeline

Create a small, deterministic reference set from known training/validation examples. Prefer sample IDs and sanitized inputs over copying a large dataset into the repository.

For each reference example:

1. Run the original training/validation inference path or its reproducible equivalent.
2. Run the packaged Phase 8 inference path using the same artifact versions and exact preprocessing.
3. Compare output dimensions, label order, logits/probabilities, predicted labels, and threshold decisions as applicable.
4. Define numerical tolerances based on the actual framework/device behavior and record them. Do not choose a tolerance so wide that meaningful mismatches pass.
5. Investigate every discrepancy. Explain expected nondeterminism, if any, with evidence.

The test must prove that the packaged inference result matches the original pipeline for representative known examples. A successful model load alone is not sufficient.

Do not use the same reference data to tune thresholds and then present it as an independent validation set. Clearly identify whether the reference examples are training, validation, or held-out data.

## 11. CPU performance and resource measurement

The playbook requires CPU memory measurement and p50/p95 inference latency.

Record:

- Ubuntu/runtime environment and CPU details relevant to reproducibility.
- Python and model-framework versions.
- Artifact/checkpoint version or hash.
- Batch size and representative input-length distribution.
- Number of warm-up runs.
- Number of measured runs.
- p50 and p95 inference latency, with model load time reported separately.
- Process memory before loading, after loading, and peak/maximum observed during inference, using a documented measurement method.
- Whether measurements include preprocessing/tokenization.

Use a repeatable benchmark script or test. Do not report a single timing as p50/p95. Do not invent performance targets that the playbook has not specified. Report measurements and let the project owner decide whether they meet project needs.

The model must be initialized once per process; repeated inference calls must not trigger repeated checkpoint loading.

## 12. Automated test requirements

Use the repository's existing test framework and conventions. Use `pytest` if that is already the project standard or is specified by the playbook. Tests must use real project artifacts for at least one integration/reference test; unit tests may use small controlled fixtures or mocks where appropriate.

At minimum, add or update tests for:

### Artifact and loader tests

- Required model files are present and missing files produce a clear, actionable error.
- Checkpoint loads successfully on CPU in the intended environment.
- Tokenizer/vectorizer and other companion artifacts load from the configured artifact directory.
- Model initialization occurs once and is not repeated for each inference call.
- Incompatible or corrupt artifacts fail explicitly.

### Input/preprocessing tests

- The exact same input text yields the same preprocessing representation as the training pipeline.
- Empty input behavior is explicit and tested.
- Long input follows the verified truncation behavior.
- Padding, special tokens, attention masks, tensor/feature shapes, and dtypes match the contract.
- TF-IDF path, if applicable, uses `transform()` and does not fit/refit on live data.
- Special characters, whitespace, repeated commands, and Unicode follow the actual training preprocessing.

### Output/label tests

- Output dimension matches the number of labels.
- Label order exactly matches the saved training mapping.
- The activation and score interpretation match the actual training objective.
- Threshold decisions match the documented values and comparison rule.
- NaN/Inf or malformed output is rejected and not converted into a valid-looking prediction.
- Known reference examples match the original training/validation pipeline within the documented tolerance.

### Runtime/performance tests

- Repeated inference uses the already-loaded model.
- CPU inference works without requiring a GPU.
- Benchmark procedure produces a machine-readable result containing p50/p95 latency and memory measurements.
- No raw session text, credentials, or secret values are emitted by routine logs.

Do not mark tests as passed if they were skipped, mocked, or not executed. Clearly distinguish unit tests, mocked tests, and real-artifact integration tests.

## 13. Validation and self-review before declaring readiness

This section is mandatory. Claude must evaluate its own implementation against the specification, run tests, inspect the resulting code, and provide evidence before saying Phase 8 is ready.

After implementation:

1. Re-read this entire specification and create a requirement-by-requirement verification checklist.
2. Inspect every changed file and its diff. Look for duplicated preprocessing, hard-coded paths, label-order mistakes, accidental refitting, model reloads per request, hidden GPU assumptions, unsafe logging, and unrelated changes.
3. Run formatting, linting, type checks, or static analysis already configured in the repository. Do not introduce a new toolchain solely to claim compliance.
4. Run all relevant unit tests.
5. Run the real-artifact CPU loading and inference integration tests.
6. Run the known-example comparison against the training pipeline.
7. Run the CPU performance/memory benchmark and attach the actual measurements.
8. Run the existing relevant project regression tests to verify Phase 7 behavior and other working components have not been broken.
9. Review the test output and failures. Fix implementation defects, rerun the affected tests, and rerun the complete relevant test suite after final changes.
10. Confirm the Git diff contains only necessary Phase 8 changes and no large raw datasets, secrets, credentials, checkpoint copies, or unrelated configuration changes.
11. Update the Model Contract and Phase 8 status with the exact evidence, environment, artifact versions, and test commands/results.

A code review by Claude is not a substitute for executed tests. A model that merely imports or loads successfully is not sufficient. A mocked test is not proof that the saved project checkpoint works.

### Mandatory final verification report

The final report must contain:

- **Requirement checklist:** every Phase 8 requirement marked `PASS`, `FAIL`, `BLOCKED`, or `NOT APPLICABLE`, with evidence.
- **Artifact inventory:** paths and versions/hashes of the actual files inspected (do not print secrets or large binary contents).
- **Confirmed input contract:** exact input representation and preprocessing, with training-code/artifact evidence.
- **Confirmed output contract:** label order, output semantics, score conversion, and thresholds.
- **Changed files:** exact paths and reason for each change.
- **Commands executed:** exact test, validation, and benchmark commands.
- **Test results:** passed/failed/skipped counts, and identification of tests using real artifacts versus mocks.
- **Reference comparison:** samples used, expected/actual outputs, tolerances, and discrepancies.
- **Performance evidence:** CPU p50/p95 latency, load time, memory measurements, and environment details.
- **Regressions:** Phase 7 and relevant project tests run, with results.
- **Known limitations:** unresolved assumptions, missing artifacts, or owner decisions.
- **Readiness decision:** `READY`, `NOT READY`, or `BLOCKED`, justified by the evidence.

Claude must not declare `READY` if any mandatory acceptance criterion is failed, untested, or blocked. If a required artifact or original training pipeline is unavailable, report `BLOCKED` and name exactly what is needed. Do not disguise incomplete validation as success.

## 14. Acceptance criteria — Phase 8 is complete only when all apply

- [ ] The actual saved model input representation has been established from the training code and artifacts.
- [ ] The exact preprocessing pipeline has been reconstructed and documented.
- [ ] The relationship between Phase 7's cumulative session text and training `full_session` has been verified.
- [ ] The seven-label mapping and actual output order have been verified.
- [ ] Multi-label/single-label semantics, logits/probabilities, activations, and decision thresholds are documented from evidence.
- [ ] All required model and preprocessing artifacts load in the intended Ubuntu/AI Core environment on CPU.
- [ ] A known reference example produces the expected result using the packaged inference path.
- [ ] Packaged inference is compared with the original training/validation pipeline and discrepancies are explained.
- [ ] CPU p50/p95 latency and memory use have been measured and recorded.
- [ ] The model loads once at process initialization, not once per inference request.
- [ ] Automated tests cover artifact loading, preprocessing, input shape, label/output semantics, invalid outputs, and known-example parity.
- [ ] Relevant regression tests pass; Phase 7 functionality remains intact.
- [ ] The Model Contract and final verification report are committed as documentation, with no unsupported claims.
- [ ] No unrelated architecture, Cowrie, Docker Compose, or Phase 9/10 behavior has been introduced.

**Phase 8 acceptance gate:** The deployed artifact produces the expected output from a known sample using the same preprocessing as training; seven labels and output semantics are documented; no TF-IDF/transformer interface mismatch remains.

## 15. Implementation workflow for Claude

Work in small, reviewable stages:

1. **Audit only:** inspect the repository, training code, model artifacts, Phase 7 output schema, and test setup. Present findings, missing dependencies/artifacts, and a plan. Do not modify files during this initial audit.
2. **Wait for approval:** begin implementation only after the project owner approves the audit and plan.
3. **Model contract:** establish and document the verified input/output contract before writing or changing the inference wrapper.
4. **Inference packaging:** implement or adapt the smallest reusable loader/wrapper consistent with the verified contract.
5. **Automated validation:** add tests and reference comparisons; execute them on CPU with actual artifacts.
6. **Performance validation:** run and record the benchmark.
7. **Self-review and acceptance:** complete Section 13 and the Section 14 checklist; fix and retest defects before reporting readiness.

Do not start Phase 9 as part of this task. Stop after the Phase 8 verification report and wait for explicit instruction to proceed.

