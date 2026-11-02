# Phase 4 Starter — Repository and Docker Compose Foundation

This starter follows Phase 4 of `Autonomous_Cyber_Deception_Full_Implementation_Playbook`.
It defines the repository layout and service/network boundaries. Only Cowrie is intended to be started in this phase.
The `application` Compose profile is deliberately disabled until AI Core, Controller and Dashboard images exist in later phases.

## 1. Place these files in the root of your Git repository

Extract/copy the contents of this package into the root of the shared project repository on the Ubuntu VM.
Do not create a nested `phase4_starter/` directory inside the repository.

## 2. Confirm the Ubuntu VM NIC addresses

Run inside Ubuntu:

```bash
ip -br addr
ip route
```

Set `COWRIE_BIND_IP` in `.env` to the Ubuntu honeypot-LAN address and `DASHBOARD_BIND_IP` to the Ubuntu management-LAN address. The defaults in `.env.example` are examples only. Do not use an address that is not assigned to the Ubuntu VM.

## 3. Create the required directories

```bash
mkdir -p deploy cowrie ai_core controller dashboard models \
  data/cowrie/var/log/cowrie data/cowrie/etc \
  data/app/state data/app/db reports tests docs
```

`data/cowrie/etc` is prepared for later configuration work but is intentionally NOT mounted in this initial Compose file. Mounting an empty directory over Cowrie's `/etc` hides the image's bundled defaults.

## 4. Create the local environment file

```bash
cp .env.example .env
nano .env
chmod 600 .env
```

Edit the two bind IP values before continuing. Keep `.env` private and never commit it. Commit `.env.example` only.

## 5. Review and validate Compose

```bash
sudo docker compose config -q
```

This validates the Compose document. It does not prove that the placeholder application images exist.

## 6. Prepare Cowrie's persistent directory permissions

The playbook identifies UID/GID 999 for the Cowrie image's runtime directory:

```bash
sudo chown -R 999:999 data/cowrie/var
```

Do not apply this ownership recursively to the entire Git repository.

## 7. Pull and start only Cowrie

```bash
sudo docker compose pull cowrie
sudo docker compose up -d cowrie
sudo docker compose ps
sudo docker compose logs --tail=100 cowrie
ls -la data/cowrie/var/log/cowrie
```

This starts the Cowrie service only. The AI Core, Controller and Dashboard are declared under the `application` profile and are not to be started until their implementations/images are ready.

## 8. Verify port binding and Docker networks

```bash
sudo docker compose port cowrie 2222
sudo docker network ls
sudo docker network inspect autonomous-deception_control_plane
sudo docker network inspect autonomous-deception_management_plane
```

The Cowrie published port must show the Ubuntu honeypot-LAN IP only. If Compose prefixes the network name differently, use the actual network name shown by `docker network ls`.

Internal API ports 8000 and 9000 are `expose`-only and are not published to the host. Dashboard port 8501 is bound only to the configured management-LAN IP when the dashboard image is implemented and started.

## 9. Git hygiene and team synchronization

```bash
git status --short
```

Check that `.env`, Cowrie logs, runtime data, model weights and generated reports are not staged. Commit the Compose foundation, `.env.example`, `.gitignore`, directory placeholders, and documentation. Push the Phase 4 branch and have the team pull the same commit.

## Design boundaries to preserve

- Cowrie logs persist on the Ubuntu VM and are mounted read-only into AI Core.
- AI Core can read Cowrie logs but must not be able to modify Cowrie logs, AI Core source code, model artifacts, Q-table, or report files owned by other components.
- The Controller and AI Core share the control-plane network.
- The Dashboard shares the management-plane network with AI Core; no internal API port is published to the attacker-facing NIC.
- The Cowrie service name is `cowrie`; later containers should use Docker DNS/service names rather than fixed container IP addresses.
- A custom Cowrie control adapter is a later implementation item. Stock Cowrie is not assumed to expose the custom action API.
- The firewall executor is a restricted Ubuntu `systemd` service, not a privileged Docker container and not a Windows-host firewall integration.
- `latest` is used only for the first smoke test. Before evaluation, record and pin a specific Cowrie version or immutable image digest, and pin Python dependencies in each application image.

## Phase 4 acceptance gate

Phase 4 is complete when:

1. The repository has the agreed directory structure.
2. `.env.example` is committed and `.env` is not committed.
3. `sudo docker compose config -q` succeeds.
4. The four service boundaries and two Docker networks are documented in `compose.yaml`.
5. Cowrie's persistent `var` directory is prepared with the required UID/GID permissions.
6. Cowrie can be pulled and started with only its port bound to the honeypot-LAN address.
7. Cowrie logs are persisted on the Ubuntu VM and are mounted read-only for AI Core.
8. Team members can pull the same Git commit and validate the Compose configuration.

Phase 5 performs the actual Cowrie telemetry/session test. Do not mark the Phase 5 telemetry milestone complete merely because the Compose foundation validates.
