# V25 — Original mmBERT Head stack-tile Rust research, still DENY_ALL

**Date:** 2026-10-16. **Scope:** research-only, additive child of V24 Draft PR #2364. Do not merge to `main`, change selected model, grant Final-use, modify Worker owner, activate CellSplit, or infer AGI/giant-model equivalence.

## Scientific/engineering problem

The **actual committed** V24 Rust source (`native_v24_packed_head.rs`, Git blob `d44f4e0a46362a79bd304cf992c490e536949e63`) already implements a *genuine feature-major fused 16-Head tile*. An earlier local uncommitted copy still performed ordinary per-Head loops; V25 does **not** re-discover fusion. V24's real tile instead allocates a `Vec<[f64;4]>` for every tile. V25 preserves the same source/Head/feature order but replaces that tile scratch with a bounded fixed-size `[[f64;4];16]` (512 bytes); only the final output `Vec` remains.

All signed and authority-relevant production owners are untouched. This is not a Q24 `NeuronFeatureDriver` implementation, no real Encoder fresh forward or platform-signed runtime tuple, and it never dispatches a real action. The source frame's generation/fence are **research-only mirrored values**, not signed production authority.

## Frozen original material

- Original SHA-pinned GitHub artifact `11890616195` from `38546717991`, complete archive SHA256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7`.
- `jhu-clsp/mmBERT-small`, fixed revision `abc32620dd4f6ab06f5fbe905dc25f310618e09f`.
- **Original, physically executed** archived f32 feature tensor SHA256 `e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490`; four original TRAIN rows, width 384; no current Encoder execution.
- Original V16 *two* independently physically trained Head parameter sets: V16 split saved SHA256 `4dc71c47b4ec297ce65a221adabd8ad7888cdd1c1ce2f67a7aee3986d4a1433e`; original mean `ce35cf92094aa1ed560654bb7bb80cb12d7dfd4e4f22723b043e2c3c243f5dbc`.
- Four real **physical copies** (64, 256, 1,024, 4,096) of the two training outcomes. These are not 4,096 independently learned skills. Weight allocations are 6,160 bytes per Head; an already prepared 32-Head active cache costs another 197,120 bytes.

## V24 → V25 controlled comparison

Unchanged baseline: exact V24 `score` + previous heap-buffer fused `packed`. Candidate: identical f64 accumulation over original f32 weights/features, same tile size 16, same output type, fixed 512-byte stack scratch and *no per-tile heap scratch vector*. This removes **source-inferred** temporary allocations per full packed invocation of 4 / 16 / 64 / 256 respectively at 64 / 256 / 1,024 / 4,096 Head slots, or 512 / 2,048 / 8,192 / 32,768 per 128-round full-Head measurement arm. These numbers describe the allocation sites in the implementation; no allocator profiling or hardware cache-miss reduction is claimed.

The native Rust CI (once actually executed) must compile **both** V24 and V25 original code, execute their separate unit tests and fresh processes on **the same exact original source frame** for all four sizes. Run order A is V24 → V25; run order B is V25 → V24 to expose warm/cold host effects. Each Rust report has 128 timed samples of each of scalar/full-fused/32-active-fused CPU wall operations, with raw p95/p99 independently recalculated. The audit must reject even one changed native **binary** output between V24 and V25, or a difference greater than 2e-6 against independently reconstructed original NumPy logits, as well as changed argmax, sources, model identities, research generation/fence, tensor sizes, authorization or resource counters.

**Do not infer stable speedup** from a single local/hosted pair; preserve negative and noisy runs. This is isolated CPU-inference research, not full Worker+Encoder+WAL+CAS, power or 4,096-Cell service throughput.

## Executed local evidence (no Rust toolchain)

- Actual original SHA-verified V24 private source frame files for all four sizes revalidated independently; binary input SHA manifests preserved.
- Independent NumPy frozen V16 Head forward vs a separately implemented 16-Head feature-major fused mathematical translation on four real TRAIN vectors: maximum f32 absolute discrepancy **0**, class identity unchanged. **This is NOT compiled Rust parity.**
- V25 new source-only + original-input tests: **11/11** ordinary, **11/11** `python -O`, no skips (includes two tests that reload original saved model files).
- Combined V24+V25 original source tests: **24/24** ordinary, **24/24** `python -O`, no skips.
- Python byte-compilation; YAML syntax; every relevant hosted Bash run block passes `bash -n` locally.
- **Local Rust compile/run: NOT EXECUTED**, rustc/cargo unavailable in the analysis container. No native speed/RSS p95/p99 or CI `SUCCESS` has been asserted before actual exact-HEAD GitHub Actions.

See machine-readable `STEM_V25_ORIGINAL_STACK_FUSED_PREFLIGHT_20261016.json`. It explicitly sets `hosted_compile_or_rust_output_verified=false` and `production_authorized=false`. Failure cases include modified original features/Head weights, spoofed version/fence, altered CPU samples or fake p99, truncated/padded logits, replayed/synthetic source claims and false Final-use/Production.

## Reproduction on real original material

```sh
# In qualification/stem-cell-v1, after provisioning the byte-exact original
# AG News/mmBERT source archive and regenerating the original V15/V16 files:
python -m unittest -v test_v25_native_stack_review
python -O -m unittest -v test_v25_native_stack_review
rustc --edition=2021 -C opt-level=2 --test native_v24_packed_head.rs -o /private/v24-test
rustc --edition=2021 -C opt-level=2 --test native_v25_stack_tile.rs -o /private/v25-test
/private/v24-test --test-threads=1
/private/v25-test --test-threads=1
# The exact-HEAD GitHub workflow additionally compiles optimized executables,
# runs A/B trials across all 4 sizes, and uploads ONLY the sanitized review.
```

## Mandatory research HOLD

`HOLD_NATIVE_RESEARCH_NO_Q24_OR_FUTURE_OWNER_EVIDENCE`: No exact-current hosted compiler/numeric performance attestation yet; no original real future-source gain, no independent issuer authentication, no signed Worker owner or Q24 parity, no NDU future utility, old-task retention, source-isolated host cost or production recovery. Keep Draft/Shadow/DENY_ALL; V25 performance is a question to be measured, not a claimed win.
