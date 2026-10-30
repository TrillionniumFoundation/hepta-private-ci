# Explicit source-scene supervision and command-blind perception

This opt-in mechanism separates learned perception from explicit command composition.
`SourceSceneModel` keeps the nominal 202→32→12×2 network and learned RGB decoder,
but copies every input and zeroes its ten instruction dimensions before forward
or gradient computation. The network predicts the source scene; existing explicit
semantic transport applies the requested edits. Serving needs observed pixels and
the request only—no source labels, group IDs or target renderer.

The 500 supervised pretraining updates use source-scene labels from the model's
own FIT training groups, instead of the direct baseline's target labels. This is
**additional FIT semantic supervision plus a representation change**, not a pure
NDU intervention. Nominal parameter count is equal, but ten encoder rows are
inactive, so effective functional capacity is not identical. Both mechanisms keep
300 adaptation updates with the original transport-aligned target-semantic anchor
and original A/N utility. A correct source scene maps to a correct requested target;
the anchor is not silently replaced with raw latent target CE.

Mode is explicit, clones retain type/mode and copy weights while resetting Adam,
and the model digest is mode-tagged. Checkpoint save/load intentionally reject
before I/O: no source-mode format or legacy checkpoint compatibility is claimed.
The original `JointModel` and default serving APIs are unchanged.

## Fixed comparison and scope

Sixteen new models: source/direct × additive/NDU × two original-FIT parity folds
× seeds 71/89. Each fold has 130 training and 130 held-out scene/instruction groups.
All bases get 300 decoder and 500 supervised updates, all clones get 300 adaptation
updates with matched batches. Both mechanisms receive exactly the same fixed
FIT-only calibration algorithm and original five quality gates. Direct controls
must reproduce all eight old adapted digests and four base digests.

All sixteen models and thirty-two calibrated heads freeze before held-out
observations are regenerated. These groups **and noise realizations were already
studied** and motivated this mechanism, so this is not a new blind evaluation.
Per-new-model group separation remains; original validation and TEST observations
stay closed. Twelve class templates remain known, not unseen-class generalization.
No post-result seed/fold/model selection, gate changes or retries.

The primary mechanism comparison is calibrated source-A minus calibrated direct-A
and source-N minus direct-N. Fair NDU increment is measured separately as calibrated
N minus calibrated A within each mechanism. Only their predeclared conjunction can
meet the joint claim; source-supervision gains cannot be relabelled NDU gains.
All 120 contrasts, including pooled descriptive values, are retained. Pooling does
not rescue failures. This finite synthetic RGB experiment does not restore the
original digit-study payloads or establish natural-image performance.

## Portable tests

Five new literal tests cover input immutability and forward/gradient command
invariance, finite-difference encoder/bias/head gradients including an inactive row,
clone/mode/digest/optimizer isolation, rejection before checkpoint I/O and explicit
mode/dimension requirements. The unchanged parent `model.py`/`utility.py` are dependencies:

```sh
PYTHONPATH=.. python -B -m unittest -v test_source_scene
```

Only portable model source, tests, fixed plan and aggregate results are published,
not weights, private inputs, runtime paths or per-request model predictions. No
production deployment, default change or unrestricted scientific runner is added.

## Results: mechanism positive, fair NDU still failed

The complete run passed all 26 literal tests and reproduced all eight direct
adapted models and four direct bases by exact digest. **All 16 primary mechanism
contrasts passed the original five gates.** Source supervision plus command-blind
perception substantially improves original joint CE, greedy text, target probability,
joint success and pixel MSE relative to the matched direct baseline. These gains
belong to the combined supervision/representation mechanism, **not NDU alone**.

Calibrated source minus calibrated direct, partial-command full/low macro:

