# learning.artifacts operational closure

**Converged source implementation commit:** `5a128fc3966218cd65ced02d8c52d9c3a660aa7a`

This addendum records the repository-controlled implementation of the four
operational optimization tracks without inventing a second artifact runtime. The
candidate also absorbs the runtime-convergence fix that revalidates authoritative
dataset membership at each live publication boundary. It is not native execution
evidence, target-host acceptance, activation or release.

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

## Withdrawal and consumption boundary

`validate_artifact_publication_v3` verifies the admission receipt and then asks the
authoritative current withdrawal registry to admit the manifest again. A
caller-constructible, digest-consistent DTO cannot bypass a newly installed
withdrawal frontier. This closes new live publication; already issued pinned views,
retention and physical erasure remain explicit product/host policies.

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

The source restores the `artifact_test_hooks` feature and installs a read-only
exact-source/PR workflow. Delivery-index execution fields remain false until the
converged candidate and its ordered-parent merge complete native build, format,
strict lint, package tests and process-crash fixtures. Main integration, target
filesystem power-loss evidence, independent acceptance, activation and release
remain separately governed.
