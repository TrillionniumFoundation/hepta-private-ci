# P0 independent regenerative scalar QVI finite-state oracle — 2026-10-31

**RESEARCH_ONLY / DENY_ALL / NO_GO.** Stacked on the exact source of draft PR #4492 (`408c1ca2e0605d09710ac6e05385b8e0317bce1c`). The original He–Xiong financial equity/bond/free-boundary code, neural training and all historic negative results remain unchanged.

## Independent discretization

`qvi_grid_independent.py` does **not** import the existing `stopping.py` threshold/value code. It approximates the scalar drift-diffusion `dX = mu dt + sigma dW`, reward `x-K`, state reset `r<K`, positive discount `rho`, deterministic refractory `tau` with `D=exp(-rho*tau)`. The finite-grid equation is `max{L_h V-rho V, x-K+D V(r)-V(x)}=0`. The Markovian generator has nonnegative jump rates (centered when admissible, upwind otherwise). For each Howard policy, separate tridiagonal M-matrix solves produce `V=a+b V(r)`, then solve `V(r)=a(r)/(1-b(r))` with a convex two-node interpolation. Policy improvement directly compares continue and fire values.

The left boundary is **imposed zero** and the right boundary is **assumed immediate FIRE**, so finite-interval truncation is not certified. The reported threshold is a discrete obstacle-crossing interpolation; boundary-location error is about the mesh size even when value errors are much smaller. An invalid domain, nonpositive pivot, missing contraction, failure to converge, disconnected fire set or unresolved boundary is explicitly refused, never treated as success.

## Executed local test evidence

Run from repository root (Python with SciPy installed):

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_qvi_grid_independent
```

- **7/7 focused test methods PASS**, no skips, in a local research environment. A preliminary test incorrectly asserted that increasing dead time lowers the boundary; the error was corrected to the proper increasing relation *before publication*.
- Three meshes (301, 601, 1201) against an independently coded Brent smooth-fit reference: absolute boundary errors **0.0459892462 / 0.0173661227 / 0.0090146906**. Value and policy residual tolerances pass on all grids.
- **64/64** fixed-seed bounded parameter cases accepted with no omitted cases: maximum boundary error **0.0285494457** at spacing `h=0.05875`; maximum `|V_grid(0)-V_analytic(0)| = 0.000135347216`. Fixed seed `20261031`; mu in [-0.4,0.4], sigma in [0.6,1.4], rho in [0.07,0.3], tau in [0,3], reset in [-1,-0.1], K=1; interval [-26,21], 801 nodes.
- Nine sign/drift/refractory combinations, zero-dead-time limit, monotonic value-versus-refractory, forced upwind signs, alternative domain width, invalid parameter/refusal cases passed. Discrete Bellman residual less than `1e-8` in checked panels.
- Exact locally tested Git blob identities: solver `1d6607de3f9b7944f0938ba1518b811b2f4461b1` (7003 UTF-8 bytes), tests `7bab0949ba117e1c802f496f5a2e78f8b14d486f` (5871 bytes). Verify the exact published blobs before making a source-seal claim.

## Scientific/admission limits

This is an **independent numerical comparison for the simplified scalar stationary regenerative Brownian QVI only**. It does **not** establish the globally admissible or coupled He–Xiong financial free boundary, real interval-arithmetic certificates, FP32/BF16 gradients, time-varying/multimodal neurons, Selective Copy/MQAR quality, native Rust/GPU, hardware energy, crash-proof live stream replay or matched-backbone advantage. The finite-grid residual is a discrete residual, not a continuous free-boundary optimality proof. The successful cases cover only stated bounded inputs; no all-domain claim. No baseline or research blocker is declared closed; `production_activation=false` and `all_scientific_blockers_closed=false`.

## Next critical path

P0: coupled HX obstacle existence/admissibility and strict interval/tail certificates; active-set and real low-precision gradient tests. P1: preregistered equal-slope/equal-active-parameter Call/Risk/Margin versus optimized conventional gates, with prior negative trials preserved. P2: genuine causal time-stamped repeated-impulse memory (Copy/MQAR/overwrite/OOD lengths) with checkpoint/restoration. P3: distinct text/image/audio/video paired alignment. P4: real Rust/GPU kernels and 64/256/1024/4096 Cell end-to-end energy/latency/recovery. P5: only scale after heldout quality-and-cost net advantage under equal compute.
