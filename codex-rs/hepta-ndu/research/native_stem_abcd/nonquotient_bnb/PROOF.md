# R19 global cost certificate for a parameter-nonquotient forward Stem

## Finite known law and broken exact convex quotient

Retain R18's 16 equally weighted leaves, X and two epsilon values in {-1,+1}, P0 in {0,1}, two stochastic preference flips, gamma=9/10, strictly positive nested entropic risks 1/2 and 1, first-stage P1/20, terminal cost (H2-X-1)^2+P2/50 and weight penalty (a²+b²)/4. The new forward is

```
H1 = a*X
H2 = b*H1 + (a-b)^2/4 + epsilon2/10 + q(a)
q(a) = a / (25*(1+a*a)).
```

The old quotient coordinates (t,d)=(ab,(a-b)²/4) are unchanged by (a,b)->(-a,-b), but q(a) changes sign. Thus this is **not** a convex optimization over independent (t,d) and R18's exact global-minimizer theorem cannot be reused.

## A rigorous auxiliary global lower-bound envelope

Define u=d+q(a) and F(t,u)=C(t,u)+t/2+u, where C is the actual two-stage fully enumerated entropic objective. Then **exactly**:

```
J(a,b) = F(ab, (a-b)^2/4 + q(a)) - q(a).
```

R18's independent algebraic proof supplies the global Hessian inequality Hess F >= mI, m=81/50, for all real (t,u); it is a property of the auxiliary function, **not an exact convexification of J in a,b**. Fix rational candidate (ac,bc)=(164044199/100000000,42331393/100000000), with zc=(ac*bc,(ac-bc)²/4+q(ac)), qc=q(ac). R18's checked Fraction/10^65 outward Taylor enclosures supply independent rational bounds |(grad F(zc))_i|<=ei for both coordinates i in {t,u}. Applying the global strong-convexity inequality coordinate by coordinate and completing the square yields, for all real a,b,

```
J(a,b)-J(ac,bc) >= qc-q(a) - (et^2+eu^2)/(2*m)
       + (m/2) * sum_i (abs(zi-zc_i)-ei/m)_+^2 .
```

This lower bound is valid for every parameter, irrespective of local Hessian of J.

## Verified rational interval subdivision

For each box B=[al,ah]x[bl,bh], exact Fractions bound t=ab via its corner products; d=(a-b)^2/4 via a squared difference interval; q(a) via rational endpoint values and the only real stationary locations a=±1 (if contained). These bounds produce interval enclosures [ti_lo,ti_hi], [ui_lo,ui_hi]. Their distances Di(B) to the fixed zc coordinates give a **boxwise rational** certificate:

```
LB(B) = qc-qmax(B) - (et^2+eu^2)/(2*m)
      + (m/2)*sum_i max(0,Di(B)-ei/m)^2 .
```

All stage and terminal costs are nonnegative. For risk rho>0, entropic certainty-equivalent of nonnegative costs is nonnegative, so J(a,b)>=(a²+b²)/4. Outside [-3,3]^2 the objective is >=9/4. An exact rational candidate upper bound based on CE_r(v)<=max(v) for each finite branch proves J(ac,bc)<1.618<9/4. Hence **every global minimizer lies in [-3,3]^2** and we do not silently assume a bounded parameter space.

The algorithm splits the initial box into two exact dyadic children and retains BOTH on a full frontier. It may use float priorities to choose which rectangle to inspect next; **priority rounding never enters bound calculations or acceptance**. The final certifying lower value is the exact Fraction minimum across the entire retained frontier (the full box cover), so scheduling ties or float priority errors cannot turn an invalid gap into a valid one.

## Registered result and independent post-hoc tightening

Registered R19 requirement was GLOBAL cost suboptimality <=1/1000 in at most 50,000 box splits. The first full valid frontier needs only **16 splits** and certifies for the fixed rational candidate:

```
0 <= J(ac,bc)-inf_{a,b in R}J(a,b) <= 0.000698987671409
```

As a **supplementary sensitivity analysis after the registered result**, 53 splits yield the even tighter valid bound:

```
0 <= J(ac,bc)-inf_{a,b in R}J(a,b) <= 0.000097943429123
```

Neither analysis uses gradient-stationarity as a global-optimum oracle. Neither locates or proves the uniqueness of the actual global optimizer. The stronger threshold is not used to change retrospective fitted-run qualifications. The full exact-rational certificates, all retained frontier rectangles, and per-file hashes are independently bundled with actual run evidence.

## Scope and negative evidence

The learning problem is genuine two-step stochastic NDU with known nonzero entropic risk and a nonlinear parameter-specific forward channel, but only two weights and an inherited strongly convex auxiliary population functional. This is a strict **global cost gap** certificate, not a general interval branch-and-bound theorem for arbitrary deep neural FBSDE, nonstationary unknown-world dynamics, Transformer/LLM training or hardware deployment. No R18 historical outcome or global CI gate is waived.
