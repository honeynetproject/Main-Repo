# Canonical event schema and Cowrie mapping

## 1. Source mapping

Cowrie JSON output is newline-delimited JSON. Shared source fields include `eventid`, `timestamp`, `session`, and `src_ip`; connection events can also include `src_port`, `dst_ip`, `dst_port`, and `protocol`. Command-input events carry the command in `input`.

| Canonical field | Cowrie source | Notes |
|---|---|---|
| `source_event_type` | `eventid` | e.g. `cowrie.command.input`; this is an event type, not a unique record ID |
| `event_time` | `timestamp` | Preserve/normalize as UTC ISO-8601 |
| `session_id` | `session` | Session correlation key |
| `source_ip` | `src_ip` | Validate as IP address |
| `protocol` | `protocol` | Typically `ssh` or `telnet` |
| `command` | `input` | Only for relevant command events |
| `src_port`, `dst_ip`, `dst_port` | same-named fields | Optional connection metadata |

## 2. event_uid

The platform adds `event_uid`. It is not Cowrie's `eventid`. Generate it deterministically in the log collector from a stable source/sensor identifier, log-file generation identifier, byte offset, and raw line (for example SHA-256). Persist the source file identity and offset. This allows replayed log lines to be recognized and deduplicated while preserving distinct identical commands at different offsets.

## 3. Processing rules

1. Follow `cowrie.json` as JSONL; read only newly appended complete lines and handle partial lines safely.
2. Parse each line as JSON; retain the raw object.
3. Map Cowrie's `eventid` to a platform `event_type` while preserving the original source event type.
4. Correlate events by Cowrie's `session` value, not source IP alone.
5. Append ordered command-input events to the session command history.
6. Trigger classification after five newly observed command-input events, using the cumulative session prefix by default; record the command count and input window.
7. Treat close/disconnect events as terminal lifecycle signals; allow for late events and deduplicate.
8. Pass the reconstructed text through the exact preprocessing/tokenizer/feature pipeline used by the saved model. If the deployed model actually requires a fitted TF-IDF transformer, load that fitted artifact; do not create a new vectorizer at inference time.

## 4. Example normalized event

```json
{
  "schema_version": "1.0",
  "event_uid": "sha256:REPLACE_WITH_64_HEX_CHARACTERS",
  "source": "cowrie",
  "source_event_type": "cowrie.command.input",
  "event_type": "command_input",
  "event_time": "2026-10-31T09:30:00Z",
  "ingested_at": "2026-10-31T09:30:00.125Z",
  "session_id": "cowrie-session-example",
  "source_ip": "10.77.10.20",
  "protocol": "ssh",
  "src_port": 53000,
  "dst_ip": "10.77.10.10",
  "dst_port": 2222,
  "command": "uname -a",
  "raw_event": {
    "eventid": "cowrie.command.input",
    "timestamp": "2026-10-31T09:30:00Z",
    "session": "cowrie-session-example",
    "src_ip": "10.77.10.20",
    "input": "uname -a"
  }
}
```

This example is illustrative. Preserve all Cowrie source fields in `raw_event` even if they are not currently mapped.
