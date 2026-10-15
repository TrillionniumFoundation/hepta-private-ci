# R24: exact Bernoulli-risk elimination and globally valid residual tangents

## Scope and original stochastic population

The inherited R21 model has parameters θ=(a,b[,c[,d]]) and X∈{-1,+1}, P0∈{0,1}, ε1,ε2∈{-1,+1} all independent and equiprobable. There are 16 elementary scenarios. P1=P0 xor [ε1=+1] and P2=P1 xor [ε2=+1]. Risk parameters are ρ0=1/2 and ρ1=1; discount γ=9/10. Stage preference cost is P1/20, terminal loss (H2-X-1)²+P2/50, and weight penalty ||θ||²/4 is outside the two entropic CEs. All candidate parameter vectors and cube [-3,3]^n match the R21 archive exactly. There is NO retraining in this round.

For x fixed and θ fixed, write z_x(θ)=H2_noeps2(θ,x)-x-1. It is a deterministic rational expression of learned θ for this fully known model. Crucially, it does not depend on ε1 or ε2. Conditional on P1=p, the two ε2 terminal costs are (z-1/10)²+p/50 and (z+1/10)²+(1-p)/50, respectively. Their mean is z²+1/50, and their half-difference is z/5+(1-2p)/100. Thus the **exact** inner conditional entropic certainty equivalent has the closed form

\[
Q_p(z)=\frac p{20}+\gamma\left(z^2+\frac1{50}+\frac{\log\cosh(\rho_p[z/5+(1-2p)/100])}{\rho_p}\right).
\]

Because ε1 swaps P1=0 and P1=1 equiprobably, the remaining outer CE for initial preference p0 is

\[
F_{p_0}(z)=\gamma\left[\frac{Q_0(z)+Q_1(z)}2+
\frac1{\rho_{p_0}}\log\cosh\!\left(\frac{\rho_{p_0}}2[Q_1(z)-Q_0(z)]\right)\right].
\]

Therefore the original **full finite-tree objective**, not an approximation to it, equals

\[
J(\theta)=\frac14\sum_{x\in\{-1,+1\}}\sum_{p_0\in\{0,1\}}
F_{p_0}(z_x(\theta))+\frac14\sum_i\theta_i^2.
\]

## Certified scalar strong convexity, not parameter convexity

Each inner ε2 branch payoff has second derivative exactly 2 with respect to z. Positive-risk logsumexp preserves convexity, and its second derivative equals an average of branch Hessians plus a nonnegative conditional variance. Thus the inner CE has second derivative ≥2. Hence Qp''≥2γ. The outer CE again preserves that bound and multiplies by γ, yielding the global scalar inequality

\[
F_{p_0}''(z)\ge2\gamma^2=\frac{81}{50}=:m
\quad\text{for every real }z.
\]

This does **not** imply that J is convex in θ because z_x(θ) is nonlinear in θ. We use only scalar strong convexity to construct valid lower bounds.

At any rational anchor z0, exact outward rational intervals enclose F(z0)∈[L,U] and F'(z0)∈[gL,gU]. Consequently for every real z and every g in that derivative interval,

\[
F(z)\ge L+g(z-z_0)+\frac m2(z-z_0)^2.
\]

For a parameter box B, calculate a rational inclusion [l_x,u_x] for every residual z_x(B) using the existing R21 interval arithmetic. With Δ∈[l_x-z0,u_x-z0], minimize the quadratic lower expression exactly over Δ and the two derivative interval endpoints. This produces a lower bound valid at *every* θ∈B. Taking the maximum over all 33 fixed public anchors z0∈{-4,-15/4,...,4} preserves validity.

### Certified transcendental evaluation

At any rational input y, calculate e^{-2|y|} using the degree-30 even and degree-31 odd alternating sums for e^{-v} at v∈[0,1], reducing arguments by exact repeated halving and restoring with interval squaring. All arithmetic bounds are rounded **outward** to integer multiples of 10^{-36}. Then obtain

\[
\log\cosh y=|y|-\log 2+\log(1+e^{-2|y|}).
\]

Compute log(1+u) from the positive atanh series (u/(u+2)∈[0,1/3]) using 25 terms and the explicit positive tail

\[
0\le R_{25}\le\frac{2r^{51}}{51(1-r^2)}.
\]

No floating transcendental value enters any proof bound. `mpmath` at 90 decimal digits independently checks the interval inclusions and original 16-leaf identity, but does not supply certification premises.

Finally for the parameter box,

\[
L_{24}(B)=\max\Bigl(L_{22}(B),\ \frac14\sum_{x,p_0} \underline F_{p_0}(z_x(B))
+\frac14\sum_i\underline{\theta_i^2}\Bigr)
\]

is a rigorous lower bound. R24 has not used R19's globally convex parameter auxiliary problem or a neural-parameter Hessian lower bound. It still assumes a known **finite** stochastic law and residual independence from inner branches, so it is not a generic FBSDE proof.

## Global box coverage and outside-domain proof

All branches start from [-3,3]^n and bisect one widest coordinate exactly, giving a partition of the parent interval at each step. A box is discarded only if its certified lower bound is at least the unchanged candidate upper. All active frontier boxes and the candidate lower form a global lower. Outside the cube some |θ_i|≥3 and the nonnegative stage/terminal cost plus ||θ||²/4 gives J≥9/4, strictly above each saved candidate upper. Thus the final exact gap certificate covers all real θ, not only the cube.

## Exact independently feasible witness and a provable impossible target

A *post hoc* independent witness is selected among the **already trained, frozen R21 weights**. Its binary64-hex vector is converted exactly to a Fraction dyadic, its SHA-256 identity checked and its cost rigorously enclosed by R21's original rational interval evaluator. The R21 full ZIP SHA256 is **75b7f84db4fa749c48b502c4ff1fe23af02e8b7fa5fd045f99c487e80c1f1d99**, and its original 120-row weight-index SHA256 is **cb548fed6aa074b8494cc47d4860d6f18ba82c40810f4279429d8936559148c5**.

For width 3, the R21 pre-fixed candidate has proven J(candidate)≥0.6670003697789101, whereas **w3-s6-bfgs** is a rigorously feasible point with J(witness)≤0.6518681756413304. Therefore

\[
J(\theta_{\mathrm{candidate}})-\inf_\theta J(\theta)
\ge J(\theta_{\mathrm{candidate}})-J(\theta_{\mathrm{witness}})
>0.0151321941375>0.01.
\]

**No globally sound certification algorithm can make THIS FIXED 3-parameter candidate pass 0.01**, however many splits it uses. This is a certified counterexample to treating proof failures as purely interval-solver inefficiency. It does not imply that the 3-parameter architecture or other trained models cannot satisfy 0.01. Width 4 has only a known candidate-vs-witness lower gap around 0.006139, so the analogous impossibility claim is *not* established there.

## Verification and limitations

The read-only audit checks every B&B split and all active/pruned/frontier identifiers for exact cube coverage, every original JSONL hash, exact final rational gap, source SHA256 identity (including unchanged original R21/R22 inherited math), and 1,134 deterministic exact box-bound recomputations. It does NOT recompute every one of the 8,525 expensive bounds. Tests compare rational analytical expressions with independent `mpmath` 16-branch evaluations. This is not an interval certificate for arbitrary real-world learned dynamics, general neural Stem training, FBSDE viscosity theory, LLM quality or whole-project deployment.
