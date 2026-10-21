# Shared Stem Final-use: Physical Worker Identity Fence (Shadow V2)

This research-only hardening is stacked on the independent signed Final-use
Workstream in PR #1517, not merged to production.

## Why V1 was insufficient

The earlier final-use request binding covered Principal, Scope, Stem features,
Head, exact payload/lease/reservation and resource grant. It **did not**
include the `InferenceWorker.worker_id` identity in the signed
`FinalUseBinding.request_sha256`. If two Worker instances were configured
with identical ResourceGrant, Generation, loaded Head and request data, a
token signed for Worker A could, in principle, be used for its *first*
execution on Worker B. A single-use nonce prevents duplicate uses but
does not authenticate the intended first consumer.

## What V2 changes

`stem_final_use_request_digest_v2` now starts with

```text
domain = "hepta.infer-worker.stem-final-use-request.v2"
encoded = domain || u32_be(length(worker_id)) || UTF8(worker_id)
          || length-prefixed request/reservation/model/lease/grant fields
          || bounded token ceiling and grant-generation/expiry values
          || exact scoped StemFeatureRef digest
sha256 = SHA256(encoded)
```

The host must require a freshly signed proposal when the selected Worker ID
changes. The old `v1` hashing function is deleted (not accepted as an alias).
The existing signed grant schema, payload hash, Scope hash, artifact format,
typed Neuron receipt, and `DENY_ALL` output all remain unchanged.

The Python and Rust SHA-256 fixtures also pin the V2 request digest for
`worker.identity-A`, fixture grant and `bound-feature-ref` to
`1edca4a4866ed8e285c1126c3073fc3fdbbc3a087d5c55cd37066700d3e71d1c`.
This is a deterministic content hash, **not** a verified signature, signed
loaded-model receipt or model performance result.

The negative test constructs **two distinct real native Worker objects**
with the exact same ResourceGrant, model and weights, Principal, Scope,
Generation, feature bytes and existing WorkerRequest; verifies that only
the signed request digest differs; then claims the real test Ed25519 grant
for A and attempts physical entry on B. B MUST reject before dispatch as
`Error::FinalUseDenied`. Even after the rejection, the test issuer's
single-use nonce must remain consumed.

This is a mechanism conformance test, not a proof of unique Worker
identity assignment. The trusted production host must independently
authenticate physical Worker IDs, prevent two concurrent processes from
claiming the same ID and pin resource authority, signed source ArtifactLoad,
generation, clock, revocation frontier and destination. This branch does
not instantiate a production issuer or NDU selector, perform checkpoint CAS,
test unclean crash recovery, download Jina weights or claim 4096 Cell p99.

## Checks

```sh
cd codex-rs
cargo +1.95.0 fmt --all -- --check
cargo +1.95.0 test --locked -p codex-hepta-infer-worker-host --lib model_worker::tests::
cargo +1.95.0 clippy --locked -p codex-hepta-infer-worker-host --all-targets -- -D warnings
```

The stacked [Worker Bridge workflow](../../.github/workflows/hepta-neuron-stem-worker-bridge.yml)
also runs the exact-source App Server E2E and transitive owner replay.
No green state is claimed until the new HEAD returns terminal CI receipts.
