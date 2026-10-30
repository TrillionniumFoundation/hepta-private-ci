# HCSN scalar regenerative QVI: independent finite-grid P0 gate

**Research-only / DENY_ALL.** Additive to #4385; this does not change or certify the He–Xiong finance equilibrium, frozen HCSN negative P1 evidence, or any production owner.

## Independent numerical method

The existing stopping.py defines arithmetic Brownian membrane dynamics with drift mu, volatility sigma, discount rho, firing reward x-cost, delayed reset at reset, refractory duration tau and D=exp(-rho*tau). Its stationary value satisfies max{L V-rho V, x-cost + D V(reset)-V}=0.

The new regenerative_grid.py does NOT use the existing Lambert-W solution or analytic threshold in its solver. The finite lower wall has V(xmin)=0 and the upper wall is a forced intervention V(xmax)=xmax-cost+D V(reset). Positive-coefficient centered differences fall back to a monotone upwind generator when drift dominates; off-grid resets use convex interpolation. Howard sparse policy iteration and independent Jacobi Bellman iteration cross-check the finite QVI.

These are artificial boundary truncations and finite-grid approximations, not rigorously certified continuum error bounds. The boundary-gradient checks are mesh refinements, not pointwise C2 smoothness proofs.

## Reproduction

From the exact parent source checkout with numpy and scipy installed, run:

    python -m unittest -v experiments.hcsn_hx_unified_v3.test_regenerative_grid

Local run on 2026-10-30: 9 of 9 test methods passed, covering 36 deterministic seeded parameter samples, three models checked by both independent algorithms, mesh refinement to 1025 nodes, an advection-dominated upwind case, independently recomputed generator/obstacle QVI residuals, free-boundary slope convergence, lower-domain wall sweep, non-grid reset, long refractory one-shot limit and invalid-input rejection. This tested stopping.py against exact Git blob d165ed777990bbf8f3606b58e1b0991de59a1544.

## Open gates

- Complete HX financial global viability (existing negative-equity counterexample retained).
- Global parameter-domain and certified interval/derivative bounds.
- Actual native f32/bf16/f16/GPU operations, quantized boundaries and hardware energy.
- Coupled cell network QVI with competing impulses, learned dynamics and stable training.
- P1 equal-parameter/slope/budget mechanism attribution; historical negative results remain.
- P2 continuous event and bounded memory; P3 multimodal; P4 Rust/GPU; P5 scaling.

Production admission: DENY_ALL. None of P0-P5 as a whole is closed.
