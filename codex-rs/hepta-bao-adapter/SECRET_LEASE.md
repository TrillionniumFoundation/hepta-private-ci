# HeptaBao dynamic SecretLease boundary

This document describes the source implemented in this crate. It deliberately
separates adapter source completion from HeptaBao server composition,
qualification, activation, and production authority.

## Current source implementation

The adapter now exposes a provider-neutral dynamic lease coordinator in
`src/lease.rs` with these mutation surfaces:

- `request_secret_lease`
- `renew`
- `revoke`
- `reconcile`

The existing exact-version KV v2 consumer remains unchanged. The legacy
metadata-only `resolve` / `assess_secret_boundary_v1` path also remains
non-dispatching; `PROVIDER_DISPATCH_ENABLED` still describes that legacy
surface only.

A dynamic provider is accepted only when it explicitly reports
`ProviderEffectIdempotencyCapability::KeyAndStatusLookup`. This is not a
feature flag the adapter upgrades on its own. The provider contract must
guarantee a stable occurrence key, same-key/different-payload conflict
handling, and an authoritative durable status lookup.

## Operation identity and no-blind-retry rule

One caller `operation_id` maps to one stable `ProviderEffectKey`. The
provider payload is not part of the key; its SHA-256 digest is part of the
intent payload digest. Therefore:

- same operation id + same semantic operation + same payload is one occurrence;
- same operation id + changed target, scope, TTL, or provider payload is a
  conflict;
- a restored pending intent is never sent automatically;
- Accepted and Indeterminate occurrences are lookup/reconcile only;
- a transport timeout, lost response, malformed post-entry acknowledgement, or
  secret/metadata mismatch is never converted into a retry.

This reuses the existing `hepta-contracts::provider_effect` state machine
rather than defining a second uncertainty model.

## Durable local state

`src/lease_store.rs` owns an adapter-local metadata journal. It contains no
raw secret values.

The current store is Linux fail-closed and uses:

- owner-only state directory (0700);
- owner-only regular files (0600), NOFOLLOW, link-count and owner checks;
- one OS-exclusive writer lock;
- append-only newline-terminated records;
- monotonically increasing sequence numbers;
- a SHA-256 hash chain across records;
- file fsync plus directory fsync before a mutation becomes visible;
- a 64 MiB journal ceiling and 1,000,000 record ceiling.

A newline-terminated frame is the publication boundary. On restart, an
unterminated final frame is conservatively truncated to the previous complete
frame. This can lose only the local acknowledgement publication, never invent
one: the previously durable intent remains, so the next action is provider
status reconciliation rather than a second mutation.

Any uncertain durable write poisons that live store instance. Reopen/replay is
required before further mutation.

Stored lease metadata includes provider lease identity, issue operation,
subject, consumer, namespace, scope digest, state, issue/expiry time,
renewability, generation, and secret digest. It never stores the secret value
or provider request payload.

## Issue ordering and secret delivery

For a new issue occurrence the order is:

1. validate provider capability and request bounds;
2. verify/claim the independently signed final-use grant;
3. fsync the exact local provider-effect intent;
4. make at most one provider dispatch;
5. validate key/payload-bound provider acknowledgement;
6. validate provider lease metadata and issued-secret digest;
7. fsync the acknowledgement and lease metadata atomically in one journal frame;
8. revalidate final-use authority;
9. invoke the synchronous trusted consumer with the issued secret.

The secret is held in a zeroizing application-owned buffer and has redacted
Debug output. It is not serialized into the journal or receipt.

If the provider completed issuance but the response was lost, a later status
lookup may establish Completed lease metadata. The adapter cannot reconstruct
the lost credential bytes and does not pretend to do so. The reconciled
receipt has `secret_delivered = false`. The safe recovery is to revoke that
lease and issue a new credential under a new operation id if credential
delivery is still required.

If final-use authority expires or is revoked after provider completion but
before step 9, the secret is not delivered. The durable lease still exists and
must be reconciled/cleaned up; retrying the original issue cannot replay secret
bytes from local state.

## Renew and revoke

Renew and revoke require the same provider occurrence-key/status-lookup
capability and fresh final-use grants.

Renew is bound to the existing lease subject, namespace, scope and consumer.
The provider must return the same lease identity and secret digest, a strictly
higher generation, Active state, and a later expiry. A provider that rotates
credential bytes during renew is not compatible with this contract; rotation
must use a new issue operation so delivery is explicit.

Revoke requires the same lease identity/bindings, a strictly higher
generation, and Revoked state. Local final-use revocation and provider lease
revocation are separate concepts; neither is treated as proof of the other.

## Reconciliation

`reconcile` is lookup-only. It accepts a fresh independently signed final-use
grant for the stored occurrence and never calls provider dispatch.

- provider Completed: persist a status-sourced acknowledgement plus validated
  lease metadata;
- provider Accepted: persist the authoritative Accepted observation;
- provider Rejected: persist terminal rejection;
- NotFound, payload conflict, or lookup failure: remain Indeterminate.

After an uncertainty marker, only a status-lookup-sourced acknowledgement may
advance the existing `ProviderEffectJournal`.

## Bounds and security notes

- maximum provider payload supplied to the adapter: 1 MiB;
- maximum requested TTL: 366 days, matching the currently reviewed
  HeptaBao plugin-host lease ceiling;
- provider payload bytes are not persisted, only their digest;
- secret digests are sensitive metadata for low-entropy credentials and should
  have bounded audit retention;
- zeroization covers adapter-owned buffers only. TLS, HTTP, plugin, allocator,
  kernel, crash-dump, or swap layers may create additional plaintext copies;
  this is not a locked-memory secrecy claim;
- the trusted consumer remains a privileged boundary and can exfiltrate by
  side effect if the host enrolls malicious code.

## Provider/runtime composition status

The currently reviewed HeptaBao source
`55f27e4258ea3f71ab7872cd7a44e8cbd4da1f18` already contains
`DurableDynamicSecretBroker` in `crates/heptabao-plugin-host/src/durable.rs`
with durable issue/renew/revoke and reconciliation mechanics.

That broker is not currently composed into the runnable `heptabao-server`
HTTP/service dependency closure used by this repository's current real-service
fixture. This adapter therefore implements the client-side lifecycle,
durability and provider contract, but it does not claim that a production
HeptaBao dynamic-lease endpoint is already activated.

The work package for this module declares
`codex-rs/hepta-bao-adapter/**` as its allowed write path. Wiring the
HeptaBao server to its dynamic broker is a separate co-owned integration
change and must not be hidden inside this adapter package.

## Verification

`src/lease_tests.rs` covers:

- metadata fsync before secret callback and absence of raw secret in the journal;
- exact-operation deduplication without second provider dispatch;
- same operation key with changed payload conflict;
- lost issue response, process restart, and lookup-only completion;
- issue -> renew -> revoke generation/state progression;
- provider secret digest mismatch quarantine;
- unsupported provider rejection before dispatch;
- Accepted -> status lookup -> Completed without re-dispatch.

Run the crate tests, all-target compile, formatting, locked dependency checks, and strict Clippy on the
exact branch candidate before treating this source as complete. Those results
are technical evidence only and do not grant provider activation or release
authority.
