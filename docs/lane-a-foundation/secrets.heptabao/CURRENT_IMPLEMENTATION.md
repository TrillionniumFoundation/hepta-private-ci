# `secrets.heptabao` current implementation

## Current executable contract

The implemented HTTPS slice is `BaoClient::consume_kv_v2`: a bounded read of one
string field from one exact KV-v2 version. It pins a supplied CA, validates the
hostname, disables ambient proxies and redirects, applies one bounded deadline
and caps the complete response at one mebibyte.

Before dispatch, `FinalUseAuthority` verifies an independently signed,
single-use binding over subject, consumer, HTTPS origin, CA, namespace, mount,
path, field, version and expected secret digest. After response and
digest/version validation, authority is rechecked before secret delivery.
Receipts contain metadata and digests, never raw secret data.

The production-capable source composition is `BaoFinalUseHost` in
`src/final_use_host.rs`. It removes the arbitrary-closure assumption from the
callsite: the signed `consumer_id` must resolve in a closed host registry of
`RegisteredBaoConsumer` callbacks. The host also requires an independent
operator approval signature for the exact grant and accepts revocation heads
only through an independently pinned signed revocation feed.

The final-use mutex is held only for the final live-authority recheck, not while
the registered callback runs. That recheck is the consumer-entry linearization
point: revocation completed before it denies delivery; revocation completed
after it is ordered after entry.

## Public symbols and source bindings

- `BaoToken`, `BaoReadRequest`, `BaoSecretReceipt`, `BaoClient`,
  `BaoClientError`: `codex-rs/hepta-bao-adapter/src/https_consumer.rs`;
- `BaoFinalUseHost`, `RegisteredBaoConsumer`, `BaoFinalUseHostError`:
  `codex-rs/hepta-bao-adapter/src/final_use_host.rs`;
- final-use grant and durable nonce/revocation state:
  `codex-rs/hepta-contracts/src/final_use*.rs`;
- independent approval and revocation-feed verification:
  `codex-rs/hepta-contracts/src/final_use_control.rs`;
- host integration and real-service procedure:
  `codex-rs/hepta-bao-adapter/README.md`.

## Durability and activation

Secret values remain owned by the external Bao service. Local durability is
limited to kernel authority nonce/revocation state. Source composition now
binds consumer identity to a registered callback and separates issuer,
approver and revocation-distributor trust, but there is still no selected
production process caller in the current candidate.

Activation requires protected host configuration, provider token, pinned issuer
/ approver / revocation trust, an independently provisioned consumer registry,
current signed revocation data, target-host qualification and operator
acceptance. Source composition alone does not satisfy those gates.

## Target-only design

Secret mutation, durable operations/evidence composition, quota settlement and
automatic product enrollment remain outside this slice. Fleet revocation
transport/freshness, external anti-rollback, trusted time and HSM/KMS/operator
ceremony are deployment or separately owned authority concerns.

## Known limits and non-claims

Local zeroization does not prove that TLS, HTTP or the OS made no transient
copies. A callback error or crash after the final entry point is indeterminate.
Revocation cannot retroactively undo an effect that has already crossed the
final synchronous entry linearization point. The current error surface does not
return the precomputed metadata receipt when the callback reports failure.

The registered host is source-composed but not product-process activated;
source implementation and tests do not grant operator acceptance, promotion or
release.

## Verification

Tests and the isolated real-service fixture cover pinned TLS, exact
headers/version, forged/replayed grants, revocation during network wait,
provider denial, response bounds, digest mismatch, timeout and consumer
uncertainty. Registered-host tests cover closed/unique consumer identities and
deny unregistered identities or forged approvals before network dispatch;
kernel control tests cover independent grant approval, signed monotonic
revocation ingestion and forged-feed rejection.

Recorded bounded evidence is not production acceptance. Exact-head and
synthetic-merge receipts for the current candidate are the relevant execution
evidence.

## Integration prerequisites

A selected production caller must durably record operation intent before
dispatch, persist response/consumer observations, reconcile indeterminate
outcomes and settle quota from terminal evidence. Secret bytes must never enter
general logs, prompts, learning records or ordinary receipts.
