# auth.authbus

Canonical landing page for AuthBus development and qualification.

## Read in this order

1. [TECHNICAL.md](TECHNICAL.md) — module ownership, target contracts, completion model and current capability table.
2. [Current implementation](../../lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md) — what the current source candidate actually executes.
3. [Implementation map](IMPLEMENTATION_MAP.json) — source roots, native operations and cross-owner composition.
4. [Implementation dossier](../../../qualification/module-execution-dossiers/detail/auth.authbus.md) — authorize/reserve/settle state-machine design and qualification cases.
5. [Signed admission](../../../codex-rs/hepta-authbus/SIGNED_ADMISSION.md) — authentication, durable replay and outbox semantics.
6. [Agentd signed-text host](../../../codex-rs/hepta-agentd/AUTHBUS_TEXT.md) — the narrow product caller and trust-file operating procedure.
7. [Preverified replay V1](../../lane-a-foundation/auth.authbus/PREVERIFIED_REPLAY_V1.md) — legacy in-process replay contract; not authentication or effect authority.

## Ownership and composition

| Surface | Owner / path | Responsibility |
| --- | --- | --- |
| Domain core | `auth.authbus` / `codex-rs/hepta-authbus` | signed-message authentication and pure policy/quota/reservation types |
| Durable state | `kernel.evidence` / `codex-rs/hepta-evidence` | replay, outbox, policy revisions, quota ledger, reservations, settlement, reconciliation and restore-checkpoint binding |
| Narrow host | `runtime.agentd` / `codex-rs/hepta-agentd` | signed text ingress into an existing private thread queue |
| Qualification | `codex-rs/hepta-authbus-p1-3-qualification` + Lane A CI | exact-source execution provenance and negative qualification |

Cross-owner placement is intentional: AuthBus does not create a second SQLite owner. The EvidenceStore remains the durable owner and Agentd remains a host, not a source of policy or quota truth.

## Claim boundary

The source candidate implements authorization/quota/reservation primitives, but the only current product composition is the narrow signed-text ingress. A provider, secret, network or filesystem effect caller has not yet been registered through the new control surface. Production implementation, activation, operator acceptance, promotion and release therefore remain separate gates.
