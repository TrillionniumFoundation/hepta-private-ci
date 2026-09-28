# AuthBus ownership and failure semantics

Source baseline: `f998dc1bc952f09ca38cfce13448eca36043c429`.
Candidate lane: `work/authbus-ownership-transactions-20260928`.
Scope: AuthBus owner/store; Evidence read-only AuthBus diagnostics; migration of
sealed-API test fixtures in Evidence, Bao and Agentd. No production activation.

## Correct source model

This source uses `AuthBusAuthorityHost` and the crate-private SQLx
`AuthBusAuthorityStore`. Issuer lifecycle changes are SQLite transactions, not
in-memory `RegistryHost` signer swaps. Non-Unix persistence already fails closed.
The previous review's `RegistryHost`, `revoke_key_tag` and non-Unix no-op claims
are not descriptions of this baseline and must not be used as acceptance facts.

## Ownership and lifetime

`OwnerFence::acquire` reserves the canonical lock pathname in-process BEFORE
opening its inode. With POSIX process locks, closing any descriptor for that
inode releases the process's locks; therefore a rejected duplicate must not open
it at all. RAII rolls the reservation back on every failed acquisition.
`OwnerFence` fields drop in order: file first, process reservation second. There
is no unlock-before-close/reacquire window. The deployed lock pathname and fcntl
protocol remain unchanged for compatibility.

`AuthBusAuthorityStore::open_owned` takes the fence. The store and its pool's
retained connection callback keep the fence alive while store/pool capabilities
exist, including in-flight SQLx work. The raw unfenced constructor is test-only.
The worker already retains `Arc<AuthBusAuthorityHost>`; dropping the original
Arc does not release ownership. A caller should stop and drop workers, recover
exclusive ownership of the host, then call `close(self)`. Close drains the pool;
it does not grant permission to erase unresolved checkpoint state. Pool cleanup
can briefly delay replacement ownership; retry only OwnerAlreadyActive, with a
bounded startup deadline. Do not retry unsafe paths or rollback errors blindly.

Persistent ownership is supported on Unix with canonical private parent paths.
Unsupported platforms return an error. Never replace this with success-returning
stubs. Protected owner directories remain part of the threat model: untrusted
users must not be able to remove/replace the lock pathname or checkpoint root.

## One owner transition boundary

All host domain mutations and sealed issuer lookups enter `Host::mutate`:

1. Acquire the instance gate; no domain future is polled before this.
2. Reconcile a prior dirty/uncertain frontier and confirm external durability.
3. Execute the local transaction(s).
4. Publish/reconcile the external checkpoint even when the domain result is Err.
5. Return a typed outcome and record bounded diagnostics.

The gate spans local writes AND external publication. Maintenance uses the same
boundary and validates policy/batch configuration before mutation. If a later
maintenance step fails after an earlier one committed, it returns
`MaintenanceIncomplete` and still attempts checkpoint publication.

SQLite COMMIT driver errors map to `CommitIndeterminate`, not ordinary statement
errors. No error is evidence that an external provider effect was not applied.

| Result | Requested transition | Required action |
|---|---|---|
| `Ok(value)` | Committed, checkpoint publication confirmed | Use the returned value within its own contract. |
| Ordinary domain rejection | Rejected; trusted time may still advance | Fix the specified identity/revision/policy error. |
| `MutationNotStarted` | This operation was not polled; prior state cannot be reconciled | Repair prior checkpoint/owner state, then retry the same identity. |
| `MutationIncomplete { Committed, ... }` | Local operation succeeded, checkpoint publication did not | Read back/reconcile; do not blindly repeat a non-idempotent operation. |
| `CommitIndeterminate`, storage or partial-batch uncertainty | Readback required | Reconcile exact issuer/reservation identity and committed frontier first. |

A rejected policy/quota request can advance monotone trusted time, deliberately.
"Rejected" is not a promise that every metadata byte remains unchanged.
`issuer_record`, `quota_snapshot`, `reservation` and diagnostics remain readback
surfaces, not new permission to dispatch an effect. Sealed issuer lookup is gated
and cannot publish an uncheckpointed trusted handle.

Dropping/cancelling an entered operation records an uncertain outcome. The next
entry repairs the dirty frontier before starting its own operation. The pool
retains ownership while queued driver work finishes. Cancellation is not rollback.

## Checkpoint files and failure injection

Checkpoint reads use NOFOLLOW descriptors and validate regular-file identity,
private mode, owner, link count, bounded size and canonical parent. A corrupted
JSON/digest/generation/owner cannot authorize a new mutation. A successful rename
followed by failed directory fsync is NOT treated as a completed publication:
preflight/reopen re-sync the external file and directory before local promotion.
Test faults are per-checkpoint AtomicU8 state, never a process-global switch.

Fault stages cover temporary file creation, payload write, file synchronization,
and post-rename/pre-directory-sync recovery. Subprocess death and I/O-failure
fixtures are regression evidence, not a claim of target-host power-loss testing.

## Diagnostics without transferring ownership

