# secrets.heptabao current implementation

This document is the authoritative source-status companion to `TECHNICAL.md`.
`TECHNICAL.md` may describe the mature architecture; this file states what the
current native source actually implements. A symbol listed here is still not a
production activation or release claim.

## Source baseline

The implementation lives in `codex-rs/hepta-bao-adapter` and consumes the
kernel-owned final-use authority from `codex-rs/hepta-contracts`. The reviewed
external authority is pinned by `external/HeptaBao/EXTERNAL_SOURCE.json` and is
used only through the host-enrolled HTTPS boundary.

## Implemented public surfaces

### Exact KV v2 read

`BaoClient::consume_kv_v2` performs one exact-version KV v2 HTTPS read and
releases one string field only to the supplied trusted synchronous consumer
under `FinalUseAuthority::with_verified_use`.

`BaoClient::new_for_destination` additionally binds the client and signed
final-use grants to one concrete destination identity such as
`provider:heptabao:node-a`. `BaoClient::new` remains the compatibility constructor
for the unsharded `provider:heptabao` destination.

### Dynamic secret lease lifecycle

`BaoLeaseManager` implements:

- `request_secret_lease`
- `renew_secret_lease`
- `revoke_secret_lease`
- `reconcile_secret_lease`
- `reconcile_indeterminate_issue`
- metadata lookup by issue operation or provider lease identity

Dynamic provider output is decoded into zeroizing application-owned buffers and
is visible only through `SecretLeaseView`, a borrowed view passed to an
`EnrolledSecretConsumer`. There is no owned raw-secret return type and ordinary
lease receipts contain metadata only.

The dynamic request adapter intentionally denies the provider control mounts
`sys`, `auth`, `identity` and `cubbyhole`. Lease administration uses only the
narrow system lease endpoints implemented inside `BaoLeaseManager`.

## Lease state machine

The durable state model is:

```text
IssuePending
  -> Active                 confirmed provider issue response
  -> IndeterminateIssue     response/transport outcome unknown
  -> Rejected               authority or definite provider rejection

Active / Orphaned
  -> RenewPending
       -> Active             confirmed renew response
       -> IndeterminateRenew unknown provider outcome
       -> prior state        definite rejection before an effect is possible

Active / Orphaned
  -> RevokePending
       -> Revoked            confirmed revoke or provider 404
       -> IndeterminateRevoke unknown provider outcome
       -> prior state        definite rejection before an effect is possible

IndeterminateRenew
  -> Active / Orphaned       provider lookup confirms a live lease
  -> Revoked                 provider lookup returns 404

IndeterminateRevoke
  -> prior live state        provider lookup confirms the lease still exists
  -> Revoked                 provider lookup returns 404

IndeterminateIssue
  -> Orphaned                an operator supplies a candidate provider lease ID
                             and provider lookup confirms it
  -> IndeterminateIssue      no candidate can be proved; never blind retry
```

`Orphaned` means the external lease is real and manageable but the original
issue response, including its credential bytes, was lost. Reconciliation never
pretends those bytes can be reconstructed.

## Ambiguous provider outcomes

Provider mutations are never automatically retried after dispatch. Before the
network effect, the operation identity and pending state are fsync-persisted.
A timeout, transport loss, server-side 5xx or malformed/oversized successful
response after dispatch changes the local state to the corresponding
`Indeterminate*` state.

Renew and revoke are reconciled with `/v1/sys/leases/lookup`. A missing lease is
terminally recorded as revoked. A present lease refreshes provider-authoritative
TTL/renewability metadata.

Generic OpenBao-compatible dynamic issuance has no universal operation-key
lookup that can prove whether an arbitrary plugin issued a credential after a
lost acknowledgement. Therefore an indeterminate issue is **not** automatically
retried. An externally observed candidate lease ID can be verified through the
lease lookup API and adopted as `Orphaned`; otherwise it remains indeterminate.
Provider-specific idempotency may be added only as an explicitly versioned
adapter contract.

## Durable local lease metadata

`lease_store.rs` owns a private local Unix state directory containing:

- `leases.lock` — exclusive local owner lock;
- `leases.meta.json` — schema and bound destination identity;
- `leases.events` — append-only, sequence-numbered, SHA-256-protected lifecycle
  events.

