# Analytic event neuron: executed research contract

This is an isolated research implementation, based on repository commit
`0acfd9b27db910c180b0d8911f39aea469b7f864`. It evaluates a Gaussian transition
model, a shared distribution over lower/neutral/upper terminal events, and an
actual stochastic recurrent pulse implementation. It does not rename a static
probit activation as a new function class.

## 1. Event and time semantics

The conditional terminal law is `X(t+tau) | public_history ~ Normal(m, v)`.
The ordered event partition is `(put, neutral, call)`:

- put: `X <= lower`;
- neutral: `lower < X <= upper`;
- call: `X > upper`.

Threshold equality follows this partition also at zero variance and after
fixed-point quantization. The terminal-event thresholds are fixed task labels,
not optimizer-controlled firing thresholds. A zero-variance law is a point
mass; its ordinary smooth variance gradient is unavailable. Missing data,
not-yet-arrived data, a neutral observation, and a silent pulse are different
records. No observed pulse is not evidence for a put outcome.

All prediction horizons refer to actual future times. Multiple thresholds and
horizons from one trajectory are dependent observations. Their marginal
probabilities are never multiplied to manufacture a joint likelihood.

The reference constant-coefficient transition is
`m_next = m + drift * dt`, `v_next = v + diffusion**2 * dt`.
These are task-law parameters, not a financial risk-neutral probability or a
risk-preference parameter. State-dependent freezing, finite-bin projection,
resets, and intermediate actions change the relevant transition or introduce
an approximation that must be reported.

## 2. Outputs and state

The continuous model emits a normalized three-way distribution and predictive
mean/variance. The pulse model samples one joint categorical outcome, advances
an explicit recurrent accumulator and eligibility state, and implements the
registered firing/reset/refractory rule. It retains probability readouts for
calibration. Its stochastic state and random-input identity are checkpointed.

The pulse runtime is a new research format. It does not change the existing
Hepta V1 Q24 journal or hide new recurrence inside an old model-port instance.
The native comparison invokes the original compiled `sparse_tick`, with its
original non-authorizing receipt semantics. A native feature comparison, a
typed model-port exercise, and Agentd deployment are separate outcomes.

`p(call)` is an event prediction; runtime confidence, actual spike propensity,
and post-admission action propensity are different quantities. Mapping to a
Q24 drive/prediction must specify units and a separate calibration profile.

## 3. Learning and comparisons

The Gaussian candidate learns transition/filter parameters from training
trajectories and observed training outcomes. Readout candidates learn their
own parameters. An equivalently parameterized classical Gaussian-filter
baseline is mandatory: an identical statistical model should give identical
predictions. A probit reparameterization check is a negative control.

Complete-history regressors receive the same public observations, times,
missingness and stage information. Their future-state labels and tuning
opportunities match the candidate. Known-law oracle parameters are identified
as privileged reference information and are excluded from fair superiority
claims. Pulse and native sparse readouts are actually fitted; a trained head
does not mean the underlying fixed sparse dynamics were trained.

All comparisons retain failed fits and outcomes. Test labels are not used to
choose hyperparameters, thresholds, checkpoints or acceptance rules. A model
changed after inspecting confirmation results requires a new registered run.

## 4. Prediction task

Each trajectory supplies six irregularly timed noisy observations of a hidden
state, with explicit missingness. Primary events use fixed thresholds
`[-0.6, 0.6]` and future horizons `[0.5, 1.0, 2.0]`. Gaussian development and
confirmation test the declared model. Additional drift-shift and Student-t
process-and-observation laws test model mismatch. These are controlled synthetic tasks,
not natural-source or large-language-model generalization evidence.

Metrics include per-trajectory event negative log likelihood, Brier score,
future-state mean squared error and event calibration. Conditional parameters
and readout changes are measured before/after learning and after reload.

## 5. Sequential decision task

The fixed endpoint is two time units after the initial observation history.
Before choosing an action, every arm reads the same public cost multiplier,
drawn independently and uniformly from `[0.5, 1, 2, 4]`. It scales both action
costs below. This pre-confirmation revision avoids a degenerate always-wait-
then-repair task; development-only checks established multiple optimal paths.
The public decision sequence permits:

1. stop: submit the current prediction;
2. repair: pay `0.12`, receive a new current-time sensor observation with
   variance `0.04`, then submit;
3. wait: pay `0.07`, advance one time unit and receive a sensor observation with
   variance `0.64`, then choose stop or repair.

Every new observation is revealed only after the corresponding action. The
same absolute terminal target is scored under every action. Actual utility is
`1 - (submitted_prediction - terminal_state)**2 - paid_costs`; severe loss is
`utility < -2`. Raw utility and actual action costs are retained separately.

Policies use their declared predictive variance and the registered sensor law
to compute a value-of-information rule. For non-Gaussian/history predictors
this is an explicitly approximate plug-in policy, evaluated by actual rollout.
A known-law Gaussian comparator does not certify optimality under model
mismatch. No population exponential-risk claim is made for Student-t squared
losses, whose exponential moment may not exist.

Four fixed policies (always stop, immediate repair, wait then stop, wait then
repair) share the learned analytic estimator and isolate the contribution of
action selection. The matched pulse ablations replace categorical draws by
their mean drive, or disable reset. Mean drive is not an exact expectation of
the nonlinear reset process. These are secondary, descriptive comparisons.

The auxiliary horizon zero estimates current-state uncertainty for decisions.
Training uses all four acquired-history contexts (initial, repair, wait,
wait-and-repair); their correlated labels define a composite conditional score,
not an independent joint likelihood. Each context is available to every arm.

Public observations are serialized and read back before model consumption.
Submitted predictions are written to UTF-8 and an independently decoded PNG
numeric transport before private terminal scoring. These media exercise an
actual synthetic transport; they are not trained natural multimodal generation.
Chronology, artifact hashes, read-back values, selected actions, state identity
and private post-decision scores remain separately auditable.

## 6. Numerical and statistical verification

The independent numerical checks cover integration, analytic gradients,
log-tail accuracy, deterministic point masses, probability-simplex quantization,
the continuous Gaussian semigroup, finite-projection error, and the endpoint
versus first-passage counterexample. See `MATH.md` for proofs and error scope.

The first-passage helper is only a semantic reference. No endpoint test label
is used to qualify a first-passage predictor. Recurrent reset propagation is
tested against its own implemented stochastic transition, not an unmodified
Brownian semigroup assertion.

Independent training seeds and whole environment trajectories are the sampling
units. Multiple arms share paired environment draws but cannot read future
draws before their actions. Nested horizons, transitions and delivered files
do not increase the independent sample count. The protocol fixes primary
contrasts and multiplicity handling before confirmation.

Student-t(4) noise has finite second moment but no fourth moment. Its empirical
utility and intervals are retained, but ordinary squared-loss bootstrap
coverage and population noninferiority are not asserted. Five training seeds
also limit the reliability of asymptotic inference in the primary study.

## 7. Scope of success

Mathematical correctness, learned prediction skill, pulse-specific benefit,
external control utility, computational efficiency and runtime integration
are separate conclusions. An outcome can support one and fail another. The
original Hepta blockers retain their original criteria; this study cannot
close them by changing their labels or by counting successful infrastructure
checks as utility comparisons.

The selected runtime parameters remain immutable during one evaluation run.
Training outputs are future candidates. Runtime persistence, exact replay,
quantization, calibration, timing and longer-horizon tests are reported under
their actual measured profile, not as production-wide guarantees.
