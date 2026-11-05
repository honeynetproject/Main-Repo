# Phase 7 Specification — Event Normalizer and Session Manager

**Project:** Autonomous Cyber Deception Platform Using Reinforcement Learning for Adaptive Honeynet Orchestration  
**Phase:** 7 — Event Normalizer and Session Manager  
**Primary reference:** `docs/IMPLEMENTATION_PLAYBOOK.docx`, Phase 7  
**Depends on:** Cowrie sample JSON from Phase 5; event schema frozen during Phase 0    
**Status:** Implementation specification

## 1. Objective

Implement the first data-processing layer between Cowrie and the AI Core. It must incrementally read Cowrie's JSONL log, parse and normalize each complete event, persist it idempotently, and maintain an evolving session record keyed by Cowrie's session ID.

The output must support later classifier integration, RL observation building, dashboard views, and incident reporting. Phase 7 does **not** implement DistilBERT inference, rule classification, RL state construction, Q-learning, controller actions, or containment.

## 2. Required outcomes

At the end of Phase 7:

1. New complete Cowrie JSON lines are processed without rereading the entire log on every poll.
2. A partial final line is retained until it is completed by a newline; it is not parsed as a complete event prematurely.
3. Malformed lines are recorded for diagnosis and skipped without terminating the follower.
4. Every valid ingested record has an internal `event_uid` suitable for idempotent ingestion and a separate `raw_fingerprint`.
5. The original Cowrie event type, timestamp, session ID, source IP, optional message, and full raw event are preserved.
6. Normalized timestamps are UTC ISO-8601, with the original timestamp retained.
7. Events are grouped by Cowrie `session`, never by source IP alone.
8. Command-input events build an ordered, cumulative session command history compatible with the exact training preprocessing.
9. Session summaries update as events arrive and survive process restart.
10. Replaying the same source file does not double-count events or commands.
11. Required automated tests cover the acceptance cases in this specification.

## 3. Scope boundary

### In scope

- Cowrie JSONL tail/follower.
- JSON parsing and schema validation.
- Event normalization and provenance.
- Event identity and replay/idempotency.
- Session Manager and incremental session snapshots.
- Persistence and checkpoint/cursor recovery.
- Malformed-record handling and structured diagnostics.
- Unit, integration, replay, restart, and rotation tests.

### Out of scope

- Loading or invoking DistilBERT.
- Designing or changing the seven model labels.
- Rule-based classification.
- Prefix-evaluation policy or deciding whether five commands are sufficient.
- Observation Builder, state encoding, reward function, Q-table, or action selection.
- Controller, Cowrie behaviour modification, firewall blocking, or session termination.
- Dashboard UI and STIX/PDF report generation.
- Changes to the existing Cowrie deployment or Docker Compose configuration unless a concrete Phase 7 integration blocker is demonstrated and the change is reviewed first.

## 4. Repository-first implementation rules

Before writing code, inspect the current repository and report:

- Current language/runtime and dependency versions.
- Existing AI Core package structure and entry point.
- Existing event schemas, database code, logging conventions, tests, and configuration system.
- Current Cowrie log path and representative sanitized records.
- Existing `.gitignore` rules for raw logs, runtime state, credentials, and database files.
- Existing Compose mounts and container permissions relevant to reading the log.

Reuse or extend existing structures where appropriate. Do not create duplicate modules or a second database abstraction if one already exists. Do not move or rename folders simply to match a proposed layout. Do not change `compose.yaml`, Cowrie configuration, image tags, port bindings, or file permissions unless the audit demonstrates a necessary issue; explain the exact reason and proposed change before applying it.

Suggested logical modules (adapt names to the repository):

```text
ai_core/
  normalizer/
    __init__.py
    follower.py          # file tailing, partial-line buffer, cursor handling
    parser.py            # raw JSON parsing and validation
    normalizer.py        # canonical event conversion and hashes
    schemas.py           # typed event / error / cursor models
  sessions/
    __init__.py
    manager.py           # apply event and build session snapshots
    schemas.py           # typed session snapshot models
  persistence/
    ...                  # reuse existing DB layer if present

tests/
  fixtures/
    cowrie/
  unit/
  integration/
```

