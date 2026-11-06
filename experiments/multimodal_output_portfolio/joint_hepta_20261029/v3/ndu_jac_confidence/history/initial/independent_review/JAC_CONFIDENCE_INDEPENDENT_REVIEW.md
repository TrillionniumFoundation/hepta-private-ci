# Independent internal review of the JAC confidence/propagation adapter

Date: 2026-11-06. Reviewed source is `/workspace/scratch/e5ecafe4ccc8/jac_safe_work/v3/ndu_jac_confidence/confidence.py` and its THEORY.md, study.py, protocol.json, retained result metadata, and tests. This is a mathematical/code review plus three targeted counterexamples. It does not rerun the 20-bank study or create new statistical observations. Status before fixes: mathematical construction sound under its stated real-arithmetic assumptions; three implementation acceptance gaps need repair.

## 1. Statistical premise is sound, and no historical-support count is missing in this finite model

The known full graph has 52 states, 124 state/action rows, and 164 coordinates in non-singleton rows. With J=20 retained banks and alpha=.05, each coordinate gets two-sided marginal failure probability `.05/(20*164)=1.5243902439024392e-05`. This is exactly what the code and retained metadata use. Singleton supports are known probability one and need no error allocation. The 164 include all supplied full-support atoms, including atoms whose empirical count is zero. Multinomial coordinate dependence does not invalidate binomial marginal coverage or the union bound. Different rows/banks also need not be independent for that union bound.

There is no additional union factor for two baselines, fitted candidates, history branches, or propagated Q/gain expressions: on the same simultaneous model event all the stated deterministic bounds apply uniformly over every policy on the supplied finite graph. This requires fixed per-row sample counts and a known sufficient fully observed graph/atom support. It does not justify adapting sample size, support discovery from observed atoms, an unknown posterior-state construction, or hidden/unavailable row resets. Those restrictions are already explicit in THEORY/README and must remain.

## 2. Entropic moment, risk-tilted mass and propagated gain inequalities have the correct direction

For eta>0, CE is decreasing in the exponential moment, so the minimum CE maximizes the moment. The box-simplex greedy ordering is correct. Recursive value intervals are valid by monotonicity and backward induction.

For a true baseline branch return x_i between x_i^- and x_i^+, `p_i exp(-eta*x_i)` is at least `ell_i exp(-eta*x_i^+)`. Its denominator is at most the maximized moment evaluated at x^-; hence the lower tilted probability is sound. The common exponential anchor in the implementation cancels between numerator and denominator and does not change this inequality. Coordinate lower tilted masses need not sum to one; their sum at most one on the model event is the property used.

Writing each action's CE gain as `-log E_w exp(-eta*discount*Delta V)/eta` is exact. If successor gains and local advantage bounds are nonnegative, replacing Delta V by its lower bound and then the risk-tilted masses by lower bounds gives the stated lower gain, with no reversed inequality. Multiplication by the *new* policy weights in the value-difference decomposition is correct. No extra independence of the two policies or their fitted data is needed.

## 3. Blocking implementation counterexample: a falsy successor is treated as terminal only in propagation

`order_support` and `policy_intervals` allow a state named the empty string; continuation is included there using `next_state is not None`. The propagation's `xl/xu` construction instead uses `if atom.next_state`, which drops that continuation. The later gain term uses `is not None`, so the two calculations disagree and the alleged tilted lower bound can exceed the true tilted probability.

Concrete accepted inputs: root has one action with probability .5 of a transition to state `''` and .5 of terminal reward zero. The child has deterministic terminal actions paying 10 and 11; baseline picks 10, proposal picks 11; eta=2, rho=0, exact probability boxes. The true root gain is about `8.911034132808027e-10`. The code reports a lower gain `.2831095847584864`, adopts at fee `.01`, and therefore loses about `.009999999108896587` net. It reports tilted mass `.5` where the true mass is `exp(-20)/(1+exp(-20))`.

Fix both successor tests to `is not None`, and/or explicitly enforce the inherited core's nonempty-string state contract. Prefer both semantic consistency and validation. Retained study state names are nonempty (`s000`, etc.), so this counterexample does not by itself falsify its reported 20-bank values. Receipt: `JAC_EMPTY_SUCCESSOR_COUNTEREXAMPLE.json`.

## 4. Blocking implementation acceptance gap: proposed policies are not validated

`certified_update` validates only the baseline through `policy_intervals`; `local_safe_policy` never validates candidate state/action coverage, finiteness, nonnegative probabilities, or unit row mass. For a one-state two-action example with deterministic rewards good=1 and bad=0, baseline `(0,1)`, and candidate `(2,-1)`, the function returns `adopt`, the non-policy `(2,-1)`, and alleged lower improvement 2. A proof for policies cannot certify this object.

Normalize/validate both baseline and proposed policies against the same complete support before computing any bounds or local advantage. Missing/extra actions, negative/nonfinite values, and invalid row mass must fail. This does not require a new experiment; a small input-contract regression is sufficient.

## 5. Tolerated probability mass plus a currency offset can create a false certificate

The inherited `ndu_jac/core.py` normalizes accepted probability rows and centers action values. The confidence adapter accepts row sums within `1e-12` but does not normalize them, and computes uncentered probability differences times Q endpoints. Thus it can report a positive bound for an unchanged actual value under the inherited semantics.

Both terminal actions pay the same deterministic amount `1e12`. Baseline probabilities are `(.5,.5-5e-13)` (accepted by its tolerance), and candidate is `(1,0)`. The inherited normalized evaluator gives exact improvement zero. The confidence update reports improvement `.5`, adopts at fee `.01`, and has actual net `-.01`. This is a semantically significant extension of ordinary rounding because an arbitrary common reward offset amplifies the admitted mass error. Receipt: `JAC_MASS_OFFSET_COUNTEREXAMPLE.json`.

Use the same policy normalization as the inherited core, center all signed-advantage endpoints by one common finite row reference before the signed sum, and use centered policy-value mixing. The real-arithmetic proof is invariant to this common subtraction because probability differences sum to zero. Retain the honest statement that SciPy quantiles and floating arithmetic are not outward-rounded interval certificates; these changes repair obvious representation-level false acceptance but do not convert arbitrary floating-point execution into a formal proof.

## 6. Final disposition

The missing model-coverage premise is mathematically supplied inside the finite known-support fixed-sample contract. The risk-tilt propagation argument is sound and can certify a downstream improvement behind an unchanged root. It does not establish independent-task superiority, full lifecycle positivity, unknown-support learning, or new RL originality. Before integration, repair the three code acceptance issues above and retain their negative tests. A frozen historical receipt should not be silently overwritten; a fresh receipt/source mapping can attest the corrected implementation if any rerun is actually performed.
