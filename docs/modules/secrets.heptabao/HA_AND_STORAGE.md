# HA and storage boundary

## Local mode

`LeaseRegistry` and `FinalUseAuthority` each use an OS-held exclusive lock.
One state directory therefore has one active owner. This is deliberate and
prevents split-brain replay or lease mutation on a single host.

The lease registry uses append-only fsynced metadata records. The final-use
authority uses a small atomically replaced head snapshot plus an append-only
fsynced claim journal. These changes remove the former O(N) rewrite from the
claim hot path.

## Capacity

Final-use claims: 1,000,000 unique nonces per authority epoch.

Revoked final-use grant IDs: 16,384 per revocation head.

Lease journal: 256 MiB local source limit and 1,000,000 records on open.

These are explicit source limits, not deployment recommendations. Long-lived
deployments must define epoch rotation, journal compaction and alert thresholds.

## Active-active

The local files must not be shared through an unqualified NFS/distributed
filesystem. Active-active operation requires a strongly consistent owner that
can atomically:

1. check-and-insert final-use nonce by authority epoch
2. compare-and-advance revocation head
3. create operation identity exactly once for lease effects
4. commit lifecycle transitions with monotonic generation/fence
5. survive node loss without forgetting acknowledged claims/effects

A distributed backend must preserve these semantics before it is selectable.
Source currently does not claim that backend exists.

Recommended deployment choices are either single-active with fenced failover,
authority/lease ownership sharded so each key has one active owner, or a
transactional strongly consistent service implementing the contract above.
