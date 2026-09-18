# secrets.heptabao current implementation

This document is the source-of-truth status page for what is implemented in the
repository. Target architecture belongs in `SECRET_LEASE_DESIGN.md`; CI or
release qualification belongs in exact-candidate receipts.

## Implemented source surfaces

### Exact-version KV v2 final-use consumer

`BaoClient::consume_kv_v2` performs one pinned-HTTPS exact-version KV v2 read,
validates version and expected digest, and releases secret bytes only to the
registered synchronous consumer under the final-use revocation fence.

### Dynamic SecretLease control-plane

`lease_control.rs` implements:

- `BaoClient::request_secret_lease`
- `BaoClient::renew_secret_lease`
- `BaoClient::revoke_secret_lease`
- `LeaseRegistry` durable metadata journal
- explicit `IssuePending`, `Active`, `RenewPending`, `RevokePending`,
  `Unknown`, `Revoked`, `Expired`, and `NotApplied` states
- operation-id semantic conflict detection
- explicit reconciliation of ambiguous provider outcomes
- dynamic secret delivery only through the final-use callback
- no persisted raw dynamic secret values

Dynamic issue explicitly binds a `GET` or `POST` method for `/v1/{provider_path}`. Renew and revoke use `POST /v1/sys/leases/renew` and `POST /v1/sys/leases/revoke`. No automatic
retry is performed after a provider operation may have been applied.

The local registry is append-only and fsyncs every state transition. It is
single-active per state directory by design and is not an active-active store.

### Final-use replay persistence

`hepta-contracts` schema 2 separates the small authority snapshot from
`claims.log`. Claims are durable O(1) appends instead of complete JSON state
rewrites. The in-memory per-epoch claim ceiling is 1,000,000. Revoked grant IDs
retain a separate 16,384 bound. Epoch advancement persists the stronger head
before compacting the old claim journal.

Schema-1 authority state is migrated without dropping used nonces.

## Not established by source implementation

The following are still separate qualification/composition work:

- a real product caller and operator-approved host composition
- active-active distributed replay/revocation storage
- provider-specific automatic reconciliation for dynamic engines that expose a
  reliable lookup/idempotency primitive
- release, deployment, canary, production acceptance, and backup anti-rollback
- proof that an arbitrary trusted callback cannot exfiltrate a secret by side
  effect; the callback remains a privileged host boundary

Do not describe source implementation as production qualification.
