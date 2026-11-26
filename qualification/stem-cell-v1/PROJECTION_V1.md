# Shared Stem low-rank projection — qualification V1

**Status:** SHADOW / algorithm-contract only. No production signature, grant, CAS publication, route cutover, or NDU promotion.

## Purpose

A text Encoder can emit 768- or 1152-wide mean features, or a 6144-wide
eight-landmark representation. The canonical Neuron Q24 worker currently
accepts at most **512** inputs. Truncating the final dimensions destroys
potential decision evidence. This V1 uses one **shared** registered low-rank
projection before many **cell-local** Heads.

```text
locally audited frozen HF snapshot
  -> existing SharedStemEngine.encode_many (one actual Torch forward for misses)
  -> FrozenFeature (canonical IEEE-754 f32 values and source digest)
  -> versioned LowRankProjectionQ24
  -> ProjectedFeatureRef (source+scope+generation+revocation+projector bound)
  -> existing NeuronFeatureRequest / CpuGatedHeadDriver
  -> independent inference-control admission and receipt
```

The final Worker arrow is **not** automatically wired to a live
inference-control owner. A Rust request verifier confirms the projected vector,
projected digest and worker generation, but does not mint a capability.
The numeric Tensor driver computes real Q24 Head outputs; there is **no native
Rust Transformer Encoder** and no qualified 4096-Cell production result.

## Exact numeric algorithm

For approved float32 Encoder values `x`:

1. Validate finite inputs, full declared source width (1..8192), and `[-8,8]`.
2. Convert f32 to signed Q24 with nearest-even tie breaking.
3. `u = round_even_Q24(A x)`, `A` row-major `[rank,input_width]`.
4. `z = round_even_Q24(B u + bias)`, `B` row-major `[output_width,rank]`.
5. Reject out-of-range intermediates/outputs. **Never saturate** or silently
   discard source coordinates.

Registered dimensions: rank 1..64, output 1..512, at most 600,000 stored
coefficients. `A`, `B`, bias each stored as exact little-independent
big-endian signed i64 Q24 in content digests. Projection weights are shared
once per permitted model/organ bundle, **not** counted as per-Cell Head weights.

Golden cross-language fixture: 3→2 rank-2 projection, input
`[0.5,-0.25,0.125]`, output Q24
`[8388608,-2097152]`.

- Frozen f32 feature SHA256:
  `e2738fbff6a632280fd48ed1022a3ea63a924111c75bc65260766e31b4f41327`
- Projection SHA256:
  `451632b3946c1d3dd690eaf2007ad71ba00b50c49c8911854aa02be25a7838c3`
- Scope/generation/revocation/projector-bound input SHA256:
  `a61a79d9d616f28356a12dbcb1eaccbf37c7d51ae3fee807fc6d8d724150a40e`

Python and native Rust each check all three identities and the exact numeric
output, including negative ties-to-even, wrong widths and overflow.

## Cache and provenance restrictions

All cached projected features are keyed by scope, generation, revocation
frontier, Encoder/preprocessor/runtime, input, immutable f32 feature digest,
and exact projection digest. Request IDs are not deduplication keys; a new
Neuron request must still have its own independent authorization.

The cache holds only immutable vectors, stays bounded and supports
scope invalidation. A changed source or projection receives a new key;
revocation-triggered eager invalidation still belongs to the authoritative
runtime lifecycle owner. A SHA digest is **not** an authenticated execution
receipt or data-use permission.

The projection manifest requires a full-file SHA256 pin, exact shape and
tensor fields, reviewed training lineage, `shadow_only=true` and
`production_authorized=false`. The strict loader denies unknown, missing,
duplicate or mutated fields; it does not write Artifact CAS.

## Signed CAS use, canonical bytes and replay restrictions

The research-only Rust selected projection reader is now loaded through the
**existing** independently verified artifact selection and `load_selected_candidate`
CAS path. Its cache uses `RevalidatingCandidate::with_current`; the loader does
not mint a signed artifact, an inference grant, an authority lease, or a
production Final-use token.

CAS projection candidate bytes must match the Python
`encode_cas_projection_candidate` canonical encoding **exactly**: compact
ASCII JSON, lexicographically sorted fields, no extra keys or whitespace,
integer-only Q24 tensors and exactly one final newline. The Rust decoder checks
these exact bytes after bounded parsing, not just a structurally equivalent
JSON object. Test vector: the 3→2, rank-1 constant-gate fixture has **548
bytes** and SHA-256
`542fe1a25af049d36e2aa2a92aac0513535f5828761812112888a2d88bcaec93`.
That digest is an integrity check and never constitutes selection authority.

