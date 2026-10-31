# API contract and service boundaries

## 1. Communication policy

- Event normalizer, session manager, classifier router, fallback, observation builder and Q-learning run inside one AI Core process initially and use typed Python interfaces, not separate HTTP services.
- Cowrie JSONL is read by an AI Core log-following worker through a read-only shared volume. Stock Cowrie does not automatically POST to the AI Core API.
- AI Core calls the separate Honeynet Controller over a private Docker network.
- Controller calls a custom Cowrie control adapter over a private network. This adapter must be implemented; stock log output is not a session-control API.
- Controller requests VM firewall operations through a protected Unix-domain socket to a narrowly scoped executor running inside the Ubuntu VM. Windows is not involved.
- Streamlit reads the AI Core's dashboard API; it does not execute actions or firewall operations.

## 2. Service names and ports

| Service | Internal address | Exposure |
|---|---|---|
| AI Core | `http://ai-core:8000` | Docker backend network only |
| Controller | `http://controller:9000` | Docker backend network only |
| Cowrie control adapter | `http://cowrie:2223` (proposed) | Backend network only; custom implementation |
| Streamlit | `http://10.77.20.10:8501` | Management network only |
| Cowrie SSH | `10.77.10.10:2222` | Honeypot network only |
| Firewall executor | Unix socket | Ubuntu VM local socket only |

The proposed Cowrie adapter port is an internal design choice, not a stock Cowrie port. Confirm it when implementing the adapter. Do not publish ports 8000, 9000 or 2223 to the attacker network.

## 3. API endpoints

### Controller
- `POST /api/v1/actions` — submit an allowlisted deception action; returns `202 Accepted` with `decision_id` and status `accepted`.
- `GET /api/v1/actions/{decision_id}` — retrieve execution status: `accepted`, `applied`, `rejected`, `failed`, or `expired`.
- `POST /api/v1/containments` — submit a Safety Guard containment request, independent of RL action selection.

### AI Core dashboard/read API
- `GET /api/v1/health`
- `GET /api/v1/status`
- `GET /api/v1/sessions?status=active`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions/{session_id}/decisions`
- `GET /api/v1/reports`
- `GET /api/v1/reports/{report_id}/download?format=pdf|stix`

### Custom Cowrie control adapter
- `POST /internal/v1/sessions/{session_id}/actions` — apply a validated behavior action to one active session.

### Firewall executor
Use a Unix-domain socket with a narrow JSON request, e.g. `block_source` or `unblock_source`, plus session ID and validated source IP. It must not accept arbitrary command strings or arbitrary firewall rules.

## 4. Request/response behavior

- All JSON APIs use versioned paths and UTC ISO-8601 timestamps.
- Include `request_id`, `decision_id`, or `correlation_id` to trace a flow across services.
- Use an idempotency key for action and containment requests so retries do not duplicate effects.
- `202` means accepted for processing, not successfully applied.
- Use explicit final statuses; the dashboard must not display `accepted` as `applied`.
- Use `400/422` for invalid fields, `404` for unknown session/decision, `409` for invalid session state/conflict, and `503` for unavailable dependencies.
- Validate all requests with Pydantic models and publish the generated OpenAPI document.
- Keep API credentials in environment/secrets, not Git. Restrict the backend network and use service authentication even on the internal network.
