# Decision-cost bounds after the negative NDU reference

This unit narrows the information-cost question to a finite known catalog with
an unknown true member, unique decision answers and fully paid regenerative
calibration. It preserves the prior 144-cell failure and does not claim new RL
originality, external scientific review, real-model gains or unrestricted
unknown-kernel learning.

## What is established internally

The [theory](DECISION_COST_THEORY.md) gives:

1. A cost/KL allocation LP containing only alternatives with a different correct
   decision; the lower bound is `kl(1-delta,delta) * C*(theta)`.
2. An explicit pilot/main/fallback sequential construction whose expected cost
   divided by `log(1/delta)` tends to `C*(theta)` for every fixed catalog member.
   All candidate laws are supplied, regeneration is paid, and the guarantee is
   asymptotic and pointwise. This is a restricted classical testing construction.
3. A time-expanded state-flow lower bound, including preparation/reset charges
   and a counterexample to treating its KL feasibility as a deadline guarantee.
4. A strict separation between full-model and decision identification when a
   nuisance parameter changes observations but not the correct action.
5. Necessary amortization and STOP-optimal-member impossibility bounds. A low
   information cost alone does not imply positive economic net benefit.

In the explicit gating example, external terminal reward is correctness and
does not depend on state. The two accuracy members are `.57` and `.87`; the
deployment threshold is `.72`. STOP is optimal at `.57`; its forced-deployment
value `.35` is not the optimum. The positive member's deploy value is `.65`.
Calibration pays reset, labels, preparation, probing and declared time: `.30`
resource units per complete macro, under synthetic prices.

At error target `.05`, the positive member's analytic necessary deployment
volume threshold is about `24.9561`, and a sufficient threshold is about
`41.5553`. Integer `M<=24` is impossible and `M>=42` suffices within the idealized
contract. These statements apply equally to the classical likelihood test;
they do not amend the failed `M=1000` endpoint of the different previous study.

## Reproduction and acceptance

```bash
python verify_decision_cost.py --output /tmp/ndu-decision-cost-new.json
```

The [accepted receipt](decision_cost_verification.json) records **45 deterministic
checks**, exact rational prefix/Bayes computations and floating-point LP
primal/dual comparisons. Sources are hashed before and after. The verifier is
not a simulation of the construction's asymptotic efficiency or a confirmation
dataset. It retains unresolved finite-prefix mass instead of treating it as
correct. The 13-probe full-sample Bayes error is exactly
`98486781024154212843089/1000000000000000000000000`, approximately `.09848678`:
the KL necessary condition passes, but uniform `.05` correctness is impossible.

The main proof was independently read by the parent and mechanism agents in
this session. Review refinements made the controlled-Markov/time indexing,
same-answer zero-acquisition case, abstention errors and deployment-value labels
explicit. This is internal review, not an external proof reconstruction.

The [primary-neighbor section](DECISION_COST_THEORY.md#7-primary-neighbors-and-unresolved-claims)
includes 2015 controlled sensing, 2019 answer-aware pure exploration and the
June 2026 ENDS preprint. The report states the remaining novelty and access gaps.