This is a logical suggestion, not a requirement to duplicate or reorganize the current repository.

## 5. Inputs and observed Cowrie format

The input is the Cowrie JSONL file on the Ubuntu VM. The currently recorded host path is:

```text
 data/cowrie/var/log/cowrie/cowrie.json
```

Verify the active path in the repository and runtime before hard-coding it. The follower should accept a configurable path and sensible runtime configuration rather than embedding the path in multiple modules.

Observed captured event fields include:

- `timestamp`
- `eventid`
- `session`
- `src_ip`
- `username`
- `input`

Observed event types include:

- `cowrie.session.connect`
- `cowrie.login.success`
- `cowrie.login.failed`
- `cowrie.command.input`
- `cowrie.session.closed`

These are examples from the current captured lab data, not a complete guaranteed schema. Inspect fixtures generated by the pinned Cowrie image and verify the exact command-input event and field names before implementing event-specific logic. The `message` field may be absent on some records; preserve it when present.

A sample event may look like:

```json
{
  "timestamp": "2026-11-04T03:00:28.435913Z",
  "eventid": "cowrie.session.connect",
  "session": "d4fbde4cdc49",
  "src_ip": "10.77.10.20",
  "username": null,
  "input": null
}
```

Do not treat sample values such as IP addresses, session IDs, usernames, or timestamps as constants.

## 6. Canonical normalized event schema

The minimum internal event contract is:

```json
{
  "event_uid": "sha256:...",
  "raw_fingerprint": "sha256:...",
  "source": "cowrie",
  "source_event_type": "cowrie.command.input",
  "timestamp_utc": "2026-10-25T10:00:00Z",
  "session_id": "abc123cowrieid",
  "source_ip": "10.77.10.20",
  "command": "uname -a",
  "raw_event": {"...": "original JSON retained"}
}
```

The implementation may extend the schema with fields such as:

| Field | Purpose |
|---|---|
| `timestamp_original` | Original Cowrie timestamp string/value, unchanged |
| `message` | Cowrie `message` if present |
| `username` | Cowrie `username` if present |
| `raw_line` | Original UTF-8 JSONL line, if safe and useful for exact provenance |
| `log_file_id` | Stable identity for the source file generation |
| `byte_offset_start` / `byte_offset_end` | Byte position of the record in the source file |
| `ingestion_sequence` | Stable tie-breaker/order marker assigned by the follower |
| `validation_errors` | Non-secret validation issues observed during parsing/normalization |
| `is_command_input` | Derived flag based on verified Cowrie event mapping |

Do not rename or reinterpret the canonical fields. Keep the source event type distinct from the internal `event_uid`.

## 7. Incremental log follower

### 7.1 Required behaviour

- Read only new data since the last committed cursor.
- Process only newline-terminated records as complete JSONL events.
- If EOF occurs after a partial JSON record, retain the incomplete bytes and resume from the same line start on the next read. Do not advance the durable cursor past unprocessed partial data.
- On shutdown, stop cleanly and ensure restart can re-read any uncommitted partial line without data loss.
- Continue after a malformed complete line: record the malformed line/error, advance past that complete line, and continue with the next line.
- Do not crash the follower because one line is invalid.
- Support both a continuously running follow mode and a deterministic replay mode for tests.

### 7.2 Cursor and file rotation

Maintain a durable ingestion cursor containing sufficient source identity and position to resume safely. At minimum, track a stable file identity and the byte offset after the last fully committed line.

Handle:

- Process restart with the same file still present.
- Log rotation to a new file/inode.
- Rename-and-create rotation.
- Copy-truncate rotation where the file size becomes smaller than the stored offset.
- Partial final lines around shutdown or rotation.

