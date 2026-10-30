# Same-count new FIT calibration views: both strong controls regress

**New−old calibration passes 0/8 for static-A and 0/8 for fresh-A. All sixteen CE differences are negative and pixel MSE differences are worse. Overall false.**

The motivation was a posthoc observation, not an established cause: fresh-noise A models had better greedy text in eight paired strata, but their calibrated CE improved in only three; static-A gained more from the existing calibration. This fixed new experiment tests whether changing reused FIT calibration views alters that comparison. It does not assume a distribution shift: both noise streams use the same recipe.

## Fair, same-count calibration intervention

Four source-masked source-supervised bases (folds0/1, seeds103/107) are shared by eight A models: static and fresh training streams. Every model retains 300 ×64 adaptation steps, the same sampler, additive utility, ordinary anchor .2 and original optimizer. All four base and eight adapted parameter digests exactly reproduce the historical studies. All old uncalibrated/calibrated model metrics, base metrics, old calibration records/profile keys and dataset manifests reproduce exactly—not merely within a tolerance. No old model weights were restored.

After all eight models froze, one new calibration dataset per fold was generated from that fold's same130 FIT content groups, six new corruptions per group, seeds5701/5702. Each fold's immutable view cache is shared across static/fresh and both model seeds. Old and new fits each use **1560 full/low rows per head**, separately: old fits only old views, new fits only new views, never a3120-row concatenation. Both groups get the same additional information and fitting budget. The original [.125,8] bounds,24 bisection steps and28 NLL evaluations/head stay fixed.

New calibration observations never enter model gradients. All32 heads/16 profiles freeze before the same previously studied held-out noises3701/3702/3711/3712 are regenerated. Original validation and TEST observations remain closed. The new observations reuse already-supervised FIT content groups; this is not independent held-out calibration, fresh blind/global-group evidence, or a general real-image augmentation technique. The separate deterministic pseudorandom stream is not a proof of statistical independence.

Old/new FIT groups, target labels and commands are identical, and full-input hashes are disjoint. We did not retain an exhaustive hash inventory of all38400 fresh training observations, so no exhaustive new-calibration-versus-fresh-training overlap claim is made. Extra synthetic views and their real costs are explicit. Equal update and added calibration budgets do not mean identical elapsed CPU.

This study trains only A models. Computing unchanged N utility auxiliaries preserves historical arithmetic; it is not NDU training or an NDU benefit. The previous fixed-temperature derivative-domain refusal remains immutable; this experiment uses existing forward/NLL APIs and never bypasses that gradient guard.

## All primary results

Partial-command full/low macro CE differences. “Content pass” refers only to fresh_new−static_new, not overall acceptance; both new−old calibration gates fail in every row.

| Fold | Seed | Noise | Static new−old | Fresh new−old | Fresh−static, new | Fresh−static, old | Content pass |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | 103 | 3701 | -0.005250 | -0.010149 | -0.004530 | +0.000370 | No |
| 0 | 103 | 3702 | -0.006060 | -0.010456 | -0.006730 | -0.002334 | No |
| 0 | 107 | 3701 | -0.012779 | -0.011064 | +0.004968 | +0.003254 | No |
| 0 | 107 | 3702 | -0.014322 | -0.011788 | +0.002300 | -0.000233 | No |
| 1 | 103 | 3711 | -0.012558 | -0.002255 | +0.001180 | -0.009123 | No |
| 1 | 103 | 3712 | -0.010724 | -0.001899 | +0.003188 | -0.005637 | No |
| 1 | 107 | 3711 | -0.008863 | -0.001962 | +0.006120 | -0.000781 | Yes |
| 1 | 107 | 3712 | -0.010812 | -0.002073 | +0.009775 | +0.001037 | Yes |

Static new−old CE ranges **−0.014322 to −0.005250**; fresh new−old ranges **−0.011788 to −0.001899**. Text mass and joint success also decrease in every one of these16 strata, and pixel MSE increases throughout. Greedy text stays exactly unchanged, as expected from the positive-temperature serving contract; unchanged ranking is not new learned improvement.