The former public split `check_worker_request` / later-dispatch path is
**test-only**, not a callable production API. The crate-private Projection-only
`run_selected_cpu_head` requires a separately authenticated CURRENT,
the independent signed selection, trusted verifier, matching Scope,
worker Generation, revocation frontier and exact already-authorized Q24
payload. Any failed check **seals the reader**, so reusing a previously valid
feature after an observed revocation fails closed. The Rust regression uses
an actual Ed25519 fixture, create-only CAS files, signed CURRENT snapshots
and an independent selector.

The separate typed `StemCpuHeadUseV1` route can execute the **actual local
Q24 CPU Head** inside `RevalidatingCandidate::with_current`, after the exact
independent signed selection, current registry view, source feature binding and
pre-existing Worker request have passed their checks. This path accepts the
**original full-width f32 feature**, not an externally constructible projected
vector. It re-executes the selected CAS projection **within** the CURRENT guard
and compares the complete Q24 output and binding against the pre-authorized
Worker request. Caller-forged Q24 values fail even if the caller recomputes
its own matching request and lease payload digests. Its non-authoritative
`NeuronFeatureReceiptV1` proves observed **model-only CPU math** in the Rust
test, not pretrained text encoding or permission to use tools. No signature,
cache lease, or Final-use right is manufactured by this route. A failure seals
the reader and prevents a prior signed CURRENT or projected vector from
reviving it.

**Not a production atomicity claim:** a caller can retain an old already
verified CURRENT value. A *production* owner must acquire the newest signed
CURRENT from its authority service immediately before each use and serialize
verification with the downstream execution/Final-use boundary, or arrange an
equivalent generation/revocation fence. The read-only research adapter neither
obtains a global owner lock nor signs a terminal model execution receipt. The
first P1 gate remains blocked until native product Owner startup, independent
Final-use and WAL/restart recovery are exercised on the target host.

## Reproducible qualifications

```sh
python3 -m unittest discover -v -s qualification/stem-cell-v1 -p 'test_*.py'
cd codex-rs
cargo fmt --package codex-hepta-infer-worker-host -- --check
cargo check --locked -p codex-hepta-infer-worker-host --lib
just test --locked -p codex-hepta-infer-worker-host --lib \
  -E 'test(model_worker::)'
```

These checks are **L1**. A synthetic Torch forward is tested to prove that
the projected batch can consume a real tensor operation, not that an audited
mmBERT checkpoint has run. No pretrained weights are included or downloaded.

For **L2**, run approved, pinned model snapshots and grouped future-window
trials: compare joint encoding, mean projection, landmarks and cross-attention,
with no-change and full Laya decisions; measure retained evidence and Head
training data requirements. Train the projection only on approved train folds;
freeze weights before calibration/held-out/future evaluation.

For **L3**, only count actual native Tensor backend executions with genuine
per-process RSS/CPU and same-clock enqueue/start/finish telemetry. Distinguish
`encoder_cold`, `encoder_batch`, `feature_hit + projected_head`,
`projection_miss`, and WAL/recovery. Do not infer shared computation from
a batch request API or from the number of logical Cells.

For **L4/L5**, require independent signed evaluator/selection/execution
receipts, negative-transfer and subgroup floors, revocation reconciliation,
and measured NDU gain. These gates are not implemented by this research module.

## Dual selected CAS: Projection **and** Cell Head Bank (L1 extension)

The original CAS reader pinning the Projection only was insufficient to
authenticate the CPU Head's independently trainable weights. The native Worker
now also provides `SelectedStemHeadBankReaderV1`:

- `encode_cpu_head_bank_candidate_v1` is a pure, bounded, canonical JSON
  encoder for 1–32 distinct Q24 Heads (at most 16 MiB of candidate bytes).
  Python `native_bridge.encode_cpu_head_bank_candidate` produces matching
  bytes and SHA-256 domain-separated weight identities. This is not a CAS
  publication operation and creates no authority.
- The Head bank must have its **own** exact immutable Artifact CAS payload,
  independently signed selection, and owner-signed CURRENT. It checks the
  artifact's compatibility digest against the recomputed bank weight digest.
  Duplicate, reordered, tampered, noncanonical, oversized or non-finite Head
  content is rejected before installing or executing the candidate.
- The externally callable combined model-only path requires **both**
  Projection and Head bank CURRENT/selection checks, identical Scope,
  Generation, revocation frontier, Encoder and exact Worker bundle weights,
  and a pre-existing admitted `NeuronFeatureRequest`. It recomputes the Q24
  projected input from the complete source feature, instead of trusting a
  caller-provided projected buffer. The Projection-only CPU dispatch helper
  is crate-private to reduce the bypass surface.
- Head bank provenance is emitted only after successful non-effectful CPU
  execution and is always `production_authorized=false`. Any failure seals
  the Head bank reader; both banks must be independently reloaded after a
  revoked/corrected artifact. Signed head selections cannot authorize tools,
  provider calls, training, route cutovers, or checkpoint commits.
