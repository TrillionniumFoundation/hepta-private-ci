# Actor-aware one-step rollout repair

This separate candidate repairs a concrete mismatch: the ordinary actor's
continuation includes its recurrent hidden state, while the original common
planner forecasts Bayesian-optimal continuations. The repaired selector scores
each legal first action using the actual frozen actor's **original value-policy
tail** under the actor's own current belief and the shared fitted world.
Both ordinary and HX actors receive exactly the same repair rule.

In actual deployment the new rule is recomputed after every observed action.
Its base-tail scores are therefore **not** Qpi of the new receding policy, and
local fitted-world score improvement is not a guarantee of true-world improvement.
The actual six-arm experiment retains A/B/C/D and adds B_prime/D_prime. It uses
fresh independently indexed tapes with fixed new seeds and no model refitting.

A separately reported secondary enumerates all27 public clock schedules per
domain. Its evaluator propagates true-world mass, copies complete actor hidden
state and calls the *actual selector again at every future branch*, including the
repair. Its expectations are of the real receding policy. True-world information
never enters the selector. This certificate is only for the finite three-step
synthetic task, not a continuous process or natural-media workload.

Each actual arm runs in its own fresh serial process. wait4 receipts include
startup/imports, identity verification, setup, full actor/owner execution,
diagnostics, serialized evidence and exit. Episode and component times are
nested measurements. The16 complete-clock workers are charged separately from
those96 measured rollout workers. Historical fitting cost is retained once;
there is no new fit and no measured device energy.

From repository root, with NumPy and SciPy available:

```bash
python experiments/hcsn_validation_r14_20261101/value/publication/pack.py restore
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m experiments.hcsn_validation_r14_20261101.value.rollout_repair.tests -v
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B -m experiments.hcsn_validation_r14_20261101.value.rollout_repair.run run --out experiments/hcsn_validation_r14_20261101/value/rollout_repair/evidence/reproduction_02
```

Use a new output path. Existing source and result freezes must not be replaced.
The original value audit and its negative/near-zero findings stay unchanged.


The final independent result audit is
`review/INDEPENDENT_RESULTS_AUDIT_01.json`: 162,036 checks passed, no failures.
It independently reconstructs every actual episode's environment and charges,
then aggregates every stored full-clock row. It does not independently re-run
the full expectation recursion. The reviewer process receipt is separate from
actor/worker timing. Both final results and limitations are in `RESULTS_ZH.md`.