Fresh_new−static_new passes2/8, with CE positive in6/8 and range−0.006730 to+0.009775. The old corresponding comparison passed0/8 with3 positive CE changes. This apparent relative improvement comes between **two services that both became worse than their own old-view controls**. It cannot rescue any of the three predeclared primary conjunctions or overall false. No weaker-baseline substitution, pooling, temperature search or gate relaxation is allowed.

All96 contrasts retain full/low/macro, all/partial and all eleven metrics, including old/new self-calibration versus uncalibrated serving. Both self-calibration variants pass16/16 against uncalibrated models, but old-view calibration is the stronger control. The12 predeclared descriptive interaction records measure `(fresh_new−static_new)−(fresh_old−static_old)` for all metrics, including pooled views. Their eight unpooled CE values are six positive/two negative (−0.004900 to+0.010303); they have **no gate**, no extra model call and no statistical causal or significance claim.

All new fitted temperatures are interior. Static new temperatures range1.4115–1.5732, versus six of eight old heads at8; fresh new temperatures range1.2377–2.0793, versus old1.8494–3.6238. Lower fitted temperatures or fresh fitting inputs are not automatically better generation policies. Held-out probability-calibration quality was not separately measured, so this result does not prove that NLL fitting or calibration in general is invalid. It closes this fixed replacement proposal without a rescue sweep.

## Validation and actual cost

All **43 tests passed before scientific FIT generation**:40 byte-identical prior tests and three model-free renderer-stub tests for the new view generator. The tests cover exact130×6 inventory, targets/instructions, full/low recipe, immutable arrays, fixed-seed determinism and invalid admission. A source-only v1 was never run; v2 changed only a readonly documentation/provenance statement, with all30 Python sources byte-identical. No numerical retry occurred.

Fully waited child: **17.314151 CPU seconds**,17.411064 wall seconds,108816 KiB RSS, under30CPU/90wall/512MiB/4MiB, CPU0, one numerical thread and the existing synthetic lock. All source checks, tests, preparation, generation, training, fits, serving and hashing are included.

Ledger:4 shared bases/8 clones;1200 decoder+2000 supervised+2400 adaptation updates;11256 forwards/779200 rows;1208 decodes/14496 images.4800 group aggregations/307200 row visits remain common auxiliary work.16 FIT serving calls/24960 tables;32 heads/896 NLL evaluations/1397760 head-row evaluations.56 evaluation calls/87360 tables plus49920 internal calibrated base tables;174720 CDF checks and99840 support/argmax checks each. Source masks zero7792000 elements. Two old FIT datasets, two new calibration datasets, four studied held-out datasets and zero TEST calls.

Fresh training redraws38400 observations (7372800 Gaussian values); twelve stream SHA passes cover374170026 bytes. Only one31180800-byte fresh cache is retained at a time. New calibration adds1560 renderer/uniform draws,299520 Gaussian values and3120 paired view rows; both fold caches total5054400 payload bytes. Their shared generation costs **0.056206970 CPU seconds**, already inside whole CPU and billed once per fold. All Python SHA work totals16675 constructions/416356631 bytes/zero copies. Per-arm training, shared preparation/guards, calibration and serving timings remain in SUMMARY; stage timings are not an exhaustive additive partition.

Prior static16.696710CPU, fresh18.582851CPU, derivative qualification/preflight and older research remain separate history. Source/review and unknown supervisor tails are additional, not zero. No model checkpoints saved/restored, default-law changes or deployment.

## Portable helper tests

```sh
PYTHONPATH=../fresh-fit-view-training python -B -m unittest -v test_calibration_views
```

Only the portable helper/tests, executed prospective plan and complete aggregates are published; no model weights, private input arrays, per-request predictions or runtime paths, and no unrestricted scientific runner.
