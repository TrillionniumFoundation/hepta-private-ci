# Authorized HeptaBao HTTPS consumer and lease manager

The legacy `resolve` and `assess_secret_boundary_v1` remain metadata-only;
`PROVIDER_DISPATCH_ENABLED` remains false for that API. A caller-provided
`Granted` observation cannot enable either executable client below.

Current native source has two separate host integration surfaces:

- `BaoClient::consume_kv_v2` — exact-version KV v2 read and final-use delivery;
- `BaoLeaseManager` — dynamic provider secret issuance plus lease
  renew/revoke/reconciliation.

See [`docs/modules/secrets.heptabao/CURRENT_IMPLEMENTATION.md`](../../docs/modules/secrets.heptabao/CURRENT_IMPLEMENTATION.md)
for the authoritative source-status/capability boundary.

## Transport and trust

Both paths use the approved `codex-http-client` owner through
`HttpClientBuilder::build_pinned_https_direct`; the adapter has no direct
`reqwest` dependency. The transport trusts only the supplied CA, disables
ambient proxies, redirects and protocol retries, and applies one deadline
through response-body reads. Responses are bounded to 1 MiB.

Before external dispatch, `kernel.authority`
(`hepta-contracts::FinalUseAuthority`) verifies an independent Ed25519
signature and durably claims a single-use nonce. The adapter owns no signing
key. The host pins public trust, epoch and revocation head; request JSON cannot
replace these trust inputs.

`BaoClient::new_for_destination` binds one concrete authority shard/replica such
as `provider:heptabao:node-a`. Destination identity participates in the signed
request/scope binding, so a grant issued for node A does not validate at node B.
`BaoClient::new` remains the unsharded compatibility constructor using
`provider:heptabao`.

## Exact KV v2 read

`BaoClient::consume_kv_v2` reads
`GET /v1/{mount}/data/{path}?version=N`, supplies `X-Vault-Token` and optional
`X-Vault-Namespace`, verifies the exact returned version and expected secret
digest, then performs a live revocation/time/epoch recheck before invoking the
trusted synchronous consumer.

The supported KV contract remains one string field from one exact KV v2
version. Other field types and secret engines are not silently coerced.

Application-owned response buffers and decoded secret strings are zeroized on
drop. This is not a locked-memory or "plaintext never existed in RAM" claim:
TLS/HTTP/parser/allocator/kernel internals and trusted callback code can create
transient copies outside adapter ownership.

`BaoSecretReceipt` computes response/secret SHA-256 values for in-process
integrity use, but those two secret-derived fingerprints are excluded from
ordinary serialization and redacted from `Debug`. Routine logs/receipts therefore
do not become a low-entropy secret fingerprint oracle.

## Dynamic secret lease lifecycle

`BaoLeaseManager::open(client, state_directory)` opens an owner-private,
destination-bound durable lease metadata store. It implements:

- `request_secret_lease`
- `renew_secret_lease`
- `revoke_secret_lease`
- `reconcile_secret_lease`
- `reconcile_indeterminate_issue`

Dynamic issue requests are bounded and deny the provider control mounts `sys`,
`auth`, `identity` and `cubbyhole`. The lease manager itself uses only the
narrow OpenBao-compatible lease administration endpoints:

- `POST /v1/sys/leases/lookup`
- `POST /v1/sys/leases/renew`
- `POST /v1/sys/leases/revoke` with `sync=true`

Raw dynamic provider fields are decoded into zeroizing values and exposed only
through a borrowed `SecretLeaseView` supplied to an `EnrolledSecretConsumer`.
There is no owned raw-secret receipt or durable raw-secret lease record.

Example shape:

```rust,ignore
let manager = BaoLeaseManager::open(client, lease_state_dir)?;
let request = SecretLeaseRequest { /* subject, consumer, op id, path, params */ };
let binding = manager.issue_binding(&request)?;
// Obtain a SignedFinalUseGrant for exactly this binding from the independent owner.
let consumer = manager.enroll_consumer("model-provider".into(), |lease| {
    provider.configure(
        lease.get("username").ok_or(())?,
        lease.get("password").ok_or(())?,
    )
})?;
let receipt = manager
    .request_secret_lease(&authority, &grant, &request, consumer)
    .await?;
// `receipt` is metadata-only; provider fields are no longer owned here.
```

The enrolled callback remains trusted host code, not a sandbox. An already
trusted callback can copy bytes through side effects. Do not expose this as a
generic in-process plugin callback; untrusted consumers need a process/sandbox
boundary outside this crate.

## Durable lifecycle and ambiguous outcomes

