# Round 3: calibration under empirical and pointwise retention constraints

## What is predicted

Every head forecasts a terminal real-valued latent state at the registered
horizons 0, 0.5, 1 and 2 after the last occupied public observation. The put,
neutral and call probabilities are the three terminal Gaussian integrals
`X <= -0.6`, `-0.6 < X <= 0.6`, `X > 0.6`. These remain distinct from a path's
first passage, a communication event, missing feedback, or runtime confidence.

The calibration study scores initial public histories at the three nonzero
horizons. All horizons and all later training stages on one trajectory are
dependent measurements. The independent sampling units are trajectories and,
at the higher level, the five separately trained seeds. Twelve windows are a
fixed recurring schedule, not twelve independent trained systems.

## Two separate retention claims

The inherited `protected` and `protected_q24` profiles preserve the original
pointwise Gaussian negative log-density difference bound of 0.02 relative to
the unchanged initial anchor, within their declared numeric domains. They
continue to use the Round 2 formula and its Q24 parameter guard. They cannot
make a large mean correction while keeping that global bound.

The new `calibrated` profile instead selects using old and new development
data. It has **no universal pointwise retention guarantee**. Its actual old
confirmation loss must pass the same 0.02 empirical retention threshold as
before. A development constraint is a model-selection rule, not evidence that
all future or past tasks are protected. The two profiles are never reported as
interchangeable.

The protected Q24 arm in this study scores the Gaussian head after parameter
rounding. Its terminal event probabilities are computed from that rounded
Gaussian. This study does not invoke the native runtime or the additional
post-native categorical projection. Those remain separately qualified layers.

## Trained public-history model

Let `(m0, v0)` be the fixed anchor's moments and `(m1, v1)` the current online
filter's moments at every horizon. Let `l0`, `l1` be the observed-sensor log
likelihoods under these filters. The learned gate is

\[
 a(h)=\operatorname{sigmoid}(b_0+b_1\operatorname{clip}((l_1-l_0)/4,-2,2)).
\]

The candidate is a **Gaussian moment projection**, not an exact mixture law:

\[
 m_c=m_0+a(m_1-m_0),\qquad
 v_c=\{(1-a)v_0+av_1+a(1-a)(m_1-m_0)^2\}\exp(k_j).
\]

There are six optimized scalars: two gate coefficients and four horizon
log-variance corrections. L-BFGS-B minimizes composite Gaussian NLL plus
`0.001 * squared_parameter_norm`, with an analytic gradient. Bounds are
`b0 in [-6,6]`, `b1 in [0,6]`, and `kj in [log(.75),log(2)]`. All fit calls,
parameter changes, objective traces, data hashes and optimizer outcomes are
retained. No hidden law name, regime label, window number, future target or
trajectory ID enters prediction.

The four horizon corrections define a marginal forecast calibration layer.
They do not establish a joint path law or a new diffusion transition semigroup.
The inherited analytic kernel and physical-time filter propagation remain the
separately defined model. First-passage claims cannot be inferred from these
marginals. If a controller uses this calibrated head, its anchor process/noise
planning parameters are explicitly a plug-in approximation, requiring separate
actual-outcome evaluation.

The gate conditions on the same public mask/time/sensor-variance history as
the filters. A missing observation contributes elapsed-time propagation but
no likelihood term. Unobserved storage values are replaced before prediction.
Same-time observed sensors each contribute their conditional likelihood once.

## Development selection

The fixed grid has 11 strengths `s = 0,.1,...,1` and five variance inflation
factors `c = 1,1.025,1.05,1.1,1.2`. Every candidate is

\[
 m_s=m_0+s(m_c-m_0),\qquad
 v_s=c\{(1-s)v_0+sv_c+s(1-s)(m_c-m_0)^2\}.
\]

