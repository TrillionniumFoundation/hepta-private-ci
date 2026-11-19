# P0 HX bond coupon unity-rounding guard (research only)

**DRAFT · DENY_ALL · all_blockers_closed=false · production_activation_allowed=false.**

## Immutable parent and actual scope

Parent: [HCSN P0 PR #4459](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4459), exact head `78519b7fe1d85000bb13a739fb70f45bba70e18c`. Inherited `hx.py` Git blob `f7443b1e5c7e769f331999bd8666516d557237c9`.

- Modified **only** `experiments/hcsn_hx_unified_v3/hx.py` in the offline financial reference (post-patch Git blob `db95f91e5f78ea1033026d9a399daf63860a97e1`).
- Added `test_hx_bond_coupon_unity.py` (Git blob `0b32f1e59d5251d9c2b2635fed02df962052aef0`).
- No changes to main, production Rust, authorization, permissions, GPU, training, model weights or CI workflows.

## Reproduced exact-expression failure

The inherited public `bond_value` uses the paper's algebraically correct finite-maturity form

`d = c/q + exp(-q*T)*(P-c/q)*(1-F) + (R-c/q)*G`.

Here `c=coupon/maturity`, `P=principal/maturity`, `R=recovery*boundary/maturity`, `q=rate+hazard>0`, and `0<=G<=F<=1`. If `exp(-q*T)` rounds to **exactly 1** at tiny positive q, subtracting large `c/q` terms can destroy the result.

Reproduced on local Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, using the inspected source's HX scalar first-passage and bond expressions, not a full checkout:

| Declared inputs (boundary = 1, maturity = 2, principal = 60, coupon = 4, hazard = 0) | Inherited expression | Valid reference / expected behavior |
| --- | ---: | --- |
| `rate=1e-20, asset=1e100, T=1`; `F=G=0` in f64 | 0.0 | 32.0 in f64; 100-dps no-hit PV ≈31.99999999999999999969 |
| `rate=nextafter(0,+inf), asset=1e100, T=.25`; `q*T=0` in f64 | NaN | No-hit limit 30.5 |
| `rate=1e-20, asset=1.1, T=1`; `F≈0.76594`, `G≈0.76594` | 32768.0 | Physically impossible: undiscounted upper bound on principal + coupon + recovery is 32.3; do **not** infer a replacement exact price from rounded F/G |

The bounds are on the declared coupon/principal/recovery cashflows, not a proof of the full financial free-boundary equilibrium.

## Narrow repair and contract

Only when `coupon>0` and `exp(-q*T)==1.0`:

1. For the f64 **no-hit** pair `F=G=0`, use the direct no-hit principal and annuity formula. Let `loss=-expm1(-q*T)` and `A=T*loss/(q*T)` when the product is positive; use the exact continuous limit `A=T` when it underflows to zero. Sum `P-P*loss+c*A` with `math.fsum`, rejecting nonfinite or unresolved results.
2. For any returned `F>0` or `G>0`, explicitly raise `ArithmeticError`. The stopped-coupon `(F-G)/q` contribution cannot be recovered from the available independently rounded f64 factors in this regime. Refusal is not a solution or a certificate.
3. With `coupon==0`, keep the old zero-coupon path. With `exp(-q*T)!=1`, keep the **byte-identical original expression**. Default and zero-duration endpoints remain unchanged.

This changes a known false-success branch without claiming a general `F-G` precision solution or certification near but not equal to unit discount.

## Evidence obtained / not obtained

- **Executed locally:** four focused unittest methods, **4/4 PASS, 0 skipped**, on a manually reconstructed subset of the source's exact first-passage and bond expressions; 1,500 deterministic ordinary-domain probes compared old and patched formulae, all jointly accepted pairs were exactly equal; no training or performance benchmark.
- **Independent high precision:** 100-decimal-place `mpmath` checks for the no-hit coupon/principal formula at `q=1e-20` and at positive minimum-subnormal q.
- **New repository integration tests authored and committed:** six methods covering no-hit small q, underflow, nonzero hit-mass refusal, zero-coupon preservation, regular formula parity and endpoints. **They have not been run against a byte-exact full checkout** and are NOT counted as passed CI.
- **No claims:** formal interval/tail bound, all-domain obstacle/fixed point, float32/bfloat16/float16 native computation, Rust/GPU speed, power, training accuracy, general architecture superiority or production admission.

Reproduce in a complete checkout at the final branch commit:

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_bond_coupon_unity
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_joint_fpt_contract
python -m unittest -v experiments.hcsn_hx_unified_v3.test_oracles
```

## Still open

P0: coupled global HX obstacle/self-consistency, verified parameter envelope, certified first-passage/coupon tails and gradients, native low precision. P1: pretrained-frozen matched Call/Risk/Margin ablations and net causal gain (prior negative `0/4` remains binding). P2: real repeated physical events, long memory and robust resume. P3: genuinely aligned four-modal encoders and OOD confirmation. P4: Rust/GPU real 64–4096 Cell, p95/p99, RAM/VRAM, joules and recovery. P5: equal-data/token/update/full-cost Transformer/SSM quality-conditioned superiority. All remain nonadmitted.
