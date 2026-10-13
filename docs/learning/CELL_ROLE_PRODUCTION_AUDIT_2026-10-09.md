# Cell role production implementation audit — 2026-10-09

**Baseline:** PR #1450, `codex/cell-split-acceptance-gates`, pinned at
`951c101a967be74c14d3f826b3f10a80e5ce98fe`.
**Hardening:** `audit/cell-role-production-integrity-20261009`.
**Review standard:** implementation and source tests are not a target-host
qualification. Never infer production activation from a passing schema check,
locally generated digest, self-signed assertion or simulated fault.

## Qualification classes

- **S0 — typed contract:** versioned role, typed input/output/state,
  capability and resource policy, deny-all effect authority.
- **S1 — source-executable owner:** an actual role runtime/adapter, an owned
  artifact and state lifecycle, restart replay, rollback/tombstone, qualified
  negative paths and role-specific metrics, with immutable source identity.
- **H2 — production host:** deployment-attested artifact/CAS/registry,
  physically executed runtime and CNS/TaskFlow dispatch, clean-process restart,
  approved physical power-loss, rollback, retirement, old-generation rejection,
  signed host/independent observer evidence and CPU/GPU/NPU measurements.
- **P3 — independently retained:** preregistered no-change baseline, future
  observation windows, retention/negative-transfer/cost evaluation, both
  learning ledgers and TaskFlow causal replay; external activation governance.

Every semantic role has S0 contracts in `hepta-types` and adapters in
`hepta-cell-roles`. S1 implementation is **heterogeneous and partial**.
None of the eleven roles has a complete, separately verifiable H2+P3 packet
in this source candidate. The earlier DecisionCell split strict result is
still **0/8 externally qualified criteria**, not 0/11 source adapters.

## Role-by-role production implementation inventory

| Role | Present concrete code | Non-negotiable missing production boundary |
| --- | --- | --- |
| Representation | `hepta-neuron::NeuronRuntimeOutputV1`, `RepresentationAdapterV1`, `LearnedRoleRuntimeInputV1`, `DurableLearnedRoleOwnerV1` | Execute approved encoder/model on named host; bind model, normalization, OOD/missingness, measured resource receipt, signed checkpoint and complete forward replay |
| MemoryRead | `hepta-memory-retrieval::RetrievalReceipt`, `MemoryReadArtifactOwnerV1`, `DurableMemoryReadStateOwnerV1` | Live approved retrieval source, provenance and freshness revocation, tombstone observation, restart-safe evidence, independently observed long-horizon recall |
| Predictor | `hepta-bellman-operator::WorldModelPredictionV1`, `PredictorAdapterV1`, durable learned state owner | Actual pinned world-model execution; reject stale revision, preserve synthetic status and multi-step uncertainty; independently score NLL/Brier in future windows |
| Value | `hepta-ndu::NduEvaluationReceiptV2`, `ValueAdapterV1`, durable learned state owner | Execute pinned objective/risk model against full legal candidate set, join real external outcome, verify bias/risk/cost and negative transfer without self-selection |
| Decision | `DecisionCellOwnerV1`, calibrated intuition adapter, neuron state migration, TaskFlow split lifecycle | Real elected DecisionCell binary and route, fenced live cutover, host crash/power-loss recovery, old-generation rejection and independent retention |
| Evaluator | `EvaluatorAdapterV1`, OOD/calibrated disposition, role metric owner, generic learned state | Separate evaluator principal/key/controller, sealed holdout and signed future-window decisions; evaluator cannot promote its own candidate |
| Planner | `PlannerAdapterV1`, bounded frontier and replay, `DurableControlRoleOwnerV1` | Bind intent to real TaskFlow run/owner generation, durable backend submission and terminal evidence, bounded restart recovery |
| Router | `RouterAdapterV1`, CNS route ABI/fence, durable control owner | Actual CNS registry commit, old-route rejection, live dispatch/return receipt, load and latency observation under adversarial restart |
| ActionProposal | `ActionProposalV1`, deny-all proposal adapter, control backend submission contract | Real operations/effect owner identity, final-use authorization, idempotent effect terminal receipt; proposal itself must never execute |
| Plasticity | `UpdateProposalV1`, `PlasticityCandidateOwnerV1`, CAS registry and governed retain/quarantine | Real candidate materialization and training budget, independent evaluation before retention, immutable next bundle load, rollback/forgetting and future-window measurement |
| Communication | `CommunicationAdapterV1`, `CommunicationReplayReceiptV1`, durable control outbox | Real transport receiver and acknowledgement, backpressure/ordering/deduplication, expiry and fence under disconnect/restart, independent latency/cost evidence |

