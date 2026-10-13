# Scoped Shared Stem → Native Neuron Worker Bridge — Shadow Qualification

This is a **Draft, fail-closed, non-promoting** additive bridge stacked on
Neuron Stem PR #1499. It does **not** load/download Jina, sign an artifact or
authorize a production inference, checkpoint, topology change or release.

## Exact native execution path

1. An **independent product owner** authenticates Principal/Scope, selected
   Stem model weights + tokenizer + preprocess + projection, current
   Generation/Authority Epoch and expiry. Those receipts are **not implemented
   in this branch**. Merely creating `StemAccessContextV1` does not do this.
2. A bounded immutable `StemFeatureRefV1` binds the actual signed-Q24 bytes,
   full frozen pipeline digest and original input digest.
3. `bind_stem_feature_request_v1` checks Scope, Principal, Generation,
   Authority Epoch, expiry, revocation claim, exact bytes/width and required
   selected Head/Stem/Projection tuple. Result has `DENY_ALL`.
4. The native Worker combines the unscoped original input digest and the
   exact source reference digest under a **new domain-separated hash**:

       SHA256(
         "hepta.infer-worker.scoped-stem-input.v1"
         || original_input_digest[32]
         || feature_ref_digest[32]
       )

   This becomes the *Worker* input digest in the pre-existing canonical
   `NeuronFeatureRequest` payload. It is **not** a new signature or a change
   to the legacy `NeuronFeatureRequestV1` serialized format.
5. The independent inference.control owner supplies an already-authorized
   `WorkerRequest` with existing request/reservation/lease payload digests.
   The bridge checks those exact bytes but **never generates or repairs them**.
   A lease obtained for Scope A cannot be reused in Scope B even with identical
   raw text, feature bytes, Stem and Head.
6. `InferenceWorker::run_bound_stem_feature_receipt_v1` validates its **own**
   current grant, exact loaded Head manifest, generation and token limits,
   dispatches through `NeuronFeatureDriver`, verifies the observed terminal
   result and returns `BoundStemFeatureExecutionV1` carrying the scoped
   reference hash and typed `NeuronFeatureReceiptV1` with `DENY_ALL`.
7. The real host (not this module) must independently verify signed final-use
   authorization, source load attestation, current revocation/generation, and
   CAS-commit the checkpoint/receipt. Crash/ack loss requires transaction-ID
   reconciliation before allowing Cell output to affect the world.

The Worker path additionally enforces
`authorization.maximum_tokens <= loaded_manifest.maximum_tokens` **and**
`<= reservation_maximum_tokens`, and rejects
`observed_memory_bytes + transient_allocation_bytes` above the resource
grant using checked arithmetic. The driver contract must report these
categories disjointly; conservative rejection is preferable to bypassing the
resource ceiling.

## Cross-language golden fixture (NOT real model output)

| Binding | SHA256 |
| --- | --- |
| signed Q24 vector `[4194304, -2097152]` | `b9b1bbf5ad007adaed29f199b62dee14de4473d79e5e13315aa8ddb06e133d23` |
| full scoped `StemFeatureRefV1` | `6a705b03b523b5a7e8cb884b0d0994d9ae76cb4dbc078102f66392b26b6f852e` |
| scoped Worker input digest | `6d6c6541396eb0f5ece9ec2ced55569133aa8f48852d7c1748509d53f3189e43` |

These hashes bind declared content, not the physical origin, a signature,
permission, observed inference or independent NDU value. Python
`stem_worker_binding.py` and Rust `model_worker_tests.rs` test the same
bytes and fail closed on other Principal, Scope, input/projection, expired
lease, Generation, resource budget or altered Head.

## Exact-source qualification

```sh
cd codex-rs
cargo +1.95.0 fmt --all -- --check
cargo +1.95.0 test --locked -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --lib
cargo +1.95.0 clippy --locked -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --all-targets -- -D warnings
cd ..
PYTHONPATH=qualification/neuron-stem python3 -m unittest discover \
  -s qualification/neuron-stem -p 'test_stem_worker_binding.py' -v
```

CI: `hepta-neuron-stem-worker-bridge.yml` holds a separate Python byte
conformance gate and Rust native package tests. Green unit tests prove only
these mechanism/contract obligations, **not** real Jina forward, real Stem
load, authenticated final-use, NDU impact, physical microbatch or 4096
Cell target-host throughput.

## Still mandatory, strictly ordered

1. Exact final SHA: obtain **actual** workflow receipts and resolve fmt,
   Rust tests, Strict Clippy, blocking-ci/cargo-deny failures without ignores.
2. Pin/review/download official Jina v5 revisions and run real selected
   Text/Omni weights under an approved noncommercial research workload.
3. Have the independent owner actually issue and verify a source
   `ArtifactLoadReceipt`, scoped signed final-use grant and Worker
   reservation/lease, then bind the immutable shared feature into this
   native path.
4. Independently match the Worker output to the owned Q24 Neuron state
   successor and atomic Artifact CAS/Checkpoint WAL. Fault inject abort,
   duplicate, lost ACK, revocation and generation rollover.
5. Evaluate real Cell learning vs frozen same-initialization and no-change
   controls in at least two future windows, including OOD, negative transfer
   and independent NDU. A positive offline score never authorizes production.
6. Only then measure 64, 256, 1024 and 4096 **actually ticked** Cell cases
   and report whole-path CPU/RSS/p95/p99/throughput, persistent write cost,
   cache validity, crash recovery and known hardware environment.
