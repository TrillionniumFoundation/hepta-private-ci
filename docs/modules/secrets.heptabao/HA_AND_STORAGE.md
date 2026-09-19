# secrets.heptabao HA and storage boundary

## Final-use authority storage

The local authority backend is schema v2:

- `authority.lock`: owner-only cross-process mutation/final-use fence;
- `authority.json`: small signer/verifying-key/revocation-head snapshot;
- `authority.next`: atomic replacement staging file;
- `claims.log`: append-only fixed-size, checksummed replay claims.

One claim appends one record and syncs it. Active owners keep a verified journal
offset and, under the OS lock, read only records appended by other owners since
their previous synchronization.

An epoch transition clears only the in-memory active-epoch nonce set. Old
journal records remain harmless because each record carries its epoch. This
avoids an O(N) journal rewrite in the hot path.

## Multi-process active owners

The lock is not held for process lifetime. Multiple processes can open one
qualified state directory and concurrently perform network work. They serialize
only:

- nonce claim;
- revocation-head mutation;
- final synchronous secret delivery.

This ensures a process cannot dispatch using a nonce claimed by another active
owner and cannot enter final secret delivery after another owner has durably
completed a revocation update.

The callback is deliberately synchronous/bounded because the cross-process
revocation fence is held during callback entry and execution.

## What this does not claim

This is not a distributed consensus algorithm.

The backend is qualified only for an owner-controlled filesystem that provides
the locking, atomic same-directory rename and fsync semantics relied on by the
implementation. Independent node-local copies, object stores, eventually
consistent filesystems and unqualified NFS mounts must not be used as if they
formed one replay domain.

For multi-host active-active deployment, use one independently qualified
strongly consistent state service or a filesystem/storage system whose locking
and durability behavior has been explicitly tested for the deployment. The
authority epoch, revocation head and nonce-claim journal must have one linearized
mutation order. Split-brain replay state is a security failure, not an
availability mode.

## Capacity

The former 16,384 replay-claim limit has been removed from the claim path.
Growth is now bounded by actual storage/resources rather than silent eviction or
an arbitrary per-epoch entry count. Storage exhaustion fails closed.

The revocation-ID set remains explicitly bounded because it is part of the small
head snapshot. Long-lived deployments should rotate authority epochs under
owner control rather than grow a revocation set indefinitely.

The lease metadata store remains capped by its 8 MiB serialized state file. It
is not on the secret-consumption replay hot path. If product scale approaches
that bound, migrate it behind the same operation-state semantics to a qualified
transactional backend before raising the limit.

## Migration

Schema-v1 authority state is accepted only when trust/head validation succeeds.
Its legacy nonce set is merged into the journal before the schema-v2 head is
published. A crash during migration can repeat the union but cannot silently
forget a prior nonce.

There is no automatic repair that converts missing/corrupt state into an empty
registry.
