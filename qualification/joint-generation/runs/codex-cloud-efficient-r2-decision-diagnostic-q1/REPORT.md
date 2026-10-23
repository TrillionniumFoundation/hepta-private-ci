# Q1: fixed TRAIN-only decision-regret diagnostic

One actual execution, exit 0, not qualification. Protocol/source were committed
and pushed before START. Only the retained T11 NC checkpoints and R2 TRAIN were
used; neither r2 nor core test was constructed/opened.

This is a new objective comparison within the already adopted 42-dimensional
low-hidden/instruction representation. The old t5 classifier used 31 probability
features and always continued; that result remains intact. Q1 does not repeat
the old 31-vs-42 representation comparison, search thresholds/features/lambda,
train content, or select on new validation statistics.

Exactly 3 fixed seeds x 4 physical-source folds x 2 methods = 24 fits. Both use
ridge .001 and fold-local normalizers. MSE predicts raw gain and compares the
existing TRAIN marginal price; binary ridge uses label[raw_gain>price],
weight abs(raw_gain-price), and fixed threshold .5. All 192 physical sources
keep all instructions/variants in one fold.

| Seed | MSE regret | Weighted regret | MSE raw routing gain | Weighted raw routing gain |
|---|---:|---:|---:|
| 11 | 0.001978304458 | 0.001258852172 | +0.000200313892 | +0.000048190390 |
| 23 | 0.000896949336 | 0.000633666928 | -0.000020925992 | +0.000242356416 |
| 47 | 0.002306223098 | 0.001058769623 | +0.000028351444 | -0.000121787974 |

Mean source-equal decision regret fell from 0.001727158964 to 0.000983762908
(43.04%). Mean raw routing gain versus own always-full instead changed from
+0.000069246448 to +0.000056252944. MSE wrong-stop net loss concentrated in a
few sources: top 1/top 5 shares for seed 23 were 52.0%/67.5%; weighted classification
reduced those to 11.0%/37.4%, but made larger wrong-stop loss on seeds 11/47.
The classifier also stopped more often on average. All per-source results,
coefficients, decisions, predictions and analytical full/low/oracle references
remain saved. No source, seed or timing sample was omitted.

The cost target is the existing TRAIN marginal-CPU proxy, not measured new
complete-system net utility. Classification scores have no raw-gain units and
cannot be inserted into the current raw-price threshold without an explicitly
frozen new controller contract, fitted target/price binding and full costing.
These data support that concrete research candidate; they do not close r2.

Cost: 443626128 declared mathematical units; 24 fits; complete child process CPU
0.938736s, launcher own CPU 0.001329442s, wall0.954485832s. Internal worker
CPU 0.837517002s excludes final receipt serialization/startup; it is not added
again to outer child CPU. Existing T11 native/model bytes were explicitly reused
for this separate R&D probe, with no compile or content updates. This is no
free cache/credit for another build and no matched cumulative research claim.

OOF holds out critic-fitting physical sources, while the content encoder has
already seen all TRAIN and the fixed checkpoint was previously validation-selected.
It therefore tests the decision mapping, not unseen content generalization.
The user's core claim proceeds separately under the predeclared core-c1 plan.