Do not assume a pathname alone uniquely identifies a file generation. Do not lose unprocessed bytes when a file rotates. If a rotation pattern cannot be handled reliably by the current implementation, fail visibly and document the limitation rather than silently skipping data.

### 7.3 Transaction/checkpoint ordering

The durable checkpoint must not move past a line unless the line's handling has been committed. A valid event should be inserted idempotently and applied to its session before the cursor is advanced. If persistence fails, the follower must be able to retry the line safely.

For a malformed complete line, persist the error/dead-letter record (or equivalent durable diagnostic) before moving past it. A duplicate replay must be harmless.

## 8. Parsing, normalization, and validation

For each complete line:

1. Decode according to the log's encoding assumptions; report decode failures safely.
2. Parse JSON and require a JSON object for a Cowrie event.
3. Preserve the original raw JSON record and source line/provenance.
4. Map `eventid` → `source_event_type`.
5. Map `timestamp` → `timestamp_original` and normalized UTC `timestamp_utc`.
6. Map Cowrie `session` → `session_id`.
7. Map `src_ip` → `source_ip` after validation using Python's `ipaddress` module.
8. Preserve `message` and `username` when present.
9. For verified command-input events, map the original command input text to `command` without arbitrary splitting or destructive normalization.
10. Record missing, malformed, or type-invalid optional values as validation issues. Never fabricate values.

A missing or invalid `session` must not cause the event to be assigned to a made-up session. Preserve/quarantine it as an orphan event and do not update a session. Likewise, an invalid source IP should be marked invalid/null according to the schema; do not invent an IP.

If the timestamp cannot be parsed, retain the original value, record a validation error, and follow an explicit policy for whether the event can be stored as an unorderable/orphan event. Do not substitute the current time.

## 9. Event identity and idempotency

Generate two separate hashes:

- `event_uid`: internal unique record identity used for ingestion idempotency.
- `raw_fingerprint`: stable content fingerprint of the canonicalized raw event JSON.

One playbook-supported `event_uid` strategy is a SHA-256 hash over source file identity + byte offset + raw line bytes. This binds the event identity to its source location and supports restart/replay at the same source. Document the selected algorithm and its version.

`raw_fingerprint` should be computed from deterministic canonical JSON serialization (stable key ordering and encoding). It helps identify equal content but is not the event's unique identity.

Rules:

- Do not use Cowrie `eventid` as a unique record ID; it is a type shared by many records.
- Do not use source IP, session ID, timestamp alone, or `raw_fingerprint` alone as `event_uid`.
- Do not silently drop two distinct source records solely because their JSON content is identical; repeated identical commands/events can be legitimate.
- Enforce a database uniqueness constraint on `event_uid`.
- On duplicate `event_uid`, do not increment command counts or reapply session summary changes.
- Ensure replaying the same fixture from the same logical source identity and offsets is idempotent.

## 10. Session Manager

### 10.1 Session identity and creation

Use Cowrie's `session` field as the authoritative session key (`session_id` internally). A source IP is an attribute, not a session key. One source IP may generate multiple independent sessions; they must remain separate.

When an event with a valid session ID arrives:

- Create the session record if it does not exist.
- Attach the event to that session.
- Update session summaries and command history transactionally/idempotently.

Events without a usable session ID remain unassociated/orphan events; do not group them under an IP-only key.

### 10.2 Session fields

At minimum, each session record/snapshot must expose:

| Field | Meaning |
|---|---|
| `session_id` | Cowrie session ID |
| `source_ip` | Validated source IP where available |
| `started_at_utc` | Earliest valid event timestamp observed for the session |
| `last_activity_at_utc` | Latest valid event timestamp observed for the session, not simply the most recently ingested timestamp |
| `command_count` | Number of valid command-input events |
| `unique_command_count` | Number of distinct command strings under a documented, deterministic equality rule |
| `full_session` | Cumulative command text assembled in event order using the exact training-time text-building/cleaning rule |
| `status` | At least `active` or `closed`; use `timed_out` only if an explicit timeout policy is implemented |
| `closure_reason` | Observed close event/reason or configured timeout reason, when known |
| `has_downloads` / `download_count` | Values derived only from verified Cowrie download-related event mappings; otherwise mark unknown rather than inventing evidence |
| `is_complete` | Whether a verified close event or explicit timeout policy has closed the session |

