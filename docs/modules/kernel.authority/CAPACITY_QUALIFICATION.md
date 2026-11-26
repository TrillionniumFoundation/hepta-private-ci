# kernel.authority capacity and durability qualification

Status: **measurement contract and executable collector; no production latency claim is implied by source limits or collector self-tests**.

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

The Agentd compatibility trust host persists a monotonic clock floor. Its
filesystem write, file fsync, rename and directory fsync costs are part of the
observed authorization path and must not be hidden by measuring only signature
verification or an in-memory fixture.

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

## Exact target-host collector

`qualification/kernel-authority/capacity_matrix.py` is the read-only orchestration
and validation boundary for this matrix. It never embeds a production driver and
cannot substitute a hosted-runner fixture for a selected target profile.

Create an immutable plan:

```bash
python3 -B qualification/kernel-authority/capacity_matrix.py plan \
  --candidate-commit "$(git rev-parse HEAD)" \
  --candidate-tree "$(git rev-parse 'HEAD^{tree}')" \
  --profile-id <selected-profile-id> \
  --samples 100 \
  --output /secure/evidence/kernel-authority/capacity-plan.json
```

Run one explicitly selected executable target driver. The driver receives
`--request <path> --output <path>` for each row and must return an exact typed
response bound to the candidate, profile and one identical host description:

```bash
python3 -B qualification/kernel-authority/capacity_matrix.py collect \
  --plan /secure/evidence/kernel-authority/capacity-plan.json \
  --driver /opt/hepta/bin/kernel-authority-target-driver \
  --output-dir /secure/evidence/kernel-authority/capacity-run
```

Re-open the retained aggregate independently:

```bash
python3 -B qualification/kernel-authority/capacity_matrix.py validate \
  --plan /secure/evidence/kernel-authority/capacity-plan.json \
  --collection /secure/evidence/kernel-authority/capacity-run/capacity-collection.json
```

The collector requires exactly 55 operation rows, all eight fault cases, one
reserve observation and 25 history-sensitive diagnostics. It rejects booleans
masquerading as integers, duplicate or missing identities, candidate/profile
mismatch, mixed hosts, synthetic results, percentile contradictions, unsafe
fault outcomes and any activation/release claim. It retains request, response
and log digests for every invocation.

The CI command `capacity_matrix.py self-test` exercises only schema and negative
logic with explicitly synthetic data. Its receipt sets
`productionEvidenceAdmissible=false`; it is not one row of the target matrix.

## History-sensitive diagnostics

At every state point the selected driver additionally measures:

- `final_use_frontier_hash`;
- `lease_state_clone`;
- `lease_image_serialize`;
- `clock_floor_persist`;
- `restart_rebuild`.

These diagnostic rows record history units, bytes touched, peak RSS and
microsecond distributions. They are not SLO rows and do not independently grant
a pass. Their purpose is to decide, from target evidence, whether an incremental
authenticated digest, checkpoint or different persistence representation is
necessary. No optimization may weaken rollback fencing, nonce retention,
pending-revocation recovery or the single-owner boundary merely to improve a
source-only timing.

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

The collector aggregate remains `productionEvidenceAdmissible=false`; its rows
must still be wrapped in the independently retained evidence envelopes expected
by `verify.py`, alongside trusted-time, frontier, key-custody, revocation and
operator-acceptance receipts. Collection and production admission are deliberately
separate authorities.

## Pass criterion

Capacity qualification is PASS only when:

- the complete v2 matrix has exact-candidate artifacts from one selected target profile;
- no p99 violates its declared target-host latency budget;
- maximum state remains inside the restart/read and memory envelopes;
- fault injection preserves fail-closed recovery and indeterminate outcomes;
- reserve/rollover alerts are demonstrated before hard capacity;
- independent review accepts the measured profile.

Until then the repository may claim bounded source behavior and an executable
collector, but not production throughput, tail latency, durability performance
or deployment activation.
