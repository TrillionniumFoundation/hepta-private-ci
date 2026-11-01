# Common finite-horizon controller

`controller.py` provides NumPy `plan` and `plan_mc`, returning a tuple-compatible
`PlanResult(action, value, qvalues)`. `qvalues` has four columns: answer 0,
answer 1, wait, read. Disallowed actions have value negative infinity; ties use
the lowest action index. The input is a batch of causal beliefs and one fixed
model. The API has no future-observation or hidden-state argument.

## Contract

* ANSWER immediately terminates with `belief @ answer_rewards`.
* WAIT propagates once by the supplied `P`, pays `time_cost * dt`, and recurses.
* READ propagates once, pays `(belief @ P) @ read_cost` and the same time cost,
  then sums the seven conditional continuation values with their evidence weights.
* `horizon=1` allows only answers. A zero read budget permits answers and wait.
* `P` already represents the chosen interval `dt`; the controller does not rebuild
  or reinterpret the generator. The same interval is used at subsequent nodes.
* Zero-evidence branches are skipped. Positive evidence is divided directly, with
  no floor. Inputs must be finite, nonnegative probability rows with unit sums to
  floating-point tolerance. No continuous-belief hashing or value cache is used.

`plan_mc` samples the **root READ observation marginal**, with the identical
transition, emission, rewards, expected costs, and exact conditional continuation.
Its root READ action-value estimator is unbiased in exact arithmetic. Its selected
maximum need not be unbiased. It does not recursively replace downstream values
with Monte Carlo maxima; therefore the comparison isolates one marginalization
step. Replanning with this controller does not make its exact-continuation Q the
value of the resulting noisy policy. Sampling timing includes sampled branches.

## Independent verification

Run:

```sh
/tmp/hepta-r12-venv/bin/python tools/hcsn/unified_cell_r12_20261031/control/test_controller.py
```

The independent checker enumerates every contingent policy's state-wise payoff
vector in a two-state fixture. It does not use the implementation's Bayesian
recursion. Nine combinations of horizons 1--3 and budgets 0--2 are checked at 17
beliefs each. The largest case enumerates 74 policies: two immediate answers,
eight wait-continuations, and 64 read-contingencies. Maximum action-value error
was `2.220446049250313e-16`; all selected actions matched.

Edge checks cover impossible observation branches, rare evidence approximately
`2e-12`, state-dependent costs after prediction, invalid belief rejection, empty
batches, and deterministic observations with identical exact/MC values. The rare
branch uses large finite rewards to ensure its contribution cannot be discarded
as numerically irrelevant.

## Fixed-belief sampling illustration

The checker fixes 13 beliefs in the same two-state model, uses 32 samples for
each root READ, and repeats 64 times with seed `20261031`. These are constructed
mechanism examples, not training, validation, or confirmation task data.

| Diagnostic | Observed value |
|---|---:|
| Exact and sampled action disagreement | 0.17427884615384615 |
| Pairwise action-rank disagreement | 0.04467147435897436 |
| Mean exact-model loss of sampled action | 0.0018903016676682638 |
| Maximum exact-model loss of sampled action | 0.04318449999999996 |

`raw.json` contains all fixed beliefs, exact Q values, sampled actions, sampled
READ values, per-belief variance and mean errors, and source hashes. With only
seven observation categories, exact marginalization is a small finite sum; this
illustration does not establish a computational or neural-architecture advantage
on larger observation spaces or a learned task.
