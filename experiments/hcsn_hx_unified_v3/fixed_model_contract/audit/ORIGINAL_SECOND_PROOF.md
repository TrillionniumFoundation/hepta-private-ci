# Uniform fixed-model local polynomial proof (research)

The polynomial is in exact absolute gap w=V-B*, not in a log computed at runtime and not at a floating replacement boundary. The full prior allowed interval 0<log(V/B*)<=2^-19 is retained; its representable binary64 endpoints are rounded inward with whole-ball comparisons. The immediate outside neighbors are verified outside. Thus every accepted binary64 input has d_min<=w<=D, both strictly bounded using the exact-root ball.

From the SAME literal A7 function with fixed B*, evaluated as an Arb series, obtain c2,c3,c4 at V=B*. The independently established free-boundary identity gives E(B*)=E'(B*)=0 exactly. No interval-centred IVP is reset to zero elsewhere. On a single interval of centres containing every V between B* and Vmax, the fifth Arb series coefficient encloses E^(5)(V)/5!. With M its absolute upper bound, Taylor's real Lagrange theorem gives

    E(V)=P(w)+R, P(w)=w²(c2+c3*w+c4*w²), |R|<=M*w^5.

Arb series' formal O term is NOT itself treated as an error certificate; the interval-centre derivative enclosure and Taylor theorem supply it. The root ball's thickness remains in both coefficient calculations and the interval of centres. This relies on the same reviewed exact-root identity and trusted rigorous arithmetic as the preceding oracle, not on new sample fitting.

Let u=2^-53. Store Bhi and Blo as exact binary64 constants, with |B*-(Bhi+Blo)|<=rho. V-Bhi is exact by Sterbenz for all accepted inputs. The second subtraction gives y=fl((V-Bhi)-Blo). Under IEEE754 binary64 round-to-nearest ties-even, normal nonoverflowing arithmetic,

    |y-w| <= u*|w+rho_actual|+|rho_actual| <= beta*w,
    beta = u+(1+u)*rho/d_min.

Set H=(1+beta)D. Conversion error for each coefficient is enclosed separately as eps_i=|chat_i-c_i|. A positive exact-value lower factor is

    L = lower(c2)-|c3|D-|c4|D²-MD³ >0,
    E(V)>=w²L.

The four error contributions divided by w² are bounded by:

    remainder: M D³;
    argument: beta[2|c2|(1+beta)+3|c3|(1+beta)²D+4|c4|(1+beta)³D²];
    coefficients: (1+beta)²[eps2+eps3 H+eps4 H²];
    arithmetic: gamma6 (1+beta)²[|chat2|+|chat3|H+|chat4|H²],
    gamma6=6u/(1-6u).

Argument error uses the mean-value theorem between w and y. The coefficient term is evaluated at y. The arithmetic term is standard absolute forward error for the four-operation Horner calculation and two multiplications forming y²*Horner(y); no transcendental library calls or fused contraction are used. Division of the sum by L gives the uniform relative error bound. The precomputation verifies normal/finite margins for intermediates; even the smallest gap/output are far above underflow. Bound is conditional on the stated IEEE environment, not a proof that arbitrary Python builds or changed rounding modes obey it.

The second-model precompute gives relative bound below1.008408e-15 across ALL accepted float inputs, not just the five samples. The pre-frozen acceptance budget is2^-40. Only after this whole-domain bound is established may a fast candidate be generated. Runtime source and validation follow independent proof review.

## Explicit normal-intermediate induction added after independent review

The original h1/h2 boxes enclosed unrounded operations only. The final precompute additionally uses endpoint intervals (not midpoint-radius boxes near zero) and follows every operation in runtime order. For each exact intermediate interval [l,h], it first proves same nonzero sign, magnitude above2^-1022 and below2^100, then encloses RN by multiplying positive endpoints by(1-u,1+u), or reversing these factors for negative endpoints. This rounded interval feeds the next operation. It includes multiplication C4*y, addition C3, multiplication y, addition C2, y² and final product. Thus earlier rounding is propagated rather than ignored when proving normality. The final result interval is bounded below by3.04070722192e-32. COEFFICIENTS.json retains all six rounded intermediate enclosures.

The startup format check and nearest-even probes are smoke checks, not proof against arbitrary later fenv mutation. The certificate assumes the trusted CPython IEEE RN environment remains unchanged for each call. No claim covers other runtimes, reassociated/FMA code generation, hostile mutation of module constants, or changed rounding modes.

## Root and local solution identity needed by the polynomial

For the frozen positive-payout tuple, r,delta,sigma,m,P,q>0 and recovery/tax fractions are in[0,1]. In log-distance x, a=(r-delta-sigma²/2)/sigma², z=sqrt(a²+2r/sigma²), eta=z-a>1 and gamma=z+a>0. The original equation11 is

    (sigma²/2) E_xx + (r-delta-sigma²/2) E_x - r E = -f_B(x),
    f_B(x)=delta*B*exp(x)+d(x;B)-(1-pi)C-P/m.

The smooth-fit integral I(B)=delta*B/(eta-1)+integral exp(-eta*y)[d(y;B)-(1-pi)C-P/m]dy is affine, with derivative >=delta/(eta-1)>0. `verify_root.py` proves strict signs at exact rational endpoints64.62517667 and64.62517668. It integrates the payout exactly to infinity and encloses the ENTIRE remaining debt tail by96*exp(-40eta)/eta, justified by nonnegative path payoff. This is not a truncated asymptotic debt substitution. Existence/uniqueness and strict guard alpha*B<min(P,C/q) follow. The paper's equation12 identity identifies the enclosed closed-form root used by `oracle.py` with this exact unique root.

At that root, E(0)=E_x(0)=0. Variation of constants gives the exact stable finite integral

    E(x)= -2*x/(sigma²*z) integral_0^1 exp(-a*x*(1-t))*sinh(z*x*(1-t))*f_B(x*t)dt.

The oracle compares this expression with independently evaluated literal A7 at the same exact root. For an arbitrary nonroot B it retains the initial-slope term2I(B)/sigma²; such a solution is not silently equated with literal off-root A7.

For completeness the sufficient positivity argument is limited: the guard makes the pathwise debt nondecreasing in x, so delta>0 makes f strictly increasing. Smooth fit gives its exp(-eta*y) weighted integral zero. In H=exp(-eta*x)E, H' has sign opposite the primitive integral_0^x exp(gamma*y)f(y)dy. That primitive starts negative and crosses at most once. H rises then falls, H(0)=0 and H(infinity)=0 because eta>1 and equity has linear growth; hence E>0 for x>0. The polynomial's local positive lower bound is also directly certified, without treating a five-point test as a theorem. No claim extends these arguments to delta=0 without a separately specified high-value normalization.

## Second frozen model identity

This copied proof uses only the exact tuple in PLAN.json (delta=2/25, m=3, alpha=3/20, k=2/25). Its root enclosure and sufficient guard are rebuilt in ROOT_PROOF.json. It does not inherit the default model numerical certificate. precompute.py is byte-identical to the reviewed #4663 package. The numerical proof and RN premises remain conditional and restricted, not a generic parameter engine.
