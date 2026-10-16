# V18 — Original pretrained features: does a frozen-logit residual beat simply continuing one Cell?

**2026-10-16 · DRAFT / SHADOW_ONLY / DENY_ALL. No main merge, selected model, physical split, FinalUse, NDU benefit, or production effect.**

This is an independently runnable, source-pinned **physical CPU learning experiment** stacked on `TrillionniumFoundation/hepta-private-ci` PR #2364 at source commit `fa5dbba09faa98f65fef63048c467946ee9f5e8c`. It changes only this research folder and a read-only CI workflow. Original V14–V17 models, runtime owners, main and previous negative results stay untouched.

## Question and authentic source

The original feature ZIP was **actually downloaded** from Actions run `38546717991`, artifact `11890616195`; SHA256 `0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7` (1,398,480 bytes). Original AG News publisher data SHA256 `50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c`; physically generated `jhu-clsp/mmBERT-small` FP32 `128 × 384` feature file SHA256 `e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490`. Frozen-feature provenance is inherited from that public original run, not a fresh encoder forward, independent cryptographic signature, or production model attestation.

Exact original 64 TRAIN / 32 CALIBRATION / 32 existing BLIND rows. The preparer checks every original case/feature/input hash and source ID and emits only source identities, feature bytes, and **TRAIN/CAL labels**. The learner receives no BLIND labels and emits their 32 per-case probabilities into a private, create-only output directory; the independent reviewer reopens exact original publisher TRAIN/CAL labels after the producer completes, but does not score BLIND. Preparation/review are separate processes, not a physical OS security boundary. CALIBRATION was previously repeatedly inspected in V14–V17: do **not** call these data new prospective samples or independent source families.

## Pre-fixed physical comparison

Mean-normalize using only first 32 TRAIN rows, train an original 384→4 parent on those rows for **80 SGD updates**, freeze the parent. Every seed (41, 47, 53) uses the same deterministic 64-row continuation schedule for comparable prefix budgets, batch size 16 and LR 0.1:

- `frozen`: never continue the parent (**true initial no-change reference**).
- `continued8`, `continued80`: update the single existing 1,540-scalar Head for 8 or 80 steps.
- `continued160`: stronger single-Head continuation for 160 steps. **Twice the 80-step budget**; a costlier strong baseline, not an equal-training-budget claim.
- `linear_residual80`: freeze original logits, add a zero-initialized learned 384→4 logit delta. It is algebraically a reparameterized linear continuation; expect near-equivalent fit absent implementation/cost differences.
- `gated_rank4_80`: freeze original logits, add a zero-initialized rank-4 `up(tanh(down(z)))` residual multiplied by a learned sigmoid gate. Gate and rank-4 factors are task-specific. Its initial outputs must be **bitwise equal** to parent logits; both residual variants must preserve base tensors byte-for-byte after training.

All five learned arm schedules and the parent are charged: **488 physically executed SGD updates per seed, 1,464 for three seeds**. Parameter inventory from the actually saved FP32 tensors: frozen/direct-continued 1,540 scalars; linear residual 3,080 resident scalars (1,540 frozen + 1,540 trainable); rank-4 gated residual 3,485 resident scalars (1,540 frozen + 1,945 trainable). This is **not** equal resident memory/optimizer work, and the archived Encoder input computation is excluded from continuation timing.

## Actually observed original-source CALIBRATION results

**Multiclass Brier, smaller is better. Exactly the same previously exposed 32 CAL cases per seed, not 96 independent tasks.**

| Arm | Seed 41 | Seed 47 | Seed 53 | Correct classes by seed |
|---|---:|---:|---:|---|
| Frozen no-change | 0.662608 | 0.659877 | 0.661246 | 15, 14, 15 |
| Continued8 | 0.654278 | 0.655909 | 0.655235 | 15, 14, 15 |
| Continued80 | 0.594811 | 0.598965 | 0.597748 | 19, 17, 17 |
| **Continued160** | **0.541397** | **0.548069** | **0.554882** | **21, 20, 20** |
| Linear output residual80 | 0.594811 | 0.598965 | 0.597748 | 19, 17, 17 |
| Gated rank-4 residual80 | 0.661601 | 0.661910 | 0.662609 | 15, 14, 14 |

The predetermined calibration-only ranking picks **continued160 at every seed**. A rank-4 gated residual does **not** provide uplift on these original features and fixed optimizer settings. Linear residual matches continued80 to reported six decimal places, confirming that putting an additive identity into the output pathway is not a free learning benefit. The gate's weak fit may arise from parameterization, initialization or data; this single retrospective experiment does not identify the unique causal failure. **Do not tune against these exposed CAL results and relabel the new outcome as independent.**

## Independent audit and strict limitations

A separate NumPy/safetensors implementation (imports neither Torch nor the producer) reopened the authentic original ZIP and independently checked the full 128-case lineage, TRAIN/CAL gold, missing BLIND labels, every model file hash/shape/scalar cost, **18 physical parameter bundles**, original parent equality in both residuals, all 18×32 held-unscored predictions, and 36 CAL/old-TRAIN aggregate scores. Max absolute numeric disagreement `8.800321515956e-08`; zero audited original CAL correct-class disagreements. The separate review does **not** recompute gradients or establish independently signed source/host authority.

`test_stem_output_residual_v18` has seven model-only mechanism cases plus two real-original archive/integrity cases. Local Python normal **9/9 PASS**, optimized `python -O` **9/9 PASS**, both zero skips when the exact archive is provided; tests include a second independent physical Torch fit, all 18 tensor SHA replay, contamination, tampering and duplicate-input negative checks. Source-only CI can separately run 7/7 without archives. All original model tensors, raw source text, per-case probabilities, source labels and optimizer state remain outside Git; only code, protocol and sanitized aggregate are committed. The hosted exact-HEAD CI must separately complete: local process success is not hosted/main acceptance.

**Scientific outcome: NO-GO for gating or Cell fission on these 32 already exposed CAL records.** Neither independent future/source-family utility, 421M vs 97M equal-lifecycle performance, a real Encoder forward in this round, Q24 integration, old-task out-of-sample retention, production 4096-Cell cost/p99, physical signed Control/CNS effect or FinalUse is established. Do not activate a production model from this study. Next scientific action: freeze *new* source-disjoint task families, register a learning-curve protocol and choose a metric-aware residual design without calibrating on these exposed labels; then compare it against the simplest budget-matched continued Head.

## Reproduction (original public artifact, no synthetic substitute)

```bash
cd qualification/stem-cell-v1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export HEPTA_V18_ORIGINAL_ZIP=/private/hepta-original-38546717991.zip
sha256sum "$HEPTA_V18_ORIGINAL_ZIP"  # must match immutable digest above
python -m unittest -q test_stem_output_residual_v18
python -O -m unittest -q test_stem_output_residual_v18
python stem_output_residual_v18.py prepare --archive "$HEPTA_V18_ORIGINAL_ZIP" --out /private/v18-input
python stem_output_residual_v18.py run --inputs /private/v18-input --out /private/v18-candidates
python stem_output_residual_v18_review.py --archive "$HEPTA_V18_ORIGINAL_ZIP" --inputs /private/v18-input --candidates /private/v18-candidates --out /private/v18-sanitized-review.json
```

Do not upload `/private/v18-input`, `/private/v18-candidates`, raw model archives, or original labels. The only publishable numerical artifact is `STEM_V18_ORIGINAL_RESIDUAL_RESULT_20261016.json`, the reviewer aggregate.