Keep the ordered command records linked to their source `event_uid` so the cumulative text can be rebuilt and audited.

### 10.3 Incremental updates

Update the session after each newly committed event. An active session may have a partial `full_session`; this is expected.

For example:

- After command `id`, the current snapshot contains the cumulative text for the one observed command.
- After command `uname -a`, the same snapshot contains both commands in the correct order.
- After each further command, update the cumulative text and counters.
- When a verified close event arrives, mark the session closed and final for the observed lifecycle.

Do not wait until a session ends before storing its events or updating its current snapshot. Do not call an active snapshot a complete session simply because it has a `full_session` field.

### 10.4 Command order and late events

Preserve each command event as a separate record. Reconstruct the sequence by:

1. normalized event timestamp (`timestamp_utc`), then
2. a deterministic stable tie-breaker such as source file identity and byte offset / ingestion sequence.

Do not depend on database row order or in-memory insertion order alone.

Late-arriving events must be retained and the ordered command sequence rebuilt or updated deterministically. `last_activity_at_utc` should remain the maximum valid event time, not move backwards because an older event was ingested later.

A late command event that predates a session-close event must not silently reopen the session. Preserve the closure evidence and include the late event in the reconstructed history according to the ordering rule.

### 10.5 Training-compatible `full_session`

The training data uses a `full_session` field. The live `full_session` must be constructed from the session's command-input text in order and with exactly the same cleaning, joining, and preprocessing expected by the training pipeline.

Before implementing the final text builder, inspect the original training notebook/code and document:

- Which Cowrie event constitutes a command-input event.
- Which raw field contains the command text.
- Whether command text is cleaned, normalized, truncated, or filtered.
- The exact delimiter/joining rule between commands.
- Whether empty or malformed command inputs are included or excluded.
- Whether command order is timestamp-based or the training dataset's recorded order.

Do not split commands on arbitrary spaces or semicolons. Do not invent a newline/space separator. Do not tokenize or lowercase text unless the training pipeline did so. If the training pipeline cannot be located or verified, implement the raw ordered command records and mark exact `full_session` compatibility as blocked pending evidence; do not claim it is verified.

## 11. Persistence requirements

SQLite is recommended for this project but is not a strict logical requirement. Inspect and reuse the existing database approach if present.

If SQLite is used:

- Keep Cowrie JSONL unchanged as the raw source of truth.
- Use an `events` table with a unique constraint on `event_uid`.
- Store the original raw JSON with the normalized fields.
- Store session summaries in a `sessions` table.
- Store ordered command records in a `commands` table linked to event and session IDs.
- Store the follower cursor/checkpoint so restarts resume safely.
- Store malformed/dead-letter records or durable diagnostics.
- Use transactions so event insertion, session update, and cursor advancement are consistent.
- Use one AI Core writer process; do not treat SQLite as a multi-writer event bus.
- Keep database files and runtime state out of Git unless the repository explicitly requires sanitized fixtures or migration files.

Suggested minimal relationships:

```text
events(event_uid PRIMARY KEY, raw_fingerprint, session_id, source_event_type,
       timestamp_utc, source_ip, raw_event_json, source_file_id, byte_offset, ...)

sessions(session_id PRIMARY KEY, source_ip, started_at_utc, last_activity_at_utc,
         command_count, unique_command_count, full_session, status,
         closure_reason, has_downloads, download_count, ...)

commands(event_uid PRIMARY KEY REFERENCES events(event_uid),
         session_id REFERENCES sessions(session_id), command_text,
         timestamp_utc, order_key, ...)

follower_cursors(source_file_id PRIMARY KEY, committed_offset, ...)
normalization_errors(error_id PRIMARY KEY, source_file_id, byte_offset,
                     raw_line_or_safe_reference, error_type, error_detail, created_at_utc)
```