- `CALLERS.toml` explicitly registers the newly privileged
  `RevalidatingCandidate::with_current` call site. The test uses real
  Ed25519 owner/selector signatures, genuine create-only candidate storage,
  two registry manifests, genuine Q24 CPU arithmetic, and head revocation.

**Still blocked:** The test authority is a fixture, not production. The
Owner must serialize both CURRENT views, revocation publication, Worker
dispatch, Artifact and Head lifecycle, independent Final-use and WAL recovery
under a shared live fence. The Rust CPU Head uses already supplied f32
features; real audited mmBERT/ModernBERT/Jina weights and target-host
64–4096 Cell measurements remain unverified. No benchmark or NDU claim
follows from these L1 tests.


## Dual-selected CAS → one native Q24 Head backend batch (L1 extension)

The read-only Rust `SelectedStemHeadBankReaderV1::run_selected_cpu_head_backend_batch` now composes **two independently selected, signed-CURRENT CAS readers** with the registered `NeuronBackendBatchDriver` for **2–32 same-scope/same-generation** Cell requests. The projection reader requires full-width source features and recomputes each Cell's exact Q24 projection *inside* authenticated CURRENT revalidation; it rejects a mutated or missing member **before any backend call**. The Head bank checks exact signed selection, manifest-bound weights, membership, Scope, Generation and revocation frontier before entering its own CURRENT guard. A failed use seals the affected readers, so a stale CURRENT object cannot reactivate them. Every successful member receives a typed inference receipt with `authority=DENY_ALL`; the returned batch digest is **not** a signature.

The concrete `CpuGatedHeadDriver::observed_backend_batch_invocations` counter is diagnostic for **native CPU Head driver dispatch**, not an independently attested full Encoder execution or fused GPU/Tensor backend. Within the driver the distinct Head calculations are still per-member; batch formation does not prove a throughput increase. A regression on real selected CAS test payloads checks that two different Head IDs produce two typed receipts after **one** Head backend invocation. A separate signed-CAS negative session introduces one modified Q24 member whose self-recomputed payload digest is valid: the selected projection rejects the whole batch, seals both readers and leaves the observed backend invocation count unchanged.

**Non-waivable P1/P2/P3 gates:** this does not install a pretrained HF Encoder in the Rust Worker, sign artifact-load/Final-use receipts, serialize two CURRENT issuances against a production revocation owner, persist a WAL checkpoint, or measure target-host p95/p99/RSS. The product Owner must perform those operations atomically or under a proven generation fence before any route may be promoted. Do not infer 4096-Cell performance or NDU improvement from these L1 fixtures.

## Dual-CAS selection-time equality (L1 replay guard)

The selected Projection and selected Head Bank are checked with **one
owner-supplied selection-time snapshot** per invocation. Both the single-Cell
path and the 2–32-member native Head batch reject the entire request if
`StemCpuHeadUseV1.selection_now` /
`StemCpuHeadBatchUseV1.selection_now` differs from the Head-bank
`selection_now`. Any mismatch seals the Head reader before native dispatch;
there is no sequential retry against an older selection-time value. A separate
signed CAS test checks 29-versus-30 rejection even though both times are within
the individual selector certificate windows.

This L1 check prevents split-time admission; it **does not** authenticate the
caller-provided clock or prove that either independently signed CURRENT is
still the newest owner head. A production owner must source time from a trusted
clock, serialize CURRENT and revocation publication against dispatch, bind a
live generation fence, and persist independently authenticated execution
receipts. It must not treat an equal timestamp, a digest or an L1 fixture
as final-use authority.


## Dual-CAS identical signed CURRENT snapshot (L1 split-view guard)

Both selected CAS artifacts must be registered in **one Artifact Registry** for
this Stem/Head composition. In addition to an identical selection-time
argument, the single-Cell and 2–32-member batch dispatchers now require the
Projection's `VerifiedCurrentRegistryViewV1` and the Head bank's
`VerifiedCurrentRegistryViewV1` to have **exactly matching registry snapshot
receipt, authenticated witness digest and pinned owner-trust digest** before
accessing either candidate or invoking the model. Two individually valid
signatures are not sufficient when they refer to different generations of the
shared registry.

The negative regression creates two genuine owner-signed CURRENT views:
an earlier Registry snapshot and a later one containing an additional
registration. Mixing them is rejected even when they have the same signing
key and selection-time argument. This avoids split-view replay but does **not**
prove live freshness: the product Owner must still serialize trusted CURRENT
acquisition, revocation publication and execution. This reader cannot issue
Final-use authority, recovery grants or durable WAL commits. Fail closed if the
two artifacts cannot be verified against the same Registry snapshot.

