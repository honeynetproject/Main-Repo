# Network and IP addressing plan (proposal)

## 1. VMware networks

Use two isolated virtual networks. Prefer VMware LAN Segments if available. Otherwise use dedicated custom private VMnets and disable the host virtual adapter for each network. Do not use Bridged networking. Ordinary Host-only networking normally includes the host; verify the host virtual adapter is disconnected.

| Network | Subnet | Members | Purpose |
|---|---|---|---|
| HONEYPOT-LAB | `10.77.10.0/24` | Ubuntu NIC 1, Kali NIC 1 | Attacker-to-Cowrie traffic only |
| MANAGEMENT-LAB | `10.77.20.0/24` | Ubuntu NIC 2, Analyst VM NIC 1 | Dashboard and analyst access only |

Disable DHCP on these segments and assign static addresses. These are proposed values; check for overlap before adoption.

## 2. VM addresses

| VM/interface | Address | Gateway | DNS |
|---|---|---|---|
| Ubuntu `ens33` (honeypot) | `10.77.10.10/24` | none | none |
| Kali `eth0` (attacker) | `10.77.10.20/24` | none | none |
| Ubuntu `ens34` (management) | `10.77.20.10/24` | none | none |
| Analyst VM `ens33` | `10.77.20.20/24` | none | none |

Actual Linux interface names must be checked using `ip -br addr`; do not assume they are `ens33` and `ens34`.

## 3. Allowed traffic

| Source | Destination | Port | Purpose |
|---|---|---:|---|
| Kali `10.77.10.20` | Ubuntu `10.77.10.10` | TCP 2222 | SSH to Cowrie only |
| Analyst `10.77.20.20` | Ubuntu `10.77.20.10` | TCP 8501 | Streamlit dashboard |
| Dashboard container | `ai-core` service | TCP 8000 | Read-only dashboard API |
| AI Core | `controller` service | TCP 9000 | Submit action/containment requests |
| Controller | Cowrie control adapter | Private internal TCP endpoint | Apply allowlisted per-session behavior change |
| Controller | Ubuntu firewall executor | Unix-domain socket | Narrow IP block/unblock operation |

Do not publish AI Core port 8000 or Controller port 9000 on the attacker-facing Ubuntu interface. Publish Cowrie only on `10.77.10.10:2222` and dashboard only on `10.77.20.10:8501`, once those interfaces exist. Firewall-executor communication is local to Ubuntu and is not a TCP service exposed to Kali.

## 4. Container IPs

Do not assign or hardcode container IPs in application configuration. Docker Compose service discovery provides stable names (`ai-core`, `controller`, `cowrie`, `dashboard`) while container IPs may change after recreation. Reserve/inspect Docker bridge subnets to avoid overlap with the VMware networks and any existing Docker networks.

## 5. Isolation checks

- Kali can connect to `10.77.10.10:2222` after Cowrie is deployed.
- Kali cannot connect to `10.77.20.10:8501`, `ai-core:8000`, or `controller:9000`.
- Analyst can reach `10.77.20.10:8501` after the dashboard is deployed.
- Ubuntu IPv4 forwarding is disabled; no route is configured between the two lab segments.
- Windows has no host virtual adapter attached to either project segment.
- Do not run tests against networks or systems outside the authorized lab.

## 6. Netplan example (Ubuntu)

Only use this after confirming the interface names with `ip -br addr`:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    ens33:
      dhcp4: false
      addresses: [10.77.10.10/24]
    ens34:
      dhcp4: false
      addresses: [10.77.20.10/24]
```

Apply with `sudo netplan try` then `sudo netplan apply`. Do not add a default route to either isolated interface. Disable forwarding and verify with `sysctl net.ipv4.ip_forward`.
