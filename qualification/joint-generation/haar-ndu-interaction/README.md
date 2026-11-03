# Fixed Haar coordinates × original row NDU: no rescue

**All 24 required unpooled five-gate comparisons fail; overall false.**
HaarN−HaarA worsens CE, text mass, joint success and pixel MSE in all eight strata;
greedy text worsens in seven. HaarN−rawN improves CE in seven but its maximum gain
is only about .004589, below .005. The descriptive difference-in-differences CE is
positive in three and negative in five. Neither partial recovery nor earlier
HaarA directional gains constitute success. The fixed adaptation-coordinate rescue
hypothesis is closed; no new basis, threshold, seed or risk sweep follows here.

Four raw Source bases are pretrained once (300 decoder + 500 source-CE steps),
then each yields raw/Haar × A/rowN fresh-moment clones. Every clone receives the
same 300 grouped64 updates, learning rate .003, ordinary aligned anchor .2 and
original rho1.5 where applicable. RowN is the ORIGINAL transported independent
joint-output per-row CE, not group/global risk or score. Coupled, FIT-calibrated
serving remains unchanged: the training/serving law mismatch is NOT repaired.
Raw and Haar execute identical coordinate auxiliary work, raw discarding its
result; this is benchmark work matching, not natural deployment timing.

The rawA/HaarA eight final models and rawN four models, four shared bases, full
historical metrics, FIT profiles and dataset records reproduce exactly. All16
models then all32 calibrated heads froze before regeneration of known heldout
noise. Original TEST/VAL remain closed. This is not a new blind-group replication.
Whole-FIT boundary admission is the prior fixed 1e-12 engineering guard, not a
universal IEEE proof; original literal and serving guards are unchanged.

## Prespecified primary results
The first two groups compare HaarN against two strong A baselines; the third is
the coordinate-mechanism requirement. Overall requires all three groups, each
8 unpooled original five-gate passes. Pooled results cannot rescue any failure.

| Contrast | Fold | Seed | Noise | CE change | Pixel MSE change | Pass |
|---|---:|---:|---:|---:|---:|---|
| HaarN_minus_HaarA | 0 | 103 | 3701 | -0.002499993 | +0.000023599 | False |
| HaarN_minus_HaarA | 0 | 103 | 3702 | -0.006822231 | +0.000095736 | False |
| HaarN_minus_rawA | 0 | 103 | 3701 | -0.000996546 | -0.000003060 | False |
| HaarN_minus_rawA | 0 | 103 | 3702 | -0.004528853 | +0.000069599 | False |
| HaarN_minus_rawN | 0 | 103 | 3701 | +0.001204917 | -0.000033706 | False |
| HaarN_minus_rawN | 0 | 103 | 3702 | -0.000238916 | -0.000012966 | False |
| HaarN_minus_HaarA | 0 | 107 | 3701 | -0.000780073 | +0.000012024 | False |
| HaarN_minus_HaarA | 0 | 107 | 3702 | -0.002718548 | +0.000037852 | False |
| HaarN_minus_rawA | 0 | 107 | 3701 | +0.002035730 | -0.000052417 | False |
| HaarN_minus_rawA | 0 | 107 | 3702 | -0.001389225 | +0.000017925 | False |
| HaarN_minus_rawN | 0 | 107 | 3701 | +0.004244763 | -0.000078695 | False |
| HaarN_minus_rawN | 0 | 107 | 3702 | +0.002276054 | -0.000054422 | False |
| HaarN_minus_HaarA | 1 | 103 | 3711 | -0.001404765 | +0.000035185 | False |
| HaarN_minus_HaarA | 1 | 103 | 3712 | -0.001522888 | +0.000035766 | False |
| HaarN_minus_rawA | 1 | 103 | 3711 | +0.000108234 | +0.000003257 | False |
| HaarN_minus_rawA | 1 | 103 | 3712 | +0.000604367 | +0.000004247 | False |
| HaarN_minus_rawN | 1 | 103 | 3711 | +0.000880884 | -0.000012738 | False |
| HaarN_minus_rawN | 1 | 103 | 3712 | +0.001750217 | -0.000029965 | False |
| HaarN_minus_HaarA | 1 | 107 | 3711 | -0.001002151 | +0.000022512 | False |
| HaarN_minus_HaarA | 1 | 107 | 3712 | -0.000707997 | +0.000011332 | False |
| HaarN_minus_rawA | 1 | 107 | 3711 | +0.003773885 | -0.000070293 | False |
| HaarN_minus_rawA | 1 | 107 | 3712 | +0.001454835 | -0.000029892 | False |
| HaarN_minus_rawN | 1 | 107 | 3711 | +0.004589157 | -0.000101412 | False |
| HaarN_minus_rawN | 1 | 107 | 3712 | +0.003007460 | -0.000054777 | False |

SUMMARY retains all108 contrasts (four self-calibration and five cross-arm claims,
with pooled records), all11 metrics/channels/populations, and all12 descriptive
interactions (HaarN−HaarA)−(rawN−rawA), explicitly gate=null. Interactions are not
additional success gates or causal generalization evidence. Full shared-base and
historical fullfactor metrics remain descriptive, not new concurrent fair arms.

## Complete costs and validation
48 literal tests passed,43 toy initializations,12 toy Adam updates and4 manual SGD
parameter steps, all inside the child cost. Fully waited child cost24.903823 CPU s;
exact wall, RSS, stage timings and wait4 receipt are retained in SUMMARY. Limits:
30CPU/90wall/512MiB/4MiB,CPU0/single thread/original shared lock/no retry.
Four shared bases,16 clones;1200 decoder,2000 supervised and4800 adapt updates.
18512 forwards/1296160 rows include40 boundary forwards/31200 rows;1208 decode
calls/14496 images. Each coordinate arm records8 encoder conversions/256 column
rows and4848 input transforms/357120 rows. All9600 group auxiliary calls,
896 NLL evaluations, serving/normalization/SHA work and phase counters are retained.
Shared preparation is charged once, not free or duplicated per arm. Prior Haar
qualification .199515 CPU s and inherited studies remain additional; unknown
older preparation cost is not zero. Equal work does not mean equal elapsed time.

## Portable files and dependencies
Exact matched_haar.py, test_haar_ndu_interaction.py and frozen PLAN accompany this
README, full SUMMARY and VALIDATION. Companion Haar/source/model/utility and
aligned/grouped helper modules and existing literal test dependencies must be on
Pythonpath; this package does not assert those local dependencies are published.
No unrestricted runner, model weights, private inputs, runtime paths, remote write,
merge or deployment is included. Saved review validates execution/accounting,
not the failed scientific claim. Publication approval is a separate operation.
