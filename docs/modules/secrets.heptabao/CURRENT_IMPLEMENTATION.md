# secrets.heptabao current implementation

This page describes source that exists on the current candidate. Target design
and production qualification are separate claims.

## Implemented

### Exact-version KV v2 consumption

`BaoClient::consume_kv_v2` performs a pinned direct HTTPS exact-version KV v2
read and releases one validated secret field only to the trusted synchronous
final-use callback.

### Provider-native dynamic SecretLease lifecycle

`lease.rs` implements:

- `request_secret_lease`
- `renew_secret_lease`
- `revoke_secret_lease`
- `lookup_secret_lease`

Dynamic database-style issuance uses `GET /v1/{mount}/creds/{role}`. Lease
lookup, renewal and revocation use OpenBao's documented POST system endpoints.
Revocation sets `sync=true`.

The raw provider lease ID lives only in non-Debug `SecretLeaseHandle`.
Receipts/status surfaces expose its SHA-256 digest rather than the identifier.
Secret response values use zeroizing application-owned buffers and are released
only through the trusted final-use callback.

Provider effects that may have happened without a trustworthy acknowledgement
become `Indeterminate`; mutation code does not blind-retry them. A known lease
can be inspected through the non-replaying lookup path. A lost issuance response
cannot be generically reconstructed because no provider lease ID is known.

### Durable local lease registry

`lease_registry.rs` provides `SecretLeaseRegistry`, an owner-private SQLite
registry using DELETE journaling and FULL synchronous mode. It writes an
operation fence before provider mutation, persists a known issued handle before
secret callback entry, records renew/revoke observations, preserves
`Indeterminate` across reopen, and blocks duplicate recorded operations.

This store is local state, not a distributed active-active consensus backend.

### Final-use replay persistence

`hepta-contracts` schema 2 stores the small authority/revocation head separately
from append-only `claims.log`. Each claim is fsynced before dispatch admission,
avoiding the former full JSON rewrite on every claim. The source ceiling is
1,000,000 unique claims per authority epoch; revoked grant IDs retain a separate
16,384 bound. Schema-1 state migrates without dropping replay protection.

## Still not established

- provider operation-key idempotency/status lookup for reconstructing a lost
  issuance response
- strongly consistent active-active replay/revocation and lease-registry state
- a production host consumer composition
- exact pinned-service deployment qualification and release acceptance
- an external anti-rollback oracle for restored authority/registry storage

Source completeness is not production qualification.
