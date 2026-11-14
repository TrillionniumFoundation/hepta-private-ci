# VERIFY-2: terminal risk, checker effects and decision value

VERIFY-2 adds a shadow research path alongside the frozen VERIFY-1 package.
It estimates whether a particular check can improve a feasible decision, with
explicit terminal targets, paired checker observations and declared costs.
It does not install a production signer, evaluator or acceptance owner.

## Components

| Module | Input and responsibility |
| --- | --- |
| `shadow_risk.py` | Strictly prospective snapshots, fixed terminal target and continuation policy; a train-only frequency baseline and per-frontier risk metrics. |
| `checker_effects.py` | Same-snapshot paired checker outcomes and separate labels; a joint empirical channel conditioned on complete observed history. |
| `check_voi.py` | Finite state probabilities, feasible actions, losses and checker channels; exact one-check Bayes decision value. |
| `shadow_schedule.py` | Binds the three components to one public context, frozen model versions and trusted host gate status; retains an auditable advisory record. |

The SHA-pinned `contracts.py`, `runtime.py` and `metrics.py` remain the original
VERIFY-1 implementation. New log loss is recorded in `verify-shadow-metrics-v1`;
it is not inserted into the old native `[0,1]` calibration-report field.

## Terminal risk is a named target

`Target` binds domain, event, terminal horizon and continuation-policy digest.
Every `Snapshot` must precede the horizon. Features must be observable at that
frontier; a later checker result, label or fault tag must not be copied backward.
The baseline uses `(observed_step, features)` bins with Beta(1,1) smoothing.
Unseen bins return an unsupported prediction.

Training groups and evaluation groups are frozen and disjoint. Group names and
hashes do not establish task independence. A repeated task at multiple frontiers
is still one trajectory, and repeated templates are not natural-task trials.

`TerminalLabel.disposition` is separate from `error`. An UNKNOWN disposition can
have a known independent outcome; an ACCEPT can lack a label. Keep one record
for every planned attempt, including failure, cancellation, no prediction and
missing truth. Missing labels require a reason and never become successful
outcomes by default. A digest binds supplied evidence; it does not authenticate
an independent evaluation organization or prove that a declared label is true.

An uninterrupted step-3 target cannot use a reached-state label from a trajectory
stopped at step 2. If all three effect steps completed before a stop, the actual
step-3 label can remain usable. The retained execution ledger must establish
which case applies. Repair creates a different state and may change the target;
do not score an earlier candidate against a later repaired success.

## Checker effects require a common observation context

`EffectScope` binds the terminal target and the pre-check context digest. Fit
separate panels for different public feature strata; pairing a feature-conditioned
risk prior with an unrelated marginal checker channel can introduce an unjustified
conditional-independence assumption.

Each `PairedPanel` contains one immutable candidate snapshot, every declared
checker identity/version, each actual outcome and its evidence digest, and a
separately obtained label. Outcomes are `pass`, `fail` and `unknown`. A checker
timeout can be recorded as UNKNOWN under its declared versioned contract;
UNKNOWN is not PASS and is not a missing label.

The fitted table preserves the joint outcome vector. `condition` receives the
original pre-history prior and the complete history once. Passing an already
updated prior counts the same evidence twice. Domain/context changes, missing
class support and unsupported histories refuse. Minimum sample counts are
support gates, not confidence bounds. Hypothetical zero-frequency outcomes are
empirical plug-in estimates and do not prove population impossibility.

## The decision objective

For finite states `s`, current probabilities `p[s]`, feasible actions `a`, loss
`L[a,s]`, and checker likelihood `q[o|s]`, the numerical layer computes:

```text
before = min_a sum_s p[s] L[a,s]
after  = sum_o min_a sum_s p[s] q[o|s] L[a,s]
net_value = before - after - incremental_check_cost
```

This is exact one-check optimization within the supplied model. It is not a
multi-check policy optimum or evidence of real-world improvement. The action
matrix must include repair cost, residual repair failures, new errors, rejection
opportunity loss and downstream mandatory work. A mandatory terminal checker
that will already catch a defect can make another optional check redundant.

`select_shadow_check` receives trusted `hard_checks_complete` and already
feasible actions. Pending permission/schema/original-owner checks block its
optional path. A model forecast cannot mark those checks complete. All results
have `production_authority=NONE`; fresh terminal acceptance remains with the
original host owner. The retained decision record includes actions, losses,
budget, gate status, model/data/context/history hashes and outcome decisions.

## Evaluation and advancement

Replay a retained VERIFY-1 model run without new neural inference or original
effects. Supply the complete original plan, operations/attempts, trajectory
rows/attempts, panel labels, assessments and decisions. The output is create-only:

```sh
python -B -m experiments.verification_cell_verify1.shadow_replay \
  --input /path/to/retained-run --output /path/to/new-replay
```

The loader validates the original roster, inference/decision bindings, mandatory
acceptance checks, actual effect order and label timing. It freezes input/source
hashes, fits only original training panels, and scores ACK-prefix observations
at steps 0 and 2. Early-stopped trajectories keep missing uninterrupted-target
labels. Calibration reference panels have no policy acceptance decision. This
replay is a historical diagnostic and does not establish prospective collection.

Profile the retained initial neural forecasts as thresholded checker channels:

```sh
python -B -m experiments.verification_cell_verify1.checker_replay \
  --input /path/to/retained-run --output /path/to/new-checker-diagnostic
```

This fixes a 0.5 threshold, fits the prior only on train labels, and fits paired
channels only on calibration panels. It retains separate confirmation-arm
labels, including their censoring. The analytical zero checker cost isolates
gross information value; it does not assert free physical checking. These
forecast channels are distinct from the mandatory SQLite owner readback.

Run the package regression suite from the repository root:

```sh
python -B -m unittest discover -s experiments/verification_cell_verify1 -t . -v
```

Keep proper risk scores, acceptance coverage, accepted error and total cost
together. `[0,0]` with complete labels is the current finite-data error range,
not a future-error confidence upper bound. With zero accepts, the conditional
error rate is undefined. Exact infinite log loss is retained as a null value
plus an explicit infinity count rather than silently clipped.

Advancement requires a frozen prospective roster, independent terminal labels
across all dispositions, then a frozen scheduler comparison showing reduced
actual terminal error with acceptable coverage/utility and full incremental
cost. The current declared decision-loss costs omit unmeasured physical costs;
`full_physical_cost_complete` remains false. Historical replay is retrospective
and must not be presented as a new prospective deployment or new model inference.

## Research boundary

[Kumaran et al., arXiv:2603.22161v3](https://arxiv.org/abs/2603.22161v3)
separate confidence-driven abstention behavior from discrimination of answer
correctness. [Ning et al., EMNLP 2026](https://aclanthology.org/2026.emnlp-main.1808/)
separate per-step score calibration from trajectory-level score events and
their interpretation as actual task correctness. These motivate separate
behavior, prediction and terminal-outcome tests; they do not qualify this code.

## Forward collection

Use the [frozen prospective journal](PROSPECTIVE.md) to preserve every planned
attempt, ordered forecasts, original completion disposition and separately
authenticated terminal labels. This adds a collection API, not a prospective
benefit result. Checker dispatch, independent real-task labels and complete-cost
scheduler comparisons remain required.
