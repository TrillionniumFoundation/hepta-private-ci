# auth.authbus

This is the canonical navigation page for the AuthBus module. It separates the
target architecture, current executable source, operating profiles and
qualification evidence so that a target contract is not mistaken for a runtime
or production claim.

## Read in this order

1. [Technical development guide](TECHNICAL.md) — ownership, target contracts,
   data authority, failure model, security requirements and completion gates.
2. [Current implementation](../../lane-a-foundation/auth.authbus/CURRENT_IMPLEMENTATION.md)
   — the executable source boundary at the current candidate, including signed
   admission, durable replay/outbox, versioned policy, quota, reservation,
   managed issuer lifecycle and rollback-checkpoint APIs.
3. [Signed admission and durable replay](../../../codex-rs/hepta-authbus/SIGNED_ADMISSION.md)
   — message authentication, replay semantics, durable delivery and safe
   replay-epoch retirement.
4. [Implementation dossier](../../../qualification/module-execution-dossiers/detail/auth.authbus.md)
   — target operations, state invariants, BUS-01..04 and the exact implemented
   subset.
5. [Agentd signed-text profile](../../../codex-rs/hepta-agentd/AUTHBUS_TEXT.md)
   — the narrow existing-thread host integration. It is not a generic effect
   dispatcher.
6. [Implementation map](IMPLEMENTATION_MAP.json) — source anchors, delegated
   durable owner, host composition and claim boundaries.

The legacy already-verified replay contract remains documented separately in
[PREVERIFIED_REPLAY_V1.md](../../lane-a-foundation/auth.authbus/PREVERIFIED_REPLAY_V1.md).

## Ownership and composition

- **Semantic/source owner:** `auth.authbus`, with core types and cryptographic
  admission in `codex-rs/hepta-authbus`.
- **Durable physical state owner:** `kernel.evidence` /
  `codex-rs/hepta-evidence`; it stores replay, outbox, policy, quota,
  reservations, issuer lifecycle and rollback checkpoint state.
- **Narrow host integration:** `codex-rs/hepta-agentd` signed text into an
  existing private thread queue.
- **Effect composition:** the repository contains a qualification-only provider
  seam that authorizes and reserves before dispatch and settles only from
  observed terminal cost evidence. It is not a production provider caller.

## Claim boundary

Source presence and passing repository tests do not grant production activation,
external trust-root authority, an independently retained rollback checkpoint,
operator consent, independent acceptance, promotion or release. Exact-head and
deterministic synthetic-merge receipts are required for the source candidate;
the external gates remain separately governed.