These are conceptual table shapes. Adapt to existing repository conventions and migrations; do not blindly replace an existing schema.

## 12. Error handling and observability

The normalizer must distinguish at least:

- Malformed JSON line.
- Non-object JSON value.
- Invalid/missing timestamp.
- Invalid/missing session ID.
- Invalid source IP.
- Missing/unknown event type.
- Unknown event type that is syntactically valid.
- Invalid/missing command text on a command-input event.
- Duplicate `event_uid`.
- File read/permission error.
- Rotation/truncation detection.
- Persistence/checkpoint failure.

An unknown but valid Cowrie event type should normally be retained as an event with its original `source_event_type`; it should not crash the pipeline. Event-type-specific behaviour (command extraction, closure, download counters) should occur only for verified event mappings.

Log diagnostics with structured fields such as source file, byte offset, error category, and `event_uid` when available. Avoid dumping credentials or unnecessarily repeating raw session contents into general application logs. Keep the original event in the evidence store or restricted dead-letter record when appropriate.

## 13. Required tests

Use pytest or the repository's existing test framework. Tests must be deterministic and must not depend on a live Cowrie service unless explicitly marked as integration tests.

### 13.1 Parser and normalization unit tests

- Valid Cowrie event maps to the canonical schema.
- `eventid` maps to `source_event_type`, not `event_uid`.
- Original timestamp is preserved and UTC timestamp is correct.
- Valid IPv4 and IPv6 are accepted by the validator; invalid IP is flagged.
- Missing optional fields remain absent/null with a validation note; no fabricated data is inserted.
- Unknown but valid event types are retained.
- Malformed JSON and non-object JSON are recorded without crashing.
- A command-input event extracts the exact original command text.

### 13.2 Follower tests

- Reads new complete lines incrementally.
- Buffers a partial line at EOF and processes it only after newline completion.
- Does not lose a buffered line after process restart.
- Malformed complete line is recorded and the next valid line is still processed.
- Same file and cursor can be replayed without duplicate insertion.
- Log rename/create rotation is detected.
- Copy-truncate/shrink is detected and handled without silently skipping data.
- Persistence failure does not advance the durable cursor past an uncommitted valid line.

### 13.3 Session Manager tests

- Events with the same Cowrie session ID update one session.
- Two different Cowrie session IDs from the same source IP remain separate.
- Duplicate `event_uid` does not increment counts or append a command twice.
- Commands are reconstructed in timestamp order with deterministic tie-breaking.
- Late-arriving older event is retained and ordered correctly.
- `started_at_utc` is the earliest event time; `last_activity_at_utc` is the latest event time.
- Command and unique-command counts are correct.
- Incremental snapshots update after each command.
- A close event closes the correct session and records closure evidence.
- An active session is not marked complete merely because no new line has arrived.
- Restart reconstructs the same session snapshot without duplicate commands.
- Download summary is derived only from verified event mappings.

### 13.4 Training compatibility tests

- At least one known training example or a controlled fixture passes through the live `full_session` builder.
- The produced text matches the verified training-time construction exactly, including delimiter, cleaning, and command ordering.
- No arbitrary tokenization/splitting is introduced.

If the original training preprocessing is unavailable, report this as an unresolved acceptance blocker rather than creating a speculative compatibility test.

## 14. Acceptance criteria — Phase 7 exit gate

Phase 7 is complete only when all applicable criteria below are demonstrated with test output or retained evidence:

