# DecisionCell target-host and future-window evidence runbook

This runbook is the execution boundary for the final DecisionCell split gate.
It describes the evidence packet that a deployment owner must produce on a
real target host. It does not manufacture a production receipt from a local
test, a virtual clock, a source-simulation report, or a digest-only manifest.

The repository currently supplies the typed ingestion and replay APIs. It does
not supply a generic command that can discover a target host, perform a CNS
route cutover, inject a power loss, obtain hardware attestation, or collect
future-calendar outcomes. Those operations remain the responsibility of the
deployment owner and an independently controlled observer.

## Fail-closed preflight

Stop before running the lifecycle when any of the following is unavailable:

* a named deployment host and its attestation evidence;
* the parent artifact, committed registry generation, CAS namespace and
  predecessor rollback reference;
* a host signing key and at least one independently controlled observer key;
* a live CNS/router owner that can return dispatch and old-route-rejection
  receipts;
* a fault-injection mechanism that produces a power-loss witness;
* real CPU/GPU/NPU counters for the selected host class;
* an immutable no-change baseline and a frozen evaluation plan;
* an independent observer that can collect at least two future windows after
  the plan is frozen; or
* a durable learning-ledger namespace and independently retained witness.

If any item is missing, the run may produce a diagnostic report with
`productionEvidence=false`, but it must not call the production evidence gate
or write a `CellSplitTargetHostProductionReceiptV1`.

The current source-simulation harness intentionally remains in that state. For
the ledger-only host measurement fixture:

```sh
HEPTA_TARGET_HOST_ID=<actual-host-id> \
  cargo run --locked -p codex-hepta-learning-ledger \
  --example target_host_qualification > ledger-measurement.json
```

This command records source/tree/binary identity, append and reopen costs, and
RSS on the machine where it runs. Its output keeps power-loss,
longitudinal-efficacy and production activation false. A supplied host ID does
not turn the fixture into target-host evidence.

## Immutable inputs

The deployment owner freezes and retains the following before the first child
is activated:

| Input | Owner/API | Required binding |
| --- | --- | --- |
| Parent and child split plan | `CellSplitV1`, `CellSplitGovernedPlannerV1` | Parent identity, generation, scope, lineage, route ABI, child bundle and rollback predecessor |
| Proposal source | `CellSplitProposalSignalV1` | Telemetry observation, policy digest, parent generation and observation sequence |
| Artifact/CAS manifest | learning.artifacts / artifact owner | Parent predecessor, child bundle, CAS receipts, writer lease and registry commit |
| TaskFlow run | `CellSplitTaskFlowJournalOwnerV1` | Run ID, owner generation, lifecycle definition and verified event-chain head |
| Baseline/evaluation plan | `ProductFrozenEvaluationPlanV1` | No-change baseline, objective, dataset, metric roles, temporal plans and final holdout digest |
| Trust distribution | learning-ledger trust owner | Host, generator, evaluator, timing observer, resource observer and selector roles; key lifetime, scope, epoch and revocation |
| Ledger namespace | `CellSplitLearningLedgerV1` plus the regular causal `LedgerWriter` | Nonzero binding, authorized files, directory handles, independent witness and retained anchor |

`CellSplitLearningLedgerV1` is the durable owner for lifecycle facts. It is
not a substitute for the regular causal learning ledger: decisions, outcomes,
baseline rows, retention, negative transfer and unlearning facts still belong
to the authenticated `LedgerWriter` path. The final packet must bind both
owners to the same split/evaluation identity.

## Target-host lifecycle

The host records an append-only
`CellSplitTargetHostEvidenceV1` payload using
`CellSplitTargetHostEvidenceRecorderV1`. The payload is signed only after the
host has completed the operations below:

1. **Artifact load.** Load the committed child artifact and verify the parent
   predecessor, child generation and target-host attestation.
2. **Route cutover.** Activate the child input/output/termination ports through
   the live CNS/router. Retain a dispatch receipt, route ABI and old-route
   rejection receipt.
3. **Restart recovery.** Restart the serving process and reconstruct registry,
   CAS, TaskFlow, route and cell state from durable storage. Retain the exact
   recovered generation and state digest.
4. **Power-loss recovery.** Use the approved fault-injection mechanism. A
   process exit, `SIGKILL`, VM pause or test panic is not a power-loss witness.
   Retain the fault-injection receipt and post-recovery replay receipt.
5. **Rollback.** Restore the predecessor through the governed rollback owner,
   advancing the runtime generation. Retain the rollback receipt and verify
   that the old child route is fenced.
6. **Tombstone.** Commit the parent/child retirement tombstone through the
   registry owner and retain the tombstone receipt.
7. **No resurrection.** Start a clean process, reload the namespace, and prove
   that the retired route, artifact and generation cannot be selected again.

Resource samples may be interleaved with this lifecycle. Every sample must
identify CPU, GPU or NPU hardware, model, measurement source, attestation
digest, sample count, latency, memory, communication, training and migration
counters. Sources containing `simulation` or `fixture` are rejected.

The verifier is deliberately narrow:

```rust
let receipt = verify_cell_split_target_host_evidence_json(
    &signed_envelope_bytes,
    &externally_pinned_trust_policy,
)?;
assert!(receipt.production_gate_passed);
```

`CellSplitTargetHostEvidenceAdapterV1::ingest_json` is equivalent. The trust
policy is supplied out of band; public keys embedded in the JSON are not
trusted merely because they appear in the envelope. The envelope must contain
host and independent observer signatures over the same canonical payload and
all required lifecycle events in replayable order.

## Future-window collection

Future-window collection starts only after the frozen plan has been registered
and the generator has signed its exact plan digest. The independent timing
observer creates `LongitudinalTimeEvidenceV1` with:

