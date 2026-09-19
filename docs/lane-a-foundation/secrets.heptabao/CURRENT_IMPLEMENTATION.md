# `secrets.heptabao` current implementation

## Current executable contracts

The module now has two source-implemented adapter profiles.

1. `BaoClient::consume_kv_v2` performs a host-composed HTTPS read of one
   string field from one exact KV-v2 version. It pins a supplied CA, validates
   the hostname, disables ambient proxies and redirects, applies one bounded
   deadline and caps the complete response at one mebibyte.
2. `BaoClient::request_secret_lease`, `renew_secret_lease` and
   `revoke_secret_lease` implement provider-native lease operations over the
   same enrolled transport. The dynamic-secret issue path delivers decoded
   string fields only to a synchronous trusted consumer and returns an explicit
   `SecretLeaseIssueOutcome`. If provider issuance succeeded but registry
   publication or final delivery is blocked/indeterminate, the known lease
   identity is preserved for revoke/reconciliation instead of being lost behind
   a generic error. It never persists secret values.

Every lease effect has a caller-supplied `operation_id` and a canonical
semantic digest persisted before dispatch. The durable owner is
`LeaseRegistry`, a SQLite/WAL metadata store. Reusing an operation identity
with changed semantics conflicts. Renew/revoke transition the lease and
operation intent in one transaction.

## Lease state and ambiguous outcomes

Lease states are `Issuing`, `Active`, `Renewing`, `RevokePending`,
`Revoked`, `Expired` and `Unknown`. Operation states are `Prepared`,
`InFlight`, `Applied`, `Rejected` and `Unknown`.

A deterministic rejection before or at the provider boundary may become
`Rejected`. Once dispatch has entered an outcome that cannot be proven,
transport loss, timeout, malformed success response or uncertain server status
becomes `Unknown`; the adapter does not issue another provider effect.
Forward reconciliation may move an Unknown issue/renew/revoke to its observed
terminal state. Reconciliation entrypoints consume a separate, exact
`FinalUseGrant` bound to the observer subject, operation semantic digest and
provider lease observation; registry mutation methods are crate-private so an
ordinary external caller cannot directly manufacture terminal state.

For issuance, current HeptaBao source defines the required
`LEASE_ISSUING_READ` unknown-outcome semantics but does not expose its
operation-ledger/outcome readback as a direct HTTP endpoint. Therefore
`reconcile_issue_observation`, `reconcile_renew_observation` and
`reconcile_revoke_observation` are explicit host-authorized seams, not
automatic provider queries and not evidence that the provider observation is
self-authenticating. Product qualification must bind them to a real
provider-owned readback/observer. Product
qualification must provide a real provider observation or outcome endpoint
before automatic recovery can be claimed.

## Public symbols and source bindings

- KV v2 path: `BaoToken`, `BaoReadRequest`, `BaoSecretReceipt`,
  `BaoClient`, `BaoClientError` in
  `codex-rs/hepta-bao-adapter/src/https_consumer.rs`;
- lease provider path: `BaoLeaseIssueRequest`, `BaoLeaseRenewRequest`,
  `BaoLeaseRevokeRequest`, `DynamicSecretFields`,
  `SecretLeaseIssueOutcome`, `SecretLeaseIssueReceipt`,
  `SecretLeaseMutationReceipt` and `SecretLeaseClientError` in
  `codex-rs/hepta-bao-adapter/src/lease_client.rs`;
- durable metadata owner: `LeaseRegistry` and the lease/operation state
  records in `codex-rs/hepta-bao-adapter/src/lease_registry.rs`;
- final-use grant and durable replay/revocation owner:
  `codex-rs/hepta-contracts/src/final_use*.rs`.

## Final-use replay durability

`FinalUseAuthority` no longer rewrites its complete JSON state for every nonce
claim. `authority.json` is the compact trust/revocation checkpoint and
`claims.log` is the complete fixed-record replay journal. A claim is fsynced
before dispatch admission. Restart replays the journal into the in-memory
replay set. Revocation/head checkpointing keeps the nonce set out of JSON and
may rewrite the complete journal outside the per-claim hot path. Legacy JSON
snapshots containing `used_nonces` are migrated into the journal before a
compact snapshot is published.

There is no longer a 16,384 claim-per-epoch limit. The separate bound on
revoked grant identifiers remains 16,384. Local state still uses an exclusive
owner lock: this source implementation is single-active per state directory,
not an active-active distributed authority.

## Security boundary

Before a provider operation, `FinalUseAuthority` validates an independently
signed, single-use binding and durably burns its nonce. KV secret delivery and
dynamic-secret delivery revalidate live authority before entering their trusted
synchronous consumer.

The callback remains a privileged host capability. A signed `consumer_id`
does not make an arbitrary closure trusted; the product host must select the
callback from an authenticated registry and keep untrusted plugins/code outside
that process capability boundary.

Application-owned response and decoded secret buffers use zeroization on drop.
This is not a claim that TLS, HTTP, parser, allocator, kernel or swap layers
never held temporary plaintext copies.

Ordinary KV and dynamic-issuance receipts no longer export a digest of
secret-bearing provider responses or the delivered secret value. The expected
KV secret digest remains inside the independently signed request binding and is
checked before delivery. Any secret-dependent digest retained by a narrower
owner-only diagnostic/evidence profile remains sensitive metadata and must have
explicit retention/keying policy.

## Durability, HA and activation

Secret values and provider lease truth remain owned by the external Bao
service. Local `LeaseRegistry` owns only operation and lease metadata.
Final-use replay/revocation state remains owned by kernel authority.

The local SQLite lease registry and local final-use store are not a distributed
consensus system. Active-active deployment requires one of:

- a strongly consistent transactional replay/revocation backend;
- explicit authority sharding with non-overlapping signer/epoch ownership; or
- single-active ownership with fenced failover.

No active-active claim is made until one of those topologies has executable
split-brain/failover evidence.

## Verification and non-claims

Focused source tests cover KV transport/final-use behavior and durable lease
operation recovery, including changed-semantic operation-ID conflicts,
provider lease-identity collisions, quarantine-to-revoke recovery, rejected-
renew rollback, Unknown persistence across restart and forward reconciliation.
The Lane-A workflow emits exact-HEAD and deterministic synthetic-merge JSON
receipts as SHA-named retained CI artifacts. Provider/target-host qualification
and independent acceptance remain separate execution gates.

Current source does **not** establish: a HeptaBao HTTP outcome endpoint for
lost issuance replies, distributed final-use state, a production caller,
independent acceptance, canary, promotion or release.
