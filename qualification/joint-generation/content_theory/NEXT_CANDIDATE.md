# Direction decision, not authorization for another training run

The target-geometry result is a real A/N distinction, but it is not a diagnosis
of the real task's conditional label posterior. There is insufficient evidence
to recommend a new LR, alpha, rho, initialization temperature or regularization
search. The fixed objective itself can prefer a different uncertain-label policy;
an optimizer change cannot be assumed to restore the CE posterior. Existing
strong CE, independent KEEP/log2 and native baselines remain intact.

## Reject the tempting fixed-marginal coupling probe without running it

A parameter-free maximal coupling has diagonal min(p_c,q_c), with residual
`(p−min)*(q−min)^T/(1−sum min)`. It preserves both head marginals. On the original
decoded reward support its expected raw-reward change versus independence is

    .3[min(p_y,q_y)−p_y*q_y] + .35[sum min(p,q)−sum p*q] >=0.

Pixel quality and head correctness marginals do not change. Joint-success gain
is exactly matched by an increase in both-wrong probability. These identities
passed pure hand checks, not a trained-model probe.

More decisively, **any** coupling preserving fixed head marginals obeys

    mean joint_success <= mean min(p_y,q_y)
                       <= min(mean text_correct, mean image_correct).

The retained aggregate means already place this upper bound below current log2:

| Family | Any fixed-marginal coupling upper bound | Existing log2 joint success |
|---|---:|---:|
| S | .980263438 | .986366781 |
| H | .981488007 | .987980621 |
| A | .979914645 | .985152799 |
| N | .983499609 | .988540796 |

Therefore this fixed-head direction cannot meet the existing joint-success
comparison for any family, regardless of its CE or sampling implementation.
It is rejected before a model/request experiment. The bound reads only saved
aggregate JSON, costs.057198 research CPU seconds and changes no old result.
See [certificate](../runs/content-native-objective-theory-v1-20261023/candidate-bound.json).

## One conditional architecture candidate: attribute-factored native law

If another architecture is considered, a minimal falsifiable hypothesis is
**task-structure reuse improves finite-source generalization**: use color3,
shape2 and position2 distributions and their product to make the SAME12-way
semantic output law. These attributes and code ordering are already the task's
declared caption/transformation structure, not new labels or a learned critic.
Sample one semantic code jointly for both original decoders. Keep the original
encoder width32, actual decoded R, rho1.5 and original interfaces. No AV work.

Pack the seven attribute logits in one32×7 projection/bias. Active content
parameters would be6,727 rather than6,892 for unrestricted native12:165 fewer,
only2.4%, with the encoder still dominant. No factor-of-two speed claim is made;
joint-law construction/backpropagation, metadata, compilation/binding, all
controls, exports and actual service must be measured in a new frozen budget.

Keep class CE EXACT:

    s(code)=p_color*p_shape*p_position
    −log s_y = CE_color + CE_shape + CE_position,

with coefficient1 for strong S and.2 for H/A/N. Do NOT average those three
terms or multiply the two output modalities again. A/N still optimize original
12-code expected/entropic reward. The gradient of each attribute logit is the
sum of the original class-logit gradients over compatible codes. Four hand
checks validate this chain, exact CE scale and a fixed linear initialization
projection. No neural model was constructed or trained.

Initialization is fixed ANOVA main-effect projection of the common base's
12-class logits/weight rows onto color/shape/position effects. It is lossless
only for additive attribute logits; for general logits it deliberately drops
interactions. A zero-update control must retain and report that initial change.
It cannot be relabeled as a training gain or silently compared to another base.

This is **not a fix for N's target-level commitment**: ambiguity in one attribute
can retain the same bifurcation. It is a separate inductive-bias hypothesis.
There is also a sharp negative control. For hand true labels0 and11 only, each
half, the product of their attribute marginals puts.75 mass on six wrong cross-
combinations: expected joint success.125 instead of.5 for a law supported on
the two true codes. The fourth hand check preserves this failure. Real conditional
posterior factorization has not been established; that is why training is not
recommended as a foregone improvement.

Any future proposal must give unrestricted native12 and attribute7 the same
applicable S/H/A/N optimization opportunities and keep strong original CE and
fixed log2 controls. Use one fixed projection/architecture, no factor ordering,
width, risk or supervision sweep. A full M ledger pays all used preparation,
all candidate training/selection and mandatory tail under the prospective
boundary; independent review is separately declared. Do not replay the old
failed10-second run at11 seconds. Dedicated best-static comparison must let
each system use its entire equal cap and exclude unused architecture costs.

Falsification is explicit: reject if same-cap attribute S cannot improve CE and
joint success over the retained strong CE/static controls, or if any gain is
only zero-update projection, agreement, or a favorable source subset. A−H and
N−A remain separate hypotheses, with all seeds, both-wrong, per-head/joint/greedy
and the correlated-ambiguity negative control retained. A positive architecture
effect does not establish either training-objective contrast. No such future
protocol or training has been executed here.
