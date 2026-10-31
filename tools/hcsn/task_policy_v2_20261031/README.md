# Task policy v2: structural baseline and learned residual

This package addresses the large teacher-to-policy loss observed in the frozen
`task_value_factorial_20261030` experiment. It leaves that package and its data
unchanged. The content checkpoint, actual READ/SKIP/FIRE/STOP owner and fitted
observation-law semantics are inherited explicitly.

## Bounded ordinary baseline

`planner.OneRead` permits at most one additional READ for each remaining job.
It evaluates public future reliability, price, time, budget and posterior. It
does not call the full Bellman recursion, read unseen packets or inspect hidden
truth. After each actual action it replans, so a whole executed episode may read
more than once per job. This is an ordinary bounded planner, **not a learned
neuron**.

For the declared nonnegative additive time/query costs, delaying a FIRE when no
more reads are allowed in that job is weakly dominated by firing now and, if
necessary, waiting in the next job. This permits the compact computation in
`read_once` without dropping a better restricted policy. An independent explicit
recursion with a per-job remaining-read cap checks this equivalence, including
asymmetric observation confusion. The restricted action values are lower bounds
on the corresponding full fitted-law action values.

## Learned policy

`training.teacher_data` uses new public schedules and fitted-law counterfactual
trajectories under teacher, bounded-planner and exploratory actions. It adds
declared belief-grid states to cover rarely visited decision surfaces. No hidden
packet observations or evaluator labels enter these teacher targets.

Each state is encoded by 65 features: job, relative remaining horizon, remaining
budget, canonical posterior/confidence, correspondingly relabeled confusion,
objective weights, current/next job future schedules, durations and four bounded
action values. Past sunk costs, absolute prefix positions and class names do not
alter this finite task's continuation value; the actual owner state is never
modified by canonicalization.

A 65→64 tanh→4 network fits the nonnegative residual over the bounded prior.
The deployment equation is documented in every checkpoint. STOP is fixed at
zero; illegal actions remain excluded. `q_mse` fits action-value residuals;
`advantage` projects errors onto the legal-action contrast space. Both use the
same initialization, batches, update budget and validation action-regret rule.
Update zero is retained as a candidate, so a trained network is not chosen merely
because it exists. Stationarity diagnostics report an actual full-training
gradient norm; fixed-budget termination is not described as global convergence.

The native deployment profile additionally specifies Q24 inputs and final
stable tie selection. That is a distinct numerical execution contract, not a
claim that arbitrary floating argmax ties are portable across backends.

## APIs

