# Round 8 finite-controller value calibration: results

The specific first-passage controller repair succeeded on the eight known
contracts. All five fitted first-passage heads now choose STOP in preset 4 and
READ in preset 6, replacing the old initial WAIT errors. A new frozen paired
confirmation supports a positive nominal return improvement after the declared
CPU-cost conversion and preparation amortization. Independent checks reproduce
all recorded actions and returns.

This does **not** establish a first-passage advantage over a similarly trained
ordinary controller. Those comparisons remain inconclusive, and performance
under all three untrained parameter shifts deteriorated. Production activation
remains false.

## Identity and scope

The immutable confirmation freeze is commit
`3a0e62c61b595576f16313c9b6016ec62cf8088b` on
`research/hcsn-five-track-closure-20261031-r8`:

<https://github.com/TrillionniumFoundation/hepta-private-ci/commit/3a0e62c61b595576f16313c9b6016ec62cf8088b>

`evidence/prepared02/FREEZE.json` has SHA256
`da08baa4464b202a0071a2767d08009464f9b60e279c540332fc09ed042096ad`.
It binds every fitted head, full Q/action/value table, source module and imported
Round 7 checkpoint. The Round 7 source commit is
`1bbf9712140ec388f7fb7967fa7b22244386441d`. The confirmation and final cost ledger
both verify that the frozen scientific source remains unchanged.

The inherited first-passage cell is a 15-voltage-state, two-refractory-state
finite CTMC with one event per tick. This lane intentionally preserves that
model to identify a controller repair. Its independent optimum is a finite
joint-state DP, not a continuum QVI certificate or an exact continuous OU law.
The content encoder, drive, diffusion, threshold, reset and recovery parameters
are frozen. No new multi-layer SNN or joint cell training is claimed.

The new 1,091-parameter head predicts three action advantages over the exact
public terminal STOP payoff. Every new family uses the same 32-hidden-unit
architecture, objective, optimizer and 2,400-iteration cap. The head is larger
than the original Round 7 readout; therefore new-versus-old results identify
the entire calibration package, not an isolated optimizer or neural-operator
effect. The old and new task contracts and information are identical.

The teacher supplies known finite-model optimal Q labels on all 673 canonical
nominal public states and their finite cell states. Training is supervised
model-based distillation. Deployment evaluates fitted weights; it never reads
an optimum, teacher, policy table or private episode evidence. Current event
cost is already sunk when an action is selected, while all future event,
decision, reset and recovery consequences remain in continuation values.

## Actual training and independent finite-model verification

Every exported head was fitted, serialized, reloaded and evaluated. All 15
optimizers made nonzero parameter changes and completed exactly 2,400
iterations. All stopped at the iteration limit; **optimizer convergence is not
claimed**. The earlier 600-iteration development attempt remains in evidence:
it improved Q values but did not repair the target decisions. The 2,400-step
budget was selected before any confirmation episode was generated.

The following values are means over five fits. Q RMSE and action regret use
legal actions on the complete known finite graph. Returns are exact finite-DP
expectations, including the registered decision and event utility costs.

| Frozen family | Q RMSE, old → new | Mean action regret, old → new | Exact return, old → new | Finite optimum |
| --- | ---: | ---: | ---: | ---: |
| First passage | 0.233108 → 0.008976 | 0.012535 → 0.001058 | 0.629975 → 0.651265 | 0.653604 |
| Clocked | 0.233262 → 0.007903 | 0.012265 → 0.000886 | 0.633042 → 0.651220 | 0.653599 |
| Direct | 0.233337 → 0.006576 | 0.012713 → 0.000844 | 0.633481 → 0.652400 | 0.653767 |

All 15 heads repair preset 4's initial STOP decision. First passage and direct
repair preset 6's initial READ decision in all five fits. Clocked seed 13 still
chooses WAIT in preset 6. This residual failure was retained under the original
fixed budget; the candidate was not retrained to make the table uniform.

The separate evaluator enumerates hidden worlds conditional on public evidence,
uses the actual task step function, and recursively evaluates returns without
using fitted Q values in its optimum. Its maximum discrepancy from the training
DP is `8.8818e-16`. Reproducing published Round 7 greedy expected returns differs
by at most `4.3299e-15`. Actual Torch-versus-NumPy execution of all 15 original
checkpoints at 31 public states has maximum Q error `4.4409e-16` and maximum
transition/event error `6.1062e-15`.

Three mechanism tests pass: exact objective-gradient differentiation with legal
action masks; execution-world enumeration versus the upstream public oracle;
and deadline/current-cost/future-cell continuation semantics. These tests are
supporting checks, not substitutes for full action/return replay.

Source: `evidence/prepared02/PREPARE.json`, its per-fit tables and checkpoints,
`evidence/TORCH_EXECUTOR_PARITY.json`, and `test_value.py`.

## Frozen paired confirmation

The campaign contains 128 new episodes per contract, fit and regime: 61,440
paired records, or 122,880 executions. Each pair shares its private episode and
keyed latent innovations; old/new execution order alternates. Five paired fit
means are the inference units. The three nominal within-family comparisons use
two-sided 98.333% Student-t intervals, the registered three-comparison Bonferroni
adjustment. Nominal task states were available during training, so new nominal
trajectories do not demonstrate unseen-state generalization.

Primary illustrative pricing is one utility unit per process CPU second and
10,000 deployment sessions per preparation. The original Round 7 training is
common sunk work for each old-versus-new fixed-core comparison. Each standalone
new head is charged all recorded development work, common setup and its own
fit, validation and export. Quality noninferiority permits a lower bound of
minus 0.02 in answer correctness.

