# kernel.authority capacity and durability qualification

Status: **measurement contract; no production latency claim is implied by source limits**.

The authority implementations intentionally bound state, but bounded state is not
the same as qualified performance. A selected host must produce exact-candidate
measurements before activation.

## Current source bounds

General leases:

- live lease records: 16,384 maximum;
- revocation tombstones: 16,384 maximum per authority epoch;
- expired unrevoked pruning: at most 1,024 records per call;
- complete persisted-state read ceiling: 64 MiB;
- revocation tombstones are retained until epoch rollover.

FinalUse:

- nonce/revocation state is bounded by the native `MAX_CLAIMS` limit;
- nonce history is not silently evicted;
- a stronger authority-epoch transition is the bounded-history reset path.

Both current Unix stores replace a complete JSON state under an owner mutex using
temp-write, fsync, rename and directory fsync. Therefore write amplification and
tail latency must be measured at realistic state sizes.

## Mandatory measurement matrix

For each selected filesystem/storage profile, run the exact candidate at these
state points where applicable: empty, 1k, 8k, 90% capacity and declared maximum.

Record separately:

| Operation | Required measurements |
| --- | --- |
| lease put/replace | p50/p95/p99 latency, bytes written, fsync time |
| lease revoke | p50/p95/p99 latency, bytes written, fsync time |
| lease verify/final use | p50/p95/p99 latency and lock hold time |
| prune 1 / 128 / 1024 | latency and reclaimed records |
| epoch rollover | latency, resulting state size and restart verification |
| FinalUse claim | p50/p95/p99 latency and persistent-state bytes |
| FinalUse final verify | p50/p95/p99 latency and lock hold time |
| revocation-head apply | p50/p95/p99 latency at representative revoked-set sizes |
| restart/open | latency and peak memory at representative and maximum state |

The artifact MUST identify CPU, filesystem, storage medium, mount/durability
settings, operating system, Rust profile and candidate SHA/tree.

## Fault-injection matrix

At minimum inject failure at:

1. before external frontier CAS;
2. after external CAS but before local temp write completes;
3. after temp-file fsync but before rename;
4. after rename but before directory fsync;
5. immediately after successful local commit;
6. during prune;
7. during epoch rollover;
8. during restart with a restored older local snapshot.

For each case record whether reopen succeeds, fences, or rejects rollback. An
unknown commit outcome must remain unavailable/indeterminate; tests must never
"repair" it by resetting authority state.

## Capacity policy

A deployment MUST choose a reserve threshold rather than operating at the hard
limit. Alerting must begin before `rollover_required_with_reserve` (or the
equivalent FinalUse capacity check) reaches the deployment reserve. Epoch rollover
is an authority operation and requires its own change/audit procedure; observability
or GC code cannot advance epochs.

Expired unrevoked general leases may be pruned online. Revocation tombstones and
FinalUse replay history must not be discarded merely to recover capacity.

## Pass criterion

Capacity qualification is PASS only when:

- the complete matrix has an exact-candidate artifact;
- no operation violates the selected host's declared latency budget;
- maximum state remains inside the restart/read envelope;
- fault injection preserves fail-closed recovery;
- reserve/rollover alerts are demonstrated before hard capacity;
- independent review accepts the measured profile.

Until then the repository may claim bounded source behavior, but not production
throughput, tail-latency or durability performance.
