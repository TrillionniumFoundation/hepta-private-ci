# R11: independent population-integration certification, frozen-candidate study
Parent: R10 PR #1898, exact commit f8cb099a79fa2bd7e3b40ad49113cf7c8b6185e3.
This protocol is pushed **before** R11 evaluation. It is an exploratory follow-on, not an externally preregistered blind confirmation.

## Fixed materials and scope
All 96 R10 final nonlinear forward-Stem candidates are frozen. R10 training law, loss, optimization, recorded checkpoints, original legacy gate and outcomes remain unchanged; no incumbent is retrained, replaced or filtered. Target is the same known uniform four-dimensional initial distribution and full entropic recursive cost. Width 64/256, four solvers, three seeds and both R10 training/monitor variants stay represented. Preserve R10 SHA256 identities and 96-run census.

## Three noninterchangeable decisions
1. Historical rule **unchanged**: max(J_CC5,J_CC9)<=.04850 AND abs(J_CC9-J_CC5)<=1e-6. Report its original outcome; it is not a proof of integral accuracy.
2. A sound **real-arithmetic deterministic bound**: derive global coordinatewise derivative majorants L_j from the actual three-step feedback, tanh derivatives, quartic terminal score, both regimes/branches and the entropic log-sum-exp recursion. For each positive tensor quadrature construct exact rational 1D W1 distances to its uniform marginals. Then |E_mu f - Q f| <= sum_j L_j W1(Unif_j,nu_j). No empirical data may shrink a majorant. State wide/inconclusive bounds honestly. Finite FP64 neural evaluations are NOT machine-interval-certified; without rigorous evaluation-rounding bounds, do not claim a machine-formal pass.
3. **Independent numerical diagnostics, not certificates**: recalculate all frozen candidates with Gaussian tensor rules GL7 and GL11, plus eight new scramble-Sobol1024 sets (seeds 2026101611 through 2026101618); compare against existing sealed CC17 and GL9. Never choose a checkpoint or alter a gate using these diagnostics.

A manufactured independent polynomial family with analytically known uniform expectations checks both bounds and a specific failure of the historical coarse-rule agreement test. Mathematical polynomial controls are not neural evidence.

## Acceptance and audit
Primary diagnostic: of 96 frozen candidates, count existing historical qualifications, apparent low-CC17 candidates and independently **tightly enclosed** candidates. If enclosures are not narrow, report INCONCLUSIVE; do not replace it with a new green status. New scalar outputs, majorants, R10 inputs and plots/tables are create-only. Verify the existing R10 ZIP manifest and exact selected-weight bytes, all 96 identities and candidate data. Repeat selected evaluations independently, verify positive quadrature mass, numerical derivative probes, manufactured polynomial expectations, and reject altered weights, missing cases, rehashed false bounds or score substitution.

Track process CPU/wall and RSS; keep raw outcomes and failures. Full FLOPs, energy and native hardware are unknown. This is local CPU mathematical research, NOT whole-repository Rust/Bazel qualification, deployment authority, an LLM/world-model superiority theorem or a generalized viscosity-solution proof. No main merge, CURRENT update, historical rewrite or production promotion.
