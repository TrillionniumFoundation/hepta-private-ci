# ADR-0001: kernel.authority lease trust model

Status: accepted for the repository-controlled candidate in PR #584.

## Decision

The version-1 general `authority_lease` is an **online registry-authoritative
reference**, not a self-verifying portable bearer capability.

An `AuthorityLease` value is useful for durable storage, reads and exact
binding comparison, but possession or serialization of that value confers no
authority. A use is authorized only when the holder presents the lease identity
and exact binding to an `AuthorityLeaseVerifier` backed by the same live
`AuthorityLeaseRegistry` owner. Final use is revalidated against the current
lease revision, revocation state, epoch and the owner-bound clock immediately
before consumer entry.

The administrative handle and verification handle are distinct capabilities:

- `AuthorityLeaseRegistry` is non-cloneable and owns put, revoke, prune and
  epoch-advance mutations.
- `AuthorityLeaseVerifier` is cloneable and read/verify only. It cannot mint,
  replace, revoke, prune or advance leases.

Production construction additionally binds an externally durable CAS frontier
and a trusted clock. The external frontier must survive rollback or replacement
of the local authority directory. Each mutation advances the external frontier
before committing local state; if either side cannot complete consistently, the
owner fences itself and recovery is explicit. The convenience
`open_state_dir_with_frontier_store` path still uses `SystemAuthorityClock`
and is therefore rollback-hardened compatibility, not a trusted-time production
composition; production uses `open_state_dir_with_trust`.

Online pruning removes expired unrevoked lease payloads but retains a compact,
frontier-covered retired revision for each pruned lease id. Reusing that id in
the same authority epoch must continue at the retired revision plus one. A
pruned id can therefore never reset to revision 1 or make a stale
`(lease_id, revision, binding)` tuple authoritative again. Retired revision
history is bounded; exhaustion requires authority epoch rollover rather than
silent eviction.

## Consequences

A lease copied to another process or node is not independently authoritative.
Cross-process or cross-node use must call a trusted authority service/host that
owns the live verifier, or use a separately defined signed protocol such as the
FinalUse grant family. There is no implicit conversion between a general lease
and a signed FinalUse grant.

This deliberately supersedes older target text that described the first general
lease as if every lease would carry a portable signature/key reference. That
model is not the V1 native implementation. If a portable signed general lease is
introduced later, it requires a new schema/signing domain and explicit rules for
offline revocation/freshness; it must not silently change V1 semantics.

## Rationale

Online verification gives revocation and CAS revision changes one owner and
prevents a stale serialized lease from acting as authority after replacement.
Separating admin and verifier handles makes least authority a Rust type property
instead of relying only on repository caller scanning. External CAS frontier and
clock interfaces make backup rollback and time trust explicit deployment
dependencies rather than filesystem or `SystemTime` claims.
