# learning.plasticity target-host qualification contract

This is the mandatory deployment-evidence contract for proposal registries,
anchor/fence journals, Agentd restart behavior and runtime topology recovery.
Repository tests may exercise the same states but cannot self-certify this contract.

## 1. Immutable identity

Each run records one candidate and one environment:

```text
source_commit
source_tree
binary_sha256
Cargo.lock_sha256
workflow_run_id
workflow_attempt
runner_or_host_fingerprint
kernel
filesystem
mount_options
container_runtime
volume_driver
registry_path
anchor_path
registry_device_inode
anchor_device_inode
registry_mount_identity
anchor_mount_identity
registry_snapshot_domain
anchor_snapshot_domain
fault_case_inventory_sha256
test_binary_sha256
```

The proposal registry and anchor/fence journal must be regular, non-aliased files.
The host derives mount and snapshot identities independently of caller-provided
labels. Equal rollback domains fail qualification.

## 2. Required crash matrix

The harness must execute each case in a fresh isolated generation:

1. before registry append;
2. after write and before file `fsync`;
3. after file `fsync` and before rename/link publication;
4. after publication and before parent-directory `fsync`;
5. after registry commit and before anchor append;
6. after anchor write and before anchor `fsync`;
7. after anchor acknowledgement and before caller response;
8. Agentd owner crash;
9. supervisor restart;
10. registry-only rollback;
11. anchor-only rollback;
12. combined stale snapshot restore;
13. generation rollover during submission;
14. incomplete final frame;
15. complete checksum-invalid frame;
16. storage-full or sync failure at every durable boundary.

Fault injection must terminate a real process or block the real storage operation.
A test-only boolean that skips the operation is not equivalent evidence.

## 3. Per-case receipt

Every case records:

```text
case_id
candidate_commit
process_exit_mode
fault_injection_point
durable_registry_bytes_sha256
durable_anchor_bytes_sha256
registry_head
anchor_head
writer_fence
owner_generation
artifact_frontier
learning_ledger_frontier
restart_result
retry_result
terminal_class
operator_action_required
started_at
finished_at
raw_log_sha256
```

`terminal_class` is one of `committed`, `rejected`, `indeterminate` or
`not_started_proved`. Unknown is never rewritten as not started. An identical retry
uses the original idempotency identity and must not duplicate a non-repeatable effect.

## 4. Pass conditions

Qualification passes only when all of the following hold:

- an acknowledged proposal is never lost after restart;
- a retained anchor rejects a registry-only rollback;
- an anchor-only rollback does not authorize reuse of an old writer fence;
- an incomplete crash tail may be repaired only after every complete predecessor
  validates;
- a complete invalid frame is retained and rejected, never truncated as a tail;
- generation rollover fences queued and prepared old-generation requests;
- deadline or cancellation before durable admission produces no proposal;
- deadline/cancellation after a possible durable append returns an indeterminate
  reconciliation requirement rather than “not written”;
- restart opens authoritative owner stores and re-resolves current frontiers;
- topology recovery uses a separately authorized exact-successor transition;
- operator actions follow the checked-in runbook and preserve evidence.

## 5. Performance and capacity receipt

Measure complete operations, including validation, queueing, blocking work, file and
directory sync, external anchor and final owner revalidation. Record p50, p95, p99,
maximum and sample count for:

```text
proposal_generation_latency
verification_latency
queue_wait_latency
blocking_execution_latency
registry_append_latency
file_fsync_latency
parent_fsync_latency
anchor_latency
reopen_latency
reconcile_latency
canary_observation_latency
total_latency
```

Also record candidate, delta and layer counts; registry records/bytes; peak RSS;
retained/cloned/serialized bytes; cold/warm cache; near-capacity registry; crash-tail
reopen; concurrent readers; slow anchor; and queue saturation. Development-profile
single samples are diagnostics, not production SLO evidence.

## 6. Readiness semantics

The repository readiness manifest sets `mergeReady=true` only when all required
source-head and deterministic-merge lanes from one workflow run/attempt pass. A real
main merge SHA is rerun separately.

`productionQualified` remains false until this target-host matrix, independent
semantic/security review and operator exercise have separately verifiable receipts.
Activation and release remain separate decisions.
