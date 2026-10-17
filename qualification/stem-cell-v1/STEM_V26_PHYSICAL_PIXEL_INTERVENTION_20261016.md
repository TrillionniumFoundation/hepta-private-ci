# V26 — Original, real-pixel ScienceQA multimodal intervention (research only)

**2026-10-16 UTC. DRAFT / SHADOW_ONLY / DENY_ALL.** This is a standalone child of V25 PR #2550. It never modifies `main`, E3 source/model, learned production Stem, Rust Worker, NDU, Artifact/CAS/CNS, signed FinalUse or any trust owner.

## Frozen task identity and negative finding

V25 original ScienceQA historical publisher-labelled replay succeeded on [Actions 38931490244](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38931490244), with artifact `12081452577`. Its source and held-label SHAs re-opened exactly. **64 original cases**: original text-only 17 correct, original trained gated Head 24 correct, image-only Bridge 21 correct. The V24 originally frozen text-margin `< 0.005` route **selects `bridge_image_only`**, not `train_gate`: 21/64 image-needed decisions, 19 Top-1 decisions changed, 5 original errors rescued and 5 new errors, **17/64 correct**, exact McNemar p=1.0. This is a historical failure to demonstrate net accuracy lift. The prior V24 partial-identification interval is now superseded by true V25 archived labels.

V26 does not retune that route or select a new Head on the exposed historical 64. A separate `full_gate_diagnostic` retains the older 24/64 trained gate as a comparator, not an automatically selected candidate. The primary visual route uses the *actually preregistered* image-only Bridge arm throughout.

## New ORIGINAL physical trial contract

1. Re-fetch original immutable E3 git `b8b2f10fe38506972301e77e3836729a90200673`, verify the E3 stager, contract, model runner and frozen `LocalEncoder` file blobs. Require the SHA-256 original E3 sealed model predictions ZIP `7807b82d...`. No model substitution, synthetic tensor fallback or external effect.
2. Physically re-acquire `lmms-lab/ScienceQA-IMG@b9984af01798586705cee1fbdfa80a6dcbef04f1`, **exact 192-case source** SHA `a561916...`, original TRAIN/CAL label SHA `e8506bc...`, TEST label SHA `b15cb81...`. The researcher producer receives only source & TRAIN/CAL label locations. No TEST label path or label use until both prediction files are sealed, but note this is *process separation*, not OS enforced independent label custody.
3. Load the exact original Granite97 and DINOv2-small pretrained tensors, verify original safetensors and materialized runtime identities through hardened original E3 source. Encode 960 genuine original text prompts physically; encode original 128 TRAIN/CAL images once for the learned 147,840-scalar organ-level Bridge and original 769-scalar gated Head. **Before any TEST image forward**, calculate each source's text-only margin and require exactly the V24 SHA-bound 21 source IDs. Unselected TEST rows temporarily use a declared existing TRAIN image feature placeholder, not a test-image forward. The source stager has already downloaded and decoded all original source images for SHA-pinned cohort selection; **the claim is only that the 43 unselected TEST images are not forwarded through DINO before the conditional seal**, not that their bytes never existed on disk.
4. Actually encode **21 original selected TEST images / 3 DINO batches**, train/freeze the same original TRAIN-only Head, then seal create-only the conditional 64-case predictions. In each nonselected case, the final response comes **only** from text. (Stored feature placeholders for unselected sources are discarded.)
5. **After the conditional seal**, separately encode all **64 original TEST images / 8 DINO batches**. Physically rerun the same 80-update fit on the unchanged TRAIN/CAL inputs. Require byte-identical trained Bridge/Head SHA; independent original historical text and image/gate numeric TOP-1 must match original V25 output, within frozen FP32 tolerance `5e-4`. Require the 21 selected original-image decisions to match between 21-image and 64-image physical batches.
6. For those SAME 21 selected cases, physically feed the original pretrained DINO first an actual PNG **black-screen pixel image of identical dimensions**, rejecting any original already-all-black image as a no-op, then a different-original-source pixel image. Rerun the frozen-equivalent Head with identically trained parameters; no reoptimization, adaptive tuning or refitting on TEST labels. Seal all transformed outputs *before* reopening original TEST labels. Save only privacy-restricted, source-bound case predictions/input digests on the runner, never upload them.
7. Separate reviewer independently re-reads publisher source, TEST labels, all sealed original/black/swapped records, validates original/black/donor image file hashes against raw bytes, checks 21 selected and 43 text-only rows, rederives Brier/NLL/correct and paired rescues/harms, and publishes **sanitized aggregate** only. The reviewer uses no model/training optimizer.

**Cost boundaries:** physically counted visual batches and measured stage CPU/wall are real descriptive original host observations after model load. Conditional serving **21 versus 64** tests 3 vs 8 original DINO batches, but original TRAIN/CAL compute and model load remain charged, and the *same research run* executes full and lesion controls. It is not evidence of full lifecycle savings, sustained deployment p99, signed host telemetry, GPU/energy, model issuer authority, or 4,096-Cell throughput. No claim of human-verified visual necessity or prospective transfer arises from original historical TEST.

## Validation and permission

`test_v26_original_pixel_lesion.SourceOnly` (source-only) and `.OriginalArchive` (requires genuine original ZIP) are **distinct suites**. Source-only CI must not substitute fake original pretrained forwards. Branch push physically runs pinned original model, original genuine pixels and source, then after the seal independent label review. If original material, strict tensor parity, pretrained weights, source, bound case identities, true altered pixels, finite scores, positive physical image counters, or frozen-training SHAs fail, job fails and no success artifact is produced. All conclusions remain `HOLD / DENY_ALL` regardless of test outcome.

The real heavy hosted physical job may be slow or unavailable. No result is claimed until the exact V26 SHA completes. V25 hosted original label replay alone is an input prerequisite, **not** a V26 real-pixel success.

## Reproduce (requires original input + original pinned models)

```bash
cd qualification/stem-cell-v1
python -m unittest -q test_v26_original_pixel_lesion.SourceOnly
python -O -m unittest -q test_v26_original_pixel_lesion.SourceOnly
HEPTA_V26_ORIGINAL_ZIP=/private/archived-original.zip python -m unittest -q test_v26_original_pixel_lesion.OriginalArchive
# Physical stages are bound to source and model material and documented in
# .github/workflows/hepta-stem-v26-original-pixel-lesion.yml
```

**Never merge this draft to main or enable FinalUse, automatic Cell fission, NDU or real tool effects.**
