# Fresh synthetic FIT noise does not rescue grouped-view NDU

**groupN−A, groupN−rowN and rowN−A each pass 0/8 original five-gate contrasts. Overall false.**

This fixed experiment tests a concrete, unproven explanation for the prior negative result: repeatedly optimizing only six fixed corruptions might limit risk training. Twelve source-masked models share four freshly trained source-supervised bases, across folds 0/1 and model seeds 103/107. Each base has additive A, row-wise NDU and grouped-view NDU clones. The prior static-noise experiment remains unchanged as a historical reference, not a substitute for the matched fresh A control.

## Exact intervention and fairness

Pretraining (300 decoder + 500 source-label CE steps per base) and FIT-only calibration still use the original fixed FIT observations. All four base digests exactly reproduce the historical static experiment; adapted model equality is neither expected nor claimed. All arms have the same 300 × 64 adaptation updates and the same eight-group × four-position × paired full/low schedule. Each selected position now receives a fresh source-scene rendering with the original uniform(.03,.25) corruption recipe, 192 Gaussian values, clipping and exact 2×2 mean/repeat low view. Source labels, commands and targets come only from each model's FIT groups.

The 300-step stream is precomputed once per base with fixed seeds 19103, 19107, 119103 and 119107, made immutable with bytes-backed arrays, and shared exactly by all three arms. Construction and before/after each arm SHA checks pass; only one base cache is retained. Models cannot adapt the stream. Source scenes are synthetically rerenderable: this adds **38,400 unique observations** and real preparation/memory/hash cost, not a free or generally available real-image augmentation.

All arms still compute four raw/aligned A/N branches and both grouped aggregations. Only the selected utility gradient changes; ordinary aligned row-mean anchor .2 is added afterward, never risk-weighted. Rho=1.5, reward, original five gates and all other settings remain unchanged. Sampled four-corruption risk is not an unbiased continuous-corruption risk estimate or an unbiased Adam update. Training still uses the independent categorical output law, while serving remains normalized maximal coupling plus FIT calibration; no exact serving-gradient claim.

All 12 models and 24 calibrated heads freeze before regeneration of the same previously studied held-out noises 3701/3702/3711/3712. Original validation and TEST observations remain closed. This is not fresh blind/global unseen-group evidence; no seed/model selection, gate relaxation or retry.

## Fixed results

Original calibrated partial-command full/low macro CE differences:

| Fold | Seed | Noise | groupN−A | groupN−rowN | rowN−A | Either primary five-gate pass |
|---:|---:|---:|---:|---:|---:|---|
| 0 | 103 | 3701 | -0.023577 | -0.010266 | -0.013311 | No |
| 0 | 103 | 3702 | -0.024827 | -0.009758 | -0.015069 | No |
| 0 | 107 | 3701 | -0.003027 | +0.001030 | -0.004057 | No |
| 0 | 107 | 3702 | -0.005124 | +0.001396 | -0.006520 | No |
| 1 | 103 | 3711 | -0.009163 | -0.001107 | -0.008055 | No |
| 1 | 103 | 3712 | -0.008212 | -0.001240 | -0.006972 | No |
| 1 | 107 | 3711 | +0.000938 | +0.001172 | -0.000234 | No |
| 1 | 107 | 3712 | +0.000040 | +0.000785 | -0.000745 | No |

Against A, groupN has negative CE in 6/8 strata, with range −0.024827 to +0.000938; pixel MSE regresses in 7/8. Against rowN, CE is positive in four and negative in four (−0.010266 to +0.001396), all below +0.005. RowN−A has negative CE and worse MSE in all eight. Fresh noise therefore does not rescue NDU in this fixed test; the prior partial recovery against rowN does not generalize to this stream. These results do not prove the cause of the original failure or rule out every augmentation method.

All 72 contrasts preserve full/low/macro, all/partial and all metrics, with pooled descriptive comparisons and self-calibration. Self-calibration passes 24/24 but cannot rescue the substantive NDU gates. All three primary comparison gates and overall remain false.

## Validation and actual cost

All **40 tests passed before FIT generation**, including 37 byte-identical prior tests and three new model-free renderer-stub tests. They check deterministic/different-seed streams, immutable input storage, exact paired views and targets/instructions, counts and invalid admission. Earlier eight-coordinate group utility and unweighted-anchor finite-difference tests also reran successfully. Literal fixtures do not certify a scientific benefit.

Whole fully waited child: **18.582851 CPU seconds**, 18.664875 wall seconds, **106652 KiB RSS**, under 60 CPU / 180 wall / 512 MiB / 4 MiB, CPU 0, one numerical thread and the existing synthetic lock. Tests and every new scientific preparation, update, calibration and evaluation are included. Equal updates do not mean equal CPU or equal information relative to historical static noise.

Additional fresh preparation: **1.535564088 CPU seconds**; SHA guards: **0.446677104 CPU seconds**, already included in whole CPU, not additional charges. Shared preparation is billed once per base, not three times; adaptation timings exclude the after-arm guards. There are 38,400 renderer calls/uniform draws and 7,372,800 Gaussian values, producing 76,800 paired view rows shared by the arms. Four caches each contain 31,180,800 payload bytes, only one retained at a time; theoretical construction payload bound 62,361,600 bytes excludes runtime overhead. Twenty-eight SHA passes cover **873,063,394 bytes**, including canonical headers.

Unchanged scientific ledger: 4 bases / 12 clones; 1200 decoder + 2000 supervised + 3600 adaptation updates; 14856 forwards / 1015840 rows; 1208 decodes / 14496 images; 7200 group aggregations / 460800 row visits / 57600 group values. Calibration: 24 heads / 672 NLL evaluations / 1048320 head-row evaluations. Serving: 56 calls / 87360 tables plus 37440 internal base tables; 174720 CDF, 74880 support and 74880 argmax checks. Source masks zero 10158400 elements. Two FIT and four held-out datasets; zero original TEST calls, no weights saved/restored.

Historical static experiment cost 16.696710 CPU seconds and earlier qualification/research are additional, not zero; source/review and supervisor tails remain additional. SUMMARY retains per-base, per-arm, calibration, generation and serving timing records. This is not a speedup claim.

## Portable helper tests

Run alongside the already published sampler and its sibling dependencies:

```sh
PYTHONPATH=../grouped-view-training:../grouped-view-risk:../explicit-semantic-transport:../transport-aligned-training:.. python -B -m unittest -v test_fresh_views
```

Only portable helper/tests, fixed plan and full aggregate results are published. No model weights, private input arrays, per-request predictions or runtime paths; no default change, deployment or unrestricted scientific runner.
