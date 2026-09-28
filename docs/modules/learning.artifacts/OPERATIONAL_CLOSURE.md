# learning.artifacts operational closure

**Exact source commit:** `088202de65c8df92b93db0c9500a0ead021872b9`

This addendum records the repository-controlled implementation that closes the
four operational optimization tracks without inventing a second artifact runtime.
It is not native execution evidence, target-host acceptance, activation or release.

## Canonical request identity and transitions

Every operation ID is bound before checkpoint creation or historical terminal
replay to a create-only canonical identity containing the full V3 admission,
manifest digest, withdrawal scope/head, admission time, payload length/digest,
registry predecessor, storage binding, signed CURRENT signing bytes/signature and
configured trust digest. Exact replay resynchronizes the same validated record;
semantic reuse returns `artifact_request_identity_conflict`.

Withdrawal durability, request-identity durability, recovery and drain use an
explicit typed state projection. New admission, same-operation reconciliation and
current-view issuance have separate gates. Error codes expose retry classes:
never retry, same-operation reconciliation, refresh authority, capacity relief or
host policy.

## Actionable metrics and phase measurements

The owner exposes bounded counters and fixed-bucket p50/p95/p99 upper bounds for
payload validation/hash, request identity persistence, recovery scan, payload
write/sync, registry write/sync, CURRENT switch, checkpoint acknowledgement,
startup recovery, current-view issuance, pinned load, withdrawal persistence and
drain persistence.

Resource gauges are host-supplied facts: pinned bytes, pending-erasure bytes,
resident bytes, logical payload bytes and durable bytes written. Cache eviction is
never treated as proof that a pin was released. See `PERFORMANCE_PROTOCOL.md`.

## Qualification boundary

The source commit restores the `artifact_test_hooks` feature and installs a
read-only exact-source/PR workflow. Delivery-index execution fields remain false
until the exact commit and prospective merge have completed native build, format,
strict lint, package tests and process-crash fixtures. Main integration, target
filesystem power-loss evidence, independent acceptance, activation and release
remain separately governed.
