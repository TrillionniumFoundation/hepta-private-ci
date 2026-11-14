# R18: a rigorous two-dimensional quotient certificate for an asymmetric risk-sensitive Stem

## 1. Fully specified known stochastic dynamics and entropic recursion

Take four independent fair binary variables: initial state `X∈{-1,+1}`, initial preference `P0∈{0,1}`, and transitions `ε1,ε2∈{-1,+1}`. Set `P1=P0 xor 1[ε1=+1]` and `P2=P1 xor 1[ε2=+1]`. The forward Stem uses **two actual trainable parameters**:

\[
H_1=aX,\quad H_2=bH_1+\tfrac14(a-b)^2+\tfrac1{10}\varepsilon_2.
\]

Set stage cost `P1/20`, terminal target `X+1`, and terminal cost `(H2-X-1)^2+P2/50`. Both successive conditional certainty equivalents are *strictly risk-sensitive*: `ρ0=1/2`, `ρ1=1`, discount `γ=9/10` at each step. The parameter penalty `(a²+b²)/4` lies outside the risk expectation. All 16 terminal branches are enumerated exactly (not sampled); the preference law and primitive dynamics are known.

This is different from R17: the second-stage random disturbance is `ε2/10` rather than `ε2 X/10`, and the terminal target is `X+1`. In particular, the preceding proof's `C(t,d)=C(t,-d)` symmetry does *not* hold.

## 2. Exact nonconvex-to-convex two-dimensional equivalence

Write

\[
t=ab,\quad d=\frac{(a-b)^2}{4}.
\]

Then every real `(a,b)` produces `d≥0`, `t+d=(a+b)²/4≥0`, and the *entire* nested entropic stochastic objective depends on both `t,d`, denoted `C(t,d)`. Conversely, **every** point of the closed convex wedge

\[
K=\{(t,d):d\ge0,\;t+d\ge0\}
\]

has real parameter representatives. The penalty identity is exact:

\[
\frac{a^2+b^2}{4}=\frac t2+d,
\]

hence

\[
\min_{a,b\in\mathbb R}J(a,b)=\min_{(t,d)\in K} F(t,d),\qquad
F(t,d)=C(t,d)+\frac t2+d.
\]

This is genuinely **two-dimensional**: the shifted problem's optimum satisfies `t*>0`, `d*>0`, and the global derivative normal to `d=0` is strictly negative at the candidate. It is *not* the R17 one-dimensional lower envelope and does not require offset-evenness. It **does** rely on a special exact quotient representation, not on a generic global method for arbitrary neural networks.

For every individual terminal branch, the residual as a function of `t,d` is
`z=X(t-1)+d-1+ε2/10`, whose Hessian of squared error is `2 v vᵀ`, `v=(X,1)`. A positive-risk two-point entropic certainty equivalent has Hessian equal to a weighted mean of its branch Hessians plus a positive-semidefinite risk-weighted covariance of gradients. Applying this twice, including two factors `γ`, yields at fixed `(X,P0)` a Hessian lower bound `2γ² vvᵀ`. After averaging the independent symmetric `X`, `E[vvᵀ]=I`. Thus **for every real `(t,d)`**,

\[
\boxed{\nabla^2F(t,d)=\nabla^2C(t,d)\succeq 2\gamma^2 I=\tfrac{81}{50}I.}
\]

This is an analytical *global* proof of strong convexity for the quotient objective.

## 3. Exact rational gradient enclosures

A candidate discovered during **pre-protocol exploratory numerical scouting** was frozen as exact rational forward weights:

\[
\hat a=\frac{1669246516087578580991543}{10^{24}},\qquad
\hat b=\frac{416891900252459728989673}{10^{24}}.
\]

Their exact quotient values are `t_hat=a_hat*b_hat`, `d_hat=(a_hat-b_hat)²/4`. The checked implementation computes the gradient of the actual nested entropic certainty equivalents using only exact `fractions.Fraction` and **outward-directed fixed-point intervals with denominator 10^65**. The probability weights are computed with bounded exponential/logarithm/tanh expressions, without using a numerical root as proof input.

