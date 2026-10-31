# Round 8 finite-task action-value calibration

This package repairs a specific, measured limitation of the frozen Round 7
controllers: their action-value scale and action choice. It keeps every old
checkpoint and research result intact. New heads are actually fitted, serialized,
reloaded and evaluated through their weights; deployment never consults a DP
table or oracle.

## Model and scope

The source baseline is Round 7 commit
`1bbf9712140ec388f7fb7967fa7b22244386441d`. The eight nominal contracts and
READ / WAIT / REPAIR / STOP execution semantics are unchanged. The public
Bayesian state is sufficient under this finite known task model. Consequently,
this study tests calibration and finite-budget representation, not an increase
in available task information or the optimal value of the underlying task.

For each of the five frozen first-passage, clocked and direct-Q checkpoints,
the encoder and cell remain fixed. A new 32-hidden-unit tanh head predicts the
three nonterminal action advantages over the exact, publicly known terminal
STOP payoff. All new families use the same head capacity, direct-value plus
action-gap squared loss, L-BFGS optimizer and update cap. The head has more
capacity than the original Round 7 readout. A new-versus-old difference is the
effect of this entire calibration package, not an isolated optimizer effect.

Targets are supervised optimal Q values on the registered finite joint
public/cell-state graph. This is known-model distillation, not model-free DQN.
The current event fee is already sunk when the action is chosen; future event,
reset, recovery and decision costs remain in continuation values. The terminal
STOP anchor includes its submission, time and decision costs. Every old and new
policy still pays all actually incurred current event costs during execution.

The training graph uses the existing independent upstream oracle. A separately
constructed reference enumerates hidden worlds conditional on public evidence,
calls the actual task execution function and recursively evaluates complete
returns. It never reads a fitted Q head when computing its optimum. The new
NumPy executor is also checked against real Torch execution of all 15 frozen
checkpoints, and against their previously published finite-DP returns.

## Development, freeze and confirmation

Development attempt 01 used 600 iterations: it improved value error but did not
repair all preset 4 and preset 6 initial decisions. Attempt 02 used 2,400
iterations on the same development checkpoint and repaired those decisions.
Both attempts and their actual costs remain under `evidence/development*`.
No confirmation trajectory was used to choose this budget.

`prepare` fits all 15 heads with the fixed 2,400-iteration budget, exports full
Q/action/value tables and independent checks, and records source and artifact
hashes. Nominal states are deliberately available during training. A fresh
nominal trajectory therefore is not evidence of unseen-state generalization.

`confirm` requires the exact prepared bytes and an immutable freeze reference.
It generates 128 paired episodes per contract and fit in nominal and three
predeclared parameter-shift regimes. Old and new actions share each episode's
private evidence and keyed latent innovations. Execution order alternates.
The three primary comparisons are new minus old within each frozen family on
nominal contracts. Five paired fit means are the inference units; primary
intervals use a three-comparison Bonferroni correction. Shifted-regime results
and new first-passage versus same-capacity new ordinary heads are secondary.

The finite-model implementation gates are source/forward parity, independent
DP agreement, real nonzero parameter learning, Q-error reduction and the
specific preset 4 STOP / preset 6 READ regressions. Efficacy additionally needs
a positive paired utility lower bound, a quality lower bound of at least -0.02,
and a positive compute-priced lower bound. Any failed gate remains failed.

## Costs and interpretation

Raw process CPU seconds, sampled task costs, decision/event utility proxies and
physical energy are separate quantities. The illustrative primary scenario
prices one CPU second at one utility unit and amortizes preparation over 10,000
sessions. The full declared sensitivity grid uses CPU prices 0, 0.1, 1 and 10
and deployment volumes 128, 1,000, 10,000 and 100,000.

Each hypothetical standalone new head is charged the common preparation,
its actual fit/certification/export, and all recorded development attempts.
The original Round 7 training is shared sunk work in the within-checkpoint
comparison. Actual research totals count common work once. These conversions
are scenarios, not measured energy or monetary prices. Audit-only replay costs
are recorded separately and do not replace the original uncached execution
counter. No sparse-event hardware saving is inferred.

The first-passage family intentionally preserves the old finite CTMC model so
that this experiment isolates the controller repair from any physical-kernel
change. It inherits that model's continuum discretization limitations. It is
not a new multilayer SNN, a continuous-QVI proof, a production installation or
evidence that every new head component has an independently identified gain.

## Reproduction

From the repository root, with NumPy and SciPy installed and BLAS threads set
to one:

```bash
python -m unittest tools.hcsn.round8_20261031.value_calibration.test_value -v
python -m tools.hcsn.round8_20261031.value_calibration.run prepare \
  --output /tmp/r8-new-preparation --iterations 2400
python -m tools.hcsn.round8_20261031.value_calibration.run confirm \
  --prepared /tmp/r8-new-preparation --output /tmp/r8-new-confirmation \
  --freeze-reference <verified-immutable-freeze>
python -m tools.hcsn.round8_20261031.value_calibration.audit \
  --prepared /tmp/r8-new-preparation --confirmation /tmp/r8-new-confirmation \
  --output /tmp/r8-new-independent-audit.json
```
