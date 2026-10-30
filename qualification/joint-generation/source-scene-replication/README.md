# Fixed new-initialization/new-noise source-scene replication

**The source-supervision decomposition passes 16/16 mechanism contrasts again; fair source NDU passes 0/8. Overall false.**

This repeats the previously fixed algorithm with new model seeds 103/107 and fixed new held-out noise seeds 3701/3702 (fold 0), 3711/3712 (fold 1). The original FIT parity split, training noise, 300 decoder + 500 supervised + 300 adaptation steps, calibration interval/evaluations and original five quality gates are unchanged. No seed search, threshold change or parameter sweep.

All sixteen models and all thirty-two calibrated heads freeze before any new noise is generated. All eight bases are prepared from scratch; the direct baseline is equally trained and calibrated, not restored from old weights. Historical exact-digest comparisons are intentionally not applied to new initializations. No model checkpoint is saved or restored.

The source model still adds FIT source-scene labels and masks ten instruction input dimensions; the baseline uses target labels and full inputs. The successful mechanism combines extra supervision and a representation change, **not a pure NDU intervention**. The nominal network is equal but source masking changes effective input capacity. Equal updates do not mean identical CPU or supervision information. Serving uses pixels and explicit commands only, never source labels/group IDs/target renderer.

New initializations and corruptions use the same historically studied scene/instruction groups. Thus this is not global unseen-group, unseen-class, natural-image or original-TEST evidence. Per-new-model group holdout remains; original validation and TEST observations stay closed.

## Results

Calibrated source minus the equally calibrated direct baseline, original partial-command full/low macro metrics:

| Fold | Seed | Noise | Objective | Δ CE | Δ greedy text | Δ pixel MSE | Five-gate pass |
|---:|---:|---:|---|---:|---:|---:|---|
| 0 | 103 | 3701 | additive | +0.201568 | +0.201311 | -0.006260 | Yes |
| 0 | 103 | 3702 | additive | +0.197803 | +0.196629 | -0.006531 | Yes |
| 0 | 103 | 3701 | ndu | +0.194019 | +0.192884 | -0.006172 | Yes |
| 0 | 103 | 3702 | ndu | +0.191364 | +0.191948 | -0.006364 | Yes |
| 0 | 107 | 3701 | additive | +0.199055 | +0.204120 | -0.006004 | Yes |
| 0 | 107 | 3702 | additive | +0.188008 | +0.191011 | -0.005601 | Yes |
| 0 | 107 | 3701 | ndu | +0.188073 | +0.197566 | -0.005580 | Yes |
| 0 | 107 | 3702 | ndu | +0.175545 | +0.185393 | -0.005299 | Yes |
| 1 | 103 | 3711 | additive | +0.141858 | +0.137897 | -0.005100 | Yes |
| 1 | 103 | 3712 | additive | +0.142785 | +0.146825 | -0.005026 | Yes |
| 1 | 103 | 3711 | ndu | +0.145475 | +0.147817 | -0.005173 | Yes |
| 1 | 103 | 3712 | ndu | +0.144768 | +0.149802 | -0.005103 | Yes |
| 1 | 107 | 3711 | additive | +0.138727 | +0.140873 | -0.005014 | Yes |
| 1 | 107 | 3712 | additive | +0.137067 | +0.142857 | -0.004864 | Yes |
| 1 | 107 | 3711 | ndu | +0.141349 | +0.142857 | -0.005103 | Yes |
| 1 | 107 | 3712 | ndu | +0.134020 | +0.138889 | -0.004689 | Yes |

All sixteen mechanism contrasts pass. Together with the preceding fixed-seed study, 32/32 mechanism contrasts pass; these finite dependent views are not 32 independent trials or a significance claim. The gains remain attributed to source supervision plus representation, not to NDU.

Fair N−A inside the source mechanism:

| Fold | Seed | Noise | Δ CE | Five-gate pass |
|---:|---:|---:|---:|---|
| 0 | 103 | 3701 | -0.000272 | No |
| 0 | 103 | 3702 | -0.001112 | No |
| 0 | 107 | 3701 | -0.002993 | No |
| 0 | 107 | 3702 | -0.004134 | No |
| 1 | 103 | 3711 | +0.000891 | No |
| 1 | 103 | 3712 | -0.000224 | No |
| 1 | 107 | 3711 | +0.000045 | No |
| 1 | 107 | 3712 | -0.001364 | No |

Source fair NDU remains 0/8, including actual text, joint and MSE regressions—not merely a small positive gain below threshold. Direct fair NDU passes 4/8, also failing its overall requirement. Uncalibrated source N−A passes 0/8. Hence mechanism=true, source-NDU=false, **overall=false**. All 120 contrasts are retained, including pooled descriptive controls; pooled values cannot rescue any failure.

Self-calibration passes all 32 comparisons and preserves greedy text exactly. Thirty fitted head temperatures reach the unchanged upper bound 8 and two are interior solutions. No interval is expanded and no fitted head is selected after evaluation.

## Cost

Whole fully waited child: **24.010599 CPU seconds**, 24.109025 wall seconds, 94984 KiB RSS under 60 CPU / 180 wall / 512 MiB / 4 MiB limits, CPU 0 / one numerical thread / existing shared synthetic lock. No retry. All fresh base preparation, 28 tests, data generation, copies/masks, calibration and evaluation are included.

Ledger: 8 bases / 16 clones; 2400 decoder + 4000 supervised + 4800 adaptation updates; 22480 forwards / 1533440 rows; 2416 decode calls / 28992 images; 896 NLL evaluations / 1397760 head-row evaluations; 124800 output joint tables plus 49920 internal base tables; 99840 support and 99840 argmax checks. Source handling adds 11240 input copies/masks, 766720 rows and 7667200 zeroed instruction elements. Twenty-eight tests are additional to scientific counters but inside whole child cost. Two FIT datasets, four new-noise datasets, zero original TEST calls.

The earlier source study cost 22.026948 CPU seconds separately; all historical qualification/research, source review and unknown supervisor tails remain additional, not zero. This replication is not a runtime-speed comparison.

## Portable files

`replication_group_data.py` exposes only the four fixed noise seeds and reuses the unchanged group partition; its rendering loop is AST-equivalent to the original recipe. `test_replication_group_api.py` contains executed invalid-domain tests that generate no observations. Existing source model/tests live in sibling `source-scene-decomposition`; group partition in `fit-group-holdout`.

```sh
PYTHONPATH=../fit-group-holdout:.. python -B -m unittest -v test_replication_group_api
```

Only portable wrapper, tests, fixed plan and aggregate results are published—not model weights, private inputs, runtime paths or per-request model outputs. No deployment/default change or unrestricted scientific runner.
