# Continuous stopping benchmark: scope and verification

This supplements the R15/R16 finite regenerative CTMC with a **separate one-dimensional continuous optimal stopping benchmark**. It does not turn that CTMC into the continuum He–Xiong model, supply a neural task-optimal boundary, or establish a training/production result.

For `dS = mu S dt + sigma S dW`, `K,r,sigma > 0` and `mu >= 0`, let `beta < 0` solve

`0.5 sigma^2 beta(beta-1) + mu beta - r = 0`,

and set `b = K beta/(beta-1)`. The candidate stopping value is

- `V(S)=K-S` for `S <= b`;
- `V(S)=(K-b)(S/b)^beta` for `S > b`.

It has `V(b)=K-b` and `V'(b)=-1`. In the continuation region `(L-r)V=0`. In the stopping region `(L-r)V=(r-mu)S-rK < 0`, because `b<K` and `mu>=0`. The continuation branch is convex and tangent to `K-S` at `b`, so it dominates that payoff for `b<S<K`; for `S>=K`, it is positive and the payoff is zero. Thus `V>=g` and `(L-r)V<=0`. The derivative matches at the boundary, so no positive local-time term arises in the generalized Ito formula. The bounded candidate makes the discounted process a supermartingale; optional sampling therefore bounds every stopping payoff by `V`. Stopping at the first crossing of `b` attains `V` (the bounded remainder is at most K exp(-rT), which vanishes as T tends to infinity). These observations provide the verification argument for this particular perpetual stopping problem.

The numerical solver uses only the GBM generator, payoff and fixed domain. It does **not** read `b` or the analytic continuation values while solving. It solves the discrete obstacle complementarity problem with policy iteration and a monotone tridiagonal stencil, with exact immediate-exercise lower data and zero upper data on a fixed log-asset interval `[-7,9]`. Four successive meshes are specified before execution; endpoints do not change. Mesh refinement and residual agreement are deterministic numerical development checks, not independent scientific confirmation. These finite observations are not a rigorous convergence-rate or truncation-error theorem.

`boundary_results_v2.json` is authoritative. All 12 predetermined solves completed. At 4096 intervals, the maximum absolute boundary error is **0.13150 asset units** for strike 100; maximum value error on `S/K in [.1,3]` is **0.0002310 asset units**, maximum discrete smooth-pasting slope error **0.012609**, and maximum LCP residual **6.47e-11**. All fixed finite gates passed. The midpoint between last discrete exercise node and first continuation node is an estimate; those nodes are **not asserted to enclose the exact continuous boundary**. The first/final value errors decrease for each of the three cases. Nonmonotonic boundary estimates remain in the raw rows and are not promoted to certified brackets.

V1 raw results and their exact executed source are preserved in `boundary_results.json` and `executed_sources/boundary_v1.py`. A review corrected unused band-storage indexing at endpoint exercise rows, replaced potentially misleading `boundary_lower/upper` names with discrete-node names, and replaced a redundant algebraic boundary calculation with a two-sided numerical derivative. V2 freezes were written before V2 checks. No numeric obstacle outcomes changed; V1 did not test a different scientific hypothesis. Internal CPU and wall time exclude interpreter/import, and are not a deployment cost measure.

Remaining open: finite-horizon and full He–Xiong free-boundary/PDE convergence; reset/regeneration boundary conditions; coupled content/control optimality; trained moving boundaries; full differentiability across free-boundary branch changes; production ownership, FP32/GPU accuracy and energy/cost admission.
