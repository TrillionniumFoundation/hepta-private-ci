# HCSN P0 — Global-QVI Subset and He–Xiong Curvature Rejection

**Status:** OFFLINE_RESEARCH_ONLY; not a production admission and not the full He–Xiong equilibrium. Date: 2026-10-31.

Mathematical reference: Zhiguo He and Wei Xiong (2012), *Rollover Risk and Credit Risk*, The Journal of Finance 67(2):391–430. This package does not redistribute the paper. https://doi.org/10.1111/j.1540-6261.2012.01721.x

## A. Precisely defined certified mathematical subset

We consider **a separate, simpler perpetual American put**, not the author's time-to-maturity debt-rollover fixed point:

- `dV=(r-delta)Vdt+sigma*VdW`, with `r>0`, `delta>=0`, `sigma>0`, `K>0`.
- `g(V)=max(K-V,0)`.
- `L f=(r-delta)V*f' + (sigma²/2)V²*f''`.
- `max{L U-rU, g-U}=0`.
- Negative characteristic root `beta<0` solves `(sigma²/2)beta(beta-1)+(r-delta)beta-r=0`.
- Boundary `b=beta K/(beta-1)`; value `U=K-V` for `V<=b`, `U=(K-b)(V/b)^beta` otherwise.

**Global-QVI proof over exact real arithmetic:** At `b` the value and first derivative match the payoff. For `V>b`, `(L-r)U=0` and `U''=beta(beta-1)U/V²>0`. By boundary tangency this implies `U>=K-V` until `K`, and beyond `K` the payoff is zero while `U>0`. For `V<=b`, `U=g` and `(L-r)g=delta V-rK<=delta b-rK = (sigma²/2)beta K<0`. The solution decays at infinity. This proves the QVI inequalities for this **stated simplified model**, not for the original HX coupled equilibrium.

Implemented independent checks include finite-domain monotone-log-grid Howard policy iteration, QVI complementarity, implicit boundary sensitivities against finite differences, positive-state/finite precision refusal, and float32-rounded event-side alias rejection.

The Python implementation and floating-point grids are **numerical diagnostics**, not formally verified programs or directed-rounding interval arithmetic. Grid boundary indices are quantized and need not converge strictly monotonically.

## B. Actual He–Xiong local reject-only gate

At candidate smooth-pasting boundary `E(b)=E'(b)=0` the original stock-value equation implies

`E''(b+)=-2 f(b;b)/(sigma²*b²)`, where

`f(b;b)=delta*b - (1-pi)C + alpha*b/m - P/m`.

`f>0` implies negative value immediately above `b` for a `C²` continuation, violating the global equity obstacle. Such candidates are rejected. `f<0` satisfies only one local necessary condition and returns `LOCAL_NECESSARY_ONLY_GLOBAL_UNCERTIFIED`. Exact zero returns unresolved. All cases still require the complete coupon/debt valuation, fixed-point consistency, global obstacle, gradient stability and independent low-precision checks before any HX qualification.

The finite-decimal inputs are converted to exact rational numbers for the sign numerator; the derivative magnitude remains decimal-rounded and is not an interval certificate. No numeric tolerance is used to turn ambiguity into success.

## C. Independent execution

```bash
python -m unittest -v experiments.hcsn_hx_unified_v3.test_perpetual_put_qvi_reference
python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_curvature_necessary
python -m unittest discover -v -s .
python -m p0_p5_gatebook
```

The negative `curvature>0` test is **not** proof of a globally admissible candidate. It is intentionally marked local only.

## D. Unclosed evidence

Full HX coupled bond and equity fixed point; full-range obstacle inequalities; rigorous directed-rounding probability and derivative enclosures; fp16/bf16/GPU; real all-modal training, six-stage efficiency, and production gate remain **unclosed**. Always keep `DENY_ALL`.
