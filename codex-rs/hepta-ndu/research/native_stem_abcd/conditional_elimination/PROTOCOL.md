# R24 frozen protocol — eliminate inner Bernoulli risk tree, certify scalar conditional envelopes

Parent R23 Draft PR #2206, exact HEAD `244b373d2bc4e20bb427b1941583bb328d6cfd19`. Exploratory sequential continuation, informed by R21–R23 failures; no blind preregistration. The method structure was derived before protocol push, but the 4000-split efficacy sweep MUST occur only after pushing this protocol. No historical R21–R23 proof, weights, or status may change.

## Invariant target and mandatory comparison
Keep the exact R21 two-step, positive-risk finite population (16 equiprobable leaves), Markov preference flips, horizon, risk coefficients, target and regularizer unchanged, and exactly the same three rational candidates for n=2/3/4. Root cube [-3,3]^n, global cost-regret threshold 1/100, strict per-width maximum 4000 **external branch-and-bound** splits. A sub-box *scalar interval evaluation* is NOT a new outer B&B split; account honestly for its cost. For each width compare the actual R23 split-localized and R22 centered-baseline results with a new R24 proof, retaining negative and resource outcomes. Do not silently give any width extra splits, adjust objective, select different candidate, or substitute a fitted model.

## New structural elimination, no global convexity of neural parameters assumed
For each X=±1 and P0, the forward recursion's common terminal residual
  z_X(theta) = b*(aX+c) + d*(aX+c)^2/4 + (a-b)^2/4 + eta*a/(1+a^2) + kappa*(a-b)/(1+(a-b)^2) -X-1
does **not depend on epsilon1/epsilon2** once state X and learned parameters are fixed. The inner epsilon2 conditional entropic CE can be collapsed algebraically:
  Q_p(z)=p/20 + gamma*[ z² + 1/50 + logcosh(rho_p*(z/5+(1-2p)/100))/rho_p ].
The remaining epsilon1 and preference flips give
  F_p0(z)= gamma CE_rho_p0(Q_0(z),Q_1(z)).
Thus the true population objective is exactly J(theta)=1/4 sum_{X,P0} F_P0(z_X(theta)) + ||theta||²/4.
For every real z, F_p0''(z)>=2 gamma²=81/50, by positive-risk logsumexp monotonicity, variance positivity and the original quadratic terminal loss. This is **one-dimensional convexity conditional on the residual**, not a Hessian bound in learned weights.

## Rigorous global scalar tangents
Precompute a fixed public grid z0=-4,-15/4,...,4 in steps of 1/4, independently for each P0. Evaluate *rational outward interval* enclosures for F_p0(z0) and F'_p0(z0). Compute logcosh exactly enclosed by its identity |y|-log 2+log(1+exp(-2|y|)), with rational alternating negative-exponential remainder (degree 30), 25-term atanh/log remainder and outward fixed decimal scale 10^36. Use exact rational Lambert tanh bounds only as a redundant independent derivative comparison. The full scalar lower tangent is F_p0(z)>=F_L(z0)+g*(z-z0)+(81/100)(z-z0)^2 for all g in its certified derivative interval; minimize this explicit quadratic on the exact rational residual interval computed from original forward expressions. Take the maximum over all 33 frozen anchors and the old natural R21/R22 hybrid lower for each parameter box. These operations produce a safe lower bound **without assuming parameter convexity, a hidden global reference or matched floating residuals**.

The inner risk elimination is algebraically exact under this precise symmetric Bernoulli model; it is not a generic theorem for unknown transitions or arbitrary continuous distributions. The candidate objective upper is inherited from the unchanged exact R21 bound, not a numerical prediction. Global `outside [-3,3]^n` exclusion uses original nonnegative stochastic loss and parameter penalty.

## Frozen experiment and audit
Execute precisely 3 new certificates, n=2,3,4, ≤4000 *outer* splits per width with the old same 0.01 gate. Save all SPLITS.jsonl, FRONTIER.jsonl, exact Fraction lows, evidence hashes, outside-bound checks, CPU/wall and peak RSS. Preserve every miss. Split priority can use float but proof comparisons and coverage must use exact Fraction. Match historical R22/R23 reported nodes and costs, do not replace them with claims of exact matched-hardware timings across sessions.

After the proof, optionally rescore all 120 R21 sealed endpoint tensors using the fixed new global lower and original exact per-tensor cost interval, without training; report new certifications separately from the R21/R22 history, or explicitly state if not completed. No optimizer experiment or new learned weight is authorized in R24.

Independent verification must check the collapsed finite-tree identity at random rational points against a separate implementation; scalar strong convexity proof algebra, rational logcosh/gradient bounds against high precision for diagnostic purposes, one-sided tangent validity, complete partition coverage, hash and exact frontier gap for ALL results, with at least 100 deterministically sampled exact parent+child bound replays per run. Real tamper tests should reject changed candidate, proof frontier or rehashed false bound if actually run. If full audit isn't completed, report its exact scope.

Local assistant CPU source slice only; no native Neuron, GPU, energy/FLOP, production activation, CURRENT/main merge, or general deep nonlinear FBSDE/LLM theorem. Hosted CI cannot be marked passed without current exact-head status.
