# Protected adaptation and recurring-task retention

This study addresses the first round's failed old-task NLL margin without
changing that failure or its original evidence. It introduces a conservative
Gaussian prediction guard, evaluates ordinary public-history routing controls,
and measures the adaptation cost of preserving an immutable anchor.

## Information and learning contract

The anchor is the original trained Gaussian filter. The adaptive filter is
trained sequentially on the currently available training window. Both contain
learned drift, process variance and sensor-noise scale. Training uses the
original composite conditional Gaussian objective; correlated stages and
horizons are not counted as independent trajectories.

Routing conditions only on actual public observation values, observation
times, occupancy, missingness and acquired sensor variances. Initial latent
state has the original N(0,1) prior. A missing observation contributes time
propagation and zero observation likelihood. Simultaneous sensors contribute
separate conditional innovations. The task's observation schedule and missing
mechanism are exogenous and common to the experts; their probabilities cancel
in the expert odds. IDs, task names, window indices, latent states and future
targets never enter inference.

For expert j, the exact observed-sensor likelihood is computed from its Kalman
innovations. With a fixed 1/2 prior, the adaptive expert's posterior mass is

    w(h) = sigmoid(log p(h|adaptive) - log p(h|anchor)).

The mixture's mean and total variance include between-expert uncertainty.
When passed to the Gaussian prediction API these are **moment projections**.
The exact mixture log score is saved separately and never substituted for the
original Gaussian NLL retention metric.

## Pointwise Gaussian protection

For each public history and each forecast horizon, write the anchor as
N(m0,v0), with v0>0, and let m1 be the public-likelihood mixture's proposed
mean. The fixed protection parameter is epsilon=0.02. Define

    d = clip((m1-m0)/sqrt(v0), -epsilon, epsilon)
    m = m0 + sqrt(v0)*d
    v = v0*(1+abs(d)).

When d=0 the anchor is unchanged. Otherwise, for z=(x-m0)/sqrt(v0) and
c=1+abs(d), the difference of Gaussian negative log densities is

    Delta(z) = 0.5*log(c) + 0.5*((z-d)^2/c - z^2).

This is a concave quadratic in z, with maximum at z=-d/abs(d). Consequently,

    sup_x Delta(x) = 0.5*(log(1+abs(d))+abs(d))
                 <= abs(d) <= epsilon.

At epsilon=0.02 the exact upper envelope is 0.019901313648089856. This is a
real-arithmetic pointwise statement relative to the **same immutable anchor**,
not an empirical assertion that the anchor is calibrated or optimal. Integrating
the density domination over any event with positive anchor mass also bounds
the increase of its event NLL. The proof does not assume the data follow the
anchor distribution and does not read held-out outcomes.

The protection is deliberately restrictive. It changes the mean by at most
0.02 anchor standard deviations and inflates variance conservatively. It
does not retain the candidate's variance adaptation and can sacrifice much of
the unrestricted adaptive filter's shifted-task improvement. The additional
efficacy gate is necessary: a completely frozen model would otherwise satisfy
the old-task condition without learning anything useful.

The theorem concerns the delivered Gaussian parameters. Lossy event encoding,
input quantization or later state transformations do not inherit it. For
decoded parameters with normalized mean displacement d and variance ratio
c>1, the applicable envelope is 0.5*log(c)+d^2/(2*(c-1)); c<1, or c=1 with
d nonzero, has no finite uniform upper bound. Runtime encoding qualification
must therefore remain separate or verify its final decoded envelope.

## Arms and budgets

Every arm has access to the original frozen model and its original training
data. The registered per-window budget is 256 independent trajectories.

| Arm | Training and prediction |
| --- | --- |
| frozen | Original anchor; no parameter update |
| online | 256 new trajectories, sequential parameter fit |
| replay | 128 new and 128 original trajectories, sequential parameter fit |
| fixed_mixture | Anchor and online filter with fixed equal weights |
| likelihood_mixture | Same two filters, exact public-history likelihood routing |
| protected | Likelihood-routed proposal followed by the pointwise Gaussian guard |
| protected_classical | Same learned parameters and guard, independently implemented dense joint-Gaussian conditional predictions |
| protected_quantized | Same routed proposal, separately certified Gaussian mean/variance on the native Q24 parameter lattice |
| protected_quantized_classical | Same quantized guard with independent dense joint-Gaussian anchor/proposal predictions |

Routing and guarding reuse the online fit and do not obtain extra labels or
optimizer steps. Their additional evaluation computation is measured. The
classical arm is an equivalence control: matching it does not establish a new
function class or a special advantage from financial terminology.

