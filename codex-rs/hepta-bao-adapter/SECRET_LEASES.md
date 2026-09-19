# HeptaBao SecretLease lifecycle

This document is the executable implementation contract for provider-native
dynamic secret issuance, lease renewal, synchronous revocation and
reconciliation in `codex-hepta-bao-adapter`. It supplements the exact-version
KV v2 consumer documented in `README.md`.

## Executable operations

`BaoClient` exposes:

- `request_secret_lease` — issue one provider-native dynamic secret through a
  configured `GET /v1/{mount}/{path}`, persist lease metadata, and release only
  explicitly requested string fields to one trusted synchronous callback;
- `renew_secret_lease` — renew one known lease through
  `POST /v1/sys/leases/renew`;
- `revoke_secret_lease` — synchronously revoke one known lease through
  `POST /v1/sys/leases/revoke` with `sync=true`;
- `reconcile_secret_lease` — query `POST /v1/sys/leases/lookup` to resolve one
  specifically named uncertain renew/revoke operation;
- `resolve_unknown_secret_issue` — apply an independently established result
  for an issuance whose acknowledgement was lost before the provider lease ID
  became durable locally.

The provider remains authoritative for dynamic values and provider lease
existence. The local registry is authoritative for Hepta operation admission,
local consumer/scope binding, observed lease metadata and reconciliation state.

## Authority binding

Every operation has a deterministic binding helper:

- `dynamic_secret_lease_binding`;
- `lease_renew_binding`;
- `lease_revoke_binding`;
- `lease_reconcile_binding`;
- `unknown_issue_resolution_binding`.

Bindings cover the subject, consumer, enrolled HTTPS origin, pinned CA digest,
namespace, operation ID and operation-specific payload. Reconciliation also
binds `target_operation_id`, the exact previously admitted renew/revoke whose
outcome is being resolved. A lookup cannot be used as a generic mechanism to
reactivate another local lease state.

The adapter owns no signing key. The host obtains an independently signed
`SignedFinalUseGrant` for the exact binding.

Issuance claims the grant before provider dispatch and calls
`with_verified_use` after the provider response and immediately before secret
values enter the trusted callback. Renewal, revocation and lookup carry no
secret bytes; their one-time grant claim is the external-dispatch admission
point.

## Dynamic value boundary

`DynamicSecretLeaseRequest` lists the exact string fields that may cross the
trusted consumer boundary. The complete response body and selected strings are
held in zeroizing application-owned buffers. `DynamicSecretValues` is
non-cloneable and non-serializable; its `Debug` implementation prints only
field names and `[REDACTED]`.

Unrequested fields never enter `DynamicSecretValues`. Missing requested fields
deny delivery and fence an otherwise observed lease as `RevokeRequired`.

Zeroization applies to adapter-owned buffers only. TLS, HTTP, JSON and allocator
implementations may keep transient plaintext copies. This module does not claim
locked-memory or complete process-memory secrecy.

## Durable registry

`SecretLeaseRegistry::open_state_dir` owns a local registry containing:

- `lease-registry.lock` — process exclusion;
- `lease-registry.json` — committed metadata/operation state;
- `lease-registry.next` — complete replacement written and synced before
  rename.

On Unix the directory must have no group/world permission bits, files are
created owner-only, and successful mutation uses file sync, atomic replacement
and directory sync. A persistence error fences the live registry.

The registry intentionally stores no provider token, no raw dynamic value and
no long-lived unkeyed dynamic-secret fingerprint. Current bounds are 4,096
lease records, 8,192 operation records and an 8 MiB serialized registry.
Exhaustion fails closed. This is a bounded single-active local backend, not a
distributed active-active state authority.

## Write-ahead uncertainty fence

Each external-effect request supplies a bounded `operation_id`. Reusing an ID
with different request semantics is `OperationConflict`.

Before a request that can create, renew or revoke a provider lease is sent, the
registry durably records `OutcomeUnknown`. Therefore a crash after local
admission but before acknowledgement cannot make a later process believe the
mutation never happened.

A definitive provider-side client rejection may move the operation to
`Rejected`; for renew/revoke the prior local lease state is restored. Transport
loss, timeout, server-side uncertainty, oversized/incomplete success bodies or
malformed success bodies stay `OutcomeUnknown` and return
`OutcomeIndeterminate`.

There is no automatic retry loop for provider mutations.

## Issuance activation ordering

A provider lease is **not** made locally `Active` merely because the provider
returned credentials. Until final-use delivery succeeds and the terminal local
write completes, the recoverable state remains the pre-dispatch
`OutcomeUnknown` record.

If final-use authorization is revoked after network I/O, the callback reports
an indeterminate effect, required fields are missing, or the provider TTL
violates the local ceiling, a known observed lease is persisted as
`RevokeRequired` instead of `Active`.

