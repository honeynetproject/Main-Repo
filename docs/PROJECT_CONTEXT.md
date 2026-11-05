# Project Context

**Project:** Autonomous Cyber Deception Platform Using Reinforcement Learning for Adaptive Honeynet Orchestration  
**Document status:** Project context baseline  
**Prepared:** 5 November 2026  
**Primary implementation reference:** `docs/IMPLEMENTATION_PLAYBOOK.docx`

## 1. Project overview

The project is an isolated, research-oriented cyber deception platform. It uses a Cowrie SSH honeypot to collect controlled attacker-interaction telemetry, transforms the raw telemetry into session records, classifies session intent using an already-trained DistilBERT model (with a rule-based fallback), and uses tabular Q-learning to select among predefined deception behaviours. A separate controller validates and applies approved actions. A separate safety/containment path handles hard safety conditions independently of the reinforcement-learning policy.

The platform also provides an analyst-facing dashboard and produces incident artifacts, including STIX 2.1 and PDF reports.

The project is designed for a contained virtual lab. It is not intended to protect a production network or operate as a public-facing deception service.

## 2. Problem and objective

A static honeypot presents largely fixed behaviour to every interaction. This project investigates whether a honeypot can adapt a controlled set of simulated responses to observed session behaviour and classified intent, while keeping enforcement and system-level operations behind a separate safety boundary.

The objectives are to:

1. Capture repeatable SSH interaction telemetry through Cowrie.
2. Convert Cowrie's event stream into reliable, incremental session records.
3. Integrate the existing trained DistilBERT classifier using the same preprocessing and label mapping used during training.
4. Provide a deterministic rule-based fallback when the classifier is unavailable or produces invalid output.
5. Convert classification and session behaviour into the project's six-feature, 144-state representation.
6. Use tabular Q-learning to select one of nine allowlisted deception actions.
7. Validate and execute actions through a separate controller rather than allowing the agent to alter Cowrie directly.
8. Enforce configured containment conditions through a restricted Ubuntu-VM-only execution path.
9. Display platform activity and produce traceable STIX 2.1 and PDF reports.

## 3. Scope

### 3.1 In scope

- One primary honeypot: Cowrie SSH.
- Cowrie deployed in Docker inside the Ubuntu virtual machine.
- Incremental ingestion of Cowrie JSONL telemetry.
- Event normalization and session reconstruction.
- Persistent structured session/event records; SQLite is the recommended store, while the raw Cowrie JSON log remains the evidence source of truth.
- Existing trained DistilBERT model integration, preprocessing verification, prefix evaluation, and fallback behaviour.
- Seven project classification labels.
- Six-feature tabular state encoding and 144 discrete states.
- Tabular Q-learning and nine predefined deception actions.
- A separate controller, safety guard, Cowrie control adapter, and restricted Ubuntu firewall executor.
- Streamlit dashboard and STIX 2.1/PDF reporting.
- Controlled testing using the project's own Kali VM or scripted test client.

### 3.2 Out of scope

Unless the supervisor explicitly changes the scope, do not add:

- HTTP or FTP honeypots or separate protocol-specific detection pipelines.
- A separate CTI Engine or dependency on commercial CTI/SIEM/SOAR services.
- Malware execution or malware-analysis functionality.
- Real exploitation of vulnerabilities or arbitrary execution of attacker-supplied commands on the Ubuntu host.
- Deep reinforcement learning such as DQN, PPO, or actor-critic methods.
- Automated offensive actions against systems outside the isolated lab.
- Production-network protection, cloud deployment, or geographically distributed honeypots.
- A second real database honeypot; Cowrie is the selected honeypot for the current implementation.

## 4. ML classification contract

The DistilBERT classifier has already been trained. The remaining work is to audit and package the trained artifacts, reproduce the training-time input preprocessing, evaluate inference on incremental prefixes, implement the fallback, and integrate the model.

The project label set is exactly:

1. `Persistence`
2. `Discovery`
3. `Defense Evasion`
4. `Execution`
5. `Impact`
6. `Other`
7. `Harmless`

