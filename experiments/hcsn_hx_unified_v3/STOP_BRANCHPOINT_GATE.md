# HCSN P0 scalar renewal: Lambert-W branch-point guard

**Research-only / DENY_ALL / all_blockers_closed=false.** This is a narrow
numerical correction to the scalar `Stop` oracle on top of HCSN draft #4377
(`166ee63c563d2df065c279ba312d0bcbc539cbce`). It does not modify financial
He–Xiong equations, experimental results, neural training, native Rust/GPU,
authority, checkpoints, or production deployment.

## Negative evidence reproduced on original exact-source blob

Git blob `d165ed777990bbf8f3606b58e1b0991de59a1544` has
`a=exp(-rho*tau)*exp(-kappa*(cost-reset))` followed by `0<=a<1`.
For `Stop(drift=0,diffusion=1,discount=.1,cost=0,reset=-1e-16,refractory=0)`,
`a` rounds to **1.0** even though exact `h=kappa*1e-16>0`. The old reference
raises `ValueError('Regenerative threshold violates proper-cycle domain')`.
The same false refusal occurs at reset losses 1e-20, 1e-40, 1e-100 and 1e-200.
This is a counterexample to all-representable-parameter admissibility, not an
example of invalid discounting or an optimization benefit.

## Mathematical repair and bounded evidence

For `h=rho*tau+kappa*(cost-reset)>0` and `t=kappa*(boundary-cost)`, the
smooth-fit equation is equivalently `h=-log(1-t)-t`, `0<t<1`. At the
Lambert-W branch point its strictly positive series starts with
`t^2/2+t^3/3+...`; eight safeguarded Newton steps invert this series for
`h<=1e-4`. The original Lambert-W formula remains for larger `h`.
Unresolved exponent products, nonfinite scales and nonrepresentable positive
boundary rewards are explicitly refused; valid but unresolvable extremes
are NOT asserted to be solved.

Executed locally using source bytes that match GitHub blobs:

```
python -m unittest -v experiments.hcsn_hx_unified_v3.test_stop_branchpoint
# 7 tests PASS, 0 skipped; Python/SciPy scalar CPU reference.
```

Independent `decimal.Decimal` root at precision 320 checks actual binary64
input values and a separate exponential smooth-fit residual. Frozen failing
cases, 96 seeded log-loss cases, the analytic/numeric solver transition,
monotonicity, four original QVI/reference parameter regimes and arithmetic
refusals pass. An additional 240-case exploratory Decimal panel found max
relative boundary error **2.1546e-15** in its sampled region; the panel is
exploration, not pre-registered proof. Original upstream `stopping.py` source
was first materialized locally byte-for-byte and checked against its Git blob.

## Still open

All-domain HX coupled obstacle/fixed point, interval/rounding certificate,
full model gradient certification, P1 mechanism gain (historically 0/4),
P2 memory superiority, P3 genuinely paired multimodal, P4 native Rust/GPU
64–4096 Cell/energy/recovery, and P5 net-compute backbone superiority.
No CI result or full original repository checkout is claimed for this change.
