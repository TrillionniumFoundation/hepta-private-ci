# Actual-output conditional baselines and LAX

This is a new numerical capability study. It preserves the earlier fullpath
negative qualification and uses a new profile, emission law, protocol, and
reserved source cohort. It trains against the same kind of actual delivered
PNG and unrepaired UTF-8 reward, with a frozen external observer. A continuous
observer is used only as a zero-mean gradient control variate.

The purpose is to test whether lower-variance gradients can improve the real
output objective while retaining the inherited strong model's clean-input
ability. This is a declared deployment-work-tariff diagnostic. It is not the
complete physical-CPU profile of the host-control study and does not certify a
physical-cost exponential tail. All actual training and inference CPU is
measured separately.

## Frozen forward law and genuine trainable paths

The inherited checkpoint is the selected seed-17 `joint_uniform` model, with
SHA-256 `508931a0cb780d413bc39de83b8de91aeab68b33cfe1b384f176cb8e8f004ee6`.
Its original encoder and gate select the two-transition plan using public
inputs and fixed exogenous noise. That reference stays frozen. The current
model's shared transition, modality adapters, decoder emissions, and encoder
are opened in four cumulative training stages.

Given the current shared state, image logits use a Normal distribution with
fixed standard deviation 0.03. Their sigmoid is rounded to a real 8-bit PNG.
Text uses a temperature-0.2 autoregressive categorical law at every one of the
seven latent token positions; sampled positions after EOS remain in the
fixed-horizon density. Actual rendered UTF-8 is scored without repair. Image
and text emissions are conditionally independent given that shared state.
Their parameters and upstream representation may be shared.

Every primary training emission is written, reopened, and scored. The code
records its receipt hashes, fixed source/noise schedule, exact complete-return
moment trace, deployment work counts, and observed CPU. Files can be removed
only after that readback; qualification retains actual media archives.

## Estimator and its conditions

Write the actual complete tariff return as `R(I,T)`, and let

\[
f_\gamma(I,T)=\begin{cases}
-R(I,T),&\gamma=0,\\
[\exp(-\gamma R(I,T))-1]/\gamma,&\gamma>0.
\end{cases}
\]

The two conditional baselines also use actual roundtrips:

- `b_I(T)` uses the quantized deterministic mean image and the same sampled text;
- `b_T(I)` uses the same sampled image and the model's greedy text.

The frozen soft observer `c(I,T)` replaces hard image argmax with softmax
probabilities inside the same metric expression. Its text labels are fixed
sampled tokens. It has no dependence on generator parameters except through
the reparameterized image. In particular, random measured CPU is not inserted
into this proxy or either baseline. The objective's work tariff is fixed by
its registered deployment operations.

The implemented image and text gradient estimators are

\[
\begin{aligned}
g_I={}&[f-b_I-c(I,T)+c(\mu_I,T)]_{\mathrm{detach}}
        \nabla_\theta\log p_\theta(I)
        +\nabla_\theta c(I,T),\\
g_T={}&[f-b_T]_{\mathrm{detach}}
        \nabla_\theta\log p_\theta(T).
\end{aligned}
\]

The score terms use detached realized Gaussian latents and categorical token
actions. The last term uses `mu + stopgrad(sample - mu)` before sigmoid. It
therefore follows the same conditional Gaussian noise path.

Conditional on `T`, both `b_I(T)` and `c(mu_I,T)` are constant with respect to
the sampled image. Their expected image-score contributions vanish. For the
proxy, differentiating its Gaussian expectation by reparameterization and by
the score identity gives the same derivative, so `-c * score_I + pathwise(c)`
has zero expectation. Conditional on `I`, the text baseline's expected text
score is zero. Consequently the two retained terms are exactly the image and
text components of the actual joint-objective gradient, including shared
parameters. A baseline may depend on current parameters, but its gradient
must be detached in the score multiplier. A proxy with any additional direct
parameter dependence would require subtracting that direct derivative; this
implementation does not introduce such dependence.

