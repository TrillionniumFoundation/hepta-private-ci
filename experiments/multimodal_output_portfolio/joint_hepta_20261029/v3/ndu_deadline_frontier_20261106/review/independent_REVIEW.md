# Independent internal review of the deadline frontier reference

This review did not change the implementation under review. Source hashes and
all deterministic assertions are retained in `review_result.json`; `review.py`
is the separate replayable checker. The source was unchanged during that run.

## Main result

No counterexample was found to the shared-policy sequence LP, the rational
Lagrangian lower bound, or the rational executable-policy upper bound under the
fixed rational contracts exercised. The LP is not accepted merely because HiGHS
reports success: independent pure-policy enumeration agrees with the proposed
risk frontier and with every tested exact Lagrangian value. This is an internal
check, not external review or a proof of a general learning result.

## Two issues to fix or delimit before publishing

1. **`binary_deadline.minimax` does not enforce its rational-probability input
   contract.** `minimax(0, p0=.57, p1=.87)` returns float-valued risk and lower
   bound from an API labeled exact. The same float inputs at n=1 and n=2 raise
   late ArithmeticErrors about risk equality/certification. Explicitly require
   Fraction probabilities (as `Contract` does for prices), or explicitly convert
   them and document the exact converted law. Fixed default Fraction calls are
   unaffected.
2. **The `catalog` family's generic default price is not the inherited fully
   paid catalog price.** `Contract(3, family='catalog')` charges each launched
   macro `1/40+3/100=11/200`, although the inherited catalog macro costs `3/10`.
   If this branch is described as the old fully paid macro, use
   `fee=27/100,time_price=1/100`, or give it an explicit factory/validation rule.
   A different tariff is mathematically valid if declared as a different
   contract. The independently exercised paid catalog cases used the correct
   `.27` non-time fee and `.03` time charge.

## Rounding recovery checked

An early source snapshot reported a raw behavioral policy plus a separate
root STOP-mixture factor. The current reviewed source embeds that mixture into
its root probabilities and reevaluates it exactly. This issue is resolved in
its current source. The checker deliberately exercised
`Contract(2,max_probes=2,family='gated')`, budget `1/100000007`; its mixture factor
was `200900028063000971/200900028063000980 < 1`. Exact evaluation of the actual
returned policy matches the reported errors, resources and unit terminal mass.

## Exact-policy and lower-bound reasoning

The sequence variable is the product of the controller's behavioral
probabilities along one observation/action history, excluding chance factors.
Its value therefore must be shared across hypotheses; the single flow system
implements precisely this. Chance products appear only in conditional-hypothesis
loss and cost coefficients. Every child observation's outgoing controller flow
sums to its parent-action flow. There are no hypothesis-specific action variables.

For fixed nonnegative lambda with sum one and nonnegative resource multipliers
mu, the backward rational dynamic program minimizes
`lambda_0 error_0 + lambda_1 error_1 + mu_0 cost_0 + mu_1 cost_1` over common
history policies. Subtracting `B*(mu_0+mu_1)` is a lower bound on minimax error
when **each** conditional-hypothesis expected resource is at most B. This is a
worst-hypothesis expected-budget contract; it should not be called merely a
prior-average budget. Truncating the resulting lower bound at zero is valid.
Rationalizing arbitrary solver multipliers cannot invalidate this inequality,
though it may enlarge the gap.

Both source methods enforce compulsory binary decisions, with no abstention
option. With no observations, one shared randomized decision has minimax risk
exactly one half. A clairvoyant per-hypothesis action selector would incorrectly
return zero; the reviewed LP does not have that leak.

## Censoring and cost checks

The checker independently rebuilt observable events from the raw joint
label-duration laws. Every late result collapses to one `(timeout,cap,state)`
event, without its eventual label or duration. These laws match the contract
for all 3 probe types and caps 1 through 4. A forced slow probe under a cap of one
unit is uninformative, yields errors `(1/2,1/2)`, and pays `(7/200,7/200)` in
conditional expected resource. Launch fees and actual consumed time are paid
once even on that timeout. No duplicate charging was found.

## Independent checks performed

The checker independently enumerates attainable pure-policy error/cost vectors,
then takes their convex hull, avoiding the implementation's sequence variables,
LP coefficients, history masses and lower-bound recursion. It covers ten
contracts: no-data, one/two-step Bernoulli, insufficient/sufficient gated
preparation, one-probe joint-clock contracts, and one/two paid catalog macros.
For each it tests five budgets. The largest float LP discrepancy against the
independent pure-policy hull is `5.551115123125783e-17`.

For each contract and budget it compares exact Lagrangian values with pure-policy
minimization at five rational priors and four resource-multiplier pairs. Every
comparison is exact Fraction equality. Binary full-string enumeration for
n=0 through 8 checks pathwise equality to the randomized full-sample decision
and exact expected sample counts. In total the retained run has **2,745
deterministic assertions**, all passed; these are not 2,745 independent
scientific replications.

## Binary stopping limits

The Neyman-Pearson equal-error threshold and least-favorable-prior certificate
are correct for the declared iid Bernoulli two-member catalog. A full n-sample
experiment can simulate any policy observing at most n iid macro outcomes by
ignoring unused suffix observations, so its exact minimax risk is also a lower
bound for all such stopping policies. The early rule is pathwise equivalent
when coupled to the same final random tie coin.

This does **not** make the early rule expected-cost optimal. For example, at
n=1 and p0=.57,p1=.87 the full-sample minimax rule can be implemented by deciding
0 immediately with probability `11/36`, and otherwise taking a single macro and
following its observation. It attains the same risk `19/48` with expected macro
count `25/36`, whereas the current early wrapper always takes one macro. The
source already says that it makes no optimal-cost claim. Retain that restriction
and include the exact frontier as the stronger control in any cost comparison.