The `s=0,c=1` candidate is exactly the anchor. For each of the 55 choices,
compute the old-development NLL difference, averaging the three dependent
horizons within each trajectory. A choice is eligible if its mean difference
plus `1.645 * paired_standard_error` is at most 0.02. This reserve is a
selection heuristic; it is not a finite-sample or simultaneous guarantee.
Among eligible choices select the lowest new-development Gaussian NLL, with
grid order breaking exact ties. All candidate scores and selected parameters
are saved. Confirmation data is never used in this selection.

The `calibrated_unconstrained` control uses the same trained candidate with
strength 1 and inflation 1. The `calibrated_classical` control uses independent
dense Gaussian covariance solves for both conditional moments and public
likelihood. The Q24 controls round mean and variance to the same parameter
grid and are explicitly empirical, with no inherited pointwise certificate.
That parameter-quantized profile rejects forecasts outside `|mean| <= 10000`
and variance in `[0.0001,100]`. Its actual native typed-domain subset
`|mean| <= 8, variance <= 8` is separately recorded. FP64 predictions must have
finite means and finite positive variances; all observed public values, times
and observation variances obey the inherited valid-history checks.

## Training, information and sampling budgets

Seeds are `607,701,809,907,1009`. Each has twelve windows alternating Gaussian
and drift-shift data. The online filter receives 256 current training
trajectories. Replay and calibration fitting both receive the same 256 old
training trajectories plus those 256 new trajectories. The unchanged anchor
was fitted independently before this study. Thus replay is a same-label-budget
strong baseline; online's smaller fit budget is disclosed. There is no claim
of identical optimizer work, parameter count, or runtime cost across models.

Each window also receives 128 independent old and 128 independent new
development trajectories. Models use the same original anchor, including the
unconstrained arms. All sixty checkpoints and all selections are completed and
frozen before generating any confirmation holdout.

The 512-row budget match refers only to the fitting stage. Calibration then
consumes another 256 labelled development trajectories for its 55-candidate
selection; the replay arm does not use these labels to select a checkpoint or
hyperparameter. `same_available_information` in the registration means equal
access to the declared public/training sources, not identical actual label
consumption. `replay_and_calibration_labelled_rows_equal` describes the 512 fit
rows only. Total supervised selection budgets and optimizer work are therefore
not matched between calibration and replay. A gain against replay alone cannot
identify a benefit of the learned gate separately from this selection budget.
The classical calibration controls use the exact same fitted parameters,
development selection and information, and provide the matched mechanism
comparison.

The seed rule is `50000000 + 10000*training_seed + 100*window + code`.
Codes are training 1, old development 2, new development 3 and new holdout 4.
The reused old holdout uses window 12 and code 5, outside the twelve training
windows. Confirmation has 256 old trajectories per seed, reused across
windows, and 256 fresh new trajectories per seed/window. Data and source hashes
bind these identities. Reused old trajectories are not counted again as new
independent observations.

## Frozen acceptance

The original bounded retention gate remains: the worst **seed-averaged** old
Gaussian NLL increase across the twelve windows is at most 0.02, and final-new
mean Gaussian NLL is no worse than the frozen anchor. Worst individual
seed/window degradation is also reported. No claim of all-seed protection
follows from the seed-averaged empirical gate.

The additional efficacy gate requires that original gate, a final-new mean
Gaussian NLL reduction of at least 0.005, a paired bootstrap upper endpoint
below zero, and improvement for every training seed. The bootstrap resamples
training seeds first, then whole trajectories within each fixed window;
4,000 replicates give empirical descriptive 95% intervals. It does not turn
five seeds into a population theorem.

The separately registered descriptive drift calibration gate is pooled
classwise ECE at most 0.04 and nominal 95% interval coverage in [0.92,0.98].
The joint empirical gate requires both efficacy and calibration. Pointwise
protected profiles retain their certificates even when this calibration gate
fails; empirical profiles do not gain a certificate when it passes.

This study measures forecasts and bounded retention. Actual control utility,
transport costs, native durability and energy are separate experiments. No
prediction-only metric here substitutes for those outcomes.
