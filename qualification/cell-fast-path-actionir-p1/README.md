# Cell FastPath ActionIR P1 (shadow qualification)

P1 upgrades the P0 typed candidate contract into a pure qualification gate.
It checks whether a candidate is eligible for observation under an exact,
already-resolved authorization envelope. It never calls Guardian, claims a
TaskFlow operation, obtains a grant, executes ActionIR, or commits an external
effect.

## Inputs bound by the gate

- `AuthorizationEnvelopeV1`: app identity, typed Guardian authorization digest,
  capability allow-set, capability scope digest, policy digest, body generation,
  revocation epoch, and expiry.
- `GenerationBindingV1`: Stem/head/objective/artifact/runtime tuple digests,
  ABI, target, body generation, and snapshot ID. The runtime tuple digest is the
  projection point for the existing Neuron model/runtime/device receipt.
- `ResourceBudgetV1` and `ResourceObservationV1`: operation count, wall-clock
  deadline, CPU/GPU nanoseconds, peak memory, and bytes touched. Every observed
  dimension is checked against the budget.
- `PreconditionCheckV1`: one checked precondition for every ActionIR operation.
  A missing or failed check rejects the candidate before any effect admission.
- `ReplayIndexV1`: replay key includes candidate, IR, artifact, authorization,
  revocation, pre-observation, and ordered idempotency keys. Same payload is a
  duplicate no-op; same key with a different payload is a conflict.
- `ParentFallbackV1`: at most one older-generation parent with the same app,
  Stem and objective identity. Invalid or absent parents produce
  `NO_SAFE_FALLBACK` on rejection.

## Decision semantics

The qualifier returns deterministic reason codes in a fixed priority order.
The only admission result is `ADMIT_SHADOW`; all other results are fail-closed
and require fallback. `cpu_non_effect` additionally rejects click, keyboard,
typing, scroll, focus, and clipboard-write operations with
`EFFECT_REQUIRES_GUARDIAN`. Effect-shaped ActionIR may still be recorded as a
planning candidate in the broader `shadow` mode, but this never means an effect
was executed.

Every decision embeds a P0 shadow receipt with:

```text
authority = DENY_ALL
executed = false
effect_committed = false
```

## Owner boundary for a future P2/P3 adapter

The repository already separates the relevant authorities:

1. `neuron.runtime` owns temporal state/checkpoints and must not execute tools
   or issue capabilities.
2. `inference.control` authenticates exact model/input/runtime receipts.
3. Guardian resolves the current app/review authorization; a stale or missing
   score is not approval.
4. TaskFlow's local boundary is deny-only.
5. Agentd/registered effect owner constructs `OperationIntentV1` or
   `AuthorizedEffectIntent`, obtains a signed final-use grant independently,
   and owns dispatch/reconcile.

The future adapter must therefore consume a qualified ActionIR candidate and
construct the trusted owner intent inside Agentd/effect-owner code. It must not
let the Cell choose the provider, destination, final-use scope, grant, or
TaskFlow fence, and it must not add a second direct socket.

## Evidence boundary

This lane proves deterministic qualification behavior with synthetic contracts.
It is not real model efficacy, not a real Guardian approval, not a TaskFlow
execution, and not a CPU/GPU performance measurement. Hosted qualification is
still required against the existing Rust runtime/receipt, Guardian review
scope, Agentd operation/reconcile, and TaskFlow negative tests before any local
non-effect runtime is enabled.