For |y|≤1, the 36-term exponential Taylor remainder is bounded by `2/37!`. For the log representation `log v=2 atanh((v-1)/(v+1))` on `|z|≤1/2`, the 12-term remainder is bounded by `4|z|^25`. Every operation is outward rounded, and code raises an error if a required series domain is violated. The hyperbolic cosine is enclosed by two independent exponentials with its analytic lower bound `cosh≥1`. No machine-float computation participates in these inequalities.

Let `g=(F_t(t_hat,d_hat),F_d(t_hat,d_hat))` and `E` be the sum of both *outward-certified coordinate magnitudes*; thus `||g||₂≤||g||₁≤E`. Strong convexity implies for the exact unconstrained minimizer `z*=(t*,d*)`:

\[
\|\hat z-z^*\|_2\le E/m,\qquad
F(\hat z)-F(z^*)\le E^2/(2m),\quad m=81/50.
\]

The exact computed quotient radius is less than `9.742×10^-25`, and the strict positive-distance checks prove that `d*>1/4` and `t*+d*>1` — the minimizer is interior to `K`. Therefore the unconstrained optimum equals the *global* constrained optimum. The rigorous population regret is less than `7.687×10^-49`.

On the verified compact neighborhood, the inverse map `a=sqrt(t+d)+sqrt(d)`, `b=sqrt(t+d)-sqrt(d)` has coordinate derivative-sum at most 2; hence the candidate's individual parameter-coordinate distance to its corresponding exact global solution is less than `1.949×10^-24`. There are four global weight solutions obtained by swapping the pair and simultaneous sign reversal, all with the same `t*,d*`.

## 4. Genuine additional channel and two matched restrictions

For the entire class `a=b`, `d=0`; by the global strong-convexity inequality every such policy incurs true population regret **greater than 0.124530095**. For `b=0`, `t=0`, the corresponding rigorous regret bound is **greater than 0.392258976**. At the candidate `t_hat`, the independent outward gradient calculation gives `F_d(t_hat,0)<-0.64458`, proving that the non-product channel is not a dispensable dummy coefficient.

Against the risk-neutral comparator, whose exact optimal quotient for this shifted affine residual is `(t0,d0)=(56/81,31/81)`, the positive-risk optimum has certified shifts `t*>t0+0.0045373`, `d*>d0+0.0093819`. These are genuine nonzero-risk changes to the learned forward solution.

## 5. Independent global proof for the zero-shift ablation

The separate ablation changes only the terminal target to `X` but keeps the same uncorrelated noise, risks, and dynamics. It is *not* justified by the shifted candidate's certificate. For **every** real `t`, at `d=0`, the symmetric input cancels the linear `2X(t-1)` term. Since `|tanh|≤1`,

\[
\partial_d F(t,0)\ge 1-2\gamma^2\cdot\tfrac1{10}=0.838>0.
\]

Global convexity in `d` therefore makes `d=0` uniquely preferable for all `t` on the enlarged half-plane. The one-dimensional restriction `F(t,0)` is globally `m`-strongly convex; its unique minimizer is positive, so it lies in `K`. This yields an **independent valid global control certificate**, with rational `a=b=834232264397470736714151/10^24`. Its exact rational interval quotient-gradient proof gives cost regret less than `5.596×10^-49`; minimizers are the two simultaneous sign choices `a=b=±sqrt(t*)`.

## 6. Actual evidence and limitations

All 64 fitting runs use original random-law enumeration and finite-tree derivatives without consulting either certificate. The fit output is sealed before the independent audit classifies success. FP64 optimizer end-point classification uses certified reference neighborhoods and an explicit `1e-12` float roundoff guard. This classification itself is a reproducible *numerical check*, not separately interval-enclosed per individual model.

This exact global theorem is valid for a **known finite-state, two-step, positive-risk, quotient-convex but parameter-nonconvex** architecture. It is not a theorem for arbitrary non-convex deep Stem networks, non-affine unknown world dynamics, continuous input laws, general multiperiod coupled FBSDEs, viscosity solutions, or LLM/world-model training. No native Neuron hardware or main/production acceptance is implied.