The quantized arms were prospectively added before confirmation/source freeze
to address the identified FP64-to-native-parameter gap. They do not replace
the FP64 protected arm or its original gates. `guard_quantized` reserves half
the normalized correction budget, rounds the mean to the Q24 lattice, and
rounds variance upward, then verifies that the **actual decoded** Gaussian
parameters have a valid pointwise certificate; an uncertified output is rejected.
Its declared anchor domain is `abs(m0)<=1e4`
and `1e-4<=v0<=100`, with finite proposed means; other inputs are rejected.
The existing native typed head has a narrower accepted parameter domain,
which is separately recorded for every scored prediction. Native execution
qualification is a separate runtime study.
Because the quantized guard also reserves half the mean-correction budget,
its efficacy difference from the full FP64 guard cannot be attributed solely
to rounding error.

Quantized-arm Gaussian and continuous-event log scores use these Q24-lattice
parameters with stable FP64 CDF evaluation. Unconstrained rounding of categorical
event probabilities to Q24 can set tiny tail masses to zero; it does **not**
inherit the uniform event-NLL guarantee. A separate anchor-constrained integer
projection addresses this final step. For total mass M=2^24 and anchor event
log probability a_k, its minimum count is at least ceil(M*exp(a_k-epsilon)),
and at least one for every finite a_k, including probabilities whose exponential
underflows FP64. With three categories and epsilon=0.02 the lower bounds leave
ample allocatable mass. Allocation preserves the exact total M and all floors.
Thus log(q_k/M)>=a_k-epsilon for every positive anchor event.

The result saves continuous Gaussian/event losses **and separately** delivered
integer-event NLL, calibration, exact counts, floor counts, projection error
and the maximum event-NLL certificate. Gaussian NLL remains the retention gate.
The corrected categorical forecast concerns the same terminal partition but
is a declared projection; it is not literally the Gaussian CDF of the emitted
mean and variance. Runtime evidence preserves raw native outputs and corrected
delivered counts separately. The same retention and additional efficacy gates
are reported separately for `protected_quantized`, without changing the
primary protected arm's verdict.

## Execution and freeze

The twelve windows are Gaussian, drift-shift, repeated six times. This order
was fixed before development outcomes were inspected. The final window is a
shifted environment so final adaptation efficacy measures an actual change.

`prepare_study` sequentially trains and writes every checkpoint, closes and
reopens it, verifies prediction identity, and uses the reconstructed online and
replay models for the next window. It never constructs or reads a holdout.
`PREPARED.json` binds source bytes, training datasets, learned model documents,
optimizer traces, predecessor checkpoint hashes and measured preparation cost.

After the parent commits the source/model freeze, `evaluate_study` verifies
every prepared artifact against `artifacts_sha256` and its code dependencies
against `sources_sha256`. It then generates untouched old/new holdouts and
scores reloaded checkpoints. Outputs go to the separate
`retention_confirmation` directory; the frozen prepared directory is unchanged.

The old holdout is fixed within a seed; new holdouts are independently generated
for each window after training/freeze. They never select parameters, routing
thresholds or a checkpoint. The full prediction arrays, targets, IDs, event
probabilities, losses, calibration scores, parameter guards and timing records
are retained. This is a supervised parameter-retention experiment, not a test
of multiyear semantic or procedural memory. The protected reference is the
original Gaussian task; this does not establish simultaneous retention of
every intervening non-anchor regime or an arbitrary growing collection of tasks.

## Registered conclusions

The original gate remains: worst window's mean old-task Gaussian NLL increase
is at most 0.02, and final-window new-task NLL does not exceed the frozen
model's. Its result is reported independently of the additional efficacy gate.

The additional gate requires mean NLL improvement of at least 0.005 over the
six shifted windows, an upper descriptive 95% bootstrap bound below zero, and
an improvement for every training seed. The bootstrap first resamples training
seeds, then resamples trajectories separately inside each fixed window. The
12 windows are not treated as 12 independent training replicates. Five training
seeds limit inference; these intervals have no finite-sample coverage guarantee.

ECE, 95% Gaussian interval coverage, MSE, exact-mixture scores and computation
are separately reported. The NLL envelope is not a calibration, latency or
long-duration production qualification.

Development uses only seeds 701 and 709. Confirmation uses new training seeds
101, 211, 307, 401 and 503, fresh named splits, and a distinct seed namespace.
No confirmation execution is permitted before the parent's source/model freeze.
