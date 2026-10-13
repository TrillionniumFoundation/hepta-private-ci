# Exact information budget for transferable finite rules

Base: `d4304b2a43c7d016db8c3b08d279951c15acd156`, Draft PR #1550.
Preserve the parallel roundoff fix and counterfactual transfer. This adds
`budgeted_rule_identification_v1` to the existing study entry. The old two-reset
profile, its objective, all neural models, Riccati kernels, owners and formal
qualification gates are untouched. This is finite experimental design, not a
new learned language model or a production action authority.

## Change the objective explicitly, not the meaning of success

The previous experiment maximizes the fraction of six states on which the
remaining candidate rules agree. Here the primary objective is identification
of the COMPLETE transition table, then minimum expected number of source calls.
Both objectives are useful but different. A policy may stop when its remaining
budget cannot identify a complete table, even though additional observations
could improve partial state agreement. Report both, not just the favorable one.

For equally probable surviving programs S and b remaining resets, store integers
N(S,b), the number of possible source programs eventually identified, and Q(S,b),
the sum of source calls over those programs. At complete behavioral agreement,
(N,Q)=(|S|,0); unresolved stopping gives (0,0). For query x with nonempty outcome
partitions S_o, an action yields:

    N_x = sum_o N(S_o,b-1)
    Q_x = |S| + sum_o Q(S_o,b-1).

Choose maximal N, then minimal Q, then the lowest query index. Every available
initial state and every nonempty result is enumerated. Integer sums avoid
roundoff-dependent policy ties; an independent bit-mask/Fraction implementation
checks all compiled states. Backward induction establishes the exact optimum
under this PRIOR and this observation interface. Randomization cannot improve a
linear prior objective over these deterministic conditional actions.

Compilation uses no private source rule, test outcome or external labels. The
readonly policy is keyed by the complete prior-table hash and declared budget;
its nodes carry both support and remaining allowance. Each real source call still
binds environment, scope, generation, selected state, full history and sequence.
Budget does not reset on a posterior update. Call failures retain their attempts
and do not return an action. Normal Python immutability is not hostile-process
attestation. Runtime decision ceiling stays at 100ms process CPU. Exact offline
compilation has a SEPARATE measured 15s/20k-node ceiling, not free inference.

## Exact frontier, not a larger budget disguised as the old experiment

Use the SAME 33 rules and SAME six controlled reset states. Budgets 0..6 are
SEPARATE experiment settings. There are no inherited free observations. Each of
33 private simulator rules is executed once per setting/strategy; the uniform
finite inventory is not a sample of independent human sources.

The exact optimal complete-identification counts are:

| Reset cap | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Identified out of 33 | 0 | 2 | 5 | 20 | 29 | 33 | 33 |

Thus at least five resets are needed in the worst case, and the compiled policy
achieves that bound. The optimal mean at full identification is 112/33 calls.
This is NOT a lower bound on richer measurements, other rule families, neural
reasoning or arbitrary control. The hidden source must really be a stationary
member of the declared family and the observations must be correct.

Compare the old greedy coverage rule, first-informative probing and the best
prior-selected fixed order, all at the SAME budget. At cap 3, optimal and cheap
first-informative both identify 20 rules, using 82 and 95 calls respectively;
best fixed and greedy each identify 14 with 92 calls. At cap 5, both optimal and
cheap first-informative identify every rule using 112 calls; fixed and greedy use
115. Hence the exact planner does NOT dominate the inexpensive baseline.

All identified tables use the parent's export/restore/apply implementation.
They are applied to all 36 name-order/state pairs; normalized states not queried
are counted separately. These are finite in-family transfers, not new authors,
new environments or authenticated semantic generalization. A time-dependent or
changed environment can match every observed effect and fail later; hashes and
finite agreement cannot rule that out.

## Execution and costs

One complete experiment is 33 rules x 7 caps x 4 controls = 924 records and
2,076 actual source calls. Compilation, fixed-order search, each arm's model
construction, own selected resets, record handling, export/application and audit
are separately visible. Comparison tables use real calls only, never imagined
future amortization. Per-arm standalone deployment attribution is incomplete;
source-call counts are not CPU or energy prices. No neural training/Encoder runs.

    python fbsde_study.py --profile budgeted_rule_identification_v1 --output /new/identification
    python fbsde_identification_artifact_checks.py -v /new/identification

The added read-only head/merge workflow is an execution lane, not a second formal
reviewer. Other workflows remain intact. Source tests, original artifact mutation
checks and final-head CI are distinct; a matching checksum or mathematical bound
does not grant production promotion. See delivered logs for actual execution.
