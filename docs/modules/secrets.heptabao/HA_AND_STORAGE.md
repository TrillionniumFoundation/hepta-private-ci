# secrets.heptabao HA and storage

## Two different state owners

Do not conflate FinalUse replay state with SecretLease lifecycle state.

### FinalUse local authority

The current filesystem backend is intentionally single-active per private state directory. `authority.lock` prevents concurrent local owners. Schema 2 keeps:

- `authority.json`: signer/verifying-key identity plus bounded revocation head;
- `authority.claims`: append-only fixed-width 32-byte claimed nonces;
- `authority.lock`: process ownership fence;
- `authority.next`: atomic head replacement temporary.

Claim admission is O(1) append + fsync rather than O(N) complete-JSON rewrite. There is no 16,384-claim logical capacity gate. The in-memory replay set still grows during a long epoch, so trusted epoch rotation/operational sizing remains required.

Revoked grant IDs remain separately bounded. Removing the claim ceiling is not permission for unbounded revocation metadata.

This backend does not qualify NFS/distributed lock behavior and does not provide active-active authority ownership.

### SecretLease registry

The current `HeptaEvidenceStore` implementation uses SQLite migration 0011 and revision CAS. It supports multiple handles/processes that coordinate through the same SQLite database and `BEGIN IMMEDIATE`.

That is not a multi-host distributed-consensus implementation.

## Multi-host active-active requirements

A distributed implementation of `SecretLeaseStore` must provide:

1. linearizable exact-idempotent create returning Inserted vs AlreadyPresent;
2. linearizable compare-and-swap on `lease_key + revision`;
3. durable reads after acknowledged writes;
4. immutable logical/provider identity and provider lease ID once observed;
5. no split-brain writer that can independently admit the same operation;
6. backup/restore semantics that do not silently resurrect terminal or older revisions;
7. bounded latency/failure behavior that surfaces Unavailable rather than falling back to a weaker local store.

Possible implementations include a transactional consensus-backed database or a correctly configured strongly-consistent service. A shared filesystem is not considered an implementation merely because all replicas can see the same path.

A future distributed FinalUse backend has additional requirements: atomic replay claim, monotonic epoch/revocation head, anti-rollback recovery policy and a final-use fence compatible with revocation semantics. The current local filesystem store remains the qualified implementation until such a backend has its own tests/evidence.

## Capacity

The nonce journal removes the previous 16,384-claim cliff and O(N) claim rewrite. It does not remove physical disk, memory or fsync costs. Operators should measure claim rate, journal size, restart load time and epoch duration.

Lease rows are one current lineage record per logical lease key and are not deleted by the migration trigger. Long-term archival/compaction needs an owner-approved policy that preserves terminal lineage and cannot resurrect a prior revision.
