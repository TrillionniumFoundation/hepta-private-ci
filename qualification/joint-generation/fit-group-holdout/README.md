# Fixed original-FIT group-held-out calibration replication

**Calibration passed 16/16 contrasts; fair NDU increment passed only 2/8. Overall false.**

This is a new finite synthetic RGB experiment, not recovery of the original digit study. The original 260 FIT groups are split by their fixed catalog parity into two folds. Each new model trains and fits temperatures only on its 130 training groups. All eight models and all sixteen fitted heads freeze before fresh held-out observations are generated. Original validation and TEST observations are unused.

Groups were historically seen by earlier research, opposite folds use complementary training groups, and the twelve scene templates remain known. Thus this is per-new-model instruction/scene-combination holdout, not globally unseen groups, unseen classes, or natural-image evidence. No result-based fold/model selection. Training diversity is halved while updates stay fixed, so comparisons to previous 260-group scores are not causal generalization estimates.

Both A and N use the same base, batch schedule, updates, FIT-only calibration and original five gates. The temperature interval remains [1/8,8], with 24 bisection steps and 28 objective evaluations per head. **All sixteen fits reached the fixed upper boundary 8; the bound was not expanded.** Original rewards, greedy-text definition and no-regression tolerances are unchanged.

## Results

Original joint certainty-equivalent changes on partial commands, full/low macro:

| Fold | Seed | Noise | A calibration | N calibration | Fair calibrated N−A | Five-gate pass |
|---:|---:|---:|---:|---:|---:|---|
| 0 | 71 | 2701 | +0.057182 | +0.053872 | +0.004368 | No |
| 0 | 71 | 2702 | +0.062616 | +0.055389 | -0.000485 | No |
| 0 | 89 | 2701 | +0.047420 | +0.046330 | +0.008133 | Yes |
| 0 | 89 | 2702 | +0.053183 | +0.050424 | +0.006275 | Yes |
| 1 | 71 | 2711 | +0.046284 | +0.039772 | -0.001350 | No |
| 1 | 71 | 2712 | +0.053925 | +0.049169 | +0.001027 | No |
| 1 | 89 | 2711 | +0.049422 | +0.041905 | -0.003639 | No |
| 1 | 89 | 2712 | +0.056908 | +0.051150 | -0.000537 | No |

Self-calibration improves the original probability/quality metrics in all sixteen contrasts while keeping greedy text unchanged. Fair calibrated N−A has negative CE or other regressions in several strata; only fold 0 / seed 89 passes both noise views. Uncalibrated N−A passes 5/8 but cannot replace the fair calibrated comparison. All 48 contrasts, including pooled descriptive results, remain in `SUMMARY.json`; pooled values cannot rescue a failure. No statistical independence or significance claim.

## Cost and scope

The completely waited child used **11.493732 CPU seconds**, 11.543454 wall seconds and 90520 KiB RSS under 30 CPU / 120 wall / 512 MiB / 4 MiB limits, CPU 0, one numerical thread and the existing shared synthetic lock. No retries, checkpoints or external model payloads.

All new preparation, 21 literal tests, data generation, 1200 decoder + 2000 supervised + 2400 adaptation updates, FIT calibration and evaluation are included. Ledger: 11240 forwards / 766720 rows; 1208 decoder calls / 14496 images; 448 NLL evaluations / 698880 head-row evaluations; 62400 output joint tables plus 24960 internal base tables; 49920 argmax and 49920 support checks. Original TEST calls: 0. Historical qualification/research, source review and unknown supervisor tails remain additional, not zero.

## Portable artifacts

`group_data.py` changes only fixed group allocation and noise seeds; the renderer/corruption recipe is unchanged. `test_group_api.py` contains the executed refusal tests, which create no observations. With the published parent task sources available:

```sh
PYTHONPATH=.. python -B -m unittest -v test_group_api
```

The fixed `PLAN.md` records the allocation, algorithm and ledger. Previously qualified calibration and numerical law are in sibling `semantic-temperature` and `coupled-simplex-longdouble` directories. Public files exclude model weights, private inputs, per-request model outputs and runtime paths. This source-only publication does not add an unrestricted scientific runner.
