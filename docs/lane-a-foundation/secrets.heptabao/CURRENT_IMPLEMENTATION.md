# `secrets.heptabao` current implementation

## Current executable contract

The module now has two executable provider paths.

The first is `BaoClient::consume_kv_v2`: a bounded read of one string field
from one exact KV-v2 version. It pins a supplied CA, validates the hostname,
disables ambient proxies and redirects, applies one bounded deadline and caps
the complete response at one mebibyte.

The second is the provider-native dynamic SecretLease lifecycle:

- `request_secret_lease` reads an enrolled dynamic-secret endpoint and
  persists metadata before returning;
- `renew_secret_lease` calls the provider lease-renew endpoint;
- `revoke_secret_lease` uses synchronous provider revocation;
- `reconcile_secret_lease` queries provider lease truth to settle an
  indeterminate renew or revoke.

All four lease operations are exposed through `BaoFinalUseHost`. The host
requires an independently signed final-use grant, a separate operator approval,
an enrolled consumer identity and current signed revocation state. Dynamic
credential bytes are delivered only to the registered consumer callback.
Ordinary return values and durable records contain lease metadata, not raw
provider credential data.

## Durable lease owner

`SecretLeaseStore` owns `heptabao_leases_1.sqlite3`. Its durable records
contain provider lease identity, namespace, registered consumer, request/scope
digests, keyed secret fingerprint, TTL, renewable flag, monotone rotation
generation, local state and revision.

The operation ledger records one caller-supplied operation identity with an
exact semantic digest and one of:

- `prepared`;
- `dispatching`;
- `applied`;
- `not_applied`;
- `indeterminate`.

Reusing an operation identity with changed semantics is a conflict. The
`prepared -> dispatching` transition is durable before the provider request.
After restart, a `dispatching` or `indeterminate` operation is recoverable
but is not automatically resent.

Renew/revoke uncertainty fences the affected local lease from normal use until
provider lookup reconciles it. A lookup showing an active lease restores the
observed provider TTL and renewable bit. A lookup showing absence fences the
local lease as revoked.

Dynamic issuance has a different recovery limit. If the provider created a
credential but the response containing the provider lease ID was lost, generic
lease lookup has no stable ID to query. That operation remains indeterminate
until an independently trusted provider/audit observation proves applied or
not-applied. The implementation deliberately does not create another dynamic
credential to discover the answer.

## Secret and fingerprint boundary

The dynamic response body is stored in a zeroizing byte buffer. The provider
`data` object is borrowed from that buffer and may cross only the registered
consumer callback.

Secret-derived metadata uses `BaoReceiptKey`, a host-provisioned HMAC-SHA-256
key. Durable metadata retains the key identifier and keyed fingerprint, not a
plain SHA-256 secret fingerprint. This reduces offline enumeration risk for
low-entropy credentials. The HMAC key is not serialized by the adapter and its
`Debug` representation is redacted.

The keyed fingerprint is still correlation metadata and must be treated as
sensitive. Rotation/retention policy belongs to the selected host and key
custody boundary.

Local zeroization is application-buffer hygiene. It does not prove that TLS,
HTTP, allocator or operating-system internals made no transient plaintext
copies.

## Registered final-use host

`BaoFinalUseHost` removes the arbitrary-closure assumption from product
composition. A signed `consumer_id` must resolve in a closed
`RegisteredBaoConsumer` registry. The host separately verifies operator
approval for the exact grant and accepts revocation state only through the
pinned signed revocation feed.

For KV reads, the kernel revalidates live authority immediately before consumer
entry. The consumer callback is not executed while holding the authority
mutex; that live check is the local consumer-entry linearization point.

For dynamic provider operations, the lease operation identity is durably fenced
before external dispatch. Once a provider-side effect may have been admitted,
timeout or protocol ambiguity is recorded as indeterminate rather than inferred
as failure.

## Public symbols and source bindings

- KV-v2 transport: `BaoToken`, `BaoReadRequest`, `BaoSecretReceipt`,
  `BaoClient`, `BaoClientError` in
  `codex-rs/hepta-bao-adapter/src/https_consumer.rs`;
- dynamic lease API: `BaoSecretLeaseRequest`,
  `BaoSecretLeaseRenewRequest`, `BaoSecretLeaseRevokeRequest`,
  `BaoSecretLeaseReconcileRequest`, `BaoReceiptKey`, `BaoLeaseError` in
  `codex-rs/hepta-bao-adapter/src/lease_client.rs`;
- durable metadata and operation state: `SecretLeaseStore`,
  `SecretLeaseMetadataV1`, operation/state enums in
  `codex-rs/hepta-bao-adapter/src/lease_store.rs`;
- closed consumer/approval composition: `BaoFinalUseHost`,
  `RegisteredBaoConsumer` in
  `codex-rs/hepta-bao-adapter/src/final_use_host.rs`;
- final-use grant and replay/revocation owner:
  `codex-rs/hepta-contracts/src/final_use*.rs`;
- independent approval and revocation-feed verification:
  `codex-rs/hepta-contracts/src/final_use_control.rs`.

## Current source-completion boundary

The source now implements the module-owned SecretLease issuance, renew, revoke,
local lease registry and reconciliation model. This does **not** establish
production activation.

The following remain outside the module-owned source-completion claim:

- selection and qualification of a named product-process caller;
- real provider-native dynamic-engine qualification on the exact enrolled
  OpenBao/HeptaBao source pin;
- protected provisioning/rotation of `BaoReceiptKey`, issuer, approver and
  revocation-distributor trust;
- external anti-rollback/trusted-time/fleet revocation qualification;
- the shared `kernel.authority` replay-store scalability/active-active work,
  which is owned by `security-authority`;
- independent acceptance, canary, promotion and release.

The current kernel replay compatibility store still has its own 16,384
claim-per-epoch ceiling and local single-active persistence model. The new
SecretLease SQLite store does not hide or bypass that kernel limitation.

## Verification

Source tests cover:

- exact-version KV-v2 HTTPS reads, TLS pinning, response bounds, replay,
  revocation races and consumer uncertainty;
- dynamic issuance through a real loopback TLS server without persisting raw
  provider credentials;
- keyed fingerprints;
- durable operation identity and semantic-drift conflict;
- restart with a `dispatching` operation and no blind resend;
- monotone rotation generation;
- renew ambiguity fencing and lookup reconciliation;
- revoke ambiguity and terminal absence fencing.

Exact-head and deterministic synthetic-merge execution receipts are required
before the source candidate may be reported as qualified. Recorded historical
fixtures are not evidence for a newer commit.
