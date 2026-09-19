# HeptaBao dynamic SecretLease lifecycle

This document describes the **implemented** provider-native dynamic-secret runtime in
lease_lifecycle.rs. It is separate from the legacy metadata-only resolve helper
and from the exact-version KV v2 consume_kv_v2 path.

## Runtime API

BaoClient exposes these host-enrolled operations:

- request_secret_lease: GET /v1/{mount}/{path} and require a real provider
  lease_id, positive TTL, and all declared string secret fields.
- renew_secret_lease: POST /v1/sys/leases/renew.
- revoke_secret_lease: POST /v1/sys/leases/revoke with sync=true.
- reconcile_secret_lease: POST /v1/sys/leases/lookup for a provider lease
  identity already known locally.
- resolve_unknown_issue: a signed recovery operation for the one generic case
  that stock OpenBao cannot resolve by lease lookup: issuance may have reached
  the provider, but the response and therefore the provider lease_id were lost.

Every provider call uses the same enrolled BaoClient transport as the KV v2
consumer: explicit CA trust, hostname-valid HTTPS, no redirects, no ambient proxy,
no automatic HTTP retry, bounded response bytes, redacted provider token, and no
ambient trace propagation.

Every effect requires an independently signed FinalUseAuthority grant bound to
the exact operation request. A claimed grant is never refunded after uncertain
dispatch.

## Secret delivery boundary

A dynamic response is accepted only if it contains a non-empty provider lease ID,
a bounded positive lease duration, and every requested field as a string.

Raw dynamic values:

- are held only in zeroizing response-owned application buffers;
- are exposed only through the synchronous BaoDynamicSecret callback;
- are never returned in BaoLeaseReceipt or BaoLeaseMutationReceipt;
- are never written to the lease journal.

The callback remains a privileged trusted boundary. It can intentionally copy or
exfiltrate bytes, so host enrollment of the final consumer remains security
critical. Zeroization covers application-owned buffers; it is not a claim that
TLS, HTTP, parser, allocator, or kernel layers never hold transient plaintext.

## Durable state machine

The local state machine uses:

- IssuePrepared
- Issuing
- IssuedPendingDelivery
- Delivering
- Active
- RenewPrepared
- Renewing
- RevokePrepared
- RevokePending
- ReconciliationRequired
- Revoked
- Expired
- Failed

ReconciliationRequired carries an explicit reason:

- IssueOutcomeUnknown
- RenewOutcomeUnknown
- RevokeOutcomeUnknown
- SecretDeliveryLost
- DeliveryAuthorizationLost
- ConsumerOutcomeUnknown
- RevokeStillActive
- OrphanedActiveLease

The dispatch ordering is deliberate:

1. persist the operation intent;
2. claim the signed final-use nonce;
3. persist Dispatching;
4. perform exactly one provider request.

A crash before step 3 is safe to resume because no provider dispatch has begun.
A crash or transport ambiguity after step 3 never triggers a blind provider retry.

Before the trusted callback starts, the registry durably enters Delivering. A process death in that window recovers as ConsumerOutcomeUnknown rather than assuming the callback had not begun.

When a valid issuance response exposes a provider lease_id, that identity is
persisted **before** validating TTL and secret payload details. If later
validation/delivery fails, the lease is retained as an orphaned active lease so
it can still be looked up or revoked instead of becoming an untrackable
credential.

## Idempotency and ambiguous outcomes

operation_id is a local idempotency identity. Reusing it with exactly the same
request returns the recorded terminal metadata where safe. Reusing it with
different semantics is rejected.

A completed issuance is never reissued and never redelivers secret bytes; replay
returns metadata with AlreadyIssuedNoRedelivery.

Changing operation_id is not an escape hatch after an ambiguous issuance. The
registry blocks a new issuance for the same
subject/consumer/namespace/mount/path while an unresolved lease exists.

Provider-native ambiguity is handled as follows:

| Operation | Uncertain result | Recovery |
| --- | --- | --- |
| issue, provider lease ID not observed | IssueOutcomeUnknown | no blind retry; trusted signed evidence must confirm absence or supply an observed lease ID |
| issue, provider lease ID observed but payload/delivery did not complete | OrphanedActiveLease, SecretDeliveryLost, DeliveryAuthorizationLost, or ConsumerOutcomeUnknown | lookup/revoke known provider lease before issuing another |
| renew | RenewOutcomeUnknown | lookup known provider lease; present updates local TTL/generation, absent closes it as expired |
| revoke (sync=true) | RevokeOutcomeUnknown | lookup known provider lease; absent closes it as revoked, present stays unresolved for a new authorized revoke |
| lookup/reconcile | read-only failure | restore prior unresolved state; retry reconciliation under a new signed operation |

resolve_unknown_issue does not manufacture certainty. Its ConfirmedAbsent or
ObservedLease input is itself final-use-authorized and binds an evidence digest.
The host is responsible for obtaining that evidence from an independent provider
audit/listing/recovery path.

## Persistence

SecretLeaseRegistry uses an append-only leases.journal plus an OS-exclusive
lease.lock in an owner-controlled 0700 state directory with owner-only regular
files. Symlink entries are rejected before open and inode/owner/mode/link-count
identity is rechecked after open.

Each event is sequence-numbered and fsynced. Replay rejects identity drift,
operation drift, malformed complete events, unsafe ownership/modes, or capacity
overflow. A torn final line is ignored. In-flight effect states are normalized to
ReconciliationRequired on restart.

The journal stores lifecycle metadata and provider lease identity. A provider
lease ID is treated as sensitive metadata but is not the dynamic credential
value. Raw dynamic secret response values are not persisted.

Current local ceilings:

- 65,536 lease records;
- 262,144 operation identities;
- 256 MiB journal;
- 64 KiB per journal event;
- 1 MiB provider response;
- 32 requested secret fields.

This append-only journal avoids an O(N) whole-state rewrite on every lease
operation. It remains a **single-active local authority** because the state
directory is protected by an exclusive OS lock. Active-active/distributed lease
state is a separate HA design and is not claimed here.

The existing FinalUseAuthority replay registry remains independently bounded by
its own authority-epoch capacity and persistence design. This module does not
silently weaken or replace that security boundary.

## Verification

Focused tests live in lease_lifecycle_tests.rs and cover:

- real TLS dynamic issuance and callback-only raw-secret delivery;
- same-operation issuance replay without a second provider request;
- provider-native renew and synchronous revoke;
- ambiguous issuance blocking a new operation until signed absence resolution;
- ambiguous renew reconciled by provider lease lookup;
- ambiguous revoke reconciled by a provider 404;
- process restart converting a dispatched issuance into ReconciliationRequired.

Run from codex-rs:

    cargo test -p codex-hepta-bao-adapter
    cargo clippy -p codex-hepta-bao-adapter --all-targets -- -D warnings

A command shown here is not an execution receipt. Exact-commit CI or a recorded
candidate receipt remains the source of pass/fail evidence.
