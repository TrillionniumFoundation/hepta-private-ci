# Independent HX far-field bond budget (P0, research only)

Status: `DENY_ALL / NO_GO`. Based on exact parent draft #4508 commit `be5299fb4c5ae5feaa421d7f49f1ac2402c4fbbd`.

This additive module provides a finite-horizon, model-derived *bond* error budget, not a certified global obstacle or equity-boundary error enclosure.

For log asset distance `v=log(A/b)>0`, log-asset drift `mu=r-payout-sigma^2/2`, and maturity `T>0`, Brownian reflection and pathwise drift comparison imply

`P(hit by T) <= min(1, erfc(max(0,v-|mu|T)/(sigma sqrt(2T))))`.

For `v<=|mu|T`, the bound is exactly 1; the implementation does not extrapolate a small-tail formula there.

The no-default representative bond is `B_nd=c/q+exp(-qT)*(P-c/q)`, where `P=principal/T`, `c=coupon/T`, `q=rate+shock_intensity*sale_fraction`. This **includes the surviving maturity principal**, which was omitted in the historical #4496 far-tail implementation and corrected in #4498.

The independent first-hit decomposition gives

`|B-B_nd| <= [exp(-qT)*|P-c/q|+|recovery*b/T-c/q|]*P(hit by T)`.

The result reports `hit_probability_envelope`, `bond_error_budget`, and an explicitly unavailable `equity_upper_error_budget=None`. It DOES NOT provide the equity upper Dirichlet error `u` required by #4508's conditional finite-grid certificate. It cannot automatically be inserted into that certificate. The `erfc` and products are binary64 operations without outward rounding, so this is a **mathematical bound evaluated approximately**, not a machine-verified enclosure.

Reproduce:
```
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_far_field_bond_budget
```
Three submitted test methods include 40 parameter/asset comparisons, shrinking far-tail budget, retained unavailable equity-bound flag, and invalid-domain refusal. **These newly submitted tests have not been executed in a full checkout in this turn**; do not mark them PASS without actually running them.

Strict blocker status: P0 whole-domain coupled financial QVI, independently certified real debt/upper-equity errors, active-set gradients, and FP32/BF16 remain OPEN. P1, P2, P3, P4 remain OPEN; P5 BLOCKED. No previous evidence was edited. `production_activation=false` and `all_scientific_blockers_closed=false`.
