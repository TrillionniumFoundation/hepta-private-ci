# HeptaBao SecretLease lifecycle

This document describes the executable SecretLease lifecycle implemented by
`codex-hepta-bao-adapter`. It is the current implementation contract for
provider-native dynamic secrets, lease renewal, revocation, and reconciliation.
It supplements the exact-version KV v2 consumer documented in `README.md`; the
two paths share the enrolled pinned-HTTPS client and independent final-use
authority but have different external-effect semantics.

## Scope

The lifecycle exposes these `BaoClient` operations:

- `request_secret_lease` — issue one provider-native dynamic secret through a
  configured `GET /v1/{mount}/{path}` endpoint, persist lease metadata, and
  release only explicitly named string fields to one trusted synchronous
  consumer callback.
- `renew_secret_lease` — renew one known lease using
  `POST /v1/sys/leases/renew`.
- `revoke_secret_lease` — synchronously revoke one known lease using
  `POST /v1/sys/leases/revoke` with `sync=true`.
- `reconcile_secret_lease` — query `POST /v1/sys/leases/lookup` to resolve a
  known lease whose prior renew/revoke result is uncertain.
- `resolve_unknown_secret_issue` — apply an independently established result
  for an issuance whose acknowledgement was lost before a provider lease ID
  was observed locally.

The provider remains authoritative for dynamic secret values and external lease
existence. The local registry is authoritative only for Hepta's operation
admission history, local consumer binding, observed lease metadata and local
reconciliation state.

## Authority and final-use boundary

Every public operation has a deterministic binding method:

- `dynamic_secret_lease_binding`
- `lease_renew_binding`
- `lease_revoke_binding`
- `lease_reconcile_binding`
- `unknown_issue_resolution_binding`

The binding covers subject, consumer, enrolled HTTPS origin, pinned CA digest,
namespace, operation ID and the complete operation-specific payload. Provider
mutation is never authorized by a boolean or by the adapter itself. The host
obtains an independently signed `SignedFinalUseGrant` for the exact binding.

Issuance claims the grant before the provider request, then revalidates the live
authority through `with_verified_use` after the provider response and before
secret bytes enter the callback. If the grant is revoked while the provider is
running, the dynamic values are not delivered and the observed lease is fenced
as `RevokeRequired` so the host can clean it up.

Renew, revoke and lookup do not expose secret material. Their final-use claim is
the external-dispatch admission point; a consumed nonce is never refunded when
the provider call later fails or becomes uncertain.

## Dynamic secret exposure

A `DynamicSecretLeaseRequest` names the exact string fields that may cross the
trusted consumer boundary. The response body and decoded field strings are held
in zeroizing application-owned buffers. `DynamicSecretValues` is deliberately
non-cloneable and non-serializable, and its `Debug` implementation prints field
names plus `[REDACTED]`, never values.

Fields that were not requested are never copied into `DynamicSecretValues`.
Missing requested fields deny delivery and fence an otherwise valid observed
lease as `RevokeRequired`.

Zeroization applies to adapter-owned buffers only. TLS, HTTP, JSON and allocator
implementations may have internal transient plaintext copies. This module does
not claim locked-memory or process-memory secrecy.

## Durable local registry

`SecretLeaseRegistry::open_state_dir` owns a local registry directory with:

- `lease-registry.lock` — process exclusion lock;
- `lease-registry.json` — committed metadata/operation state;
- `lease-registry.next` — complete replacement written and synced before rename.

On Unix, the directory must have no group/world permission bits and files are
created owner-only. Writes use a complete temporary snapshot, file `fsync`,
rename and directory `fsync`. A persistence error fences the live registry. A
pre-existing lock marker without committed state is treated as corrupt rather
than silently reinitializing admission history.

The registry intentionally contains no provider token and no raw secret value.
It also avoids storing a digest of dynamic secret values, because long-lived
unkeyed fingerprints can leak information about low-entropy credentials.

Current bounded limits are 4,096 lease records, 8,192 operation records and an
8 MiB serialized registry. Exhaustion fails closed. This local backend is a
single-active owner, not an active-active distributed authority.

## Operation idempotency and the write-ahead uncertainty fence

Each external-effect request supplies a bounded `operation_id`. Reusing one ID
with different request semantics is `OperationConflict`. A completed or
terminal operation cannot be silently replayed.

Before a request that can create, renew or revoke a provider lease is sent, the
registry durably writes `OutcomeUnknown`. Therefore a process crash after local
admission but before receiving a response cannot make the next process believe
that the operation never happened.

A definitive provider-side client rejection can move the operation to
`Rejected` and, for renew/revoke, restore the prior local lease state. Transport
loss, timeout, server-side uncertainty, oversized/incomplete success bodies, or
malformed success bodies do **not** become a retryable failure: they remain
`OutcomeUnknown` and return `OutcomeIndeterminate`.

