# auth.authbus implementation and verification matrix

This matrix binds security claims to source, fault tests and immutable execution evidence. It is descriptive only for the commit that contains it. A claim is qualified only when `.github/workflows/authbus-authority-qualification.yml` finishes successfully for both the exact pull-request head and its deterministic synthetic merge candidate, and the uploaded receipt names those exact Git objects. A run for another SHA, a skipped job, a source-mutating workflow, or a green result obtained before the final documentation commit is not evidence for this candidate.

## Result contract

| Public result | What the caller may infer | Required caller action |
| --- | --- | --- |
| `Ok(value)` | The authoritative SQLite mutation committed and the independent checkpoint was published and locally promoted. | Continue with `value`. |
| Deterministic domain error | The requested operation was rejected before commit. `mutation_disposition()` is `NotCommitted`. | Correct the request or stop; do not reinterpret it as transient storage failure. |
| `AuthorityUseBlocked` | Checkpoint/recovery admission failed before the requested operation future was polled. | Stop new authority use and repair/reconcile the owner state. |
| `CheckpointReconciliationRequired` | The SQLite mutation committed, but independent checkpoint publication or promotion did not complete. `mutation_disposition()` is `CommittedNeedsReconciliation`. | Reconcile the checkpoint and query by stable operation identity before any retry. |
| `MutationOutcomeUnknown` | A storage error occurred at a boundary where commit status is not safe to infer. | Do not blindly retry; query/reconcile by stable operation identity. |

## Security and recovery claims

| Claim | Implementation entry | Normal/fault evidence | Qualification command or job |
| --- | --- | --- | --- |
| One process cannot create two authority owners for one database. | `codex-rs/hepta-authbus/src/owner_fence.rs::ProcessOwnerClaim` | `owner_fence::tests::rejects_duplicate_owner_before_open_and_releases_after_drop`; `host::tests::second_owner_is_rejected_and_release_allows_reopen` | AuthBus package tests in `exact-head`; repeated in `synthetic-merge`. |
| A failed same-process duplicate open cannot close a second descriptor and release the live POSIX process lock. | Process claim is acquired before `open(2)` in `OwnerFence::acquire`. | `host::tests::failed_same_process_duplicate_does_not_release_cross_process_fence` starts a third process before and after live-owner release. | AuthBus package tests. |
| The fence lives as long as any maintenance worker can operate the store. | `AuthBusAuthorityWorker` owns `Arc<AuthBusAuthorityHost>`; the host owns the fence and crate-private store. | `host::tests::worker_retains_host_and_owner_fence_until_worker_drop`; `host::tests::kill_nine_releases_the_process_owner_fence` | AuthBus package tests. |
| External callers cannot obtain a raw durable writer. | `AuthBusAuthorityStore` is `pub(crate)`; host APIs are the public mutation boundary. | `scripts/check-authbus-closed-world.py`; generated `PUBLIC_API_INVENTORY.json` | `Verify generated AuthBus public API inventory`. |
| Mutations, recovery maintenance, checkpoint publication and authority-bearing reads share one host-owned serialization boundary. | `AuthBusAuthorityHost::mutation_gate`, `mutate`, `read_authoritative`, `run_maintenance_mutations` | Host fault tests plus full package regression. | AuthBus, qualification, Evidence, Agentd and Bao test jobs. |
| Every issuer lifecycle mutation exposes the same post-commit checkpoint-failure semantics. | `AuthBusAuthorityHost::finish_locked`; `AuthBusAuthorityError::mutation_disposition` | `host::tests::every_issuer_lifecycle_mutation_has_the_same_checkpoint_failure_contract` covers enroll, rotate, revoke and retire. | AuthBus package tests and strict Clippy. |
| Checkpoint write failures at write, file-sync, rename and directory-sync boundaries are recoverable and never reported as ordinary success. | `AuthorityCheckpointFile::replace`; test-only checkpoint failpoints. | `host::tests::checkpoint_stage_failures_are_classified_and_recoverable` | AuthBus package tests. |
| Restoring an older authority database or witness fails closed. | `recovery.rs`; checkpoint dirty/frontier migrations; host preflight. | `recovery_tests.rs`; host bootstrap/open tests. | AuthBus package tests and qualification package. |
| Durable replay remains rejected after restart and witness reconciliation. | Evidence-owned AuthBus replay checkpoint and recovery implementation. | `codex-rs/hepta-evidence/src/authbus_recovery_tests.rs` | `Test Evidence AuthBus recovery and outbox`. |
| Evidence/Bao handoff does not settle early and preserves ambiguous outcomes. | Evidence outbox identity/lease checks; Bao dispatch fence and signed settlement. | Evidence outbox tests; `hepta-bao-adapter` HTTPS consumer tests. | Evidence, Agentd and Bao package jobs. |
| Seal, digest, checkpoint and settlement tampering is rejected without publishing partial authority. | Checkpoint identity validation, signed settlement verification, closed handles and digest-bound records. | Host symlink/hard-link/checkpoint tests; settlement negative tests; Evidence/Bao tamper tests. | Focused package jobs and workspace regression. |

## Operational claims

`AuthBusOperationalSnapshot` exposes bounded, non-secret state and cumulative runtime counters. `blocking_reasons()` converts current state into operator actions rather than requiring log interpretation. The current owner exports:

- owner acquisition failures grouped as active-owner, unsafe-path and storage classes;
- checkpoint synchronization failures split into rollback conflict and storage failure;
- blocked authority use, deterministic mutation rejection, committed-but-reconcile, and unknown-outcome counts;
- replay rejection count;
- maintenance failures and incomplete bounded recovery ticks;
- complete-operation mutation and maintenance latency summaries (`count`, `p50`, `p95`, `p99`, `max`), measured across gate wait, checkpoint preflight, SQLite work and checkpoint publication.

Counters are process-lifetime cumulative values. Exporters compute rates/deltas and use only bounded labels. Evidence outbox claim retries and Agentd/Bao acknowledgement latency remain owned by their downstream components; AuthBus must not fabricate those observations. The exact-head workflow executes those product owners alongside the AuthBus crate.

## Exact-candidate evidence

The authoritative workflow is `.github/workflows/authbus-authority-qualification.yml`. For each final candidate it must produce terminal-success jobs for:

1. `exact-head`: verifies checkout identity, generated API inventory, formatting, AuthBus/qualification/Evidence/Agentd/Bao tests, workspace all-target regression, strict Clippy, clean tracked state, and a receipt containing commit/tree/schema/migration/lock/test/build digests;
2. `synthetic-merge`: constructs the declared base plus exact head, verifies merge-tree identity, and repeats the same validation on that immutable merge candidate.

The run URL and receipt are not hard-coded here because any source or documentation commit invalidates them. Reviewers must use the terminal workflow attached to the final PR head shown by GitHub. This rule prevents documentation from claiming a result produced for an earlier commit.
