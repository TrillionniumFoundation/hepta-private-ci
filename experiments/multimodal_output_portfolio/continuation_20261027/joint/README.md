# Actual-output joint training with retention and generator attribution

The new generator-update and clean-retention gates pass on fresh MNIST pair
sources. The updated generator also exceeds a privileged exhaustive search of
the original generator's sixteen two-action plans. However, **the risk-weighted
generator proxy loses to the equally budgeted uniform proxy**. The complete
joint-training acceptance gate therefore remains false.

Both updated arms use the same exponential-moment NDU controller. `joint_uniform`
means uniform weighting of the generator's supervised loss; it is not a
risk-neutral controller. This distinction is necessary to interpret the failed
matched-training comparison.

## Actual held-out results

The metric is entropic certainty equivalent (CE), with higher values better:

\[
\operatorname{CE}_\gamma(U)=-\gamma^{-1}\log\mathbb E[e^{-\gamma U}],\qquad\gamma=2.
\]

Reported CE is the average of three fixed-seed CEs, not a pooled population
claim about random training seeds. Each interval resamples complete source
image pairs, retaining their conditions and fixed-seed predictions together.

| Comparison | Test CE difference | Paired 97.5% interval | Result |
| --- | ---: | --- | --- |
| Risk-weighted update − frozen original | +0.117276 | [0.098386, 0.136516] | Pass |
| Uniform update − frozen original | +0.134471 | [0.115402, 0.153328] | Positive secondary comparison |
| Risk-weighted update − uniform update | −0.017195 | [−0.026919, −0.008027] | Fail |
| Risk-weighted update − original 16-plan oracle | +0.054343 | [0.036804, 0.072227] | Generator attribution passes |

Risk-weighted update versus original clean-retention CE is `+0.031772`, interval
`[0.008442, 0.056121]`; the predeclared noninferiority margin is `−0.01`.
All three fixed seeds improve over the original and over its sixteen-plan
oracle. All three also lose to the uniform update on the test CE.

Absolute test CE is `0.644801` for the original, `0.762077` for the risk-weighted
update, and `0.779272` for the uniform update. Actual mean utility follows the
same ranking. Full metrics, per-seed differences, and all gates are in
[evidence/RESULT.json](evidence/RESULT.json).

## What changed

The experiment starts from the exact three original controlled generators,
including their image/text encoders, shared controlled transitions, pixel
decoder, caption decoder, and gate. It changes no architecture and uses the
same four registered deployed plans and two-transition inference depth.

1. The controller regresses the **actual quantized PNG/UTF-8 output's conditional
   exponential moment**, using a positive prediction whose ordering exactly
   reverses the deployed raw-score argmax. There is no soft-mixture/argmax
   mismatch in this target.
2. The generator receives a supervised selected-plan update, a small all-plan
   anchor, and clean same-plan teacher distillation. Half of each minibatch is
   clean replay to protect the original capability.
3. The risk arm weights its selected-plan supervised losses by detached,
   minibatch-normalized `exp(-gamma * actual_utility)`. The uniform arm changes
   only these weights. This is a proxy gradient, not an exact derivative of
   discrete delivered utility.
4. Validation alone selects a checkpoint and interpolation with the original,
   subject to the same clean-retention rule. Every arm still pays for all 600
   training steps and the full selection grid, including unselected checkpoints.

Each updated arm uses identical source batches, latent-noise draws, four-plan
evaluations, actual codec roundtrips, observer calls, teacher computations, and
600 optimizer updates at batch size 32. The recorded schedule hashes and logical
counts match within every seed. Wall and CPU times are measured separately;
equal operation counts are not asserted to give identical physical runtime.
The frozen original receives no additional optimization, so it is not the
matched-training-budget control.

The detailed objective, scoring rule, and budget boundaries are in
[METHOD.md](METHOD.md). Compact training/selection evidence is in
[evidence/DEVELOPMENT_SUMMARY.json](evidence/DEVELOPMENT_SUMMARY.json); every
checkpoint, candidate validation score, and training record is in the raw bundle.

## New sources, frozen selection, and real delivery