- [ ] Follower reads only new complete Cowrie JSONL lines during normal operation.
- [ ] Partial final JSON line is buffered and later processed without loss.
- [ ] Malformed lines are recorded and do not terminate the follower.
- [ ] Canonical event records preserve source event type, original timestamp, UTC timestamp, Cowrie session ID, validated source IP, and full raw JSON.
- [ ] `event_uid` and `raw_fingerprint` are separate and documented.
- [ ] Replaying the same sample file twice does not double-count events or commands.
- [ ] Session identity is Cowrie session ID, not source IP.
- [ ] Two sessions from one source IP remain distinct.
- [ ] Command records and cumulative command text preserve deterministic order.
- [ ] `full_session` matches the verified training-time construction, or the exact compatibility blocker is explicitly recorded and Phase 7 is not reported as fully accepted.
- [ ] Session snapshots update incrementally and persist across process restart.
- [ ] Session close status is based on a verified close event or an explicit timeout policy.
- [ ] Log rotation, restart, late-arriving events, and malformed/missing fields have automated tests.
- [ ] No Phase 7 code grants arbitrary shell execution or firewall privilege.
- [ ] No raw Cowrie logs, credentials, or runtime secrets are staged for Git commit.

The playbook's core acceptance gate is: replaying the same sample file does not double-count events; command sequences are reconstructed in order; source event types remain distinct from unique event IDs; sessions are never merged merely because they share an IP.

## 15. Deliverables

1. Incremental Cowrie JSONL follower with restart-safe cursor and rotation handling.
2. Typed normalized-event schema and parser/validator.
3. Event identity/fingerprint implementation with documented algorithm.
4. Session Manager with incremental session snapshots and ordered commands.
5. Persistence integration and schema/migration (if SQLite is used).
6. Malformed-event/dead-letter handling and structured diagnostics.
7. Unit and integration tests for all required cases.
8. Sanitized Cowrie fixtures for repeatable tests.
9. A short Phase 7 implementation report containing:
   - files created/modified;
   - actual schema and `event_uid` strategy;
   - actual Cowrie event types/field mappings observed;
   - exact training `full_session` compatibility evidence;
   - persistence/checkpoint design;
   - commands used to run tests;
   - passed/failed/skipped test results;
   - known limitations and unresolved issues.

## 16. Implementation sequence for Claude Code

Claude Code must follow this sequence and pause at the review gates:

### Gate 1 — Repository audit (no edits)

Read `CLAUDE.md`, `docs/PROJECT_CONTEXT.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, this specification, and the Phase 7 section of the implementation playbook. Inspect repository files and representative Cowrie fixtures. Report the actual repository state, reusable components, proposed changed files, dependencies, risks, and any conflicts. Do not modify files yet.

### Gate 2 — Contract and persistence design

Propose the normalized event schema, session schema, unique-ID formula, file-cursor format, malformed-record strategy, and transaction ordering. Verify command-event/closure mappings and training text construction against actual evidence. Identify unresolved items. Do not begin implementation until the user approves the audit/design plan.

### Gate 3 — Implement and test in small increments

Recommended order:

1. Typed schemas and parser/normalizer.
2. `event_uid`/`raw_fingerprint` and idempotent persistence.
3. Session Manager and command ordering.
4. Incremental follower and cursor recovery.
5. Rotation/restart/late-event handling.
6. End-to-end replay against sanitized Phase 5/6 fixtures.

Run the relevant tests after each increment and preserve working functionality.

### Gate 4 — Acceptance review

Run the complete Phase 7 test suite, walk through every acceptance criterion, and produce the implementation report. Do not mark an item complete without evidence. Do not start Phase 8 or modify classifier/RL/controller functionality as part of this task.

## 17. Final constraints

- Do not guarantee zero defects; use tests and evidence to find and reduce defects.
- Do not invent Cowrie event names, data fields, model preprocessing, timeout values, or thresholds.
- Do not use source IP as a session key.
- Do not deduplicate by `eventid` or raw content fingerprint alone.
- Do not process partial JSON as a complete line.
- Do not lose a line because the process restarts or a log rotates.
- Do not mark incremental sessions complete prematurely.
- Do not allow Phase 7 to call the classifier, Q-agent, controller, or firewall executor.
- Do not make unrelated changes to Cowrie, Compose, network configuration, or host firewall.
