# `secrets.heptabao` current implementation

## Current executable contract

The implemented slice is `BaoClient::consume_kv_v2`: a host-composed HTTPS read
of one string field from one exact KV-v2 version. It pins a supplied CA, validates
the hostname, disables ambient proxies and redirects, applies one bounded
deadline and caps the complete response at one mebibyte.

Before dispatch, `FinalUseAuthority` verifies an independently signed,
single-use binding over subject, consumer, HTTPS origin, CA, namespace, mount,
path, field, version and expected secret digest. After response and
digest/version validation, authority is rechecked before the bounded synchronous
consumer callback. Receipts contain metadata and digests, never raw secret data.

## Public symbols and source bindings

- `BaoToken`, `BaoReadRequest`, `BaoSecretReceipt`, `BaoClient`,
  `BaoClientError`: `codex-rs/hepta-bao-adapter/src/https_consumer.rs`;
- final-use grant and durable nonce/revocation state:
  `codex-rs/hepta-contracts/src/final_use*.rs`;
- host integration and real-service procedure:
  `codex-rs/hepta-bao-adapter/README.md`.

## Durability and activation

Secret values remain owned by the external Bao service. Local durability is
limited to final-use nonce/revocation state. Activation requires protected host
configuration, provider token, pinned trust, independent grants and a
host-selected consumer callback.

## Target-only design

Secret mutation, generic lease issue/renew/revoke, durable operations/evidence
composition, quota settlement and automatic production enrollment are
target-only.

## Known limits and non-claims

Local zeroization does not prove that TLS, HTTP or the OS made no transient
copies. The consumer callback and authority configuration are trusted host
inputs. A callback error after entry is indeterminate, and the current error
surface does not return the precomputed metadata receipt to its caller.

## Verification

Tests and the isolated real-service fixture cover pinned TLS, exact
headers/version, forged/replayed grants, revocation during network wait,
provider denial, response bounds, digest mismatch, timeout and consumer
uncertainty. Recorded bounded evidence is not production acceptance.

## Integration prerequisites

A production caller must durably record operation intent before dispatch,
persist response/consumer observations, reconcile indeterminate outcomes and
settle quota from terminal evidence. Secret bytes must never enter general logs,
prompts, learning records or ordinary receipts.
