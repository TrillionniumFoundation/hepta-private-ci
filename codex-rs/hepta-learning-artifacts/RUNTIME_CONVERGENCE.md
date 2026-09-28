# learning.artifacts runtime convergence — 2026-09-28

## Candidate and truth boundary

This work is on `work/learning-artifacts-runtime-convergence-20260928`, PR #1152.
It inherits R4 `3d0d744fe572c25ea9024ad26bcb9de07a4df022` against the inspected
main `a126987b84737dbc2ee2592442a314117bddb4a2`. Inherited durable drain,
withdrawal high-water, recovery/input checks and qualification tooling are not
new implementation by this change. Main is not updated by this branch.

The current protocol is LearningArtifactOwnerService / LearningArtifactOwnerHost,
scoped V3 admission, immutable V1 compatibility snapshots and signed CURRENT.
Earlier conversational references to `submit`, `attempt_id`, GraphSpace and an
`artifact_test_hooks` Cargo-feature failure do not describe this fixed source.
They must not be used as implementation or verification evidence.

## Canonical identity and live membership

`RequestIdentityVerifier::verify` checks full payload size/digest, V3 admission
integrity and the configured head-key signature before returning a domain-separated
request diagnostic digest. It covers operation ID, admission digest, predecessor,
payload digest/length and the complete signed-head envelope. Retry observation
`now` is excluded; live time/lease/withdrawal checks still run where required.

The existing durable publication intent and phase/state digests remain the replay
protocol. The new diagnostic digest does NOT replace checkpoint checks, migrate
old records, or prove that every pre-witness signature field was independently
persisted at Prepared. Complete durable-envelope migration remains open.

Live `validate_artifact_publication_v3` now rechecks authoritative dataset
membership, not only a caller-supplied digest and current chain head. A resealed
public DTO cannot admit an already withdrawn dataset. Historical integrity and
DENY_ALL terminal-receipt replay remain separate and do not renew authority.
No durable format, signature verification, fsync or existing fault test was removed.

## Runtime observations and error handling

`LearningArtifactOwnerService::diagnostics` returns bounded process-local counters
and timings from actual owner calls. Fixed stages cover successful open, identity,
checkpoint reconciliation, payload plus checkpoint, registry plus checkpoint,
witness plus checkpoint, acknowledgement checkpoint, withdrawal installation,
durable drain and the complete publish call. Timings include failed calls.
Successful startup has one observation; failed startup has no returned service
and must be observed by its embedding host. No hidden histogram or percentile
claim is derived from count/sum/max.

Pending, drain and withdrawal-durability-block durations are observation windows
in this process. `pending_predates_process` / `drain_predates_process` explicitly
prevent mistaking a restarted timer for total historical age. There is no
unbounded label map, per-operation metric cache or new durable metric writer.

`pinned_bytes` and `pending_physical_erasure_bytes` are unknown (`None`), not zero.
This service does not own an authoritative pin/refcount/physical-erasure observer.
Counts for owner/context rejection, owner contention, capacity, withdrawal blocks,
identity rejection and recovery reconciliation failure are not general health flags.
The original typed errors remain available; stable codes never authorize retrying
an unknown operation under a new identity.

Operational action examples:

| Code / observation | Required interpretation |
| --- | --- |
| `artifact.identity_conflict` | Resolve changed input/identity; do not allocate a new ID to bypass a conflict. |
| `artifact.owner_context`, `artifact.authority_stale` | Reconcile owner/trust/lease context before an authorized retry. |
| `artifact.withdrawal_frontier`, `artifact.dataset_withdrawn` | Obtain authoritative state; never lower a withdrawal floor. |
| `artifact.persistence_unknown`, `artifact.recovery_required` | Reconcile the same operation; a response failure is not proof of no effect. |
| `artifact.capacity` | Stop new admission and use a qualified retention/migration procedure; do not clear history. |
| Increasing observed pending/drain time | Investigate checkpoint and durable-control state, preserving the writer fence. |
| Unknown pin/erasure bytes | Obtain an owner measurement; absence of telemetry is not successful erasure. |

## Phase measurement producer