- `OneRead(meta, confusion, multiplier, latency_price).q(job,tick,budget,p)`.
- `OneRead.features(...)`: no teacher access; raw 65-vector with finite prior
  entries (illegal entries are zero, accompanied by the owner's legal mask).
- `teacher_data(seed, environment_count, protocol, confusion)`: development or
  training supervision, including generation CPU/wall and all public metadata.
- `fit(train, validation, seed, mode, width=64, updates=6000, batch=256)`:
  returns a portable JSON checkpoint plus all candidate checkpoints, losses,
  initialization and batch hashes, validation choice and costs.
- `execution.rollout`: actual inherited owner execution, with all events and
  action scores. `diagnose` recomputes teacher regret **after execution** and
  records that diagnostic CPU separately.
- `execution.rollout(..., numeric_contract="hepta.task.native-q24-residual.v1")`
  imports the single shared implementation in
  `native_task_bridge_20261031/reference.py`. Residual raw inputs and priors use
  signed Q24 rounding; all three policies use the same output Q24 ranking and
  lowest-index tie rule. The default remains the separately identified float64
  development contract. Traces retain the five integer drives and legal mask.

## Preserved development outcomes

All data below use a new namespace. They are development observations, not a
frozen confirmation result or evidence of independent neural task gains.

| Development comparison | Bounded planner | Residual Q-MSE | Residual advantage |
| --- | ---: | ---: | ---: |
| 5,112 training / 2,592 validation states | 0.00191390 | 0.00296577 | 0.00293280 |
| 40,815 training / 10,131 validation states | 0.00139162 | 0.00094881 | 0.00110642 |

Entries are mean fitted-teacher action regret of the best **trained** candidate,
alongside the zero-residual prior. The small-data run selected update zero for
both losses. The broader run selected the nonzero 6,000-update Q-MSE candidate.
One earlier attempt aborted during development collection because a JSON list
confusion matrix lacked explicit NumPy conversion; the failure receipt is kept.

Fresh real-owner development rollouts of the broader selected model gave:

| Distribution, 128 sessions | Exact teacher utility | Planner utility | Residual utility | Planner / residual cumulative teacher regret |
| --- | ---: | ---: | ---: | ---: |
| IID | 1.020270 | 0.990230 | 1.062637 | 0.003721 / 0.003602 |
| OOD | 0.793551 | 0.855773 | 0.883797 | 0.003767 / 0.007534 |

The OOD learned residual has **higher** fitted-teacher regret despite its positive
realized utility difference in this small development sample. No task benefit is
claimed from that point estimate. Planner controller CPU is about 0.71 ms/session;
residual CPU is 1.15–1.18 ms; full teacher is 4.66–4.77 ms in this probe. Teacher
data generation, calibration and fitting must also be charged to a learned
deployment. Packets used a temporary RAM filesystem; these are not production
retrieval or hardware energy measurements.

## Fixed numeric-profile verification

The existing 10,131 validation states were replayed without fitting or changing
weights. Switching from float64 argmax to the shared Q24 profile changed 139
teacher, 184 OneRead and 46 residual actions. Teacher changes cost at most
2.23e-16 in its own fitted value. The residual's mean teacher regret remained
0.000948812; its largest pre-output score difference was 2.81e-7. A tie in the
bounded planner's Q can be a substantial non-tie for the full teacher: the
largest single-state teacher regret increase among OneRead changes was 0.08654.
Its average teacher regret changed from 0.00139162 to 0.00137931. Quantization
bounds on a controller's own scores do not imply bounds on full-teacher regret.

All three policies and both numeric profiles also re-executed the same 256
retained development sessions. Q24 IID OneRead/residual utilities were
0.990230/1.062637; stress utilities were 0.840148/0.868465. Different choices
between equal fitted-value actions can change realized outcomes on fixed hidden
packets. These are numerical diagnostics on development data, not a fresh
confirmation or an opportunity to retune the model.

## Prospective campaign

`python -m tools.hcsn.task_policy_v2_20261031.campaign prepare --out PATH` creates
only TRAIN calibration and counterfactual TRAIN/VAL data. Five new seeds
(73031, 73037, 73043, 73049, 73057), namespace 487103100, 128 calibration READs,
1,024 training environments, 256 validation environments, and 6,000 Q-MSE
updates are fixed in `campaign.protocol()`. Every candidate's actual Q24
validation inference is saved. The primary nonzero candidate is selected from
updates 100/300/1000/6000; update zero, the overall best, and the 6000-update
model are all preserved. A nonzero model which fails to improve zero prevents
learned admission. The complete teacher data, optimizer losses, candidate
parameters, selected-model full-training gradient and measured preparation
costs are retained. Fixed-budget optimization is not asserted stationary.

Only after remote publication of source, protocol and the prepared manifest may
`campaign confirm --prepared PATH --out NEW_PATH --freeze-receipt RECEIPT` run.
The receipt must provide the repository, full commit hash, remote manifest
SHA-256 and `remote_verified: true`; remote verification is performed by the
orchestrator. Before generating any data the runner checks that receipt and
every local prepared/source byte. It then creates 128 IID plus 128 stress
sessions per seed and runs exact teacher, OneRead and the selected nonzero
residual on the same packets and Q24 action contract (3,840 runs).

The two primary residual-minus-OneRead utility contrasts use paired seed means,
95% Student-t intervals and Holm correction. Quality is correct submissions
divided by two available jobs, including unsubmitted jobs in the denominator;
the noninferiority margin is two percentage points. Conditional accuracy,
completion, wrong submissions and fitted-teacher regret remain separate.
Measured complete owner CPU, raw-result persistence, model loading and the full
incremental residual preparation are charged at declared CPU prices and
amortization horizons 128/1000/10000. CPU sensitivities use 0/0.1/1/10 research
utility units per host CPU-second; the primary gate uses 1 and 1,000 sessions.
These are declared research accounting prices, not measured production expenses
or hardware energy prices. Bellman uses declared task time, while host CPU enters
the post-execution admission calculation. Main activation and analytic-cell
benefit are outside this ordinary-planner/residual study.

## Verification

`python -m unittest tools.hcsn.task_policy_v2_20261031.policy_tests` checks the
independent restricted recursion and full-teacher lower-bound relation, label
symmetry, and both masked weighted loss gradients against independent finite
differences. Actual owner probes preserve all files, model inference receipts,
actions, task costs and post-execution regret. Formal confirmation must use new
seeds and be created only after publication of its protocol and selected models.
