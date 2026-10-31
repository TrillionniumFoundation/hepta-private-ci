# P0: killed-occupation financial equity far-field enclosure (2026-10-31)

**Strict scope: RESEARCH_ONLY / DENY_ALL / NO_GO.** Stacked on Draft #4514 exact parent HEAD \`0d4d948cdd7c9f9ce83971659d29d764435cfa61\`. This increment adds new files only under \`experiments/hcsn_hx_unified_v3\`; it does not change the original He–Xiong (HX) Eq.(8)/(12)/(A7), the previous fixed-grid/PDE code, negative evidence, authority, native execution, CI or GPU paths. The parent #4514 fixed-barrier upper Dirichlet envelope remains intact for direct comparison.

## Improvement: not merely a pointwise fit

For a *fixed positive absorbing financial barrier* \`b\`, the HX stockholder continuation problem has log-asset \`Y=log(A/b)\`, killed at zero, and cashflow \`delta*A+B(A;b,T)-C\` where \`C=(1-tax)*coupon+principal/T\`. With \`q=r+shock_intensity*sale_fraction\`, \`c=coupon/T\`, \`par=principal/T\`, \`rec=recovery*b/T\`:

\`\`\`text
B_inf = c/q + exp(-q*T)*(par-c/q)
D     = exp(-q*T)*abs(par-c/q)+abs(rec-c/q)
abs(B(b*exp(y);b,T)-B_inf) <= D * F_T(y)
F_T(y) <= exp(-max(y-abs(mu)*T,0)^2/(2*sigma^2*T))
mu = r - delta - sigma^2/2
\`\`\`

The first inequality uses the coupon/default/terminal **bond payoff decomposition**, not the code under test. The second bound follows from comparing lower Brownian first passage to the maximum of a driftless Brownian path and an exponential-martingale estimate. Neither invokes the financial pricing Eq.(8), free-boundary Eq.(12), equity Eq.(A7), or a numerical PDE solver.

For rational log cutoffs \`0=u0<...<un=U<L\`, form decreasing certified upper bounds \`fj >= F_T(uj)\`. Then the staircase upper bound of \`F_T(Y_t)\` gives, for **every stopping time before financial default**:

\`\`\`text
E[ integral_0^tau exp(-rt)*abs(B(A_t)-B_inf) dt ]
 <= D * [ fn/r + sum_j (fj-f(j+1))*J(L,u(j+1)) ]
\`\`\`

where \`J\` is discounted occupation of \`Y<=u\` before absorption. For \`a=mu/sigma^2\`, \`z=sqrt(a^2+2r/sigma^2)\`, \`gamma=a+z\`, \`eta=z-a\`, the *independent* killed-Brownian Green integral supplies:

\`\`\`text
J(L,u) =
 [ exp(-gamma*(L-u))*(1-exp(-gamma*u))/gamma
   -exp(-gamma*L)*(1-exp(-eta*u))/eta ] / (sigma^2*z).
\`\`\`

The first term is rounded **up**, the second term rounded **down** before subtraction, and the square-root coefficients are bracketed with integer \`isqrt\`; all exponential bounds use positive Taylor/geometric rational remainders. This is a mathematically conservative real-number envelope for the declared fixed-parameter stochastic model, not a floating-point simulation tolerance.

For constant \`B_inf\`, the stockholder cashflow expectation is \`A+d-E[e^-rτ(Aτ+d)]\`, \`d=(B_inf-C)/r\`. A feasible hold-to-default policy gives the lower enclosure. To bound the optional-stop premium, the function \`C_put*b/A\` dominates \`(K-A)^+\` for all \`A>=b\`, \`K=max(0,-d_lower)\`, and is an \`r\`-super-solution when **\`delta+sigma^2<=2r\`**. Unsupported inputs, zero payout, failed root brackets, unrepresentable exponent bounds and insufficient work budgets explicitly refuse. No automatic acceptance outside this conditional domain.

## Actually executed local test evidence

Run from repository root with SciPy, NumPy, mpmath:

\`\`\`sh
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_hx_equity_upper_envelope \
  experiments.hcsn_hx_unified_v3.test_hx_occupation_bound
\`\`\`

**10/10 focused test methods PASS, zero skipped** on local Python 3.13.5: five unchanged parent tests and five new methods. New tests cover 400-digit mpmath exponential checks, exact-square-root brackets, nine independent killed-Green/first-hit point comparisons, the financial held-policy witness inside the envelope, 8/16/32-step budget monotonicity and invalid-domain/unsafe-put refusal. Tests were performed with an **exact parent \`hx_equity_upper_envelope.py\` Git blob** (\`69a73f2db466993df3cba0512cf1c9dffa307119\`) and a locally reconstructed HX reference subset. The reconstructed \`hx.py\` is **not** byte-identical to upstream, so **no full checkout/whole-repo CI or independently reviewed proof claim** is made.

Fixed \`L=3.6\`, 32 staircase segments, cutoff \`1.5\` (exactly interpreted from binary64):

| Financial sale_fraction | Parent #4514 error upper | New error upper | Occupation component upper | Optional-stop premium upper |
|---|---:|---:|---:|---:|
| 0.015 | 278.220790742521 | **1.640608880050** | 1.111828090031 | 0 |
| 0.2 | 370.901575840771 | **4.255687461278** | 3.295784212750 | 3.663960206662 |

The new error budgets are **~169.6x / ~87.2x tighter** than the existing conservative fixed-barrier envelope. These ratios measure bound tightening, **not** improved forecast accuracy, model superiority, or certificate coverage. The upper bound remains too loose to guarantee that every interior finite-grid STOP/CONTINUE decision has the right sign; no all-state financial obstacle certificate is asserted.

The immutable two-case JSON is \`HX_OCCUPATION_BOUND_SMOKE_20261031.json\`, SHA-256 \`88c1ff8ed82c5405936208879c38d7dfefa37479006143d9a45d5b21e1cc955b\`. The complete local source/test code was verified against fetched exact remote Git blobs after upload. A first exploratory test failed because 140-digit mpmath could not resolve a sub-140-digit Taylor enclosure; the test reference was raised to **400 digits before publication**, without changing the inequality or selecting away any physical-model failure.

## Explicit remaining blockers

P0 remains **OPEN**: genuine endogenous self-consistent HX default/liquidity equilibrium and globally admissible obstacle; certified financial bond **interior** PDE/time and rounding error, cross-mesh and degenerate extremes; active-set financial FP32/BF16/GPU gradients. The new envelope bounds **only the fixed-barrier far-field continuum equity endpoint**, one input to an overall P0 error budget.

P1 **OPEN**: pilot eight-arm result is negative or non-significant; need same-information, same-slope, same-parameter, same **measured full-cost**, preregistered held-out causal benefit. P2 **OPEN**: trained physical-time FIRE Copy/MQAR/overwrite OOD and real host interruption/recovery; existing negatives persist. P3 four actual modalities, P4 native GPU/Rust 64/256/1024/4096 and Joules, P5 equal-budget Hybrid scaling remain **OPEN/BLOCKED**.

\`complete_debt_error_budget=false\`, \`global_equilibrium_certified=false\`, \`scientific_gate_closed=false\`, \`production_activation=false\`. This research increment must remain Draft and unmerged until full independent review.
