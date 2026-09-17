# HeptaBao dynamic SecretLease lifecycle V1

This document is the Lane-A implementation detail for the currently implemented dynamic lease boundary. It describes source behavior, not production activation or release authority.

## Admission and issue

`BaoLeaseManager::request_secret_lease` validates a bounded dynamic provider path and parameter map, rejects reserved provider control mounts, builds a final-use binding over subject, consumer, enrolled HTTPS destination, namespace, provider path, operation ID and request payload digest, then fsync-persists `IssuePending` before provider dispatch.

The independently signed final-use grant is claimed exactly once. There is no automatic provider retry. A confirmed provider response must contain a valid non-empty lease ID, positive lease duration and bounded string fields. Lease metadata is persisted before the raw fields can enter the enrolled synchronous consumer.

Raw dynamic values are available only through a borrowed `SecretLeaseView`; the normal receipt contains metadata, field count and byte count only.

## Durable state machine

```text
IssuePending
  -> Active
  -> IndeterminateIssue
  -> Rejected

Active / Orphaned
  -> RenewPending
       -> Active
       -> IndeterminateRenew
       -> prior live state on definite rejection

Active / Orphaned
  -> RevokePending
       -> Revoked
       -> IndeterminateRevoke
       -> prior live state on definite rejection

IndeterminateRenew
  -> Active / Orphaned when provider lookup confirms a live lease
  -> Revoked when provider lookup returns 404

IndeterminateRevoke
  -> prior live state when provider lookup confirms a live lease
  -> Revoked when provider lookup returns 404

IndeterminateIssue
  -> Orphaned only after an externally observed candidate lease ID is confirmed by provider lookup
  -> IndeterminateIssue otherwise
```

`Orphaned` means the provider lease is known and manageable but the original issue response containing credential bytes was lost; those bytes are never reconstructed or replayed to a consumer.

## Provider operations

The manager uses the reviewed OpenBao-compatible lease endpoints:

- `POST /v1/sys/leases/lookup`
- `POST /v1/sys/leases/renew`
- `POST /v1/sys/leases/revoke` with synchronous revocation requested

A provider 404 during reconciliation is treated as terminal evidence that the lease is not live and closes local state as `Revoked`.

Generic dynamic-secret issuance has no universal operation-key lookup that can prove non-creation after a lost acknowledgement. Therefore `IndeterminateIssue` is fail-closed and cannot be converted into a retry permit. Provider-specific idempotency requires a separately versioned contract.

## Persistence

The private local store contains:

- `leases.lock`: exclusive local process owner;
- `leases.meta.json`: schema and enrolled destination identity;
- `leases.events`: append-only, sequence-numbered, SHA-256-protected lifecycle events.

Every lifecycle event is appended and `sync_data` completes before the corresponding local transition is admitted. The journal contains only control metadata: operation identity, provider lease identity/path/namespace, consumer scope, expiry, renewability, generation and state. Provider tokens and dynamic secret values are not journal fields.

Corrupt sequence numbers, event digests or destination mismatches fail closed. A state directory cannot be reopened under another replica destination.

## Replay and active-active composition

Final-use replay state is owned by `kernel.authority`. Claims are persisted as fixed 40-byte `(authority_epoch, nonce)` records in `authority.claims`; revocation/trust metadata remains in the atomic `authority.json` snapshot. This removes the previous 16,384-claim semantic stop and O(N) claim snapshot rewrite.

One local state directory is still single-owner. Active-active operation uses authority/destination sharding: each active replica has a distinct signed destination such as `provider:heptabao:node-a`, private durable replay/lease state and grants scoped to that exact destination. Grants are therefore non-portable across active replicas.

Multiple writers sharing one authority/destination identity require a separately qualified strongly consistent shared backend and are not claimed by V1.

## Consumer and memory boundary

`EnrolledSecretConsumer` is trusted host code, not a sandbox. An enrolled callback can copy bytes via side effects, so production enrollment must be closed-world and audited.

Application-owned tokens, response buffers and decoded secret strings are zeroized on drop. This is not a guarantee that TLS/HTTP/parser/allocator/kernel internals contain no transient plaintext copies.

Secret-derived KV response/value digests are not part of ordinary serialized receipts and are redacted from `Debug` to avoid turning routine evidence into a low-entropy fingerprint oracle.

## Verification anchors

Source tests in `codex-rs/hepta-bao-adapter/src/lease_tests.rs` cover:

- dynamic issue and borrowed secret delivery;
- lost issue acknowledgement with no blind redispatch;
- renew uncertainty followed by provider lookup reconciliation;
- revoke uncertainty followed by provider-404 reconciliation;
- explicit orphan adoption after lost issue response;
- destination-sharded grant non-portability;
- destination-bound lease state and reserved-control-mount rejection.

`codex-rs/hepta-contracts/src/final_use_tests.rs` covers replay persistence and operation beyond the former 16,384-claim boundary.
