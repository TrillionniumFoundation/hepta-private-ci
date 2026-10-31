# Registered tasks and trainable mechanisms

Every trajectory has an independent Gaussian initial state of mean zero and
variance one. Six increments have durations in {0.2, 0.6, 1.1, 1.7}; the hidden
state follows constant drift 0.12 and process variance rate 0.18. Observation
variance is 0.64. Each observation except the last can be missing with probability
0.18. The observation mask and timestamps are public. Missing values do not denote
put or neutral events. Future increments share one physical path, at offsets
0, 0.5, 1, 1.5, 2, 3 from the last initial observation.

## Prediction and training

Public terminal events use fixed thresholds -0.6 and +0.6, with put <= -0.6,
neutral (-0.6, 0.6], and call > 0.6. Primary prediction horizons are 0.5, 1, 2.
An auxiliary current-state estimate at horizon zero supports control. All fitted
models receive the same training targets (current and future continuous states),
and four contexts per trajectory: initial, repair, wait, wait plus repair.
Context expansion is training augmentation, not additional independent subjects.

The analytic candidate fits drift, process-variance rate and sensor-noise scale
using a composite conditional Gaussian score and bounded L-BFGS-B. Correlated
stages and horizons are not asserted to form an independent joint likelihood.
The complete-history baseline uses observation values, masks, times and sensor
variances in a Gaussian/probit regression. Three ridge choices and variance
calibration use development data only. The pulse and native baselines use the
same readout training and target opportunities. Native features must come from
the original executed sparse kernel. Pulse features come from the actual shared
stochastic recurrence and reset, with deterministic per-trajectory random marks.
Its driving distribution and readout are trained; leak/reset/refractory constants
are fixed. There is no claimed unbiased end-to-end gradient through hard spikes.

A classical Gaussian-history predictor uses independent joint-covariance
conditioning and linear solves, with the same fitted parameters. It is an
explicit equivalent baseline and does not call the filter recurrence. The
known-parameter filter is privileged:
it is exact under the Gaussian task law, but merely a known-moment linear
reference under Student-t noise. It is excluded from primary superiority tests.

Two secondary mechanism controls share the learned driving filter, eight state
features, Gaussian readout family, training labels and ridge-selection procedure
with the pulse model. `mean_drive` replaces the sampled categorical evidence by
p(call) - p(put), retaining the same leak, threshold and reset. Because threshold
and reset are nonlinear, this is a deterministic mean-drive approximation, not
the exact expectation of the stochastic recurrence. `pulse_no_reset` uses the
same random marks and event samples as `pulse`, and disables only potential
reset after emission. Readouts are refitted separately for each representation.
These controls address mechanism attribution; the primary pulse-versus-analytic
comparison changes the whole representation and cannot isolate a spike benefit.
The `fixed` arm has a fixed predictive filter but shares fitted planning-law
parameters, so it is not described as a wholly untrained controller.

## Sequential control and real observation boundary

The final target time is fixed at two time units after the initial history.
Every arm first emits a preview. Stop submits its current terminal mean. Repair
costs 0.12 and acquires a sensor of variance 0.04 at the current time, then emits
a revised terminal prediction. Wait costs 0.07 and moves forward one time unit,
receiving a sensor of variance 0.64; the next choice is stop or repair. A repair
after waiting measures the state at that new time. All selected observations
are passed through the observer readback hook before entering the model.

Each trajectory also has public action-cost terms: a multiplier sampled
uniformly from {0.5, 1, 2, 4}, independently of the hidden trajectory. Both
action costs are multiplied by this value. A separate NumPy SeedSequence
`[data_seed, 0xAE71]` draws these terms without changing any existing state or
noise draw. The terms pass through `observer(case, arm, "terms", multiplier)`
before the preview and first choice. All policies receive the same terms and
the record stores their readback and every actually paid cost item. This
pre-confirmation design revision prevents a single fixed action sequence from
being optimal for every episode at the original constant action costs.

The submitted prediction is reopened through the delivery hook before the latent
terminal target is read. Utility is 1 - squared prediction error - actual paid
wait/repair costs. Severe loss is utility below -2. Each potential observation
is pre-generated only for a coupled environment; unchosen observations never
enter the online public history. Training is allowed to see all action contexts.

The policy uses a registered variance value-of-information approximation. For
current variance P and sensor variance R, expected squared-error reduction is
P^2/(P+R). Wait propagates P by the fitted process variance and compares its
sensor update and possible subsequent repair. Under the fitted Gaussian filter
this is the MSE dynamic-programming calculation. For learned unconstrained
readouts it is a plug-in approximation; reported utility always comes from the
actual selected continuation, never the predicted variance score. All learned
arms use the same fitted process and sensor parameters for this planning step.

Four control-only references use the fitted analytic estimator but force
`always_stop`, `always_repair`, `always_wait` (then stop), or
`always_wait_repair`. They require no new readout training and do not appear in
the prediction benchmark. They distinguish gains from estimation from gains
from choosing a continuation. They are secondary references, not additional
primary superiority comparisons.

## Mismatch, independence and scope

Drift-shift evaluation changes drift to 0.32. Student-t evaluation uses df=4
innovations scaled to unit variance for both state and sensor noise. The same
terminal labels and costs apply. Squared errors have heavy tails in this latter
task; finite-sample statistics are reported without a population exponential-
utility claim. Main uncertainty calculations resample independent training runs
and whole trajectories, retaining paired observations across arms.
Student-t(4) innovations have no finite fourth moment, so squared-loss utility
can have infinite variance. Its empirical bootstrap summaries are descriptive
stress evidence and do not establish population noninferiority.

These are controlled synthetic numeric tasks with actual file delivery hooks.
They do not constitute natural-language/image/audio generator training, a
production owner admission, or a universal SNN advantage. The equivalent
classical filter specifically tests whether Gaussian closure is being mistaken
for a unique new neural capability.