The control-variate method follows the LAX identity in
[Grathwohl et al., *Backpropagation through the Void*](https://arxiv.org/abs/1711.00123).
It does not assume that a smooth observer is the correct terminal reward.
Gradient clipping and Adam are optimization choices after the estimator;
pre-clipping module norms are recorded. No auxiliary retention penalty or
proxy reward is mixed into the NDU objective.

## Independent mathematical and primitive verification

`fullpath_oracle.py` integrates the production surrogate against an analytic
Gaussian hard-threshold codec crossed with a Bernoulli text variable and a
correlated cost branch. Parameters affect both emissions. For gamma zero and
two at two parameter settings, independently split Gaussian quadrature agrees
with the closed-form delivered-objective derivative to a maximum absolute
error of `4.371503159461554e-15`. Finite differences agree as well. Deliberately
omitting the pathwise term or using an image-dependent image baseline exposes
bias, so the check can fail for the relevant estimator mistakes.

The same report checks the actual new production sampler with independently
computed Normal densities, teacher-forced autoregressive categorical
densities, all four original plans, all sixteen parameter modules, and stage
finite differences. This is an independently derived oracle executed against
the production functions, not an independent human review. Such a review is
still separate from the analytic test.

## Development, retention, and one-time qualification

The main protocol freezes three training seeds, paired mean/risk arms, 256
updates in each cumulative stage, batch size twelve, two emissions per
context, learning rate 0.00005, clipping at five, and two Torch threads. All
arms start from the same strong prior. Their schedules, initial parameters,
and counted training work must match. Extra baseline roundtrips and proxy
observer calls are measured as training overhead.

Selection compares all four learned checkpoints, the exact greedy prior, and
the same-temperature frozen stochastic prior. It takes the highest primary
population CE among candidates whose clean validation CE is at least the
strong prior's CE minus 0.005. The same-law comparator distinguishes a learned
gain from the lower sampling temperature alone. A fallback preserves its
explicit greedy/stochastic mode in deployment.

Only after all development selections are fixed may qualification begin. The
mean selected-risk gain must exceed both frozen comparators by at least
0.002, be nonnegative against matched mean training, include a learned risk
checkpoint, and satisfy retention for every selected seed. A smoke run can
never qualify.

The reserved cohort uses 384 new original pixel sources: 128 quality pairs
and 64 clean retention pairs. It excludes all known historical, prior-fresh,
prior-heldout, admission, and original fullpath qualification sources, with
hash-based selection before training. It does not establish independent
handwriters or omniscient global historical provenance.

Qualification has an exclusive one-time claim. It validates live and archived
code, profiles, observer, reference, candidate hashes, selection, and source
allocation before predictions. Four actual arms run for each fixed trained
seed. No fallback result is copied from another arm. The same original pairs
are resampled jointly across all seeds for 10,000 paired source-cluster
bootstrap draws; the statistical target is the average CE difference across
fixed trained seeds, not a CE mixing seeds as risk outcomes.

The frozen final claims require a positive one-sided lower bound for risk
against the greedy prior, frozen stochastic prior, and matched mean, and a
retention lower bound of at least -0.005. The four bounds use Bonferroni alpha
0.05. Bootstrap coverage remains approximate; no finite-sample coverage or
global optimization theorem is claimed. Actual qualification media are
reopened again and their primary returns must reproduce within 1e-6.

## Commands

From the repository root in the Torch research environment:

```sh
python -m experiments.multimodal_output_portfolio.closure_20261028.fullpath_oracle \
  --output /new/oracle.json
python -m experiments.multimodal_output_portfolio.closure_20261028.fullpath_train \
  --assets /path/to/historical --baseline /path/to/strong-prior.pt \
  --output /new/development --oracle /new/oracle.json
python -m experiments.multimodal_output_portfolio.closure_20261028.fullpath_qualify \
  --assets /path/to/historical --baseline /path/to/strong-prior.pt \
  --development /new/development --output /new/qualification
```

The last command refuses a failed development gate. Reusing an already claimed
cohort as another independent qualification is also refused. A source or
profile revision is a new study and must preserve the earlier result.

## Completed development result

[DEVELOPMENT_RESULT.json](fullpath_results/DEVELOPMENT_RESULT.json) records all
6,144 effective updates, 147,456 actual primary bundles, 294,912 actual
counterfactual baseline bundles, and 2,485.740 training CPU seconds. All sixteen
opened generation modules received nonzero actual-objective gradient sums and
changed parameters in every arm. The inherited auxiliary `digit_head` was
intentionally unopened and stayed unchanged; it supplies no terminal reward.

The first run paused after the complete seed-17 pair because shared memory
approached its limit. The second run inherited those two complete arms exactly
and trained only the remaining four. Its source, objective, model law, total
budget, retention rule, and admission gates were unchanged. No approximate
optimizer/RNG restoration was used. The partially executed next-arm first
counterfactual was retained as interrupted overhead and never promoted to a
completed training step. See [ATTEMPTS.json](fullpath_results/ATTEMPTS.json).

| Seed | Arm | Selected candidate | Quality CE | Clean retention CE |
| --- | --- | --- | ---: | ---: |
| 17 | Mean | Full encoder stage | 0.817589 | 0.887349 |
| 17 | Risk | Full encoder stage | 0.800978 | 0.907735 |
| 29 | Mean | Exact greedy prior fallback | 0.850043 | 0.866596 |
| 29 | Risk | Exact greedy prior fallback | 0.850043 | 0.866596 |
| 43 | Mean | Adapter stage | 0.811693 | 0.884823 |
| 43 | Risk | Exact greedy prior fallback | 0.811665 | 0.884819 |

Across the three fixed training seeds, the selected-risk development CE gain
was `+0.002245666` versus the exact greedy prior, `+0.004188176` versus the
same-law stochastic prior, and `-0.005546491` versus matched mean training.
The selected models satisfy the declared validation retention constraint, with
two risk arms taking the prior fallback. The seed-43 mean improvement is only
about `0.00002754`; it is not presented as a meaningful ability gain.

**Qualification was not admitted.** The frozen risk-versus-matched-mean gate
failed. The actual qualification guard was executed against the completed
seal and refused it. [QUALIFICATION_STATUS.json](fullpath_results/QUALIFICATION_STATUS.json)
records zero new qualification predictions and no qualification claim; all
384 reserved original pixels remain unpredicted by qualification models.
The report establishes the expanded real-output training path and its tested
gradient identity. It does not establish a fresh-source capability gain or a
risk-training advantage over the matched mean control.
