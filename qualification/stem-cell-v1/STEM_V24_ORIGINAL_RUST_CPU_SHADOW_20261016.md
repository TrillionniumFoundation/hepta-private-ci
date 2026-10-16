# V24 — Original frozen-feature Rust tiled CPU kernel, no production owner

**2026-10-16 · DRAFT / SHADOW_ONLY / DENY_ALL.** Research-only continuation of [PR #2364](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2364), stacked on exact V23 commit `79bb561e5daa0c980193290fe87d49ac6be734ba`. **This is NOT the live `NeuronFeatureDriver`, production Worker batch, final-use model, signed Artifact CAS, NDU selection, or Q24 parity.** No authority/production owner source files were edited.

## Why the Rust bridge is separate

`codex-rs/hepta-infer-worker-host/src/model_worker.rs` currently checks a lease, reservation, model digest, feature payload, terminal outcome and resource grant for **single Q24** feature requests. V23 actually ran **FP32 Python/NumPy** operations on cached **original** mmBERT features. Treating the V23 speedup as already integrated into the live Worker would be incorrect. V24 first qualifies a native **Rust** kernel on the exact saved original FP32 weights, without bypassing any production grant checks. Future product integration must preserve and requalify the existing Worker authority owner, Q24 deterministic semantics, per-request typed receipts and cache invalidation.

## Exact original research inputs

- Unmodified original GitHub archive `11890616195` (run `38546717991`), entire ZIP SHA-256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`.
- Original saved 128×384 pretrained mmBERT FP32 feature safetensors SHA-256 `e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490`; original train/cal/held roster SHA-256 `d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a`.
- V15 original normalizer SHA-256 `ce35cf92094aa1ed560654bb7bb80cb12d7dfd4e4f22723b043e2c3c243f5dbc`.
- V16 frozen `41-joint` original saved Head SHA-256 `4dc71c47b4ec297ce65a221adabd8ad7888cdd1c1ce2f67a7aee3986d4a1433e`.
- Four *old TRAIN* inputs, no heldout labels; a single 384D feature is borrowed by all physical Head slots per invocation. Only the two genuinely trained Head parameter values are repeated, not 4,096 different skills. **No new pretrained Encoder forward** is executed.

### Bounded private wire

`v24_rust_original_handoff.py` loads and revalidates exact frozen source tensors using the existing V20 immutable source path. It writes create-only `HPV24\0\0\1` frames with two mirrored research-only generation/fence/epoch/scope/principal/purpose tuples, three source/model/normalizer digests, four normalized original 384D vectors and both original 4×384+4 Head parameter sets. Rust refuses malformed, truncated, oversized, symlinked, stale-generation, wrong-fence, bad-authority and nonfinite frames *before* allocating Head slots. **The mirrored values are research scope tags, not a signed or production grant.** Full bytes and private tensors remain local to the Runner.

`native_v24_packed_head.rs` allocates 64/256/1024/4096 distinct 1,540-scalar Head slots, implements an independent scalar baseline and an actually **tiled 16-slot** native Rust FP32 operation (one input feature read feeds the tile, one accumulator per slot/class), plus a 32-active-slot cache. Both accumulate original f32 products in f64 before casting to f32, so this is explicitly **not original Q24 production numerical parity**. It validates the native scalar/packed outputs, times 8 warmups + 128 real iterations for each arm and records actual local CPU wall samples plus Linux process RSS observations. There is no invented FLOP, energy, inference queue, WAL or recovery metric.

`v24_rust_original_review.py` imports **no Rust producer**. It independently reloads original feature/weight bytes, rereads every native private input frame, reconstructs all full original scores from the saved two Head tensors using NumPy float64, checks original class choices and f32 tolerances, recalculates p99 directly from all 128 raw samples and emits only a sanitized source-bound research receipt. Failed source identity, wrong slot count, changed/rerouted weight values, missing raw samples or any promotion claims are fail-closed.

### Completed local validations versus pending Rust execution

| Check | Status |
| --- | --- |
| Exact original archive, source feature, V15 normalizer and V16 saved two-Head material | Verified locally |
| Four actual original-material private Rust input frames (64, 256, 1024, 4096) | Created and independently re-read locally |
| V24 Python source/adversarial/original-material tests | **13/13 normal and 13/13 `python -O` PASS**, zero skipped |
| Unchanged V23 CPU mechanism tests | 15/15 PASS locally |
| Python independent original-model expected output digests | Calculated, source bound and retained only as hashes |
| Local Rust compile and binary execution | **NOT PERFORMED: rustc/cargo unavailable** |
| GitHub-hosted actual `rustc --test` + four-size original Rust binary + independent Python readback | **Pending exact-new-HEAD CI** |
| Live Rust Worker Q24 model driver, authorization and signed Final-use | **NOT INTEGRATED / DENY_ALL** |

**No Rust wall time, p99 or whole process RSS is asserted from the local container.** The known V23 Python CPU measurements are only a historical comparator and cannot substitute for V24 native numbers.

## Hosted qualification

Dedicated read-only `.github/workflows/hepta-stem-v24-rust-original-head-shadow.yml` performs exact Git checkout and native `rustc --test` on PR. Push/dispatch additionally downloads the one SHA-pinned original GitHub Artifact, privately rebuilds V15/V16 frozen models, compiles native optimized Rust, runs all four physical sizes as separate processes, and requires a separate NumPy original-input/model/output/p99 audit. Only sanitized aggregate counts and timings upload; the Runner never uploads the source text, original feature matrices, labels, model safetensors, Rust input frames or raw native logits.

### Strict next implementation sequence

1. Require the **exact SHA** source-only and physical hosted V24 Rust jobs to pass and retain independent original output receipts; record negative/slow results without cherry-picking.
2. Implement a genuine **authorization-preserving Worker batch port** using existing inference-control `NeuronFeatureDriver` and typed Q24 receipts, not this FP32 qualification wire. Add stale generation/fence, model and grant/revocation adversarial tests.
3. Charge scheduler, encoder, worker, CAS, WAL, CNS, signatures and clean-recovery CPU/RSS/p95/p99 on the actual target host at 64/256/1024/4096, with full independent source and process evidence.
4. Evaluate frozen no-change and independent future-window/negative-transfer NDU utility before any Cell differentiation, topology change or model promotion.

**Mandatory disposition: `DRAFT / SHADOW_ONLY / DENY_ALL`; 0 prospective new source families. The Rust kernel is an integration candidate, not production approval or demonstrated general intelligence.**
