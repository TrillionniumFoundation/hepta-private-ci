# secrets.heptabao current implementation

## Current executable contract

The implemented slice is `BaoClient::consume_kv_v2`: a host-composed HTTPS read
of one string field from one exact KV-v2 version. The client uses a pinned CA and
hostname validation, disables ambient proxies and redirects, applies one
bounded deadline and caps the complete response at one mebibyte.

Before dispatch, the final-use authority validates an independently signed,
single-use binding covering the subject, consumer, HTTPS origin, CA, namespace,
mount, path, field, version and expected secret digest. After response and
digest/version validation, authority is rechecked before the bounded synchronous
consumer callback. Ordinary receipts contain only metadata and digests, never
the raw secret.

## Target-only design

Secret mutation, generic lease issuance/renewal/revocation APIs, automatic
production enrollment and an adapter-owned issuer are not implemented. Adding a
mutation path requires durable operation identity, idempotency and uncertainty
reconciliation rather than reuse of read retry semantics.

## Known limits and non-claims

The external HeptaBao service remains the authority for secret values. Local
zeroization does not prove that TLS/HTTP libraries or the operating system made
no transient copies. The host callback and authority configuration are trusted
inputs; a signed consumer-name string cannot authenticate an arbitrary plugin
closure.

## Verification

Source tests and the recorded isolated service fixture cover bounded TLS reads,
headers/version, forged and replayed grants, revocation during network wait,
provider denial, response bounds and consumer uncertainty. Recorded bounded
evidence does not replace final exact-head workspace/Bazel checks, a named
production caller or independent operator acceptance.