| Fold | Seed | Noise | Objective | Δ CE | Δ greedy text | Δ pixel MSE | Five-gate pass |
|---:|---:|---:|---|---:|---:|---:|---|
| 0 | 71 | 2701 | additive | +0.196913 | +0.201311 | -0.004581 | Yes |
| 0 | 71 | 2702 | additive | +0.187256 | +0.191948 | -0.004357 | Yes |
| 0 | 71 | 2701 | ndu | +0.192859 | +0.199438 | -0.004571 | Yes |
| 0 | 71 | 2702 | ndu | +0.187371 | +0.194757 | -0.004321 | Yes |
| 0 | 89 | 2701 | additive | +0.208421 | +0.219101 | -0.007186 | Yes |
| 0 | 89 | 2702 | additive | +0.198439 | +0.206929 | -0.006333 | Yes |
| 0 | 89 | 2701 | ndu | +0.200368 | +0.210674 | -0.007002 | Yes |
| 0 | 89 | 2702 | ndu | +0.192564 | +0.200375 | -0.006146 | Yes |
| 1 | 71 | 2711 | additive | +0.147368 | +0.140873 | -0.005173 | Yes |
| 1 | 71 | 2712 | additive | +0.141051 | +0.143849 | -0.005139 | Yes |
| 1 | 71 | 2711 | ndu | +0.149321 | +0.145833 | -0.005165 | Yes |
| 1 | 71 | 2712 | ndu | +0.139622 | +0.142857 | -0.005144 | Yes |
| 1 | 89 | 2711 | additive | +0.156056 | +0.161706 | -0.004995 | Yes |
| 1 | 89 | 2712 | additive | +0.151240 | +0.156746 | -0.004890 | Yes |
| 1 | 89 | 2711 | ndu | +0.159608 | +0.164683 | -0.005195 | Yes |
| 1 | 89 | 2712 | ndu | +0.151857 | +0.154762 | -0.004985 | Yes |

Fair NDU comparison within the stronger calibrated source mechanism:

| Fold | Seed | Noise | N−A CE | Five-gate pass |
|---:|---:|---:|---:|---|
| 0 | 71 | 2701 | +0.000314 | No |
| 0 | 71 | 2702 | -0.000370 | No |
| 0 | 89 | 2701 | +0.000080 | No |
| 0 | 89 | 2702 | +0.000399 | No |
| 1 | 71 | 2711 | +0.000603 | No |
| 1 | 71 | 2712 | -0.000402 | No |
| 1 | 89 | 2711 | -0.000087 | No |
| 1 | 89 | 2712 | +0.000080 | No |

Source fair NDU passes **0/8**; direct fair NDU remains **2/8**. Several source
N−A contrasts also regress in text mass, greedy text, joint success or pixel MSE,
not merely fail the CE-size threshold. Uncalibrated source N−A also passes 0/8.
Thus mechanism=true, source-NDU=false and **overall=false**. All 120 contrasts
are retained, including the unfavorable values and pooled descriptive controls.

Self-calibration passes all 32 comparisons; all 32 temperatures reach the fixed
upper inverse-temperature bound 8, with no expansion. Source-A calibrated partial
macro CE is about .982–.992. A descriptive upper-bound check on saved scalars gives
1−CE=.008157–.018080, always above .005: this loose reward bound does **not** establish
that the original NDU gain threshold is impossible. It cannot excuse the failure.

## Complete cost

Whole child: **22.026948 CPU seconds**, 22.128531 wall seconds, 93832 KiB RSS,
under 60 CPU / 180 wall / 512 MiB / 4 MiB, CPU 0, one numerical thread and the
existing synthetic lock. Fully waited, no retry, model restore or checkpoint save.
All new base preparation, tests, data generation, copies, calibration and evaluation
are inside this receipt. Equal fixed update counts do not mean identical CPU cost,
and extra source-label supervision is not information-equivalent to target-only FIT.

Ledger: 8 bases / 16 clones; 2400 decoder + 4000 supervised + 4800 adaptation
updates; 22480 forwards / 1533440 rows; 2416 decode calls / 28992 images; 896 NLL
evaluations / 1397760 head-row evaluations; 124800 output tables plus 49920 internal
base tables; 99840 support and 99840 argmax checks. Source input handling adds
11240 copies/masks across 766720 rows, zeroing 7667200 instruction elements.
Literal-test work is additional to these scientific counters but included in whole
child CPU. Two FIT datasets, four held-out noise datasets, zero original TEST calls.

Historical experiment/qualification costs, source preparation/review and unknown
supervisor tails remain additional, not zero. Per-model preparation, adaptation,
calibration and serving costs are retained in SUMMARY. No general-purpose model,
fresh blind group or natural-image performance claim follows from this finite task.
