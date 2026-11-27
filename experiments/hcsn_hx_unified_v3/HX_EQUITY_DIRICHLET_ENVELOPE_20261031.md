# P0 fixed-HX-barrier equity far-field envelope (2026-10-31)

Status: RESEARCH_ONLY / DENY_ALL / NO_GO. Stacked on #4512 exact parent `99fa3ad1f75eb021fc95fd2b6cd5dbda37898e2c`. Neither source nor historical result from #4512/#4511/#4508 is edited.

## Independent bound and limits

At a *fixed* financial absorbing default barrier b, discount r>0 and payout delta>0, representative HX debt value B(A) lies in [m,M] where `m=min(coupon/(Tq),principal/T,recovery*b/T)` and M is the corresponding maximum, `q=r+shock_intensity*sale_fraction`. This follows from the nonnegative mixture of discounted coupon annuity, nondefault principal and first-hit recovery. `C=(1-tax_shield)*coupon+principal/T`.

The killed-GBM ex-dividend stock plus accrued dividend is a discounted martingale. For a fixed barrier and zero equity exercise payoff, comparison with the feasible hold-until-default policy gives
`max(0,A-b-max(C-m,0)/r) <= V_opt(A) <= A+max(M-C,0)/r`.
This is deliberately loose; it is not a global free-default-barrier existence or self-consistency theorem.

`hx_equity_dirichlet_envelope.py` computes rational finite-Taylor lower/upper bounds on `b*exp(log_upper)`, using the exact binary64 values of user-supplied finite inputs. **Lower rational bounds are rounded downward and upper bounds upward** to 12 decimal places; using upward rounding for lower values would invalidate an enclosure. The absolute difference against a user-supplied nominal Dirichlet value is rounded upward and can be passed only as an **equity boundary uncertainty component** to #4508. Debt spatial/time/roundoff components remain missing.

Run:
```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_equity_dirichlet_envelope
```

Five focused checks cover outward decimal rounding, Taylor bracket behavior, three bounded regimes, invalid financial inputs, and refusal to promote this to complete HX certification. These newly committed files have **not** been executed against a full repository checkout in this turn; no verified remote CI or empirical PASS is claimed. A related locally constructed prototype (different module bytes) passed five tests before submission; do not confuse it with the exact GitHub files.

## Open scientific gates

P0 still requires self-consistent financial default-barrier fixed point, globally admissible obstacle under the original financial debt coupling, certified full source/mesh/time/rounding enclosures and financial FP32/BF16/active-set gradients. P1 controlled causal Call/Risk/Margin attribution; P2 long memory/host recovery; P3 genuine paired four-modal; P4 actual Rust/GPU/4096 Cell and measured Joules; P5 equal compute quality/cost advantage. No gate is marked closed; `production_activation=false` and `all_scientific_blockers_closed=false`.