Only a successful trusted callback followed by successful durable completion
commits the lease as `Active`. If the process dies before that durable
completion, restart sees the uncertainty fence and requires reconciliation; it
does not infer successful secret delivery.

## Lease state machine

The locally observed lease states are:

- `Active` — final-use delivery completed and the provider lease is eligible for
  normal renewal/revocation;
- `RenewOutcomeUnknown` — renewal was durably admitted but its terminal provider
  result was not observed;
- `RevokeOutcomeUnknown` — revocation was durably admitted but its terminal
  provider result was not observed;
- `RevokeRequired` — the provider lease is known but local policy refuses normal
  use and cleanup is required;
- `Revoked` — synchronous provider revocation completed;
- `ProviderAbsent` — provider observation established that the lease no longer
  exists.

Operation records use `OutcomeUnknown`, `Completed`, `Reconciled`, `Rejected`
and `ResolvedNoLease`. `Reconciled` means the original mutation was not
retroactively declared a direct success; a later provider observation resolved
its uncertainty.

## Lost issuance acknowledgement

Dynamic issuance is asymmetric: the provider may create credentials while the
HTTP acknowledgement carrying the new `lease_id` is lost. Repeating the
original dynamic endpoint could create a second independent credential lease,
so the adapter never retries it automatically.

If the acknowledgement is lost before the lease ID becomes durable locally, a
repeated operation ID returns `ReconciliationRequired`. Independent
provider/audit inspection must then submit one signed
`UnknownIssueResolutionRequest`:

- `NoLeaseObserved` marks the original issue operation `ResolvedNoLease`;
- `LeaseObserved { lease_id, ... }` adopts the observed orphan only as
  `RevokeRequired`.

An adopted orphan is never promoted to `Active` by `reconcile_secret_lease`.
Its generated secret values were not durably delivered through this process;
the safe next external mutation is revocation under a new exact grant.

## Renew/revoke reconciliation

Renewal and revocation start with a known provider lease ID, so an uncertain
result can be resolved without repeating the mutation.

`LeaseReconcileRequest` includes both:

- `operation_id` — the new read-only lookup operation; and
- `target_operation_id` — the exact previous `Renew` or `Revoke` operation that
  is still `OutcomeUnknown`.

The registry requires the target operation, lease ID and current local unknown
state to agree. A `RenewOutcomeUnknown` lease may reconcile only a matching
unknown `Renew`; a `RevokeOutcomeUnknown` lease may reconcile only a matching
unknown `Revoke`. `RevokeRequired`, `Active` and terminal leases are not lookup
reactivation candidates.

A successful lookup:

- marks the target mutation `Reconciled`;
- records the new lookup operation `Completed`;
- if the provider lease exists, refreshes observed TTL/renewability and returns
  it to `Active` unless the TTL violates the local ceiling, in which case it is
  `RevokeRequired`;
- if the provider reports the lease absent, moves it to `ProviderAbsent`.

A failed lookup itself does not rewrite the local lease state and may be retried
under a new lookup operation ID and a fresh exact grant.

## TTL semantics

`LeaseRenewRequest::increment_seconds` follows OpenBao semantics: it requests
the desired remaining TTL from the current time; it is not an amount to add to
the old TTL. Zero asks for the provider default. Provider policy may cap the
result.

Issuance carries `max_lease_duration_seconds` as a local policy ceiling. A
provider result above that ceiling is never delivered to the secret consumer.
Renewal and reconciliation retain and enforce the same ceiling.

## Required caller behavior

| Error/state | Required action |
| --- | --- |
| `OutcomeIndeterminate` | Do not repeat the mutation; inspect registry and reconcile. |
| `ReconciliationRequired` | Resolve the existing unknown operation instead of creating a duplicate mutation. |
| `OperationConflict` | Reject reuse of the operation ID with changed semantics. |
| `LeaseNotActive` | Reconcile or clean up the recorded state; do not bypass the state machine. |
| `LeaseDurationExceeded` | Treat the lease as `RevokeRequired` and revoke it. |
| `ConsumerIndeterminate` | Treat consumer effect as uncertain and clean up the associated lease before reissuing. |
| `StateUnavailable` / `StateCorrupt` | Fail closed and repair storage without clearing history implicitly. |

## Verification boundary

Focused native tests cover real pinned loopback TLS dynamic issuance,
requested-field-only delivery, absence of raw values from persistent state,
registry reopen, durable issuance timeout, duplicate-operation rejection,
exact renew/revoke endpoints, renew-timeout lookup reconciliation, explicit
transition of the original mutation to `Reconciled`, and proof that an adopted
orphan `RevokeRequired` lease cannot be lookup-promoted to `Active`.

The existing real-service fixture is KV-focused. A production dynamic-engine
qualification receipt, named production caller and production HA/state-owner
architecture remain separate work. Source tests and this document are not an
independent production-acceptance claim.