* the frozen Unix-microsecond timestamp;
* two to thirty-two distinct window IDs;
* snapshot IDs already present in the frozen bundle;
* non-overlapping start/end times after the freeze;
* a preregistered minimum duration for every window;
* nonzero observation counts;
* distinct observed source-cut digests; and
* the observer's `SignedLearningEvidenceV1` signature over
  `future_window_signing_payload_v1`.

The observer must be independent from the generator, evaluator and resource
observer by principal, credential chain, signing key and controller. The
window end must be before both the observer's signed issuance time and the
trusted `now_unix_micros` supplied to the verifier. IDs with future-looking
names or synthetic timestamps do not satisfy this gate.

The production evaluation sequence is:

```text
freeze product plan
  -> consume final holdout through FencedFinalHoldoutOwnerV1
  -> release sealed candidate/baseline observations
  -> evaluate candidate and no-change baseline
  -> collect independent observed future windows
  -> persist signed qualification decision
  -> evaluate_cell_split_long_horizon_v1
  -> append lifecycle evidence to TaskFlow and learning ledger
```

The typed evaluation entrypoint is:

```rust
let evaluation = evaluate_cell_split_long_horizon_v1(
    CellSplitEvaluationRequestV1 {
        split: &split,
        profile: &profile,
        temporal: &product_temporal_receipt,
        qualification: &product_qualification_receipt,
        bundle: independent_bundle,
        roles: metric_roles,
        evidence: &signed_evaluation_evidence,
        timing: &longitudinal_time,
        resources: &target_host_resource_receipt,
        resource_evidence: &signed_resource_observer_evidence,
    },
    &learning_trust_verifier,
    trusted_now_unix_micros,
)?;
```

The call rejects local resource origins, missing retention or negative-transfer
support, mismatched no-change baselines, unsealed temporal receipts, role
collisions, missing future windows and resource observations that are not
bound to the target-host sample. It returns an evaluation receipt; it does not
select, activate or retire a child.

## Learning-ledger witness and replay

For each lifecycle transition, append a typed
`CellSplitLifecycleRecordV1` to `CellSplitLearningLedgerV1` with:

* the split and record identity;
* monotonic lifecycle sequence and state transition;
* evaluation/target-host evidence digest;
* current state digest;
* TaskFlow event digest; and
* causal support digest from the regular learning ledger.

The append must use the exact current chain predecessor. The owner fsyncs the
event and advances its independent witness before returning an append receipt.
After the host process is restarted, call `CellSplitLearningLedgerV1::recover`
with the same binding and independently retained witness; a ledger-ahead or
witness-behind state must fail closed as an unwitnessed tail.

The replay packet must contain, at minimum:

```text
proposal signal
governed CellSplitV1 plan
TaskFlow definition/run/event chain
artifact manifest and CAS receipts
target-host signed evidence envelope
target-host production receipt
ProductTemporalEvaluationReceiptV1
ProductQualificationReceiptV1
CellSplitLongHorizonEvaluationReceiptV1
regular learning-ledger snapshot/anchor
CellSplitLearningLedgerV1 anchor and witness frontier
independent future-window observer evidence
```

The clean-room verifier then performs, in order:

```text
verify target-host envelope
  -> recover TaskFlow journal
  -> recover CellSplitLearningLedgerV1 and witness
  -> verify regular learning-ledger snapshot and causal support
  -> verify product qualification and future-window timing
  -> verify CellSplitLongHorizonEvaluationReceiptV1
  -> replay proposal -> evaluate -> canary -> retain/quarantine -> retire/rollback
  -> verify registry generation, route fence, tombstone and no-resurrection
```

There is currently no repository-wide `cell-split-replay` executable. Until a
deployment owner supplies one that reads the retained packet, the available
commands are source/negative-path checks only:

```sh
cargo test --locked --manifest-path codex-rs/hepta-learning-ledger/Cargo.toml --lib
cargo test --locked --manifest-path codex-rs/hepta-intelligence-eval/Cargo.toml --lib
cargo test --locked --manifest-path codex-rs/hepta-operator-acceptance/Cargo.toml --lib
```

These commands must pass for source qualification, but they do not read a
target-host envelope, exercise a live route, wait for future calendar windows,
or create a production receipt. A production replay command must be supplied
by the deployment owner and must fail closed unless it can independently read
and verify every artifact listed above. Its successful output must include the
verified target-host receipt, both ledger witness frontiers, the TaskFlow
replay head, the future-window observer digest and the terminal lifecycle
state. A command that reports only content digests is not sufficient.

No single digest is sufficient. A missing owner, missing independent witness,
unknown write result, or missing future window leaves the run unqualified and
must leave the durable lifecycle in `EvaluationPending`, `Quarantined` or
`RolledBack` according to the recorded evidence.

## Acceptance output

The deployment owner may submit an acceptance packet only when all of these
artifacts are externally retained and reproducible:

1. host/observer-signed target-host envelope and
   `CellSplitTargetHostProductionReceiptV1`;
2. artifact, CAS, registry and live dispatch receipts;
3. restart, power-loss, rollback, tombstone and no-resurrection witnesses;
4. CPU/GPU/NPU resource samples with real hardware attestation;
5. independently signed future-window timing and metric evidence;
6. no-change baseline, retention, task coverage, negative transfer and failure
   metrics;
7. regular learning-ledger decision/outcome snapshot and anchor;
8. `CellSplitLearningLedgerV1` lifecycle journal and witness frontier;
9. TaskFlow replay journal; and
10. a clean-process replay report with all bindings checked.

Until that packet exists, the strict external evidence result remains **0/8**.
Running repository tests or the source-simulation harness can qualify source
boundaries and negative paths, but cannot advance the production result.