The qualification uses 512 new source pairs under four corruption conditions
and 512 disjoint clean-retention pairs. Their official MNIST test pixel hashes
exclude every source in the restored original corpus and the historical prior
holdout exclusion. No writer metadata exists for this comparison, so new pixels
do not establish a new-writer population result. The test set is not used for
checkpoint, interpolation, objective, or threshold selection.

The qualification seal binds source identities, all selected checkpoints,
original reference checkpoint files, both frozen observers, metric digest, and
executed source bytes **before** any new test prediction or audit-observer load.
The scorer is inaccessible to the deployed model interface; it runs after
delivery. This is an in-process experimental separation, not an OS security
boundary or proof that a learned recognizer equals human judgment.

All 23,040 deployed bundles were physically written as PNG plus UTF-8 text and
read back before scoring: 46,080 actual media files. The independent audit
reopens every bundle and reconstructs caption parsing, utility arithmetic,
bootstrap intervals, and acceptance flags. Its maximum utility discrepancy is
`2.22e-16`; maximum aggregate-statistic discrepancy is `6.18e-16`.

The original-generator oracle enumerates all sixteen two-action sequences at
the same initial latent noise and final decoder. All 98,304 candidate bundles
were delivered inside a ZIP archive and independently reopened. Exact source,
condition, semantic-plan, candidate-index, and archive-member grids are checked.
The oracle is allowed private target-aware selection and extra search compute;
it is an attribution upper bound for this finite original action family, not
an equally informed or equally budgeted deployed competitor. Beating it rules
out improved routing among those original sequences as the whole explanation
for the new generator's gain. It does not establish a global generation optimum.

See [evidence/INDEPENDENT_AUDIT.json](evidence/INDEPENDENT_AUDIT.json) and
[evidence/ORACLE_RECEIPT.json](evidence/ORACLE_RECEIPT.json).

## Preserved attempts and scope

The first development command failed on a Python bracket syntax error before
creating a run directory or producing any model output. A subsequent one-seed,
200-step pilot used historical train/validation sources only. Before the full
qualification, review corrected validation tie ordering, counted the complete
teacher computation, and strengthened source/metric/oracle seals. Pilot,
training, qualification, and audit executed sources are preserved separately.
These changes are documented in [evidence/ATTEMPTS.json](evidence/ATTEMPTS.json).

Three behavioral objective tests passed, including a numerical gradient check
and a tail-risk case where mean and exponential-moment decisions disagree.
The validation-only integration check established bitwise equivalence with the
registered deployment path and matching delivered bytes for its oracle plan.
The final qualification audit then checked the actual new-source results.

The result establishes bounded image/text generation improvement with retained
clean capability. It does not establish a superior risk-weighted generator
gradient, natural speech/video synthesis, a Hepta owner inside the generation
network, unrestricted dynamic NDU optimality, or foundation-model scaling.

## Reproduce

The raw archive includes restored input data and original reference weights,
all updated checkpoints, complete outputs and oracle candidates, source
snapshots, attempt logs, and a full member hash manifest. Its identity and saved
location are recorded in [RAW_ARCHIVE.json](RAW_ARCHIVE.json).

From the repository root, use Python with the versions in
[evidence/RUNTIME_ENVIRONMENT.json](evidence/RUNTIME_ENVIRONMENT.json) and
[requirements.txt](requirements.txt). This environment receipt was recorded
after the audit from the unchanged task environment; the original executed
runtime records remain inside the archive.
Always choose a new directory for development or qualification:

```sh
python -m experiments.multimodal_output_portfolio.continuation_20261027.joint.run \
  --assets /path/to/original-assets --output /path/to/new-development
python -m experiments.multimodal_output_portfolio.continuation_20261027.joint.evaluation \
  --assets /path/to/original-assets --development /path/to/new-development \
  --output /path/to/new-qualification
python -m experiments.multimodal_output_portfolio.continuation_20261027.joint.audit \
  --assets /path/to/original-assets --run /path/to/new-qualification
```

The existing evidence can be audited without retraining. Formatting of the
reviewable repository sources does not rewrite historical executed snapshots.
