# kernel.authority capacity and durability qualification

Status: **measurement contract; no production latency claim is implied by source limits**.

The authority implementations intentionally bound state, but bounded state is not
the same as qualified performance. A selected host must produce exact-candidate
measurements before activation.

## Current source bounds

General leases:

- live lease records: 16,384 maximum;
- revocation tombstones: 16,384 maximum per authority epoch;
- retired lease-ID revision lineage: 16,384 maximum per authority epoch;
- expired unrevoked pruning: at most 1,024 records per call and never beyond
  remaining retired-lineage capacity;
- pruning removes the live record only after durably recording that lease ID's
  last revision; same-epoch reuse must continue at exactly the next revision and
  can never restart at revision 1;
- complete persisted-state read ceiling: 64 MiB;
- revocation tombstones and retired revision lineage are retained until an
  explicit authority-epoch rollover.

FinalUse:

- claimed nonce history: 1,048,576 maximum per authority epoch;
- revoked grant IDs: 16,384 maximum in one head;
- nonce history is not silently evicted;
- a stronger authority-epoch transition is the bounded-history reset path.

The general-lease store serializes and atomically replaces its bounded JSON
image under the owner mutex. The FinalUse hot claim path instead appends a fixed
40-byte `(authority_epoch, nonce)` frame and fsyncs the claim journal before
admission; revocation/trust snapshots use atomic replacement and journal
compaction. This local append optimization does **not** by itself prove
constant-cost production admission: a production-oriented claim also computes
and CAS-advances the external frontier, whose current digest covers the complete
revocation head and nonce set. Both modes therefore require exact-host
measurement at realistic history sizes.

## Mandatory v2 measurement matrix

For each selected filesystem/storage/frontier profile, run the exact candidate
at these state points:

- `empty`
- `1k`
- `8k`
- `90_percent`
- `max`

At every point measure all of:

| Evidence operation ID | Measured behavior |
| --- | --- |
| `lease_put_replace` | lease create/replace mutation |
| `lease_revoke` | durable lease revocation |
| `lease_verify_final_use` | first and final live lease checks |
| `prune_1` | one-record expired-lease prune |
| `prune_128` | 128-record prune |
| `prune_1024` | maximum online prune batch |
| `epoch_rollover` | durable authority-epoch transition |
| `final_use_claim` | signature/binding check, nonce burn, external frontier and local journal |
| `final_use_final_verify` | final consumer/dispatch entry check |
| `revocation_head_apply` | authenticated monotonic head update |
| `restart_open` | store/frontier reopen and validation |

Each point/operation row must retain a content-addressed receipt and record:

- at least 100 samples;
- p50, p95 and p99 milliseconds in monotonic order;
- an explicit positive latency budget, with measured p99 no greater than it;
- bytes written;
- fsync p99 no greater than total p99;
- positive peak RSS bytes.

The artifact must identify CPU, filesystem, storage medium, mount/durability
settings, external frontier implementation, clock implementation, operating
system, Rust profile and candidate SHA/tree. Compatibility constructors without
external trust may be measured separately but cannot stand in for the selected
production configuration.

## Fault-injection matrix

At minimum inject failure at:

1. `before_external_frontier_cas`;
2. `after_external_cas_before_local_temp_write`;
3. `after_temp_fsync_before_rename`;
4. `after_rename_before_directory_fsync`;
5. `after_successful_local_commit`;
6. `during_prune`;
7. `during_epoch_rollover`;
8. `restart_with_older_local_snapshot`.

For each case retain a receipt and classify the observed result as exactly one
of `reopen_succeeds`, `fenced` or `rollback_rejected`. Every case must preserve
indeterminate state and must record that no reset was attempted. An older
restored snapshot must be rejected. A mutation made uncertain after external
CAS, during prune or during epoch rollover may not reopen as ordinary success.
Tests must never “repair” uncertainty by resetting authority state.

## Capacity policy

A deployment must choose a reserve threshold rather than operating at the hard
limit. The evidence bundle records hard limit, reserve threshold, observed
remaining capacity and whether the alert fired. The alert must be demonstrated
at or below the reserve threshold, and that threshold must remain below the hard
limit.

Epoch rollover is an authority operation and requires its own change/audit
procedure; observability or GC code cannot advance epochs. Expired unrevoked
general leases may be pruned online only while retired lease-ID lineage has
capacity. Pruning is not identity deletion: the last revision remains
authoritative for same-epoch reuse and is included in the anti-rollback
frontier. Revocation tombstones, retired revision lineage and FinalUse replay
history must not be discarded merely to recover capacity.

## Evidence admission

The target-host measurement receipt is a required artifact in the
[`kernel.authority` production evidence bundle](../../../qualification/kernel-authority/README.md).
Schema `hepta.kernel-authority-production-evidence.v2` requires the complete
5-by-11 matrix, all eight structured fault results and the demonstrated reserve
alert. Missing rows, fewer than 100 samples, percentile contradictions, p99 over
budget, unsafe reopen outcomes or prose-only pass flags are machine failures.

## Pass criterion

Capacity qualification is PASS only when:

- the complete v2 matrix has exact-candidate artifacts;
- no p99 violates its declared target-host latency budget;
- maximum state remains inside the restart/read and memory envelopes;
- fault injection preserves fail-closed recovery and indeterminate outcomes;
- reserve/rollover alerts are demonstrated before hard capacity;
- independent review accepts the measured profile.

Until then the repository may claim bounded source behavior, but not production
throughput, tail latency, durability performance or deployment activation.