`artifact_owner_phase_measurement_smoke` executes four independent real local-file
publications of a seven-byte fixture. Set `HEPTA_ARTIFACT_PHASE_OUTPUT` to a fresh
output directory to retain a create-only CSV. This is a measurement-producer smoke
test, not a production workload, capacity curve, physical power-loss test or SLO.

The read-only command below binds the actual checked-out commit and Git blobs,
checks test-source identities, and optionally validates the complete native CSV:

```sh
python3 scripts/hepta_artifact_convergence.py \
  --source "$(git rev-parse HEAD)" \
  --phase-dir "$HEPTA_ARTIFACT_PHASE_OUTPUT" \
  --out "$RUNNER_TEMP/artifact-delivery-index.json"
```

The report uses exact nearest-rank p50/p95/p99 on the four retained samples; p95
and p99 are the sample maximum. It rejects missing/duplicate/foreign/negative or
oversized input. A valid CSV and source index are not authenticated CI provenance
or proof that every native/merge gate passed. Review them with the existing
qualification bundle and independently authenticated Actions run/attempt.

Separate physical syscall timings, cold pinned read/hash, RSS, write amplification,
large-history capacity curves, real target-host SLOs and long-lived retention
remain unmeasured by this fixture. No larger cache or weakened persistence was
introduced as a speculative performance optimization.

## Verifiable delivery index

| Capability | Initial source commit / current identity | Entry | Regression source | Actual-result boundary | Remaining limit |
| --- | --- | --- | --- | --- | --- |
| Live withdrawal membership | `11bb1ad9b0bb4fd9dd923d1b38a4a7d1536fe989`; current Git blob in qualification | `validate_artifact_publication_v3` | `admission_v3/tests/admission_membership_tests.rs` | Test source added; current native result must come from Actions | Published CURRENT and already-issued views need separate withdrawal propagation. |
| Canonical diagnostic identity | `ec55f87b2b067d2d0275988c184120dd39c472a2`; generated index binds current commit/blob | `RequestIdentityVerifier::verify` | `owner/observation_tests.rs` | No native pass inferred from source | Not a new durable-envelope deduplication format. |
| Owner observations and error codes | `ec55f87b2b067d2d0275988c184120dd39c472a2`; generated index binds current commit/blob | `LearningArtifactOwnerService::diagnostics`, error `code` | `owner/diagnostics.rs`, `owner/observation_tests.rs` | No native pass inferred from counters or source presence | Process-local age; pin/erase measurements remain unknown. |
| Phase measurement producer | Current test blob and tested commit in generated index | `artifact_owner_phase_measurement_smoke` | `owner/observation_tests.rs` | Requires actual native CSV, not fixture data from Python | Tiny hosted fixture, no production SLO or capacity qualification. |
| Delivery/measurement verifier | Current script Git blob in implementation map | `hepta_artifact_convergence.py` | `test_hepta_artifact_convergence.py` | Eight local Python regressions passed on authored source; synthetic fixtures/temporary Git only | Not Rust runtime execution or independent acceptance. |
| Durable drain and withdrawal floors | Inherited R4, not new work | `begin_drain_durable`, `DurableWithdrawalFloor` | Retained R4 service/floor/process suites | Must rerun on final exact source and ordered-parent merge | Independent external floor and real filesystem power loss remain separate. |

Source preparation is an explicit, separately named branch-only workflow. It
formats owned Rust and refreshes implementation-map blobs/tests without changing
historical sourceBase, previous obligations or acceptance/activation/release flags.
It may produce a new commit; that new commit must receive fresh read-only
qualification. A source-preparation success is never a qualification success.

## A–C remaining acceptance ledger

A is not closed until current exact-head/actual-base native build, strict lint,
format, source binding, complete test discovery/execution and inherited fault tests
actually pass. The existing Lane E and repository required checks remain mandatory.
The new diagnostic digest does not complete durable full-envelope migration.

B remains open for withdrawal-to-CURRENT updates and already-issued-view policy,
authoritative pin accounting, structured quarantine/retention/compaction and truthful
physical-erasure confirmation. The local floor is not a substitute for these.

C remains open for authenticated deployed host/transport, independently provisioned
keys and external restart/withdrawal/stop floors, capability-protected ancestors,
real target-filesystem power-loss evidence, backup/migration rehearsals and actual
long-term resource/SLO measurements. No deployment, independent acceptance,
activation, selection, promotion or release is claimed.
