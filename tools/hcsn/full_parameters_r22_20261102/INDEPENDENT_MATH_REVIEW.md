# Independent nine-parameter mathematical review

The selected OLD-point audit passed. I found no mathematical chain, sign, or
array-index defect in `dual.rs`, `financial.rs`, and `main.rs`. This review covers
the declared static boundary and its 40-state synthetic finite law. It does not
qualify a continuous financial/PDE/neural model or production use.

## Separate calculation

`independent_math.py` imports no candidate, reference, or verifier module. For
each B term it uses the identity

\[
B(z,s,y)=s\phi(ys)\int_0^\infty u\exp(-u^2/2-zsu)
                 \operatorname{exprel}((z+y)su)\,du,
\qquad \operatorname{exprel}(w)=\frac{e^w-1}{w}.
\]

To derive this, write each Gaussian probability using
\(\Phi(v)=\phi(v)\int_0^\infty e^{vu-u^2/2}du\), factor out
\(\phi(ys)\), and combine the two exponentials with exprel. This differs from
both the candidate's bounded interpolation-derivative integral and the primary
reference's subtraction of two normal probabilities. It needs no normal-CDF
implementation or finite truncation of the unbounded integral.

The script uses adaptive mpmath tanh-sinh quadrature with splits
`[0,1,2,4,8,infinity]`. It computes the complete finite law at each complex
perturbation and extracts all nine derivatives by imaginary part divided by the
step. The real point chooses the interpolation interval; that interval stays
fixed during each local derivative calculation. Two independently recomputed
precision/step pairs, 80 digits with step `1e-25` and 90 digits with step
`1e-35`, must agree within `1e-40` after division by `1+abs(value)`.

## Analytic chain and array inspection

The forward-dual sum, product, quotient, exponential, expm1, square-root, and
logarithm rules are correct for their admitted arguments. The stabilized eta
branch is algebraically equivalent to `z-a`: `(z-a)*(z+a)=2*r/sigma^2`.
The subsequently computed gamma equals `z+a`. The branch is not a distinct
mathematical model, including across `a=0`.

The candidate B integrand follows the fundamental theorem of calculus applied
to `Phi(s*y)-exp((z^2-y^2)*s^2/2)*Phi(-z*s)` between `-z` and `y`. Its tail
integral omits `Phi(x-12)` for a negative normal argument x. The omitted
probability is at most `Phi(-12)`; this does not bound the finite quadrature
error. The numerical results below are selected-point evidence for that error.

All physical coordinates feed the static-boundary chain. In the finite law,
`r`, `delta`, and `sigma` additionally change the centered transition rates.
The independent direct-rate derivatives are:

| Coordinate | Up rate | Down rate | Absorption rate |
|---|---:|---:|---:|
| r | 5 | -5 | 0 |
| delta | -5 | 5 | 0 |
| sigma | 95*sigma | 105*sigma | 200*sigma |
| Other six coordinates | 0 | 0 | 0 |

For boundary V, reset is `log(90/V)` and its derivative is `-dV/V`.
The upper interpolation weight has derivative `-10*dV/V`; the lower weight
has the opposite derivative. These weights feed both recovery reinjection and
the four-label prior. The review script differentiates those value formulas
as a whole instead of importing or copying the primary reference's explicit
Jacobian assembly. Each generator diagonal is rebuilt as the negative sum of
its outgoing row, independently of the candidate's increment/decrement edge
accumulation. READ and REFRESH are constant in these nine coordinates and
therefore have zero derivatives.

Flattening is consistent: boundary (1), row-major generator (1,600), READ
(200), REFRESH (160), prior (40), totaling 2,001 values and 18,009 Jacobian
positions per point. The native outer Jacobian axis is the declared order
`r, delta, alpha, tax, coupon, principal, sigma, liquidity, maturity`.

## Development evidence using OLD points only

Six original fixed parameters are `.08,.02,.6,.27,6.39,61.68`. The only opened
development points were the two previously opened R20 corners below and the
existing baseline. No new random or formal confirmation points were generated
or read for this development audit.

| sigma, liquidity, maturity | Boundary | Max value tolerance ratio | Max Jacobian tolerance ratio |
|---|---:|---:|---:|
| .15, .002, .5 | 70.9826624205041 | 1.87550e-5 | 1.95399e-5 |
| .4, .04, 2 | 58.4180215355304 | 3.66816e-5 | 7.86688e-6 |
| .3, .02, 1.3 | 65.0198402339191 | 7.72917e-6 | 3.38468e-5 |

Every one of 6,003 value and 54,027 Jacobian comparisons passed the registered
native tolerances (ratio limit 1). Maximum absolute discrepancies were
`7.63779e-15` for values and `1.39141e-13` for derivatives. The worst normalized
80/90-digit consistency discrepancy was `5.46457e-49`, below `1e-40`.
Machine-readable per-coordinate and per-point results are in
`INDEPENDENT_MATH_REVIEW.json`.