The event journal contains lease IDs, provider path, namespace, consumer scope,
expiry, renewability, generation and operation identities. It never persists
dynamic secret values or provider tokens. Writes are append + `sync_data` before
an external operation is considered admitted.

The store is destination-bound. Opening one replica's state with another
replica identity fails closed.

## Final-use replay persistence

`FinalUseAuthority` now separates trust/revocation metadata from replay claims:

- `authority.json` schema 2 contains signer identity, verifying key and the
  current revocation head;
- `authority.claims` is an append-only fixed-width journal containing
  `(authority_epoch, nonce)` records;
- each claim appends one 40-byte record and calls `sync_data` before dispatch;
- restart reconstructs only the current epoch's replay set;
- future-epoch journal records fail closed as rollback/corruption evidence;
- the legacy schema-1 JSON nonce set is migrated to the journal on open.

This removes the former 16,384-claim epoch stop and the O(N) full-JSON rewrite
from the steady-state claim path. A bounded 1 GiB journal guard remains a local
resource/corruption ceiling, not a 16,384-operation semantic limit.

## Active-active boundary

A single local authority state directory remains single-owner by design. It is
not a distributed multi-writer database.

For active-active deployment, the implemented safe composition is **authority
sharding by destination**: every active replica has a distinct final-use
destination such as `provider:heptabao:node-a`, its own private replay/revocation
state, and grants signed for that exact destination. Because destination identity
is part of the request and scope binding, a grant for one replica fails binding
validation on another replica.

If a deployment requires multiple writers to share the *same* authority
identity, it needs a separately qualified strongly consistent shared backend;
this local implementation does not claim that capability.

## Trusted consumer boundary

The Rust callback runs inside the trusted host process. `EnrolledSecretConsumer`
prevents ordinary lease call sites from casually substituting an arbitrary
consumer identity, but it is not a sandbox: trusted callback code can still copy
bytes through side effects. Production composition must enroll only audited host
consumers; untrusted plugins require a process/sandbox boundary outside this
library.

The older `consume_kv_v2` closure remains a compatibility API and has the same
trusted-host assumption. It must not be exposed as a generic plugin callback.

## Fingerprint governance

`BaoSecretReceipt` still computes response/secret SHA-256 values in-process for
integrity decisions, but `response_sha256` and `secret_sha256` are excluded from
ordinary serialization and redacted from `Debug`. This prevents routine logs,
receipts and exports from becoming a low-entropy secret fingerprint oracle.

Any future export of a secret-derived digest is a security-sensitive contract
change and requires an explicit retention/threat analysis. A keyed digest should
be preferred where cross-system stable correlation is not required.

## Zeroization claim boundary

The implementation zeroizes application-owned provider tokens, bounded response
buffers and decoded secret strings when their owners are dropped. This is **not**
a claim that plaintext never exists anywhere in process memory. TLS, HTTP,
serde/parser internals, allocator behavior, kernel socket buffers and trusted
consumer code can create transient copies outside the adapter's ownership.
Production hardening should therefore combine short lifetimes, process isolation,
core-dump policy, memory-dump controls and audited consumers with application
buffer zeroization.

## Verification

Focused source tests cover:

- exact TLS KV reads and final-use revalidation;
- dynamic lease issue with borrowed secret delivery only;
- lost issue acknowledgement with no blind retry;
- renew timeout followed by provider lookup reconciliation;
- revoke timeout followed by missing-lease reconciliation;
- explicit orphan adoption after lost issue response;
- replica destination binding and destination-bound lease state;
- replay persistence across restart and process death;
- replay journals exceeding the former 16,384-claim limit without growing the
  authority metadata snapshot.

`.github/workflows/heptabao-lease-qualification.yml` runs exact-candidate format,
tests and strict Clippy for `codex-hepta-contracts` and
`codex-hepta-bao-adapter`. On success it emits
`secrets-heptabao-receipt.json`, binding the tested SHA/tree, external HeptaBao
pin and hashes of the executed command records. The receipt proves only source
candidate checks; it does not grant activation, operator acceptance or release.
