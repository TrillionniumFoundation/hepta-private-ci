# HCSN P0 — HX bond coupon non-unity small-discount cancellation

Status: DRAFT / RESEARCH ONLY / DENY_ALL. all_blockers_closed=false; production_activation_allowed=false.

## Immutable dependency and scope

Parent: draft PR #4462 HEAD 4a8d353be565eb20211252375603a88a51f6c934.
Only offline experiments/hcsn_hx_unified_v3/hx.py, one new unittest and this record are changed.
No production training, Rust/GPU owner, authority, deployment, CI policy or finance transaction code is modified.

## Counterexample and cause

Rate q=1e-16, hazard=0, T=1, maturity=2, principal=60, coupon=4,
asset=1e100, fixed default barrier=1. The calculated first-hit factors are F=G=0.
exp(-qT)=0.9999999999999999 (not 1). The inherited #4462 formula yields
36.0 for the bond while the independent no-first-hit principal-plus-coupon
cashflow is about 32.0. The original exact unity-rounding guard never runs.
Other positive qT and coupon choices show the same subtraction catastrophe.

## Narrow intervention

For a positive coupon with qT < 2**-26, calculate no-hit cashflows using
loss=-expm1(-qT); discounted principal=P0-P0*loss and annuity
=T*loss/(qT), with T as the underflowed zero-product limit.
Use math.fsum for the final three cashflow terms.
Reject (ArithmeticError) if F or G is nonzero, because the stopped coupon
requires the difference F-G to be resolved and division by tiny q can
amplify separate f64 first-passage errors. No silent clamping.
Outside this band the prior expression is unchanged, and the zero-coupon path
is identical. The cutoff is a conservative heuristic, not certified rounding.

## Executed tests / evidence levels

- Focused parent-vs-patch reproduction, including independent 100-dps mpmath
  no-hit cashflow and 1,500 seeded cases: 7/7 methods PASS, zero skipped.
- Seven source-importing tests with a locally reconstructed subset of #4462
  HX, first-passage and bond functions: 7/7 PASS, zero skipped, including
  240 independent 110-digit Decimal no-hit probes.
- Same source-subset tests against unchanged parent coupon branch: exit 1,
  149 failed assertions/subtests (including the q=1e-16 36-vs-32 witness).
- This local subset is NOT a full exact-repository checkout; the submitted
  regression has not been executed against all exact upstream files or CI
  in this session. No complete GitHub Actions success is claimed.

## Reproduction with a complete checkout

    python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_bond_small_q_nonunity
    python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_bond_coupon_unity
    python -m unittest -v experiments.hcsn_hx_unified_v3.test_oracles

## All remaining blockers

P0 coupled HX self-consistent obstacle/fixed point, certified error and tails,
gradients/low precision; P1 causal benefit of Call/Risk/Margin with matched
ordinary gates; P2 repeated events and long memory; P3 real four-modal
paired quality and OOD; P4 native GPU/Rust 64–4096 Cell power, tail latency,
recovery; P5 quality-conditioned GPU-hour and end-to-end cost superiority.
Refusals are not successful calculations, and existing negative evidence
is unchanged. Do not merge this draft for production activation.
