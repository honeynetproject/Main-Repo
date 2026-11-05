# Phase 7 Implementation Report — Event Normalizer and Session Manager

**Date:** 5 November 2026
**Status:** Implemented; all Phase 7 acceptance criteria demonstrated by test output (see §6). Awaiting user review. Nothing is committed.
**Scope kept:** no classifier, RL, controller, firewall, Cowrie, or `compose.yaml` changes.

## 1. Files created

All new. No existing source file was modified for Phase 7 (`.gitignore` and `.dockerignore` were adjusted separately at your request).

| Path | Purpose |
|---|---|
| `ai_core/config.py` | Settings from existing compose env vars (`COWRIE_LOG_DIR`, `DATABASE_DIR`) |
| `ai_core/ingest.py` | CLI: `python -m ai_core.ingest --replay` / `--follow` |
| `ai_core/normalizer/{schemas,parser,normalizer}.py` | Typed contracts, JSON parsing, canonical conversion, `event_uid`, `raw_fingerprint` |
| `ai_core/normalizer/follower.py` | Incremental follower, durable cursor, rotation handling |
| `ai_core/normalizer/phase0.py` | Projection to the Phase 0 canonical-event schema |
| `ai_core/persistence/db.py` | SQLite schema (WAL, one writer), transactions, cursor helpers |
| `ai_core/sessions/manager.py` | Idempotent insert, deterministic session recompute |
| `ai_core/sessions/fullsession.py` | Training-compatible `full_session` builder (rule `section0-v1`) |
| `tests/` | 67 tests; fixtures `tests/fixtures/cowrie/phase5_6_sanitized.jsonl` (passwords redacted) and `tests/fixtures/training/fullsession_parity.jsonl` (20 dataset rows) |
| `.dockerignore`, `.gitignore` (+`/models/*`) | Keep weights/datasets out of build contexts and git |

Not committed to git yet; `.venv/` (pytest 9.2.0) is git-ignored.

## 2. Schema and identity (actual)

* **`events`** (PK `event_uid`): normalized fields, `raw_event` JSON, `raw_line`, `orphan_reason`, `validation_errors`, `log_file_id`, `file_seq`, byte offsets, `schema_version`, `uid_version`.
* **`sessions`** (PK `session_id`): all spec §10.2 fields plus `closed_at_utc`, `duration_ms`, `full_session_rule`. `has_downloads` / `download_count` are NULL (unknown).
* **`commands`** (PK `event_uid`): ordered command records, `is_empty` flag.
* **`follower_cursors`**, **`normalization_errors`** (unique on file/offset/type, so replay is idempotent), **`meta`**.
* **`event_uid`** = `sha256("cdp-uid-v1" \0 log_file_id \0 byte_offset \0 raw_line_bytes)`.
* **`raw_fingerprint`** = SHA-256 of canonical JSON (sorted keys, compact separators).
* **`log_file_id`** = SHA-256 of the file's first complete line (identity of a file generation; independent of path/inode).
* **Ordering key:** `(timestamp_us, file_seq, byte_offset_start)`; aggregates are recomputed from stored rows in that order.
* **Transaction:** per batch — insert events, insert commands, recompute touched sessions, write dead-letters, advance cursor, commit. Any failure rolls back, including the cursor.

## 3. Cowrie fields observed (captured Phase 5/6 data; 156 lines, 14 sessions, one source IP)

| Event type | Count | Used for |
|---|---:|---|
| `cowrie.command.input` | 39 | command text in `input` → `commands` |
| `cowrie.session.closed` | 14 | verified close signal (`duration_ms`) |
| `cowrie.session.connect`, `.client.version/.kex/.size/.var`, `.session.params`, `.log.closed`, `.login.success/.failed` | various | stored as events only |
| `cowrie.command.failed` | 3 | stored as events; never a command (duplicate trace with trailing space) |

`cowrie.log.closed` always precedes `cowrie.session.closed`. No download events were captured, so downloads are not mapped.

## 4. `full_session` compatibility evidence

* Rule source: `models/section0_data_preprocessing_and_cleaning.ipynb` (`decode_session` → `clean_full_session`) plus `" ".join(tokens)` from `models/section4_language_model_exploration.ipynb`.
* In-repo test: all 20 fixture rows reproduce the dataset tokens exactly (6 need Base64 decoding).
* Larger one-off check (scratch script, not in the repo): 15,000 / 15,000 rows from three slices of the 233,035-row dataset matched, 2,641 with Base64 decoding.
* **Scope:** this verifies the text-building stage only. The tokenizer and model were not run.
* Known quirks reproduced on purpose: trailing digits stripped (`python3`→`python`), value after `=` dropped, case preserved. One defensive deviation: a trailing `echo` (which crashes the training code) falls back to cleaning without the Base64 step.

## 5. Commands and results

```bash
.venv/bin/python -m pytest tests -v     # 67 passed in 1.67s (run twice, same result)
COWRIE_LOG_DIR=data/cowrie/var/log/cowrie DATABASE_DIR=<scratch> .venv/bin/python -m ai_core.ingest --replay
```

* Passed 67, failed 0, skipped 0. By file: parser/normalizer 18, fullsession 9, sessions 17, follower 16, end-to-end 7.
* Smoke run on the real log (scratch DB): 156 events, 14 sessions (all closed), 39 commands, 0 errors; log SHA-256 identical before and after.
* Host Python 3.14.4, SQLite 3.46.1. Not run in a container image (none exists yet).

## 6. Acceptance criteria

