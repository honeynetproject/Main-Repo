# RL state and action contract (retained proposal values)

## State: six discrete features, 144 possible states

| Feature | Values | Phase 0 rule |
|---|---|---|
| Threat tier | `LOW`, `MEDIUM`, `HIGH` | Derive from a documented risk score and behavioral evidence; not from classifier confidence alone |
| Session phase | `RECON`, `EXPLOIT`, `PERSIST` | Map seven classifier labels into three phase values; define tie/unknown handling |
| Attacker profile | `AUTOMATED`, `HUMAN` | Treat as behavioral heuristics, not verified identity; use rolling command rate/patterns |
| Behavioral risk | `SAFE`, `RISKY` | Based on observed attempts/events, not proof that a simulated command changed the real VM |
| Engagement depth | `SHALLOW`, `DEEP` | Retain proposal rule: shallow if duration <60s OR commands <5; deep if duration >=60s AND commands >=5 |
| Model confidence | `LOW`, `HIGH` | Retain initial threshold 0.7, but define how it is computed for multi-label predictions and fallback results |

State count = 3 × 3 × 2 × 2 × 2 × 2 = 144.

## Action IDs: retain nine proposal actions

| ID | Name in proposal | Intended effect |
|---:|---|---|
| 0 | `NO_OP` | Maintain current profile |
| 1 | `RETURN_TO_SAFE_PROFILE` | Restore baseline low-interaction profile |
| 2 | `PROFILE_A_DEFAULT_LOW_INTERACTION` | Standard baseline persona |
| 3 | `PROFILE_B_HIGH_INTERACTION_AGGRESSIVE` | More responsive, richer interactive persona |
| 4 | `PROFILE_C_DELAYED_RESPONSE` | Apply bounded response delay |
| 5 | `PROFILE_D_DECOY_RICH` | Present approved fake files/data |
| 6 | `PROFILE_E_VERBOSE_LOGGING` | Enable additional internal logging/output; note this may not itself increase attacker engagement |
| 7 | `PROFILE_F_MISLEADING_BANNER` | Use an approved simulated banner profile |
| 8 | `PROFILE_G_CUSTOM_COMMAND_RESPONSES` | Use approved command-specific response templates |

The RL agent may request only these nine actions. The controller validates preconditions and applies allowlisted behavior. Containment is not an RL action; the Safety Guard/controller owns it independently.

Before implementation, define an action registry for each ID: supported Cowrie hook, parameters, preconditions, per-session scope, timeout, rollback and expected success event. An action is not considered implemented merely because its ID exists in the Q-table.
