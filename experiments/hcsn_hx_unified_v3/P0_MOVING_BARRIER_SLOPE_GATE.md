# HCSN P0/P2 moving-boundary first-hit reference

**DRAFT / RESEARCH ONLY / DENY_ALL.** No production or trained neural implementation. `all_blockers_closed=false`; `production_activation_allowed=false`.

## Exact mathematical scope

For X(t)=x+mu*t+sigma*W(t), sigma>0, frozen coefficients, and a lower boundary b(t)=b0+c*t, the gap a=x-b0>0 has effective drift nu=mu-c. The real-arithmetic first-hit CDF at T>0 is

    F_c(T) = Phi((-a-nu*T)/(sigma*sqrt(T)))
           + exp(-2*nu*a/sigma^2)*Phi((-a+nu*T)/(sigma*sqrt(T))).

For q>=0, the discounted first-event weight is

    G_c,q(T) = exp(-(nu+s)*a/sigma^2)*F(T; a, -s, sigma),
    s = sqrt(nu^2+2*q*sigma^2).

This is a first-event probability, NOT a repeated-firing count, financial equity value or a full HX coupled QVI result. An initial crossing fires at time zero.

If the actual boundary has **globally proved** c_lo <= b'(t) <= c_hi over [0,T], then b0+c_lo*t <= b(t) <= b0+c_hi*t pathwise, hence hitting-time order gives

    F_lo <= F_actual <= F_hi
    G_lo <= G_actual <= G_hi   (q>=0).

This is an exact **mathematical** enclosure from pathwise comparison. It is NOT directed-rounding/interval-certified floating-point error. Sampling b'(t) is not proof of a global bound. Input-dependent or stochastic changes to drift, sigma, or reset rules require separate analysis.

## Reproduced limited CPU evidence

Python 3.13.5, mpmath 1.3.0; from a checkout with these research files:

    python -m unittest -v experiments.hcsn_hx_unified_v3.test_moving_boundary_enclosure

**11/11 PASS, 0 skipped**. Four independent time-domain inverse-Gaussian density quadratures agree to 1e-35 absolute at 80 decimal digits. Also tested physical F/G ordering, moving-vs-frozen difference, increasing velocity, strict/nested slope envelopes, immediate crossing, zero T, q=0, sub-binary64 probability, and invalid-input rejection.

Witness x=1, b0=0, mu=0, sigma=.4, T=1, q=.2:

| boundary velocity | first-hit F | discounted G |
| --- | ---: | ---: |
| 0 | .012419330651552275 | .010572863746527633 |
| .8 | .38337626958978765 | .3293476006088544 |

A *separately justified* slope interval [.1,.3] at T=2, q=.3 gives F in [.13780193517219252,.3392012374453132] and G in [.09072578462393768,.22580170108229491]. Focused local Python test wall 1.38s and process peak RSS 105616 KiB; **not** a cell-speed/energy result.

## Open blockers, not waived

No full financial HX equity/debt global obstacle and coupled endogenous threshold; no certified low-precision/interval error; no proof that a learned HCSN boundary has a qualifying velocity bound; no repeated-event or long-memory superiority; no P1 same-info matched Call/Risk/Margin win; no P3 four-modal paired learning; no P4 Rust/GPU/4096 Cell/joule data; no P5 quality-adjusted foundation-scale win; no full repo CI/checkout in this standalone run. Existing adverse HCSN evidence is preserved unchanged.