`Other` and `Harmless` are project-specific classes; they are not MITRE ATT&CK tactics.

The available training-data fields are understood to include `session_id`, `timestamp`, `full_session`, and a label field. The exact serving contract is not assumed here. The model owner must inspect the training notebook and saved artifacts to verify tokenizer/vectorizer, text cleaning, sequence length, label order, output semantics (single-label or multi-label), and thresholds. Do not assume that TF-IDF vectors are accepted by a standard DistilBERT checkpoint.

## 5. Reinforcement-learning contract

The project uses **tabular Q-learning only**. Its state representation has six features and 144 possible encoded states. Its action set has nine predefined deception actions. The action IDs and names are recorded in `DECISIONS.md`.

The agent selects a deception action. It does not have permission to execute shell commands, alter Cowrie directly, change host firewall rules, terminate sessions, or request/veto containment. A separate controller validates the decision and applies supported behaviour changes. Safety/containment decisions are independent of the learned policy.

Initial thresholds and heuristic boundaries are experimental parameters until evaluated; they must not be presented as validated facts.

## 6. Lab environment and known endpoints

The current lab is based on:

| Component | Current recorded value |
|---|---|
| Host operating system | Windows 11; VMware Workstation only |
| Honeypot platform | Ubuntu VM |
| Attacker platform | Kali Linux VM |
| Ubuntu/Cowrie VM address | `10.77.10.10` |
| Kali VM address | `10.77.10.20` |
| Cowrie SSH endpoint | `10.77.10.10:2222` |
| Cowrie JSON log on Ubuntu host | `data/cowrie/var/log/cowrie/cowrie.json` |

These addresses describe the current lab record and must be checked against the VM configuration before network-sensitive testing. The honeypot port should be bound only to the intended honeypot-lab interface, not exposed on every interface by default.

All project services and blocking logic run inside Ubuntu. The Windows host is not an application host or firewall executor.

## 7. Current implementation baseline

The project repository is maintained at `~/projects/Main-Repo` on the Ubuntu VM. The working repository includes areas for Cowrie deployment, AI Core, controller, dashboard, models, data, reports, tests, and documentation.

The user has completed the Cowrie deployment and controlled-session capture work for Phases 5 and 6 and reports that the test sessions were recorded. Captured telemetry includes Cowrie session connection, login, command-input, and session-close events. The normalizer must still verify event names and available fields against the actual captured fixtures and pinned Cowrie image/version; do not rely only on this summary.

Phase 7—Event Normalizer and Session Manager—is the next implementation phase described by this documentation set.

## 8. Engineering and security principles

- Preserve working Cowrie deployment and controlled test evidence.
- Inspect the repository before creating or modifying code.
- Keep raw Cowrie logs as the unmodified evidence source; do not edit them in place.
- Treat sessions as incremental records that evolve as events arrive.
- Use Cowrie's session ID as the session key; never merge sessions by source IP alone.
- Preserve event provenance, timestamps, raw records, and ingestion identity.
- Do not silently invent missing fields, confidence values, timestamps, labels, or training preprocessing.
- Keep the RL agent unprivileged and separated from the controller and containment executor.
- Restrict firewall operations to the Ubuntu VM and fixed, validated operations.
- Do not grant Cowrie or the controller broad privileges, the Docker socket, or unrestricted shell execution.
- Do not commit `.env` files, credentials, Cowrie runtime logs, or other sensitive lab evidence.
- Report test results only when the tests have actually been executed.

## 9. Documentation precedence

Use the implementation playbook as the master phase and acceptance reference. Use `ARCHITECTURE.md` for the agreed system topology and data paths, `DECISIONS.md` for the current decision register, and the relevant phase specification for the implementation contract.

If repository reality, a phase specification, and the playbook conflict, do not silently choose one. Identify the conflict, show the affected files or requirements, and ask for a decision before making a change that would alter the approved design. The actual repository and captured test fixtures are authoritative for what currently exists; the playbook is authoritative for the intended phase requirements unless a newer explicit decision supersedes it.