No mutating operation has an automatic retry loop.

## Lease state machine

The locally observed lease states are:

- `Active` — the provider lease was observed and is eligible for normal renew or
  revoke under a new exact grant.
- `RenewOutcomeUnknown` — a renew was durably admitted but its terminal provider
  result was not observed. Further renew is blocked until lookup reconciliation.
- `RevokeOutcomeUnknown` — revoke was admitted but its terminal result was not
  observed. Further mutation is blocked until lookup reconciliation.
- `RevokeRequired` — the provider lease is known but local policy refuses normal
  use, for example because the provider TTL exceeded the requested ceiling, a
  required secret field was absent, final-use authorization was revoked before
  delivery, the consumer reported an indeterminate effect, or an orphaned
  issuance was independently discovered after lost acknowledgement.
- `Revoked` — synchronous provider revoke completed.
- `ProviderAbsent` — provider lookup/revoke establishes that the lease is no
  longer present. This is terminal locally.

Each successful renew/reconciliation/revocation transition advances
`rotation_generation`; rollback must not resurrect an earlier generation.

## Issuance ambiguity and orphan handling

Dynamic issuance has an asymmetric failure mode: the provider may create a
lease and generate credentials, while the HTTP acknowledgement carrying the
new `lease_id` is lost. A generic retry of the original read endpoint may create
a second independent credential lease, so the adapter never performs that
retry.

If issuance becomes `OutcomeUnknown` before the lease ID is known, a repeated
`operation_id` returns `ReconciliationRequired`. The host must independently
inspect provider/audit state and then submit one exact signed
`UnknownIssueResolutionRequest`:

- `NoLeaseObserved` means independent reconciliation established that no lease
  was created. The original operation becomes terminal `ResolvedNoLease`.
- `LeaseObserved { lease_id, ... }` adopts the observed external lease only as
  `RevokeRequired`. It is never promoted to `Active`, because the raw dynamic
  values associated with that issuance were not durably delivered through this
  process. The safe next external action is revoke.

This design deliberately prefers a leaked-but-fenced provider lease requiring
operator reconciliation over duplicate unrestricted credential issuance.

## Renew and revoke reconciliation

Renew and revoke start from a known provider `lease_id`, so an uncertain result
can be reconciled without repeating the mutation. `reconcile_secret_lease`
performs the provider lookup under a fresh exact final-use grant:

- a present lease updates its observed TTL/renewability and returns it to
  `Active` unless the observed TTL exceeds the locally configured ceiling, in
  which case it becomes `RevokeRequired`;
- a provider `404` becomes `ProviderAbsent`;
- transport or malformed lookup failures do not alter the local lease record.

A later mutation requires a new operation ID and a new signed grant.

## TTL semantics

`LeaseRenewRequest::increment_seconds` follows OpenBao lease semantics: it asks
for the desired remaining TTL from the current time and is not interpreted as
an amount to add to the old TTL. Zero requests the provider default. The
provider may cap the result according to its role/mount/system maximum TTL.

Issuance includes `max_lease_duration_seconds` as a local policy ceiling. A
provider response above that ceiling is persisted as `RevokeRequired` and is
never delivered to the trusted secret consumer. Renewal and reconciliation use
the same ceiling retained on the lease record.

## Failure classification

Important caller actions:

| Error/state | Required caller behavior |
| --- | --- |
| `OutcomeIndeterminate` | Do not repeat the mutation. Inspect the registry and reconcile. |
| `ReconciliationRequired` | Resolve the existing unknown operation instead of creating another one. |
| `OperationConflict` | Reject the caller: the operation ID was reused with different semantics. |
| `LeaseNotActive` | Reconcile or clean up the recorded lease state; do not bypass the state machine. |
| `LeaseDurationExceeded` | Treat the observed lease as `RevokeRequired` and revoke it. |
| `ConsumerIndeterminate` | Treat consumer effect as uncertain and revoke the associated lease before reissuing. |
| `StateUnavailable` / `StateCorrupt` | Fail closed and repair the registry without clearing history implicitly. |

## Verification requirements

Focused native tests cover:

- real pinned loopback TLS dynamic issuance;
- requested-field-only delivery and absence of raw values from persistent state;
- registry persistence across process-style reopen;
- issuance timeout leaving durable `OutcomeUnknown` and blocking duplicate use;
- exact renew/revoke provider endpoints and request bodies;
- renew timeout followed by provider lookup reconciliation without automatic
  renew retry;
- independently observed lost-ack issuance adopted only as `RevokeRequired`.

Before production composition, keep the existing exact-head workspace/lint
qualification requirements. The local registry remains a single-active pilot
backend; active-active/distributed replay and lease-state ownership is a
separate production architecture decision rather than an implicit property of
this implementation.