| # | Criterion | Evidence (test) | Result |
|---|---|---|---|
| 1 | Reads only new complete lines | `test_reads_only_new_complete_lines_incrementally` | Met |
| 2 | Partial final line buffered, later processed | `test_partial_line_buffered_until_newline`, `test_buffered_partial_line_survives_restart` | Met |
| 3 | Malformed lines recorded, follower continues | `test_malformed_complete_line_recorded_and_next_line_processed`, parser/normalizer error tests | Met |
| 4 | Canonical record preserves type, both timestamps, session, IP, raw JSON | `test_valid_event_maps_to_canonical_fields`, `test_timestamp_original_preserved_and_utc_normalized`, e2e raw-JSON check | Met |
| 5 | `event_uid` and `raw_fingerprint` separate and documented | `test_identical_content_distinct_uid_same_fingerprint`, `test_event_uid_depends_on_location_and_bytes`; §2 | Met |
| 6 | Replaying the sample twice does not double-count | `test_replaying_capture_twice_does_not_double_count`, `test_replaying_same_file_does_not_duplicate` | Met |
| 7 | Session key is Cowrie session ID | `test_ip_is_never_a_session_key`, `test_orphan_events_stored_but_update_no_session` | Met |
| 8 | Two sessions from one IP stay distinct | `test_two_sessions_same_ip_stay_separate`; e2e: 14 sessions, 1 IP | Met |
| 9 | Deterministic command order and cumulative text | `test_commands_reconstructed_in_timestamp_order_with_tiebreak`, `test_late_arriving_older_event_is_ordered_correctly` | Met |
| 10 | `full_session` matches verified training construction | `tests/unit/test_fullsession.py` (20 rows) + 15,000-row scratch check (§4) | Met for text building; tokenizer/model not run |
| 11 | Snapshots update incrementally and survive restart | `test_incremental_snapshots_update_after_each_command`, `test_restart_reconstructs_same_snapshot_without_duplicates` | Met |
| 12 | Close from verified event only; no timeout | `test_close_event_closes_correct_session_only`, `test_active_session_not_complete_without_close`, `test_late_command_does_not_reopen_closed_session` | Met |
| 13 | Rotation, restart, late, malformed/missing fields tested | follower rotation/copy-truncate/truncation tests; late-event and orphan tests | Met |
| 14 | No shell or firewall privilege | `test_phase7_code_grants_no_shell_or_firewall_access`, `test_phase7_does_not_import_classifier_rl_or_controller` (static checks only) | Met |
| 15 | No raw logs/credentials staged | 0 staged files; `.env`, Cowrie logs, DB, weights, `.venv` ignored; fixture has only `REDACTED` passwords (`test_fixture_has_no_credentials`) | Met (nothing committed yet) |

## 7. Known limitations and unresolved items

1. **Rotation:** if the old generation is already gone when a rotation is detected, unread bytes cannot be recovered; this is recorded as `rotation_source_missing` rather than skipped silently. A first line longer than 1 MiB prevents file identification.
2. **Timestamps:** `timestamp_utc` keeps microseconds (`…:50.395330Z`), not the seconds-only form in the spec example, so ordering is preserved. Naive timestamps are rejected, not assumed UTC.
3. **Empty commands:** stored in `commands` (`is_empty=1`) but excluded from `command_count` / `unique_command_count`; they add no `full_session` tokens.
4. **Phase 0 schema:** the closed Phase 0 schema cannot represent orphan events, IPv6 or null IPs, so `to_phase0()` raises `ValueError` for those. Phase 7 follows the Phase 7 spec/playbook (see proposed D-058).
5. **Model label order:** the trained model emits labels alphabetically (Defense Evasion, Discovery, Execution, Harmless, Impact, Other, Persistence); D-010 lists a different order. Not a Phase 7 issue; needs a decision before serving (Phase 8).
6. **Downloads** remain unknown until a download event is captured and mapped.
7. **Not verified:** the built container (no Docker access in the build session), that your local Cowrie image digest equals the pinned one (see §8), behaviour when Cowrie's own rotation settings differ from the rename-style rotation seen (empty dated file), multi-process writers (not supported by design), and tokenizer/model behaviour.
8. **`ai-core` mount:** `./models:/app/models:ro` also exposes `models/data` (≈1.3 GB of datasets). Mounting only `models/models` would need a reviewed `compose.yaml` change (not made).
9. The 15,000-row parity script lives only in the session scratchpad; the repo test uses the 20 committed rows.

## 8. Container image and Cowrie pin (added after Gate 4)

* **AI Core image:** it did not exist (no Dockerfile in the repo). Added `ai_core/Dockerfile`: `python:3.14-slim-bookworm` pinned by digest, standard library only, code root-owned, runs `python -m ai_core.ingest --follow` as a non-root user. **Not yet built or run**; the session had no Docker access.
* **`compose.yaml`:** `ai-core` gets a `build:` block, `user` (default 1000:1000 to match `./data/app`), `read_only`, `tmpfs: /tmp`, `cap_drop: ALL`, `no-new-privileges`, and only `./models/models` mounted read-only (previously all of `./models`, including the datasets). `cowrie` is pinned to `cowrie/cowrie:3.1.5@sha256:797d45ca…e3fe`. `docker compose config` validates; the profile is still not started.
* **Why pin:** `cowrie/cowrie:latest` is a moving tag. A later pull could change event names or fields, and the Phase 7 mappings were verified only against the captured logs. The pinned digest is what `latest` pointed to (3.1.5, pushed 2026-11-02 04:19 UTC), before the first Cowrie run on this VM (2026-11-02 16:40 UTC). That makes it very likely the image that produced the captures, but only `docker image inspect` on the VM can confirm it.
* **`.env`:** image names changed from `Main-Repo/...` to `autonomous-deception/...` because Docker requires lowercase repository names. `.env.example` was added with placeholders.
* **Test added:** `test_works_when_log_directory_is_read_only` (log dir `0555`, file `0444`) mirrors the `:ro` mount. Suite is now 68 tests, all passing.
