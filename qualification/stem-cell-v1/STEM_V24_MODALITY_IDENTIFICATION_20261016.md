# V24 — Original ScienceQA modality specialization: observable routing and unidentified value

2026-10-16 · Hepta research only · **DRAFT / SHADOW_ONLY / DENY_ALL**. Additive analysis after V22/V23 on PR #2364. No modification to `main`, original E3 material, pretrained models, Rust Worker, Control/CNS, CAS/FinalUse, NDU, selected Stem or existing frozen future study.

## Original evidence boundary and identity

- Original completed E3 physical text/vision producer: [Actions 38672941350](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38672941350), exact producer commit `b8b2f10fe38506972301e77e3836729a90200673`, artifact `11945106672`.
- The **original ZIP bytes** SHA256 = `7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30`; original sealed predictions member SHA256 = `c91824b378357c60f6272b785233854eaa762efd8fadc421bf99b996a58dd8e4`; original source identity `a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202`.
- Original **64 held TEST observations**, eight historical arm probability vectors per original case, source-only group identifiers and raw-output SHAs available; original **per-case answer labels are NOT present in this archive**. The original `independent-descriptive-review.json` contains aggregate correctness and rescue/harm counts; this V24 auditor **cannot independently recompute individual correctness**.
- V24 verifies exact outer ZIP/inner member SHA256 roster, source/held-label-seal joins, no label leakage, 64 unique matched case IDs, exact 4-class probability normalization, original no-authority status, all eight complete arms, frozen text/image-mask/calibration parity, reviewer accuracy/count consistency and exact binomial McNemar p-values. It does not independently authenticate producer signatures, label ownership, host hardware or original input media bytes.

## Actual historical readout and label-blind finding

| Historical arm | Published correct /64 | Recomputed Top-1 changes vs text | Published rescues / harms | Top-1 differences where both historical arms were wrong (inferred) |
|---|---:|---:|---:|---:|
| Text-only | 17 | 0 | — | — |
| Image only | 21 | 50 | 16 / 12 | 22 |
| Learned gated Head | 24 | 38 | 14 / 7 | 17 |
| Equal fusion | 16 | 26 | 5 / 6 | 15 |
| Calibrated fusion | 17 | 0 | 0 / 0 | 0 |

The inferred both-wrong count follows from: `changed_top1 − rescues − harms`. It is an **aggregate mathematical consequence of the archived reviewer counts**, not re-opened original labels or source-level visual necessity. The original calibrated weight is 0.0 (text-only). Unadjusted learned-gate McNemar p = 0.18924713134765625. No trial supports a new stable, independent or prospective modality benefit.

A source-only, outcome-blind conditional-vision policy is frozen for **protocol illustration** at a text Top-1/Top-2 margin strictly `< 0.005`. The historical archived text score would request the expensive image path in **21/64** cases and would change the Top-1 answer **19/64** times *if* the corresponding archived image-only predictions could be substituted. **No conditional image model forwards were actually skipped or executed; the extra image cost and end-to-end latency are NOT measured.**

With only the archived text-vs-image aggregate correctness, the 21-case conditional policy's *true task accuracy cannot be recovered*. Among the 19 prediction-changing cases it could have from 0–16 rescues and 0–12 harms subject to totals, giving a mathematically sharp but extremely wide **5/64 to 33/64** correctness interval. That interval is a **partial-identification bound**, not a measured score or a confidence interval. Separate real per-case labels, output/causal media perturbations and prospective groups are needed to evaluate this routing policy. The text/image answer-known oracle ceiling is 33/64 and is unattainable without answer information, not a deployable Cell policy.

## Executed code and tests

- `v24_multimodal_causal_bounds.py` — genuine original ZIP/receipt verifier and pure-stdlib aggregate analyzer; read-only, deterministic, create-only sanitized output, source-bound and explicit failure on alterations.
- `test_v24_multimodal_causal_bounds.py` — 25 source-only tests per mode (including small combinatorial exhaustive bound proof, forged score, bogus model-win, source drift, missing cases, fake probabilities and label-seal tampering), plus four genuine original-archive tests (tampered full ZIP, original top-1 counts, byte-identical re-execution, create-only write).
- Local **25/25 normal + 25/25 `python -O` source-only PASS**; with full pinned original archive, **29/29 normal + 29/29 `python -O` PASS**, zero skips. Local isolated analysis CPU, not user dot or target host. No pretrained forward, training, new modality ablation or real future data in this continuation.
- `STEM_V24_ORIGINAL_PAIRED_BOUND_20261016.json` is a **sanitized aggregate**, deliberately omitting original per-case source IDs, prediction vectors, photographs, labels, learned weights and private credentials. Its deterministically re-emitted bytes must match the locally committed checked result. SHA256 digest recorded by Git objects when submitted.
- `.github/workflows/hepta-stem-v24-modality-audit.yml` runs exact checked-out HEAD source-only tests for PR; on branch push requires the original pinned Actions artifact byte hash, both full original-data test modes and a `cmp` against the checked aggregate. Missing original artifact or changed SHA fails; it does NOT produce a fake positive result.

## Hard remaining prerequisites

1. Acquire *new, untouched, independently labeled* multimodal source families, including human-certified cases where visual/audio/temporal signal is necessary; lock sample selection/weights/training before label opening.
2. Physically execute real text Encoder and conditional image/audio/video module, with complete input/preprocessor/model/tokenizer digest joins and source-first original material. Include the genuine native small-VLM and OCR-only baselines.
3. On the same cases, compare text-only, OCR, frozen native, learned bridge, learned private Head, missing-media and shuffled-media **with real changed input bytes**. Compute paired whole-answer accuracy, negative transfer and modality necessity after postseal label custody.
4. Measure complete lifecycle CPU/GPU RSS, energy or explicit null, tail latency, Encoder forward count, training, routing, Q24 bridges, checkpoints and crash recovery for 64/256/1024/4096 Cells. A hypothetical 21/64 image-call schedule is not a measured saving.
5. Preserve V18–V23 hard HOLD (no genuine post-2026-10-17 independently sourced future panel) and all independent Control/CNS, CAS, signed FinalUse, source-owner and host attestation requirements. Never treat local signatures as independent institutions.

**Scientific verdict:** `HOLD_LABELS_AND_CAUSAL_NECESSITY_UNOBSERVED`; `stem_winner_verified=false`, `scientific_promotion_authorized=false`, `production_authorized=false`, `DENY_ALL`; no automatic Cell fission/fusion or `main` merge.

## Reproduce

```bash
cd qualification/stem-cell-v1
python -m unittest -q test_v24_multimodal_causal_bounds.SourceOnly
python -O -m unittest -q test_v24_multimodal_causal_bounds.SourceOnly
# Obtain the original artifact 11945106672, verify SHA256 first; don't substitute data.
export HEPTA_V24_ORIGINAL_ZIP=/private/e3-scienceqa-original.zip
python -m unittest -q test_v24_multimodal_causal_bounds
python -O -m unittest -q test_v24_multimodal_causal_bounds
python v24_multimodal_causal_bounds.py --archive "$HEPTA_V24_ORIGINAL_ZIP" --output /private/fresh-v24.json
cmp /private/fresh-v24.json STEM_V24_ORIGINAL_PAIRED_BOUND_20261016.json
```