| Nominal new minus old | Utility difference [interval] | Correctness difference [interval] | Priced net difference [interval] |
| --- | --- | --- | --- |
| First passage | +0.025051 [0.012589, 0.037512] | +0.013086 [0.006777, 0.019394] | +0.018301 [0.006157, 0.030445] |
| Clocked | +0.020192 [0.004634, 0.035749] | +0.010352 [0.003585, 0.017118] | +0.013303 [-0.002300, 0.028905] |
| Direct | +0.020637 [0.004918, 0.036355] | +0.010547 [0.002677, 0.018417] | +0.014086 [-0.001623, 0.029795] |

First passage passes the registered nominal repair, quality and priced-net
gates. Both ordinary families improve nominal utility, but their primary
priced-net lower bounds do not exceed zero. This does not show that an ordinary
model has inferior absolute performance: the first-passage old checkpoint had
more room for repair, especially seed 11.

All three shifted regimes were excluded from the new head's training domain.
The first-passage new-minus-old utility differences are:

| Shift | Mean utility difference | 98.333% interval | Mean correctness difference |
| --- | ---: | --- | ---: |
| Drift/reliability/prior | -0.036907 | [-0.088531, 0.014716] | -0.008789 |
| Missing/corrupt delayed evidence | -0.081311 | [-0.201319, 0.038698] | -0.041211 |
| Changed action/latency costs | -0.050859 | [-0.116094, 0.014376] | +0.009375 |

These are failed robustness gates. The increased correctness in the cost shift
does not compensate for unnecessary expensive actions. No confirmation or
shifted trajectory was used for a further model update.

Source: `evidence/confirmation01/SUMMARY.json` and `RAW.jsonl.gz`.

## Fair comparison with the new ordinary heads

The secondary comparisons use the same new-head capacity and training method
in each family. Frozen upstream cell and content parameters differ, so this is
a family comparison, not a one-factor randomized architectural intervention.

| New first passage minus new baseline, nominal | Utility difference [interval] | Priced net difference [interval] |
| --- | --- | --- |
| Clocked | +0.001350 [-0.003528, 0.006227] | +0.001283 [-0.004127, 0.006692] |
| Direct | +0.000019 [-0.006153, 0.006190] | -0.000550 [-0.007627, 0.006526] |

Neither comparison establishes positive net superiority. Original warm episode
CPU for the new first-passage model exceeds new clocked by 0.234 ms and new
direct by 0.405 ms per episode on average. These are measured CPU counters in
this runtime, not energy measurements or neuromorphic hardware projections.

The independent audit replays **all 61,440 pairs and 444,930 decisions** without
calling the recorded runner or the head's prediction method. It verifies the
registered seed coverage, absence of duplicate episodes, latent innovations,
greedy legal actions, guard behavior, event/decision counters, rewards,
terminal correctness and aggregates. Maximum Q and return discrepancies are
zero; maximum aggregate discrepancy is `9.6728e-15`.

The original compressed confirmation raw SHA256 is
`cda448227d60d77ebe127d1ea9446c18779a32a114d47dcbd1895c5700aec65f`.
Source: `evidence/CONFIRMATION_AUDIT.json`.

## Application pipeline cost supplement and accounting limits

A post-confirmation cost-only supplement replays the first 16 registered seeds
per contract, using 30 separate cold workers and 3,840 executions in total.
Every action and outcome matches its original confirmation record. No model,
protocol or original timing was changed. Each worker's parent measures child
CPU through exit, including interpreter startup, scientific imports, input and
model loading, inference, task execution, gzip, report writing and shutdown.
The scenario runs one new worker per 128-session batch; it is not a promise
about a different service process lifetime.

With these complete batch-pipeline counters, new-first-passage minus old has
priced-net difference **+0.018095 [0.005117, 0.031073]** at the same primary
pricing. New first passage minus new direct is **-0.000212
[-0.006926, 0.006503]**. The main conclusions are unchanged. New first passage
and direct consume approximately 6.260 ms and 6.193 ms of complete batch CPU
per session, respectively. Import overhead dominates this small batch, and
the paired timing difference is too uncertain to claim a speed advantage.

All original and supplemental comparisons include the declared CPU-price grid
`{0, 0.1, 1, 10}` and deployment-volume grid `{128, 1000, 10000, 100000}`. These
are scenarios in utility per CPU second, not market prices or measured energy.
The supplemental timings are explicitly post-confirmation and do not replace
the preregistered primary timing.

`evidence/COST_LEDGER.json` sums **619.860 recorded CPU seconds** across disjoint
stage scopes: development, formal preparation, confirmation, independent audit
and supplemental worker/parent work. It does not multiply shared development by
15. Per-head hypothetical deployment charges are separate from this actual
campaign ledger and must not be added again.

This is a sum of measured scopes, **not a claim of a fully measured campaign
total**. Initial parity-export failure, the before-training path bookkeeping
failure, some interpreter/final-serialization overhead, parity/test execution
CPU, developer time and physical energy were not measured. They remain null or
explicitly unmeasured rather than zero. The failed attempts and their error
records are retained. The successful preparation and confirmation stage timers
also exclude their final summary/freeze serialization; full cold deployment
pipeline measurement addresses deployment overhead, not these missing past
research counters.

Source: `supplemental_cost/pipeline.py`, `evidence/pipeline01/PIPELINE_COST.json`,
all supplemental worker raw records, `evidence/AUDIT_RUNTIME.json` and
`evidence/COST_LEDGER.json`.

## Research decision

The new weights are a reproducible, bounded repair of known finite-controller
value calibration and action selection. They can be studied as a candidate
nominal controller. The evidence does not justify replacing the existing
production controller or declaring a general new SNN advantage. The next
scientific gap is robust policy/value learning under changing costs and evidence
laws while preserving a positive net comparison against similarly trained
ordinary models. That remains open rather than being hidden by nominal repair.
