# Regularity of the analytic channels and of the caption router

For log distance \(x=\log(V/V_B)\), the stopped equity extension has zero value on the default side and a zero first derivative from the live side. The finite-horizon first-passage probability \(F_T(x)\) takes value one at the wall and has a nonzero right derivative there. Extending it as one on the absorbed side makes it continuous and piecewise differentiable. These two distinct matching laws matter when a model backpropagates gradients close to a hitting event.

`law_lookup_audit.py` compares the pinned floating-point lookup with `Published` in `parent_cell.py`. It evaluates one midpoint of each of the 8,192 interpolation intervals over [0,2] and three allowed principal settings, 0.72, 1.00 and 1.28 times baseline. The largest absolute equity error at those sampled points is 3.91e−5. The largest one-year and one-quarter hit-probability errors are 1.27e−7 and 3.25e−7. These are finite-grid comparisons at the stated settings. They bound neither all-parameter errors nor derivative errors.

| At the absorbing wall, derivatives by log distance | Absorbed side | Analytic live side | First lookup segment |
|---|---:|---:|---:|
| Equity at baseline principal | 0 | 2.98e−12 | +0.11316 |
| One-year first-hit probability | 0 | −4.14012 | −4.13940 |
| One-quarter first-hit probability | 0 | −7.59079 | −7.58960 |

Equity’s live-side result is consistent with exact smooth pasting at double precision. The short straight lookup segment preserves equity values closely while giving a positive slope at the edge. A cubic Hermite table can impose the analytic boundary derivative and match adjacent segment slopes if the derivatives at shared knots are supplied consistently. The single-channel hit probability keeps its mathematical kink against its absorbing extension even when evaluated from the exact formula.

The grid is clamped at two, but the current four-patch caption router cannot reach that cap under its bounded tanh drive. Its log-boundary lies between −0.3474662 and +0.2573704. Across the stored vertices the largest value of `moved_margin(x)−x` is 0.300000012 and linear interpolation preserves this affine upper bound. Set \(y_t=x_t+b_t\). At a live step \(y_{t+1}\le y_t+0.300000012\). At an absorbed step \(y_{t+1}\le0.300000012+b_{max}\). Starting from \(y_1=0.18\), these bounds give upper log distances 0.52747, 0.90484 and 1.20484 for its three active patches. Longer recurrent applications require their own domain analysis.

## A smooth two-path release probability

As a separate candidate, suppose each computational unit emits when the first of two conditionally independent paths with the same fixed boundary and diffusion parameters hits. Conditional on the common parameters, its release probability is exactly

\[
q_2(x)=1-\bigl(1-F_T(x)\bigr)^2\quad(x>0),\qquad q_2(x)=1\quad(x\le0).
\]

If the source has \(F_T(x)=1-a x+O(x^2)\), then \(q_2(x)=1-a^2x^2+O(x^3)\). The value and first derivative match the absorbing extension. At the quarter horizon the diagnostic gives \(q_2(10^{-4})=0.9999994239\) and derivative −0.01152, compared with −7.59079 for the one-path probability at the wall. More generally \(q_n=1-(1-F_T)^n\) matches derivatives up to order \(n-1\) for positive integer \(n\), given the analytic one-sided passage law. This is a different event with higher release probability, and its gradient weakens near absorption. Shared noise or correlated paths require a joint survival law. Testing the two-path model requires applying the corresponding event law consistently in the recurrent dynamics, including any reset rule. The registered six-arm caption experiment uses the original one-path release law throughout.
