# auth.authbus

Canonical landing page for the AuthBus implementation and its composition boundary.

## Read order

1. [TECHNICAL.md](TECHNICAL.md) — stable module mission, contracts, authority boundaries and completion model.
2. [Current implementation](../../lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md) — executable source capability at the current candidate.
3. [Signed admission](../../../codex-rs/hepta-authbus/SIGNED_ADMISSION.md) — signature, durable replay and delivery semantics.
4. [Implementation dossier](../../../qualification/module-execution-dossiers/detail/auth.authbus.md) — operation/state-machine design and qualification cases.
5. [Trust/key lifecycle](TRUST_LIFECYCLE.md) — enrollment, rotation, revocation, external checkpoint and safe replay-epoch retirement.
6. [Agentd signed text host](../../../codex-rs/hepta-agentd/AUTHBUS_TEXT.md) — the narrow product-composed ingress.
7. [IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json) and [COMPOSITION.json](COMPOSITION.json) — machine-readable source/composition evidence.

## Ownership split

AuthBus deliberately spans existing owner boundaries rather than creating another
database or execution spine.

| Layer | Package | Responsibility |
| --- | --- | --- |
| Protocol/domain core | `codex-rs/hepta-authbus` | signed authentication, deny-all verification receipts, typed policy/quota/reservation/checkpoint records |
| Durable state owner | `codex-rs/hepta-evidence` | policy revisions, quota conservation, reservations, replay/outbox state, trust heads, replay checkpoints and guarded effect coordination |
| Host integration | `codex-rs/hepta-agentd` | protected trust projection and signed-text ingress/dispatch into the existing App Server queue |
| Qualification binder | `codex-rs/hepta-authbus-p1-3-qualification` | exact execution-provenance-bound negative qualification |

The Agentd path is product-composed only for signed text into an existing thread. The
guarded provider-effect path remains qualification-only until a named production
effect adapter is enrolled and the external acceptance gates close.

## State model

The effect-control sequence is:

`authorize + reserve (atomic) -> begin/recheck policy -> effect seam -> settle`

An unknown outcome becomes `Quarantined` and keeps quota held. It is released only by
a terminal reconciliation proving non-application, or converted to consumed quota from
observed terminal cost. Expiry alone never refunds an in-flight effect.

## Source-base note

`IMPLEMENTATION_MAP.json.sourceBase` is the shared repository-wide implementation-map
migration baseline. The map verifier requires all module maps to retain the same
baseline; it is **not** the current Git HEAD. Current candidate identity belongs in CI
source/native receipts and synthetic-merge receipts, not by independently rewriting
one module's shared map baseline.