**Consequence:** An adapter's valid `CellStepReceiptV1` is not a proof that
the named model or downstream transport executed. `InMemoryCellProductionOwnerV1`
is only a deterministic test implementation. Production owners must obtain
source receipts from distinct, trusted runtime/registry/observer principals.

## Hardening implemented on the audit branch

1. **Signed checkpoint idempotency:** retries must match all material facts,
   including predecessor, host and independent observer bindings.
2. **No resurrection:** tombstoned state rejects both historical serving reload
   and rollback, including after a clean reopen. Tombstone generation cannot
   precede a previously committed generation.
3. **Replay continuity:** strict per-cell contiguous sequence, predecessor
   existence, signed owner identity, operation uniqueness, monotonic generation,
   duplicate tombstone and duplicate active-head rejection.
4. **Failed write isolation:** invalid first commits do not create ghost
   histories or enable a later tombstone for an uncommitted cell.
5. **Active serving state:** `reload_active` rejects inactive historical
   states and superseded generations, even for byte-identical state digests.
   `reload` remains audit-capable while refusing tombstoned cells.
6. **Role-specific reopen:** the generic learned owner and MemoryRead owner
   both verify signed snapshot contents against the actual cell, schema and
   active generation, not merely an old digest or owner key.
7. **Genesis exclusivity:** initial state publication will not overwrite an
   existing durable checkpoint with a fresh empty in-memory owner.
8. **Six-role cognitive frontier:** closure receipt verification recomputes
   the canonical digest and rejects mutated final frontier, generation,
   membership receipts and commitment.
9. **Evidence origin:** in-memory model refuses
   `RoleQualificationEvidenceOriginV1::TargetHostMeasurement`; synthetic
   fault and recovery receipts remain explicitly non-production.

Regression tests are added alongside these source changes, but **none of the
new tests should be marked passed until run on the exact branch SHA**.

## Acceptance blockers (all eleven roles)

A deployment-specific implementation must bind
`CellSplitTargetHostRuntimeV1` to **actual** CAS/parameter registry, CNS route
registry/fence/dispatch, checkpoint/owner process, approved fault injector,
TaskFlow run, tombstone store, hardware attestor, signed learning ledger and
independently controlled observer. Missing adapters must not be simulated by
digest-producing fixtures.

The externally retained packet must include at least:

- `CellSplitSignedTargetHostEvidenceV1` and verified
  `CellSplitTargetHostProductionReceiptV1`;
- artifact write/load, generation/CAS/registry and state commit receipts;
- live CNS cutover and dispatch, route fence, restart, approved power-loss,
  governed rollback, tombstone and no-resurrection witnesses;
- real CPU/GPU/NPU measurement samples with host attestation;
- signed TaskFlow and *both* learning-ledger replay frontiers;
- an independently signed preregistered no-change baseline and at least two
  future observation windows, including retention, coverage, negative
  transfer, failure, cost and rollback outcomes; and
- an isolated clean-process replay verifier proving every binding.

No host, credentials, fault injector, deployment route, future-window data or
independent signing authority has been supplied in this code review.
**Do not issue production-qualified receipts or activate these roles from
source-only tests.**

## Source verification commands (not yet a pass report)

From `codex-rs/`, on one pinned commit and locked toolchain:

```sh
cargo fmt --all -- --check
cargo test --locked -p codex-hepta-cell-roles
cargo test --locked -p codex-hepta-learning-artifacts
cargo test --locked -p codex-hepta-neuron
cargo test --locked -p codex-hepta-memory-retrieval
cargo test --locked -p codex-hepta-bellman-operator
cargo test --locked -p codex-hepta-ndu
cargo test --locked -p codex-hepta-intuition
```

After these tests, rerun target-host qualification **separately**; do not
reuse CI artifacts from PR #1450's prior head as proof for this branch.