The development script body used 52.47236 parent CPU seconds, 0.01535 child CPU
seconds, and 54.09846 elapsed seconds on CPU 1. Those counters begin after
imports; they are not a complete external process receipt and must not be
added to another enclosing receipt.

The executed development source hash was
`883dd82bd246ea69a9b5fc0e3870561ebbd9240b168321866277ca05f301438b`.
After that run, only provenance/finite-input validation was hardened: formal
raw digest, campaign counts and namespace, selected row indices, finite
comparisons, and reference Jacobian row count. Mathematical computation did
not change. The final freeze-ready script hash is
`af524d0ea3c936dbb523c7e5b65f56e0715443527738b07fbd86fc0b073dedad`.

## Preregistered formal follow-up

Before source publication and before opening any formal points, the exact
selection was fixed as raw indices `[0,127,255,383,511,512,543,575,594]`.
The script hardcodes that list and requires the matching protocol key
`independent_math_selected_indices`. Its formal mode refuses raw access until
publication readback, all frozen source identities (including the script), a
passing formal summary, campaign counts/namespace, and raw-file digest agree.
No formal follow-up result is claimed in this development review.

Selected high-precision agreement is not a uniform FP64/quadrature error proof.
Excluded interpolation knots do not possess the same ordinary local derivative
guarantee. There is no claim here about learned emissions/rewards/controls,
continuous free boundaries, full equity/debt valuation, runtime performance
advantage, or production activation.

## Formal fixed-selection follow-up after publication

After the complete source publication/readback at commit
`7a319af55c8c99805ad445290af72c674438fd00`, the unchanged final audit script
passed its source/registration/raw-provenance gates and audited exactly the nine
preregistered indices. The command completed with exit 0 and `passed: true`.
No selection, tolerance, precision pair, or mathematical implementation changed
after opening these points. The original development JSON above is unchanged.

| Formal raw index | Boundary | Max native value tolerance ratio | Max native Jacobian tolerance ratio |
|---|---:|---:|---:|
| 0 | 71.0562339600534 | 6.33015e-5 | 3.12216e-5 |
| 127 | 58.7227884230141 | 3.07457e-5 | 1.95761e-5 |
| 255 | 58.6977427400358 | 1.25533e-5 | 2.00686e-5 |
| 383 | 58.5326903770273 | 7.65805e-5 | 1.19195e-5 |
| 511 | 58.5083355271113 | 1.97389e-5 | 2.39196e-5 |
| 512 | 68.9812343533668 | 4.80096e-6 | 1.81873e-5 |
| 543 | 76.0892786905676 | 1.82542e-5 | 2.32022e-5 |
| 575 | 60.7913503266500 | 1.78475e-5 | 2.66993e-5 |
| 594 | 65.0198402339191 | 7.72917e-6 | 3.38468e-5 |

All 18,009 native value and 162,081 native Jacobian comparisons passed. Maximum
absolute discrepancies were `1.59117e-14` for values and `2.19893e-13` for
derivatives. The primary high-precision reference, converted to its stored
FP64 arrays, also passed every selected value and Jacobian comparison against
the independent calculation: maximum tolerance ratios `1.82542e-5` and
`2.72576e-6`, respectively. The maximum 80/90-digit consistency discrepancy was
`3.69287e-48`, below the preregistered `1e-40` gate.

`INDEPENDENT_MATH_CONFIRMATION.json` contains the complete selected-point
results, all nine boundary derivative decimals per point, provenance, and
inner timing. `INDEPENDENT_MATH_CONFIRMATION_PROCESS.json` records the complete
invoked child process: 156.007366 CPU seconds, 160.538100 elapsed seconds, and
44,308 KiB maximum single-process RSS. Simultaneous family peak RSS is unknown.
These external counters include imports and final serialization; do not add the
nested inner counters. The small measurement wrapper and transport remain
outside that receipt's scope. Execution used CPU 2 with one BLAS/OpenMP thread.

Retained identities:

| Artifact | SHA256 |
|---|---|
| Unchanged audit script | `af524d0ea3c936dbb523c7e5b65f56e0715443527738b07fbd86fc0b073dedad` |
| Formal raw gzip | `5b70d87e52524f0623de045d0fd950454b4816dd1ce66e9d59dea19d6e151d9a` |
| Formal audit JSON | `9df5c5c1431705effd4fbf3cee0fa231b5f46098ceb23611bea38db695dae326` |
| Formal process receipt | `98c069fc1a18a2d5d795b16a0eaed706d325ea280409ddacf13bf6e78cd151cb` |
| Formal audit stdout | `83d2fd2ae797f56bba8748e6d83289bb8e48d1f5c33882858ed242e47a3610c2` |
| Formal audit stderr (empty) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

The formal result supports the selected local finite-law Jacobians and the
correctness of the independent/reference agreement at those fixed points.
The scope limits stated above still apply.
