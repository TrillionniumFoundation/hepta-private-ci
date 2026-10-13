# Training-only prototype routing and a two-sided capability gate

Parent: `219e394a7e324844850b24d8149ae0dbe06893df`, Draft PR #1654.
This is additive research in the existing qualification path, not a production
router, runtime, model selector, memory store or deployment. V11 is already on
the remote branch; do not reapply the earlier differently named local patch.

## Change the routing model, not the meaning of successful learning

A group can contain several separated clusters. One old/new affine hyperplane
cannot express every such boundary. This candidate fits one prototype per class,
with a class-balanced, source-group-balanced shared diagonal covariance. Shrink
that covariance toward its isotropic mean; compute class discriminant scores.
The group mass is the sum of its class probabilities. Frozen specialist rows
still determine the conditional class probabilities WITHIN each group. No
inference task ID, true class membership or future label is supplied.

The spherical/diagonal Gaussian discriminant has a common quadratic term that
cancels in softmax. Its remaining weights and biases are folded into the existing
old-only-normalized coordinates. No prototype training samples are needed at
inference. Conditional within-group log odds are preserved to the established
1e-4 float tolerance; this is not global no-forgetting or a generative modality.

Two replay budgets are separate: the original 32 old memory rows plus 120 new
training rows, and all 160 old base rows plus the SAME 120 new rows. The latter
is explicitly a larger-memory control. Original teachers, labels, question,
options and publisher content-group handling are unchanged. All fourteen V11
controls remain, plus two prototype-routed and two geometry-only controls.
The geometry-only controls omit expert weights and execute no expert forward;
they are matched ablations, not independently optimized eight-way classifiers.

## No calibration or held-out features fit the routing geometry

For EACH replay budget, four deterministic class-stratified folds keep complete
source groups together. Every fold recomputes means and covariance from its own
training rows; raw features are used, so the old teacher normalizer is not leaked
into routing cross-validation. Conflicting training-group labels and insufficient
group support fail. Duplicating identical rows within one group does not add
weight. Groups are content identifiers, NOT authenticated independent speakers.

The grid was fixed before the first V12 observation: shrinkage (0.1, 1.0),
temperature (1, 4, 16, 64). Select by class/group-balanced binary group log loss
on the TRAINING folds, then refit on that arm's training data. This is eight
configurations, eight fold-statistic fits plus one final fit per arm. There are
1,216/2,240 CV prediction rows respectively, not that many independent examples.
No optimizer runs, but statistics fitting, validation and replay cost are real.
All candidates/CV records are sealed before the calibration decision. The study
is exploratory retrospective work on an already inspected public task, not fresh
prospective evaluation or independent preregistration.

The V9/V11 rule is unchanged in its original study. The NEW selector retains
its per-old-class .02 accuracy-drop and .02 Brier-increase limits AND requires:
new macro accuracy >=.90, every new-class accuracy >=.80, every new-class Brier
<=.20. These additional descriptive thresholds are fixed before this experiment.
No qualified candidate returns frozen WITH qualified=false. Tiny positive new
accuracy no longer counts as qualified learning. This is not a confidence bound,
causal NDU gain estimate, production acceptance or automatic promotion.

## Observed cached-real-feature result

Local execution uses the verified BGE f30abc25 feature bundle, no new Encoder.
The fourteen parent predictions are preserved; the newer remote V11 adds the
concatenation and two-scalar score controls absent from the earlier local ZIP.

| Rule | Old correct / 120 | New correct / 120 |
| --- | ---: | ---: |
| Old teacher | 120 | 0 |
| V11 selected memory gate | 120 | 6 |
| V11 concatenated specialists | 119 | 118 |
| V9 distilled | 117 | 119 |
| Prototype gate, 32 old examples | 118 | 118 |
| Prototype gate, all old examples | 120 | 116 |
| Geometry only, 32 old examples | 118 | 117 |
| Geometry only, all old examples | 120 | 115 |

The all-old prototype result is encouraging on this reused test set but DOES NOT
pass calibration: reminder is 16/20 versus old teacher 19/20, Brier .3222 versus
.0899. Frozen remains selected with qualified=false. Both prototype variants
meet the new-task usefulness floor, whereas the V11 conservative gates do not.
There is no statistical superiority, whole-task optimum or retention guarantee.
Parameters/grid/thresholds were not retuned after these results.

At width 384, the conditional candidate stores 6,160 FP32 scalars / 24,640 bytes;
3,080 are fitted routing coefficients, the rest are frozen expert coefficients.
Geometry alone stores 3,080 scalars / 12,320 bytes. Neither count includes Encoder,
normalizer, training memory, temporary statistics, Python state or process RSS.
The new task introduces 18 statistics fits and 3,456 CV prediction rows in total.
The referenced V11 gates are re-executed when source identity changes; their 600
optimizer steps and calibration costs remain separately bound, never charged as
zero. This is not an equal-training-cost comparison or a throughput measurement.

## Reproduce and interpret evidence

`cell_prototype_study.py` takes the existing --source-run, --dataset,
--consolidation-run, --anchor-run and --conditional-run, plus a create-only
--output. Supply --review-run to write separate scores. The inherited reviewer
adds explicit calibration-only review with its full-scoring default unchanged.
The producer removes held-out labels before this boundary. All eighteen rules
are scored and audited, including rejected candidates.

The reviewer replays statistics/CV using the SAME fitting implementation, then
reconstructs the forward formula separately. It verifies all parameters, folds,
training membership, cost census, fixed floors and prediction identities. It is
not independent optimizer/hardware attestation. On the local observed run, all
7,218 calibration/test predictions reconstruct within 3.82e-6 with zero argmax
reversals; only 240 distinct held-out inputs exist. Real fresh BGE execution and
all global/native gates must be checked on the new SHA, not borrowed from a parent.

Primary related background: Rebuffi et al., iCaRL (CVPR 2017),
https://arxiv.org/abs/1611.07725. This prototype gate is NOT an iCaRL reproduction;
it freezes the Encoder and uses its own declared fitting/acceptance protocol.
