# First-event risk feature study

This is a separate, post-baseline exploratory study. It does not change the
frozen `content002` code, protocol, results, or scientific interpretation.
The same copy and MQAR dataset splits have already been observed in earlier
studies. New seeds do not make their heldout examples a pristine confirmation
set.

## Mechanism and equal-capacity comparison

Every arm receives the complete finite-state physical distribution and all
seven local physical coefficients. Three extra feature slots have the same
trainable projection and no unused parameter padding:

| Arm | Three engineered feature slots | Boundary |
|---|---|---|
| `risk_ordinary_two_gates` | Active mean, variance, active mass | Value derived |
| `risk_margin` | Margin, active mean, variance | Value derived |
| `risk_margin_j` | Margin, policy continuation J, variance | Value derived |
| `risk_margin_j_risk` | Margin, J, current-interval first-event probability | Value derived |
| `risk_fixed_full` | Margin, J, first-event probability | Fixed at 1.2 |
| `risk_direct_full` | Margin, J, first-event probability | Learned constant |
| `risk_conditional_full` | Margin, J, first-event probability | Learned intercept and slope times local drift |

This is an equal-capacity **feature replacement** ladder. It does not isolate
information by removing the underlying probability state from the controls.
The four free-boundary feature arms and fixed arm have 17,936 backbone
parameters; direct and conditional controls add 8 and 16 active parameters.
All use a width-32 common content state, eight physical channels, eight active
cells, and two refractory phases. The learned boundaries use the same domain,
`0.35 + 3.99 sigmoid(...)`, initialized at 1.2; the conditional slope starts at
zero. The value-derived boundary solves the infinite-domain Brownian/Erlang
surrogate, not the finite grid or classification objective.

For a row probability vector p, the risk operator is

`p (1 - R_nohit exp(Q_nohit.T dt) 1)`.

The substochastic overlap map `R_nohit` removes all mass crossing a shrinking
boundary. The killed generator removes all new firing destinations, including
instantaneous reset to the same state, while preserving release from existing
refractory phases. A finite unnormalized Poisson series approximates the matrix
exponential in float64, with the truncation error retained separately from
roundoff. Survival mass is never normalized. Risk plus surviving mass equals
incoming mass; the incoming float32 cast can differ slightly from one.
Expected repeated-event count remains a separate quantity and may exceed one.
This risk is a first-event probability of the declared finite model, not a
financial put value or a claim about biological firing probabilities.

The ordinary regenerative distribution alone uses the independently audited
`roundoff_unit_mass_v1` profile. The correction denominator remains in the
gradient graph. Every token exposes the actual correction, pre/post mass, and
transition row defect. Negative probabilities and excessive defects raise an
error. This projection is never applied to killed survival operators.

## Frozen experiment

The planned matrix is seven arms, two tasks, eight paired initialization seeds
(9401 through 9408): 112 candidates, one fixed learning rate 0.001, and 20
process-CPU seconds of training per candidate. Nominal training cost is 2,240
CPU seconds; full worker cost also includes imports, setup, validation,
checkpoint writes, and heldout evaluation. The update cap cannot substitute
for the CPU budget. Validation checkpoints at 5, 10 and 20 CPU seconds select
the model before heldout access. Whole updates and endpoint overruns are
charged. A fixed-step-128 checkpoint, when reached, is descriptive only.

The two task accuracy differences are averaged **within each seed** before
the paired test. They are not counted as sixteen independent observations.
Four primary contrasts use exact two-sided sign flips and Holm correction:
full risk versus margin+J; full risk versus ordinary gates; margin+J versus
margin; and the value-derived full model versus the conditional threshold.
Each success gate also needs a mean gain of at least one percentage point
and a positive nominal paired-t 95% lower bound. The remaining margin versus
ordinary and value-derived versus fixed/constant-threshold comparisons are
descriptive secondary results.

With eight independent paired seeds, the smallest two-sided exact p-value is
2/256 = 0.0078125. Seven primary Holm tests would make the smallest first
adjusted p-value 0.0546875, so no primary rejection would be possible at 0.05.
The four-primary/three-secondary split was fixed during training-only design,
before new study training or heldout access.

## Execution

Registration requires both training-only preflight and independent numerical
risk audit to pass. Source hashes, dataset hashes and their receipts are then
bound into a new protocol. Do not reuse a partially executed result directory,
retune against heldout results, or replace older evidence.

```bash
python -m experiments.hcsn_risk_ablation_v1.study register \
  --output experiments/hcsn_risk_ablation_v1/results/risk001 \
  --math-audit experiments/hcsn_distributional_v2/results/sixstage_20261030_risk_independent/RESULTS.json

python -m experiments.hcsn_risk_ablation_v1.study run \
  --output experiments/hcsn_risk_ablation_v1/results/risk001

python -m experiments.hcsn_risk_ablation_v1.analysis \
  --study experiments/hcsn_risk_ablation_v1/results/risk001 \
  --output experiments/hcsn_risk_ablation_v1/results/risk001_analysis
```

The runner uses two one-thread isolated workers and records `os.wait4` CPU and
peak RSS for every complete worker. A failure stops new launches and drains
active workers. A `STOP_REQUESTED.json` file in the output directory requests
the same cooperative stop. Energy, GPU efficiency, and foundation-scale
training are not measured by this experiment. Equal-CPU test accuracy does
not establish quality-matched runtime superiority.
