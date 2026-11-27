# Cell role production qualification

The role crate provides shared contracts and owner-facing qualification seams.
It does not create one neural runtime per role, grant effect authority, or
turn a repository fixture into a target-host receipt.

## Maturity levels

### L0: semantic contract

Every role has a `CellRoleV1`, capability profile, typed ports, persistence and
update mode, owner module, fallback role, evaluation profile, and immutable
`CellStepReceiptV1`. `CellDefinitionV2` binds identity, generation, scope,
lineage, parameter bundle, state schema, and evidence owner.

### L1: executable qualification

Learned or stateful roles add a runnable owner, artifact/reload receipt, state
replay, role-specific metrics, no-change baseline, clean transfer, bounded
fault exercise, and a reproducible report. Control-plane roles use the same
receipt boundary but qualify deterministic replay, generation fences, fallback,
idempotency, and failure recovery instead of training a second model.

`RoleQualificationHarnessV1` is the shared seam for this level. An owner
provides `reload_artifact`, `step`, and `exercise_fault`; the harness joins the
owner receipts with the frozen metric profile and an independent evaluator
receipt. The harness has no `accepted`, `retained`, or `production_qualified`
field.

### L2: target-host production qualification

An external owner must provide the real artifact/CAS/registry publication,
live route or effect dispatch, restart and power-loss witnesses, rollback,
tombstone, no-resurrection, non-simulation resource samples, and host plus
independent observer signatures. The target-host evidence verifier, learning
ledger, and CNS owner decide whether those facts are admissible for activation.

Changing an origin label to `TargetHostMeasurement` cannot create L2 evidence.

## Role-specific owner boundary

| Role group | Roles | Production evidence focus |
| --- | --- | --- |
| Stateful learned | Representation, MemoryRead, Predictor, Value, Decision, Plasticity | artifact/reload, state transform, no-change baseline, role metrics, long-horizon outcome, rollback and resource cost |
| Control plane | Planner, Router, Communication | typed owner dispatch, bounded replay, generation/fence, fallback, ordering/backpressure, stale request rejection |
| Effect boundary | ActionProposal | typed proposal, preconditions, effect classification, expiry, idempotency, downstream owner receipt; proposal never executes the effect |
| Independent governance | Evaluator | proposer/evaluator separation, false accept/reject, OOD, retention/rollback precision, signed observer evidence |

## Minimum cognitive closure

`compose_cognitive_closure_v1` verifies the ordered frontier:

```text
Representation -> MemoryRead -> Predictor -> Value -> Decision -> Evaluator
```

The function consumes immutable step receipts and rejects missing, reordered,
stale, cross-generation, cross-scope, rejected, or failed steps. It does not
execute a model, publish an artifact, activate a route, or authorize an
effect.

## Current implementation boundary

The repository now contains the shared L0/L1 role seams, a formal MemoryRead
artifact/evaluation owner, the minimum cognitive-closure receipt, and replay or
fence qualification for Planner, Router, ActionProposal, and Communication.
These are source and repository qualification artifacts. Real target-host
execution, hardware measurements, external signatures, and independent future
calendar windows remain required for L2.
