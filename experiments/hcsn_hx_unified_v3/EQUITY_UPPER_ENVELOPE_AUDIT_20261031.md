# P0: independently bounded fixed-barrier continuum equity at far field

2026-10-31. Research-only. DENY_ALL / NO_GO. No production changes.

## Provenance

Main observed SHA at the start of this increment: 732e934ba496d90fbe042b8d41d479ef901643e5.
This increment stacks on Draft PR #4512, exact parent HEAD 99fa3ad1f75eb021fc95fd2b6cd5dbda37898e2c. Previous numerical failures and all financial / PDE sources are preserved.

This work supplies a conservative upper *equity* Dirichlet absolute-error envelope for a positive fixed default barrier in a killed-GBM stationary stockholder optimal-stopping problem. It does not claim the candidate barrier is self-consistent, or that the full He-Xiong equations, all-state financial obstacle, low-precision gradients, or P0 admission are certified. PR #4508 still needs a separate fully validated interior debt-cashflow uncertainty budget. PRs #4511/#4512 bound narrower debt components, not the complete debt PDE error.

## Model contract and mathematical proof

Assume parameters interpreted as exact binary64 physical inputs: r > 0, delta > 0, sigma > 0, maturity T > 0, principal > 0, nonnegative coupon and shock, recovery and tax in [0,1]. Let b > 0 be any FIXED absorbing boundary. A follows risk-neutral geometric Brownian dynamics dA=(r-delta)A dt+sigma A dW, until first hitting b. Stockholders may stop at any time no later than default, with zero stockholder termination payment. The running cashflow matches the financial obstacle used in #4499:

    f(A) = delta*A + B(A,T) - C
    C = (1-tax_shield)*coupon + principal/T

The defaultable finite-maturity debt has positive terminal par=principal/T and default recovery R=recovery*b/T, nonnegative coupon rate c=coupon/T, and total debt discount q=r+shock_intensity*sale_fraction. The positive discounted killed-process representation (or maximum principle) gives an unconditional fixed-barrier bond price bound m <= B(A,T) <= M for A >= b, where

    m = min(c/q, par, R)
    M = max(c/q, par, R)

For delta > 0, the discounted ex-dividend asset plus its accumulated dividend stream is a martingale. For the first hit tau_b, the discounted remaining asset term at infinity vanishes in expectation; hence the feasible hold-to-default policy collects expected dividends at least A-b. Since the remaining debt-minus-constant running cashflow is at least -max(C-m,0), the optimal equity is bounded below by

    max(0, A-b-max(C-m,0)/r).

Every admissible stopping policy collects expected dividends at most A; its remaining cashflow is at most max(M-C,0)/r. Hence its optimal value is at most

    A + max(M-C,0)/r.

These inequalities hold for the fixed-barrier CONTINUUM optimal-stopping problem under the stated assumptions. They do not imply that the fixed-barrier resolvent is globally optimal, do not establish endogenous b, and are not QVI/regenerative results.

For log upper L in (0,12], the implementation bounds exp(L) using an EXACT rational positive Taylor partial sum and a geometric upper bound on the positive remainder, with 64..160 terms. All supplied floats are converted to exact fractions. It computes the maximum error of the nominal upper equity Dirichlet float relative to the exact lower and upper continuum envelopes. The returned decimal error budget is rounded UP, the asset/equity/bond lower endpoints DOWN, and their upper endpoints UP. Zero-payout coalescence and oversized/invalid inputs are explicitly rejected. The method cannot promote itself to a complete P0 certificate.

## Actual local execution, limitations, and negative evidence

Python 3.13.5 CPU, five targeted unittest methods PASS, zero skips, including 18 high-precision exp interval comparisons, 90 independent HX bond samples across five regimes, 15 fixed-boundary equity samples, outward-decimal assertions and invalid-domain/false-admission tests.

Command from a complete upstream checkout:

    python -m unittest -v experiments.hcsn_hx_unified_v3.test_hx_equity_upper_envelope

Panel generator:

    python -m experiments.hcsn_hx_unified_v3.run_equity_envelope_panel --out EQUITY_UPPER_ENVELOPE_SMOKE_20261031.json

Executed against a locally reconstructed HX subset from earlier isolated audits, not a byte-identical full checkout. No full-repo CI or GPU/energy run is claimed. The first exp test used an insufficient 140-decimal-digit reference and failed nine tiny-remainder subcases; the reference was increased to 900 digits. There was no relaxation of mathematical inequality or implementation thresholds. An initial wrong-direction decimal rounding for LOWER endpoints was fixed before publication. Original bad tests and reviewer concerns are described, not concealed.

Five observed examples at L=3.6:

| Regime | Nominal | Local fixed-barrier reference | Observed absolute difference | Conservative upper-equity absolute budget |
| --- | ---: | ---: | ---: | ---: |
| Nominal HX | 2307.04282 | 2306.51404 | 0.528781 | 278.749571532540 |
| High-liquidity sale fraction 0.2 | 3475.15404 | 3477.85810 | 2.704057 | 368.197518882637 |
| Zero shock | 2199.96515 | 2199.10979 | 0.855354 | 312.879410016645 |
| Low payout / high volatility | 1806.07474 | 1800.67063 | 5.404103 | 347.191136022123 |
| Lower coupon | 2238.66288 | 2238.21395 | 0.448938 | 319.472065471753 |

Full lossless sampled JSON is committed alongside the runner. Its SHA-256 measured locally is 0845230c49a58d83cc669d40a136ee1db1038f510b3c94329129aa21114bf6d6. Sampled discrepancies are NOT rigorous estimates of continuum error or proof of the stopping region. The hundreds-wide envelope is too loose to close a financial active-set or smooth-fit gate. Previous high-liquidity extra-STOP / coarse mesh disagreements are preserved.

## Unclosed P0–P5 gates

P0 OPEN: globally coupled financial equilibrium, all-domain obstacle/topology, provable full PDE time/space/roundoff debt errors, tight upper-equity bound, native FP32/BF16 and implicit derivatives.

P1 OPEN: cost-matched dynamic causal Call/Risk/Margin advantage; negative eight-arm pilot retained.

P2 OPEN: independently trained event-time FIRE with strong Copy/MQAR overwrite/OOD, real durable crash/recovery, immutable provenance; negative results preserved.

P3 OPEN: independently trained real text/voice/image/video encoders and cross-modal OOD.

P4 OPEN: native Rust/GPU 64–4096 Cell throughput/RSS/p95/p99/Joules and crash recovery.

P5 BLOCKED: matched-scale hybrid experiment only after prior scientific gates.

Admission flags remain complete_debt_error_budget=false, global_equilibrium_certified=false, scientific_gate_closed=false, production_activation=false. Keep this branch as an unmerged Draft, no threshold changes or deployments.