`host.owner_diagnostics()` is a bounded process-local snapshot: attempts,
waiting/in-flight operations, committed/rejected/not-started/reconcile-required
outcomes, cancellations, pending publication, conflicts, storage failures and a
stable blocking reason. Startup failures expose `error.blocking_reason()` so the
host caller can count them even when construction fails. No new global metrics
registry, per-request map or authority store is introduced.

Operation latency starts at entry and includes gate wait, validation/store work,
and checkpoint publication. Separate fixed histograms cover gate wait and
checkpoint synchronization. Quantiles from these histograms are bucket UPPER
BOUNDS; no observations and overflow are represented as None, not zero or a made-up
SLA. Counter values saturate. Process restarts reset these observations.

`EvidenceStore::authbus_outbox_diagnostics()` reads at most 4097 narrow rows in one
snapshot. It exposes queued/leased/quarantined/expired/acked counts, oldest pending
age, retry backoff, expired leases, retained claim retries, replay-checkpoint
pending, and retained enqueue-to-ACK latency aggregates. More than the declared
4096 rows is corruption. No payload/key is loaded; diagnostics do not claim,
retry, ack, settle or maintain records. ACK latency includes retries and is not
Bao/provider RTT. Retention-window aggregates are not lifetime counters.

Bao settlement/indeterminate reservations remain AuthBus-owned facts. A provider
timeout continues to hold quota; an Evidence delivery ACK is not provider success.
Replay rejection event counters and external metric exporter/alert thresholds
remain responsibilities of the actual admission/operations callers. No invented
history or synthetic production measurements are emitted.

## Full operation measurement

Run on the exact candidate:

```sh
cargo +1.95.0 test --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-authbus --all-targets
cargo +1.95.0 run --locked --manifest-path codex-rs/Cargo.toml -p codex-hepta-authbus --example owner_latency -- 64
```

The example uses fresh private directories and fixture keys only, and bounds
sample count to 1..256. It reports measured end-to-end enrollment p50/p95/p99,
bootstrap/reopen time, retained state size and owner histograms. CI separately
captures `/usr/bin/time -l` for the built executable (not the compiler), including
peak RSS. This is a runner diagnostic, not a production capacity or latency SLA.
No batching, extra cache, weakened fsync or acknowledgement reordering is used.

## Constraint → source → regression → evidence matrix

All names below identify source tests, not pass receipts. The candidate becomes
verified only when the immutable run on that exact SHA has terminal-success steps.

| Constraint | Implementation | Regression anchors |
|---|---|---|
| Duplicate open preserves original OS lock | `owner_fence.rs` reservation/drop order | `duplicate_open_does_not_release_existing_process_lock`, `failed_lock_file_validation_releases_process_reservation` |
| Worker and store/pool keep owner alive | `worker.rs`, `authority_store.rs::open_owned` | `live_worker_retains_owner_after_original_host_handle_is_dropped`, `cloned_pool_retains_owner_until_its_final_capability_is_dropped` |
| Key transaction failure preserves predecessor | `trust_store.rs` transactions | `failed_rotation_rolls_back_old_key_and_survives_reopen`, `failed_revoke_and_retire_preserve_exact_previous_state` |
| Checkpoint failure is not rollback | `host.rs::mutate` | `pending_checkpoint_blocks_new_mutation_and_is_not_a_rollback`, `checkpoint_stage_failures_remain_recoverable` |
| Faults/cancellation/concurrency cannot bypass publication | instance gate/fault state | `checkpoint_faults_are_isolated_between_owner_instances`, `cancellation_after_commit_requires_reconciliation_before_next_operation`, `concurrent_mutations_publish_one_consistent_frontier` |
| Tampered checkpoint rejects before mutation | private checkpoint reader/preflight | `tampered_checkpoint_rejects_before_starting_the_next_mutation` |
| Old replay DB cannot resurrect authorization | Evidence recovery frontier | `external_checkpoint_detects_real_old_database_restore`, `issuer_retirement_proof_prunes_replay_rows_but_tombstone_prevents_resurrection` |
| Interrupted delivery preserves exact lease/ACK identity | Evidence worker/fences | `enqueue_commit_response_loss_is_idempotent_across_reopen`, outbox stale-lease/issuer suites |
| Diagnostics do not mutate delivery | Evidence narrow read projection | `diagnostics_distinguish_backoff_lease_retries_and_ack_without_mutating` |
| Bao timeout is not NotApplied | Bao AuthBus integration | existing TLS/AuthBus product and timeout-hold suite in `https_consumer_tests.rs` |
| Source, documentation and test target agree | immutable workflow + API inventory | `--locked`, format `--check`, closed-world `--check`, clean-worktree gate |

Evidence is retained as `authbus-execution-${GITHUB_SHA}`: source SHA, source tree,
toolchain, per-suite logs, diagnostic JSON and peak-RSS output. Run/job conclusions
are authoritative for execution status. No compilation or test pass is inferred
from source presence or an uploaded input archive. Final production activation,
independent acceptance and target-host fault drills remain separate gates.
