# Fixed grouped-view risk training against matched strong baselines

**Both groupN−A and groupN−rowN pass 0/8 original five-gate contrasts. Overall false.**

This scientific run tests the separately qualified equal-group entropic objective. Twelve source-masked models share four fresh source-supervised bases: additive A, original per-row NDU and new grouped-view NDU, across two fixed FIT folds and seeds 103/107. All three arms use identical immutable schedules: eight distinct content groups × four of six variants × paired full/low views = 64 rows, for 300 adaptation updates. A and rowN receive the same sampler change; they are not older IID-model baselines.

Every arm computes all four raw/aligned A/N terms plus groupA and groupN aggregation. Only the selected utility gradient differs, and each adds the same ordinary row-mean aligned anchor with weight .2 afterward. Risk weights never multiply the anchor. The grouped risk is over a sampled four-variant subset, not an unbiased estimate of complete twelve-view risk; no unbiased-Adam claim. Content groups are source-scene/instruction groups, not target classes. All source labels and new bases use only each model's FIT training groups.

Training retains the original independent categorical output law with semantic reward pullback. Evaluation retains the original normalized maximal coupling plus FIT-only calibration. This experiment does not claim the training gradient is an exact derivative of that coupled/calibrated serving law. Reward, rho=1.5, original five gates and calibration bounds/evaluation counts are unchanged.

All twelve models and twenty-four calibrated heads freeze before held-out regeneration. Groups and noise seeds 3701/3702/3711/3712 were already studied, not new blind or global unseen-group evidence. Original validation and TEST observations remain closed. No model/seed/noise selection, threshold adjustment or retries.

## Fixed scientific results

Original calibrated partial-command full/low macro CE differences:

| Fold | Seed | Noise | groupN−A | groupN−rowN | rowN−A | Either primary five-gate pass |
|---:|---:|---:|---:|---:|---:|---|
| 0 | 103 | 3701 | +0.000028 | +0.002229 | -0.002201 | No |
| 0 | 103 | 3702 | -0.000426 | +0.003864 | -0.004290 | No |
| 0 | 107 | 3701 | -0.000982 | +0.001227 | -0.002209 | No |
| 0 | 107 | 3702 | -0.002009 | +0.001657 | -0.003665 | No |
| 1 | 103 | 3711 | -0.000902 | -0.000130 | -0.000773 | No |
| 1 | 103 | 3712 | -0.000314 | +0.000832 | -0.001146 | No |
| 1 | 107 | 3711 | -0.000483 | +0.000332 | -0.000815 | No |
| 1 | 107 | 3712 | -0.001041 | +0.000512 | -0.001553 | No |

Compared with rowN, groupN improves pixel MSE in all eight strata and does not regress greedy text, text mass or joint success. Seven CE changes are positive, but the maximum +0.003864 is below the unchanged +0.005 threshold; one CE change is negative. Thus all eight fail the substantive primary threshold, not a relaxed alternative.

Compared with the stronger matched A baseline, groupN has negative CE in seven strata and **worse pixel MSE in all eight**; every contrast fails. RowN−A also fails all eight, with all CE differences negative. This is partial recovery of rowN losses, **not evidence that NDU beats A**. Both primary gates and overall are false.

All 72 contrasts retain full/low/macro, all/partial and all metrics, including self-calibration and pooled descriptive comparisons. Self-calibration passes 24/24; it cannot rescue NDU gates. No pool or threshold change reclassifies a failure.

## Integration and cost

All **37 tests passed before FIT generation**. New K=8 partial-command integration tests check the independent flattened pulled-reward law, exact additive parity, fixed sampler inventory/determinism and eight coordinates each for utility-only and utility-plus-unweighted-anchor gradients. Maximum absolute errors were 3.35e−11 and 3.48e−11 versus the prospectively fixed 3e−8 bounds. The separate six-test risk qualification is not substituted for these integration checks.

Whole fully waited child: **16.696710 CPU seconds**, 16.772659 wall seconds, 93256 KiB RSS under 60 CPU / 180 wall / 512 MiB / 4 MiB, CPU 0, one numerical thread and the existing synthetic lock. All new preparation, tests, schedule creation, masks, extra aggregations, FIT calibration and evaluation are included. Equal update counts do not assert equal elapsed CPU.

Ledger: 4 bases / 12 clones; 1200 decoder + 2000 supervised + 3600 adaptation updates; 14856 forwards / 1015840 rows; 1208 decode calls / 14496 images; 1200 schedule batches / 9600 content-group selections / 38400 variant selections / 76800 scheduled view rows reused by all three arms. All arms together compute 7200 group aggregations / 460800 row visits / 57600 group CE values.

Calibration: 24 heads, 672 NLL evaluations / 1048320 head-row evaluations. Serving: 56 calls / 87360 output tables plus 37440 internal base tables; 174720 CDF checks, 74880 support and 74880 argmax checks. Source masks zero 10158400 instruction elements across 1015840 copied rows. Two FIT datasets, four held-out datasets, zero original TEST calls; no weights saved/restored. Tests are additional to scientific counters but inside whole CPU.

Separate prior risk qualification cost 0.144417 CPU seconds; older research, source/review and unknown supervisor tails are additional, not zero. This smaller experiment is not claimed as a runtime speedup over larger prior studies.

## Portable integration tests

The sampler and integration helper require published sibling risk, transport and aligned-training helpers plus the parent utility/control modules:

```sh
PYTHONPATH=../grouped-view-risk:../explicit-semantic-transport:../transport-aligned-training:.. python -B -m unittest -v test_grouped_training
```

Only portable helpers/tests, fixed plan and complete aggregates are public. No model weights, private inputs, per-request predictions or runtime paths; no default change, deployment or unrestricted scientific runner.
