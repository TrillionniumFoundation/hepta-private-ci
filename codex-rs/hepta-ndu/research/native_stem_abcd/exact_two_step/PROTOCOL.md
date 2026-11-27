# R14: exact two-stage nonzero-risk forward/backward Stem qualification

Stack on R13 Draft PR #1969 exact HEAD `395496e26a425fc60aa7e2872476b575031bdcae`. The R13 certificate remains unchanged. **A high-precision two-dimensional candidate was scouted and a preliminary rational certificate run before this protocol was pushed**; this is openly exploratory, not independent blind preregistration.

## Frozen law and model

X has five atoms {-1,-1/2,0,1/2,1}, each 1/5. Initial P0 is uniform {0,1}; epsilon1, epsilon2 independently take -1,+1 with probability 1/2. Full support has 5*2*2*2=40 terminal configurations. Gamma=9/10, entropic risk rho0=1/2,rho1=1, both nonzero.

The two **shared trainable forward weights** a,b occur at the first stage H1=X+a X²+b X³+epsilon1/5. P1=P0 xor 1{epsilon1=+1}. Stage-1 target T1=X²+X⁴/2 and loss l1=(H1-T1)²+P1/20. Stage-2 H2=(1+epsilon1 X/10) H1 +epsilon2/10, T2=(1+epsilon1 X/10)T1+X/8. P2=P1 xor 1{epsilon2=+1}, terminal l2=(H2-T2)²+P2/25. Backward equations Y1=l1+gamma/rho(P1) log(mean_e2 exp(rho(P1)l2)), then Y0=gamma/rho(P0) log(mean_e1 exp(rho(P0)Y1)). Population J=E_{X,P0}Y0. Each branch has an explicit Bernoulli martingale difference. No learned unknown dynamics, pretrained representation or oracle labels.

The parameters enter forward dynamics at two stages, but H2 is **affine in theta at fixed X,epsilon1**, despite nonlinear dependence on X. Thus stage costs convex in theta; entropic CE is coordinatewise monotone and convex for positive rho, yielding global Hessian >= 2gamma E[(X²,X³)(X²,X³)^T] >= (117/160)I. The proof is specific to this two-parameter convex family, not unconstrained deep nonlinear feedback/FBSDE.

Frozen rational candidate a=14790233104650800/10^16 and b=-10033907548161366/10^16. Exact interval enclosure uses 2^160 outward directed fixed-point rational arithmetic, exp power series through order30 on arguments <=1/2 with explicit remainder, and atanh-based log through 36 terms with geometric bound after power-of-two normalization. Verify all preconditions and no finite-support branch omission. The pre-specified certificate gates are global parameter error <1e-10, global excess <1e-18 and b=0 restriction penalty >1/10. Independent mpmath floating comparisons do not count as proof.

## Numerical optimization control

Run actual fresh-seed (11,23,47,59,83) from-scratch Adam, full-law backward-adjoint-gradient root (analytic Hessian), and L-BFGS on the IDENTICAL two-weight family/objective and exact enumerated support. No weight warm start or oracle-label fit. Predeclare a 3-second CPU fitting cap, and a common parameter-quality radius 1e-6 measured against the independently rational-certified optimum (candidate distance + exact bound). Record first observed threshold crossing, optimizer calls, accepted weights, whole process CPU/wall and peak RSS; misses remain censored. A closed-form reference is not used during optimization. The finite-sample domain is fully known; no statistical generalization inferred.

Outside the proof, independently evaluate the zero-risk version (same law), branch martingale reconstruction, alternative risk coefficients, and a continuous-uniform X law as an explicitly *different* target-population stress test. Do not conflate continuous target evidence with the certified discrete law.

## Evidence

Store full exact rational JSON (possibly large denominators), a concise readable receipt, all optimization seeds and raw weights, no cherry-picking, test logs and explicit resource totals. Run all algebraic tests, independent high-precision checks, adversarial certificate-parameter/law/rounding tests, and read-only replay. Publish a new dedicated Draft PR/workflow without modifying main, R13/R10 gates, CURRENT, native contracts, or production selection. GPU/FLOPs/energy unmeasured; complete physical research TCO not claimed.