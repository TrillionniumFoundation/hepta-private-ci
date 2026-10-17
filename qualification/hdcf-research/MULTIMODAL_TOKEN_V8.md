# HDCF V8: source-bound multimodal tokens to existing CellBank Head study

**DRAFT · RESEARCH_ONLY · SHADOW_ONLY · DENY_ALL · NO MODEL SELECTION · NO MAIN MERGE · NO FINALUSE**

## Why this is an additive child, not another runtime

This research increment is stacked on HDCF original Model / Head / source custody:

- Original physical pretrained ModernBERT trial: [PR #2490](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2490), original run `38930339541`, frozen parent HEAD `b89a0b4a32eaa92881a79140256079aed0c38fe4`.
- Source-only independent original BANKING77 held-label check: [PR #2556](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2556), parent `d13c14873dedc5aaa87a80565b4ff236061c1831`.
- **Do not alter or reinterpret** V1 `NeuronFeatureRequestV1`, `codex-hepta-neuron`, NDU, CAS/CNS, inference worker, HNMF source owners, production FinalUse or permission checks.

The V1 frozen-feature bank can already train and review real numerical Heads on **one vector per case**. V8 is an intentionally narrow, **lossy bridge** from externally produced text/image/audio/video token features to that existing 384D CPU Head trial. It allows an original multimodal encoder producer to use the existing *training and two-process blind review* without falsely calling a 384D vector a native token-aware Runtime contract.

## Input contract (no raw media and no held targets)

`hepta.hdcf.multimodal-token-bank.v8` uses strict known-key JSON:

- `producer`: exact `principal`, `purpose`, `generation`, `epoch`, declared `source_sha256`, modality-keyed `encoders` and `preprocessors` for **text/image/audio/video** (all SHA256), and `topology` (`separate_frozen_frontends` or `shared_transformer`). These are **assertions**, not publisher signatures or proof of GPU/CPU execution. A recorded shared topology is NOT proof that weights were physically shared.
- `dimension`: **384**. `types`: exactly two independent logical Cell categories. `fit`: 8–512 labeled cases, with each Cell category containing both binary labels. `held`: 4–256 cases with **no label field**. Families, case IDs, source event identities and asset IDs must be non-overlapping across partitions. Family strings are asserted and do not prove independent issuers.
- Each case has `id`, `family`, `type`, `event_sha256`, `modalities` plus `target` **only for fit**. Modalities are lexically ordered without duplicates. Each span has `kind`, `asset_sha256`, `encoder_sha256`, `preprocess_sha256`, `tokens_sha256`, `time_ms` and `vectors`.
- Each token is an exactly 384-element bounded finite FP32 array; 1–8 tokens per span (audio/video require at least 2). Tokens are bound by domain-separated SHA256 of little-endian FP32 bytes and shape. Audio/video timestamps are strictly increasing, bounded, length-matched; text/image have no fake timeline. Overall canonical JSON <=4MB.

A source feature digest proves local payload equality **only**. It does not authenticate that actual media, source, pretrained weights or tokenizer produced that payload. The original media stays at its existing owner and must be read by an independently authorized source reviewer.

## Transformation

The vector-only **baseline** uses each modality's token mean; audio/video additionally use a signed `(last-first)/2` endpoint difference to detect trivial temporal reversal. The temporal vector is `0.75 mean + 0.25 signed_difference`. The average of the present modalities is rounded with signed nearest/ties-to-even Q24 and emitted as a 384D vector.

This is **not** a learned cross-modal projection; all inputs are required to have previously been projected into 384 dimensions, and shape equality does not establish semantic alignment. More expressive attention/resampler/organ-adapter models remain research candidates and must beat this baseline **under matching budgets**. A video reversing control can reveal whether a temporal representation is insensitive to order; it cannot prove video understanding. Modality drop ablations explicitly fail if they eliminate all information for any case.

`to_physical_bank()` emits the **existing** `hepta.hdcf.frozen-feature-bank.v1` JSON accepted by `physical_bank.validate_bundle()` and `physical_cli.py`, without changing any original classes, label scopes or Head algorithms. No held label enters this conversion. It carries derived Encoder and preprocessor tuple hashes and preserves the producer's original declared source SHA. Two-process blind scoring and existing independent original-case source review remain mandatory.

## Shared feature fan-out (no new authority)

`SharedFeatureFanout` binds `principal/purpose/generation/epoch/whole-bundle digest`, defensively copies original input rows, and memoizes **one pooled feature per case**; up to 4,096 distinct logical Cell borrowers use the same immutable Python tuple. **Every** borrow re-evaluates a host-supplied current-use predicate, including cache hits. Stale/revoked/wrong-scope borrows fail closed. The tally named `pool_count` is a Python pooling counter, **not a pretrained Encoder forward count**; it is not evidence of no-copy GPU kernels or real-worker RSS savings.

The Python callback is not an authenticated host grant. No model/permission controller is installed, no live inference is dispatched, and no current-run Cell update or production authorization is added.

## Reproduction

From repo root on the **stacked branch with `physical_bank.py`**:

```bash
python3 -m py_compile qualification/hdcf-research/multimodal_token_bridge_v8.py qualification/hdcf-research/test_multimodal_token_bridge_v8.py
cd qualification/hdcf-research
python3 -m unittest -v test_multimodal_token_bridge_v8
python3 -O -m unittest -v test_multimodal_token_bridge_v8
```

All fixture token arrays and control labels in these tests are synthetic. The first integration test runs the **actual existing `physical_bank.train` CPU scalar SGD** on converted fixture vectors; a second integration test runs the actual *conversion, CPU fitting, and blind review* as separate operating-system processes, verifies 0600 create-only output, and rejects swapped target identity. Neither executes a pretrained model. Reproducing V8 without the parent trainer is useful for contract checks only and must not be reported as an integrated physical trial.

For an authentic original case-feature export produced and SHA-reverified **outside** the repo:

```bash
python3 qualification/hdcf-research/multimodal_token_bridge_v8.py \
  --features /private/original-train-plus-blind-features.json \
  --out /private/q24-384-bank.json
python3 qualification/hdcf-research/physical_cli.py train \
  --features /private/q24-384-bank.json --out /private/heads-sealed.json
# In a genuinely separate reviewer process with original held labels:
python3 qualification/hdcf-research/physical_cli.py review \
  --predictions /private/heads-sealed.json \
  --targets /private/independently-verified-original-held-labels.json \
  --out /private/paired-review.json
```

Do **not** upload model tensors, media, labels, original case text, or per-case private predictions from new experiments as CI artifacts. Existing original public artifacts follow their own exact SHA/permission constraints. The V8 workflow does not access any remote pretrained model or dataset and is `contents: read` only.

## Next true multimodal science gate (NOT completed here)

1. Pre-register at least two genuinely independent publishers/source families, distinct held cohorts and model/asset licenses **before** seeing their labels. Freeze matching cases for text-only, modality-added and modality-lesioned inference, including source-validated cases where non-text modality is necessary.
2. Physically execute and independently byte-audit pinned **real** text Stem, vision/audio teachers and 384D projections; attest encoder forward count, tokenizer/processor identity, devices, CPU/GPU memory, complete wall/CPU times, host resources, cache warm/cold and failure costs. `separate_frozen_frontends` does not save the teacher front-end memory unless distilled away.
3. Run existing **frozen/shared-one-touch/split/swapped** Head controls on identical original feature data. Compare trained Organ/Cell adaptations only after adding equal-parameter/equal-FLOP controls and strict train-only learning.
4. Preserve publisher labels away from model-producing runs; independently recompute each sealed prediction and source/label identity. Include counterfactual modality substitution, sequence reversal and hidden-order lesions, measured coverage, Brier/calibration, old-task retention and negative transfer.
5. Report complete end-to-end cost with CIs at 64/256/1024/4096 logical Cells and budget-equivalent replicated/shared 421M controls. **No Stem winner or Cell Split promotion** from a source-only or synthetic gate.

## Exact scientific state

The physical ModernBERT five-arm original 32-case result remains inconclusive: `split 20/32`, `shared_one_touch 16/32`, paired exact `p≈0.503`; one source family and no independently verified task-level generalization. V8 contributes **an executable token/type/source/timeline adapter and adversarial coverage**, not new pretrained encodings, cross-modal efficacy, audio/video generation, multimodal System2/FBSDE, actual live worker latency or general-intelligence evidence.

**Unconditional `HOLD_NO_GO / DENY_ALL`; retain `blocking-ci` and independent architecture/owner approval.**
