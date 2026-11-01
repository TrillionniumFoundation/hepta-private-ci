# R16 finite reset and boundary selection

This is a separately declared, fully observed finite maintenance task. It uses
R15's 40-state generator but exposes the phase and content state to every arm.
It does not transfer a full-observation result to R15's hidden-content task.
Content labels here specify a synthetic maintenance payoff; they do not
establish learned address binding or semantic memory.

## Real interventions and matched comparisons

Every arm has the same `STOP`, `RUN`, and `RESET` actions, the same public state,
the same interval and remaining horizon, and the same known stochastic model.
`RESET` samples a new owner state from the selected recovery kernel, pays the
registered fee, and then propagates that intervened state for one interval.
Thus it changes future outcomes. It is not the R15 `REFRESH` observation.

Three content kernels and two recovery stages are finite candidate sets.
Separate training and selection namespaces choose the content kernel alone,
the recovery stage alone, their joint setting, and a threshold policy for the
selected joint setting. All evaluated candidates, including rejected ones,
are retained with returns and measured process CPU. Selection uses training
rank to form a fixed-size shortlist; selection mean chooses the winner.
Original candidate order resolves training ties and shortlist order resolves
selection ties. Neither namespace accesses confirmation draws.

The seven reported arms are:

| Arm | Reset content / recovery | Timing policy |
| --- | --- | --- |
| fixed | registered retain / early | registered threshold |
| kernel_only | selected content / early | same registered threshold |
| recovery_only | retain / selected recovery | same registered threshold |
| learned_reset | selected joint reset | same registered threshold |
| learned_boundary | same selected joint reset | selected threshold and stopping horizon |
| finite_dp | same selected joint reset | full-state finite-horizon DP |
| ordinary_same_q_dp | same selected joint reset | the identical ordinary DP |

The learned-boundary versus learned-reset contrast isolates the finite timing
selector with the reset setting fixed. The kernel-only and recovery-only
contrasts each change only their specified reset component. Selection in this
study is finite empirical policy search, not a learned neural reset network.

## Exact finite optimality and its limit

Let `r` be the stage reward rate, `g` the stop value, `P=exp(dt*Q)` the row
transition matrix, `K` the selected reset kernel, and `c` its fee. With `h`
remaining intervals, backward induction is

\[
V_0=g,\qquad
V_h=\max\{g,\;dt\,r+PV_{h-1},\;K(dt\,r+PV_{h-1})-c\}.
\]

The maximum is taken separately at every state, in the common deterministic
tie order STOP, RUN, RESET. At zero horizon the actor must STOP. At a positive
horizon the three terms are exactly the three admissible action returns,
followed by a subproblem with one fewer interval where relevant. Induction
therefore proves optimality for this registered finite MDP and selected reset
kernel. It does not prove optimality for continuously chosen intervention
times, unobserved states, an unbounded horizon, or kernels outside the candidate
set. `ordinary_same_q_dp` uses the same recurrence and information; no HX-only
control gain is claimed.

`checks.py` independently evaluates the scalar recurrence, checks dominance
over all registered thresholds, and checks actual owner reset states and
deterministic replay. `DEVELOPMENT_CHECKS.json` uses only development draws.
Its Monte Carlo comparison is descriptive and is not confirmation evidence.

## Freeze and execution

The four executable/specification files are `PROTOCOL.json`, `model.py`,
`campaign.py`, and `checks.py`. Publish those first and record the resulting
full Git commit SHA. Then run:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m tools.hcsn.reachable_state_r16_20261101.control.campaign train --source-commit SOURCE_COMMIT --output tools/hcsn/reachable_state_r16_20261101/control/run_01/TRAINING.json
```

Publish the training manifest and all eight referenced compressed training
artifacts. They contain every selection and all frozen policy tables. Only
after that commit exists, create its receipt and run confirmation:

```sh
python3 -m tools.hcsn.reachable_state_r16_20261101.control.campaign freeze --selection-commit SELECTION_COMMIT --training tools/hcsn/reachable_state_r16_20261101/control/run_01/TRAINING.json --output tools/hcsn/reachable_state_r16_20261101/control/run_01/PUBLICATION.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m tools.hcsn.reachable_state_r16_20261101.control.campaign confirm --training tools/hcsn/reachable_state_r16_20261101/control/run_01/TRAINING.json --receipt tools/hcsn/reachable_state_r16_20261101/control/run_01/PUBLICATION.json --output tools/hcsn/reachable_state_r16_20261101/control/run_01/CONFIRMATION.json
```

The caller must use real published commit identities; a correctly formatted
string is not evidence of publication. The parent workflow verifies the GitHub
objects. The runner additionally checks local source and training hashes before
accessing confirmation randomness. Each fit/domain archive preserves complete
owner execution traces, returns and action counts for all arms. It verifies
that the ordinary same-Q DP and the other DP have identical full traces.

All reported resource quantities are CPU seconds from these processes.
Research totals include common preparation once; an independent deployment
must charge its own preparation and selection. Encoded arrays, synthetic
reward units, CPU seconds, energy, and network cost remain different quantities.
This experiment provides no production activation or continuous optimality
certificate.
