# `secrets.heptabao` current implementation

## Current executable contract

The source implementation has two separate provider paths.

- `BaoClient::consume_kv_v2` reads one string field from one exact KV-v2
  version over pinned direct HTTPS. KV v2 is versioned static-secret retrieval
  and does not create a provider-native lease.
- `BaoClient::request_secret_lease`, `renew_secret_lease`,
  `revoke_secret_lease` and `reconcile_secret_lease` implement the
  provider-native dynamic lease lifecycle.

The dynamic path writes a durable lifecycle intent before each provider
mutation. Creation returns an explicit durable insert winner, so only one
concurrent caller can cross the issuance boundary. Later mutations use revision
compare-and-swap.

## Public symbols and source bindings

- KV v2 transport/final-use consumer:
  `codex-rs/hepta-bao-adapter/src/https_consumer.rs`;
- dynamic lease issue/renew/revoke/reconcile:
  `codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs`;
- lifecycle contract and strong-CAS store interface:
  `codex-rs/hepta-contracts/src/secret_lease.rs`;
- SQLite CAS owner:
  `codex-rs/hepta-evidence/src/secret_lease_store.rs` and migration
  `0011_secret_lease_registry.sql`;
- final-use nonce/revocation owner:
  `codex-rs/hepta-contracts/src/final_use*.rs`.

## Durability and recovery

`SecretLeaseRecord` persists metadata only: logical/provider identity,
namespace/path, provider lease ID when observed, lifecycle state, TTL,
generation, revision and pending-operation identity/digest. Raw dynamic secret
values are never record fields.

Executable states are `Requesting`, `Active`, `Renewing`,
`RevokePending`, `Unknown`, `Revoked`, `Expired` and `Rejected`.
Timeout, transport loss, provider 5xx or an unusable successful reply never
causes a blind mutation retry. A generic issuance response lost before a
provider lease ID is observed requires provider-specific/operator
reconciliation.

The current lease registry uses SQLite `BEGIN IMMEDIATE` plus revision CAS.
It safely coordinates handles/processes sharing one database; it is not a
multi-host distributed-consensus backend.

FinalUse schema 2 keeps the bounded revocation head in `authority.json` and
appends each 32-byte nonce claim to `authority.claims`. Claims no longer
rewrite the complete replay set and have no 16,384-claim logical ceiling.
The filesystem authority remains single-active per private state directory.

## Secret and authority boundary

Dynamic values are delivered only through the synchronous trusted
`BaoSecretFields` callback after the lease metadata is durable and final-use
authority is rechecked. The callback is a privileged host capability, not a
sandbox.

Application-owned request values, response buffers and selected dynamic
strings use zeroizing owners. TLS, HTTP, JSON-parser, allocator and trusted
consumer code can still make temporary plaintext copies; the implementation
does not claim complete RAM secrecy.

The dynamic lifecycle does not retain a per-value SHA-256 fingerprint. Provider
lease IDs are privileged metadata and are redacted from `SecretLeaseRecord`
Debug output.

## Current limits and non-claims

- local FinalUse is single-active and does not qualify NFS/distributed locking;
- SQLite lease CAS is not active-active multi-host consensus;
- generic lost-response issuance without an observed provider lease ID cannot
  be safely auto-reissued;
- the trusted callback and trust configuration remain protected host inputs;
- source/tests do not establish production activation or independent acceptance.

## Verification

Focused source tests cover exact KV-v2 TLS/final-use behavior, dynamic issuance
winner serialization, ambiguous response quarantine, FinalUse schema-1 to
schema-2 migration/journal durability and multi-handle lease CAS.

Exact-candidate qualification is a separate CI receipt bound to the checked-out
commit/tree and security-sensitive source digests. Historical evidence does not
establish that a later HEAD passed.

## Integration prerequisites

Production composition must provide protected provider credentials/trust,
registered callback selection, a deployment-appropriate lease store, operator
reconciliation for irreducible unknown issuance outcomes, target-host
qualification and independent acceptance. Secret bytes must never enter general
logs, prompts, learning records or ordinary receipts.