The durable lease states are:

- `IssuePending`
- `Active`
- `RenewPending`
- `RevokePending`
- `IndeterminateIssue`
- `IndeterminateRenew`
- `IndeterminateRevoke`
- `Orphaned`
- `Revoked`
- `Expired`
- `Rejected`

Before a provider mutation, the operation identity and pending lifecycle event
are fsync-persisted and the final-use nonce is burned. There is no automatic
mutation retry.

Timeout, transport loss, server-side uncertainty or an unusable successful
response after dispatch creates an `Indeterminate*` state. Renew/revoke
uncertainty is reconciled from `/v1/sys/leases/lookup`: a live provider lease
refreshes provider-authoritative TTL/renewability; 404 records `Revoked`.

Generic OpenBao-compatible dynamic issuance exposes no universal operation-key
lookup that proves whether an arbitrary plugin created a lease after a lost
acknowledgement. Therefore `IndeterminateIssue` is never blindly retried. An
operator/provider-specific observer may supply a candidate provider lease ID;
the adapter verifies it through lease lookup and adopts it as `Orphaned`. The
lost credential bytes are not reconstructed and are never re-delivered.

## Lease metadata persistence

The private Unix lease state directory contains:

- `leases.lock` — exclusive local process owner;
- `leases.meta.json` — schema plus enrolled destination identity;
- `leases.events` — append-only, sequence-numbered and digest-protected
  lifecycle journal.

Durable events contain lease/provider identity, consumer scope, expiry,
renewability, generation, operation identity and lifecycle state only. Provider
tokens and raw dynamic secret values are never journal fields. A state directory
opened under a different destination fails closed.

One local state directory is intentionally single-owner. Active-active
composition uses distinct replica destinations and private per-replica state.
Multiple concurrent writers sharing the same authority/destination identity
require a separately qualified strongly consistent shared backend; this crate
does not claim to provide one.

## Final-use replay persistence

`FinalUseAuthority` persists trust/revocation metadata separately from replay
claims. `authority.json` schema 2 contains the small trust/revocation snapshot;
`authority.claims` appends one fixed 40-byte `(epoch, nonce)` record and
`sync_data`s it before dispatch.

This removes the old 16,384-claim epoch stop and the O(N) full JSON rewrite from
the steady-state claim path. A 1 GiB journal guard remains a fail-closed local
resource/corruption ceiling. Schema-1 nonce snapshots are migrated to the
journal on open without silently clearing replay history.

Deleting/restoring the state directory from an old snapshot is still an
authority reset and requires independent issuer trust/epoch recovery.

## Independent issuer

The separate `hepta-final-use-signer` binary in `hepta-supervisor` remains
behind the existing `production-authority` feature:

```text
hepta-final-use-signer sign --key OWNER_ONLY_SEED_FILE < grant-proposal.json
```

It signs the complete bounded proposal and never derives authority from a
boolean. Signing material remains outside this adapter and normal runtime.

## Verification

Focused source tests cover:

- real loopback TLS KV exchange and exact headers/version;
- signature/replay/revocation/final-use races;
- dynamic issue with borrowed enrolled-consumer delivery only;
- lost issue acknowledgement with no blind redispatch;
- renew timeout followed by provider lookup reconciliation;
- revoke timeout followed by provider 404 reconciliation;
- explicit orphan adoption after a lost issue response;
- destination-sharded grants and destination-bound lease state;
- replay persistence after restart/process death;
- replay journal operation beyond the former 16,384-claim limit without
  per-claim metadata snapshot growth.

The focused exact-candidate workflow is
`.github/workflows/heptabao-lease-qualification.yml`. It runs format, tests and
strict Clippy for `codex-hepta-contracts` and `codex-hepta-bao-adapter`, then
emits `secrets-heptabao-receipt.json` containing the source/tested SHA, tested
tree, external HeptaBao pin and SHA-256 hashes of the executed command records.
That receipt is source evidence only; it does not claim product composition,
operator acceptance, activation, promotion or release.

Historical candidate records remain under `qa/evidence/` and retain their
original scope/limitations. They must not be substituted for the current exact
candidate receipt.

The separate real-service fixture remains available:

```text
python codex-rs/hepta-bao-adapter/qa/real_service_smoke.py \
  --service-checkout /absolute/HeptaBao \
  --server /absolute/heptabao-server \
  --consumer /absolute/consume_secret \
  --signer /absolute/hepta-final-use-signer \
  --work-dir /absolute/new-private-test-directory
```

It is an isolated synthetic fixture and never connects to an existing production
service.
