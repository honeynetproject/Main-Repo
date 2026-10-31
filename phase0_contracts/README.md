# Phase 0 contracts — Autonomous Cyber Deception Platform

This is a starter contract pack for the single-Cowrie SSH honeypot project. It describes intended interfaces; it is not a running implementation.

## Decisions captured
- One Cowrie SSH/Telnet honeypot as the primary deception service.
- AI Core modules run together initially: event ingestion/normalization, session management, DistilBERT + rule fallback, observation builder, tabular Q-learning, persistence/reporting.
- Honeynet Controller is a separate service and is the only service allowed to request Cowrie behavior changes or containment.
- VM firewall executor runs inside the Ubuntu VM (not Windows) and exposes a narrowly scoped local Unix socket to the controller.
- Streamlit is the dashboard; it reads the AI Core API.
- The six-feature 144-state design and nine action IDs are retained from the proposal for Phase 0 contract compatibility.

## Files
- `docs/network-ip-plan.md`: proposed VMware VM network addressing and port exposure.
- `docs/event-schema.md`: how Cowrie JSON records become normalized platform events.
- `docs/api-contract.md`: component boundaries and API behavior.
- `docs/rl-state-action.md`: retained state features and action IDs.
- `schemas/*.schema.json`: JSON Schema examples for shared data contracts.
- `contracts/openapi.yaml`: proposed REST API contract for service boundaries.

## Before implementation
1. Confirm the proposed subnets do not overlap any existing lab networks.
2. Confirm the available VMware isolation option and ensure Windows has no virtual adapter attached to the project networks.
3. Confirm the exact seven-label names and order against the saved classifier artifacts.
4. Confirm the exact nine action names against the approved project proposal.
5. Review these contracts with all five team members and merge changes through a pull request.

## Important
- Do not commit `.env`, passwords, private keys, raw Cowrie logs, downloaded artifacts, raw training data, model weights, SQLite databases, or generated incident data.
- Docker container IP addresses are dynamic. Use Compose service names for inter-container connections.
- `eventid` in Cowrie is the source event type (for example `cowrie.command.input`); it is not a unique per-record identifier. The platform's `event_uid` is separate.
- The OpenAPI file is a contract blueprint. Endpoint paths must be implemented and tested; stock Cowrie does not automatically expose the custom session-control API described here.
