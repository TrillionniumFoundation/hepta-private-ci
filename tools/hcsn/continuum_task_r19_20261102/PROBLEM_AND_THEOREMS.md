# The actual R18 delayed-reset diffusion: continuum theorem draft

Status: proof draft for independent mathematical review. No new convergence or
boundary-location experiment has been run in this directory. Results below
concern the exact declared synthetic R18 task, not the full He–Xiong model,
semantic learning, continuum parameter gradients or production execution.
Numerical residuals are not used as proofs of any theorem here.

## A. Exact problem and assumptions

Let I=[a,b]=[−4,4], L=b−a, σ>0, ρ>0 and modes j∈{0,1}. During active waiting,
X is normally reflected Brownian motion on I with generator D∂xx, D=σ²/2.
The mode is observed and constant until a completed reset. STOP at (j,x) has
an actual Bernoulli reward with conditional mean g_j(x). Its future realization
is unavailable to the actor. Expected-reward optimization is therefore exactly
the problem with deterministic terminal payoff g_j(x).

Assume 0≤g_j≤1 and g_j Lipschitz, c≥0, κ_j:=k_j+c_recρ≥0, M a stochastic
nonnegative two-by-two matrix, and x_r∈I. A reset pays κ_j, permits no decision
during its fixed recovery ρ, and at completion sets X=x_r and samples the next
observed mode from row M_j. It may start only if it finishes by the deadline,
including equality. All later decisions use the actual remaining time.

A strategy is nonanticipating for the public process and revealed reset marks;
it cannot inspect unread mode/reward randomness. STOP is always allowed and is
mandatory by the deadline. From horizon t a strategy has N≤floor(t/ρ) resets.
Writing W for total active WAIT time, its objective is

    E[g_(J_STOP)(X_STOP) − c W − Σ_(resets) κ_(mode before reset)].

Recovery time itself is not active WAIT; its charge is already in κ. Let U_j(t,x)
be the supremum over these strategies. Define U_j(0,x)=g_j(x). Positive delay
bounds N independently of costs and excludes an instantaneous intervention loop.
Immediate STOP and the payoff bound imply g_j(x)≤U_j(t,x)≤1. Extra remaining
time never removes a strategy, so U is nondecreasing in t.

## B. A single continuous-slab stopping operator

For continuous initial data z(x), continuous obstacle h(s,x) on [0,S]×I and
z≥h(0,·), define

    S[z,h](s,x)=sup_(0≤τ≤s) E_x[
        1_(τ<s) h(s−τ,X_τ) + 1_(τ=s) z(X_s) − cτ].            (B.1)

At s=0 the terminal convention returns z. This matters: waiting until a slab's
lower remaining-time endpoint accesses the already available right-valued
continuation value, not a discarded left obstacle.

Lemma B1 (continuous stopping slab). For bounded Lipschitz-in-space data and
continuous h, (B.1) is continuous jointly in (s,x), dominates h, equals z at
s=0, and has the dynamic-programming property. It is the unique continuous
viscosity solution of

    min(w−h, w_s−D w_xx+c)=0,                               (B.2)

in the canonical reflected/Neumann sense specified in section C. If z and all
h(s,·) have spatial Lipschitz constant at most K, so does w. If both are
nondecreasing in x, so is w. The same statement gives ε-optimal Markov stopping
rules; an exact boundary-hitting rule is not needed for later conclusions.

Proof details. On a finite time partition the recursion is a finite maximum
of immediate obstacle values and the reflected heat semigroup applied to the
next value minus elapsed carry. It is continuous in x. The reflected semigroup
satisfies

    (P_N(t)f)' = P_D(t)f',

first for smooth f by the cosine/sine heat kernels and integration by parts,
then for Lipschitz f by approximation. P_D is positive and sub-Markov. Thus
spatial monotonicity and the K bound survive every semigroup/max recursion.

To approximate any stopping time, round it upward to a refining partition
containing both0 ands. It remains a stopping time and converges almost surely.
For τ<s it eventually stays before s and uses the continuous obstacle; for
τ=s it remains s and uses z. Continuity of X and bounded convergence prove
convergence of expected payoffs. Hence the finite recursion increases to(B.1)
along nested partitions and the spatial bounds persist. The construction also
provides Borel ε-optimal rules; this avoids an unspecified policy-selection
assumption when slabs are concatenated.

For time continuity, compare horizons s ands+δ. A rule with τ>s can be truncated
at s: its final obstacle is bounded above by z at the nearby position plus the
time modulus of h, since z≥h(0). A rule ending exactly at s can instead wait to
s+δ. The two errors are bounded by the modulus of h overδ, the expected modulus
of z over a reflected displacement duringδ, and cδ. They tend uniformly tozero.
This proves continuity at s=0 as well as inside the slab. For joint policy
selection take the relative dyadic partitions {rs/2^n:0≤r≤2^n}. Their finite
Bermudan values are jointly continuous in(s,x), increase with n, and converge
to the now-proved continuous limit. Dini's theorem on a compact trace slab
therefore gives a single mesh with uniform ε accuracy. Its finite maximum
rules are Borel in(s,x), supplying the joint ε-optimal family needed for reset
concatenation. The same partition recursion and stopping-time concatenation
give DPP.

DPP permits a small compulsory wait and implies the viscosity supersolution
inequality. In an open set where w>h, ε-optimal stopping cannot exercise with
nonnegligible probability before a sufficiently small exit time: the strict
obstacle gap would lose a fixed amount. Apply DPP and Itô's formula to an upper
test, with ε=o(exit-time scale), to obtain the subsolution inequality. This is
the local stopping argument, not an assumption of classical derivatives of w.
Comparison is proved in C.                                       □

## C. Exact fold representation and comparison

Let q be the globally1-Lipschitz triangular fold from the circle of circumference
2L onto I. At points in I it is the identity. The Neumann heat semigroup is
exactly intertwined with Brownian heat on that circle:

    P_circle(t)(f∘q) = (P_N(t)f)∘q.                          (C.1)

The heat kernel/image construction proves(C.1). Finite stopping recursions
commute with q, and the preceding stopping-time approximation passes this
identity to(B.1). Thus the circle and observed reflected-state stopping values
coincide; observing a fold phase supplies no extra value. The lifted initial
and obstacle functions are continuous/even. A sigmoid payoff may have a cusp
at a fold; no false classical endpoint compatibility g'(a)=g'(b)=0 is imposed.

We use this exact folded formulation as the canonical Neumann problem. For a
classical continuation point at an endpoint the normal derivative is zero.
If an interval viscosity formulation is used, its boundary convention must be
the relaxed one: an upper test satisfies min(F,∂nφ)≤0 and a lower test satisfies
max(F,∂nφ)≥0, F=min(w−h,φ_s−Dφ_xx+c). Classical normal slope at an active
exercise payoff is not demanded. The comparison proof below is stated directly
for the folded problem, so it does not import an undocumented converse for an
arbitrary weak boundary convention.

Lemma C1 (scalar comparison, including ordered obstacles). On a time slab of
the circle, let u be a bounded upper-semicontinuous viscosity subsolution with obstacle
h1, v a bounded lower-semicontinuous supersolution with obstacle h2, h1≤h2,
and ordered continuous initial traces. Then u≤v.

Proof. A supersolution lies above h2; otherwise a localized lower test would
violate the first component of the obstacle inequality. Strictify u by
subtracting ηs+ε/(S−s). A positive doubled-variable maximum against v occurs
away from the initial/upper time edge; for nearby spatial points u>h1, so its
heat inequality applies. The parabolic maximum lemma gives time jets α=β
and spatial jets X≤Y. Subtracting the two PDE inequalities yields

    0 ≤ −D(X−Y) ≤ −η,

a contradiction. Let ε,η↓0. Periodic distance is smooth near the limiting
doubled points, so the circle has no boundary term. The precise maximum-lemma
dependency is CIL Theorem8.3. Localization above the obstacle can be made by
locally taking the maximum with a lower affine-in-time heat subsolution that
still lies strictly above h1; at the positive contact this preserves u and
supplies the local heat-jet bound. Thus semicontinuous half-relaxed limits, not
only continuous trial solutions, are covered.                                     □

This proves uniqueness in B1 after the exact lift. It also permits ordered
initial data and ordered obstacles, the properties needed below. It does not
assert global time continuity across the delayed-reset admissions.

## D. Strict causal recursion and identification with the control value

Write κ=k+c_recρ and evaluate mode vectors at x_r. Set G0=g. Construct continuous
slab functions W_k(s,x), 0≤s≤ρ, recursively:

    h_0(s,x)=g(x),                 W_0=S[G0,h_0],
    b_k(s)=−κ+M W_(k−1)(s,x_r),
    h_k(s,x)=max(g(x),b_k(s)),     W_k=S[Gk,h_k]       (k≥1),
    G_(k+1)(x)=max(W_k(ρ,x), −κ+M G_k(x_r)).                      (D.1)

All maxima in(D.1) are componentwise. G_k≥h_k(0) by construction, so every
slab has compatible initial data. Define

    U(kρ+s,x)=W_k(s,x), 0≤s<ρ;       U(kρ,x)=G_k(x).             (D.2)

The upper endpoint W_k(ρ) is the left limit at(k+1)ρ, not the new right value.
The recursion uses only earlier slabs; it is not a simultaneous nonlocal fixed
point with an unverified contraction assumption.

Theorem D1 (value, comparison and time contract). For each finite horizon,
(D.1)–(D.2) equal the admissible control value. They are uniquely determined in
the class continuous on each closed trace slab and right-valued at admissions.
The map t↦U(t,·) is càdlàg in C(I), can jump only at multiples ofρ, and satisfies

    U_j(kρ,x)=max(U_j(kρ−,x), B_j(kρ)),
    B_j(t)=−κ_j+Σ_l M_jl U_l(t−ρ,x_r), t≥ρ.                    (D.3)

It is spatially Lipschitz and, for nondecreasing payoffs, nondecreasing in x.

Proof. Before the first admission, Lemma B1 gives the ordinary no-reset stopping value.
Assume all earlier slabs identified. Within the next slab, a first STOP/RESET
before reaching its lower endpoint has exactly the obstacle in(D.1), including
the earlier full successor. Waiting to the endpoint accesses G_k. First-action
conditioning and the strong Markov property give the upper bound(B.1).
Concatenating its Borel ε-optimal rule with the already constructed earlier
mode rules gives the lower bound, with only finitely many reset stages.

At t=(k+1)ρ, an immediate RESET accesses −κ+M G_k. Immediate STOP is already
bounded by W_k(ρ). Any strictly positive initial wait moves the horizon below
(k+1)ρ; its value is bounded by W_k(ρ) through that slab's stopping DPP. Conversely,
waiting an arbitrarily small positive duration and then using earlier rules
approaches W_k(ρ) by uniform spatial/time continuity. Randomization at timezero
cannot exceed the maximum of these alternatives. This proves the admission
rule and identification by finite induction.

Every W_k is continuous on its compact closed slab; G_(k+1) is a continuous
spatial maximum. Hence(D.2) is right-continuous with uniform spatial left limits.
Only the finite admission set can jump on a finite horizon. Global comparison
follows by slab comparison and induction: M≥0 preserves the order of delayed
obstacles and the admission maximum preserves endpoint order. Applying that
comparison twice gives uniqueness. Spatial bounds follow from B1 and maxima
with constants. Horizon monotonicity also follows directly by embedding any
shorter-horizon strategy in the longer admissible set.              □

The theorem does not prove differentiability at admissions or of an ordinary
parameter derivative that moves their locations. Those are different questions.

## E. Exact continuum discontinuity in the registered baseline task

Use the actual baseline rewards

    g0(x)=1/5+(3/4) sigmoid(13x/10),
    g1(x)=1/10+(2/5) sigmoid(13x/10),

ρ=1/5, x_r=3/5, κ1=29/1000, M1=(1/4,3/4), andσ≤13/10.

Proposition E1. The continuum mode1 value at x=−3/2 has an admission jump atρ
strictly greater than .11175. It is therefore not globally continuous in remaining
time, even before any numerical discretization.

Proof. Exp(.78)>1+.78+.78²/2>2 gives sigmoid(.78)>2/3, hence g0(x_r)>7/10 and
g1(x_r)>11/30. Therefore B1(ρ)>.25*.7+.75*(11/30)−.029=.421.
Exp(1.95)>1+1.95+1.95²/2+1.95³/6>6 gives sigmoid(−1.95)<1/7, so
 g1(−3/2)<11/70. Its Lipschitz constant is at most13/100.

Realize reflected Brownian motion as q(x+σW). The fold is1-Lipschitz, so its
maximum displacement up toρ is at most σ sup|W|. Doob/Jensen give
E sup_(s≤ρ)|W_s|≤2√ρ<.9. No reset is feasible beforeρ and WAIT cost is
nonnegative, yielding

    U1(ρ−,−3/2) < 11/70 + (.13)(1.3)(.9) = .309242857… .

Use(D.3): U1(ρ,−3/2)≥B1(ρ)>.421. The difference exceeds .11175714.             □

## F. An exact all-RESET region, independent of risk and meshes

Proposition F1. In the same baseline task, for everyσ>0, x∈I and t≥3ρ=.6,
U1(t,x)=B1(t), and immediate RESET is optimal.

Proof. Consider the feasible policy that resets while in mode1, stops as soon
as mode0 is sampled, and makes at most n resets. With no active WAIT its return
from mode1 is

    R0=g1(x_r),   R_n=(1/4)g0(x_r)+(3/4)R_(n−1)−29/1000.

The positive cubic Taylor bound for exp(39/50) gives

    sigmoid(39/50)>540823/790823.

Substituting this rational lower bound into the recursion gives exactly

    R3 > 12720913317/25306336000 > 1/2.

Hence B1(3ρ)≥R3>1/2 and, by horizon monotonicity, B1(t)>1/2 for every t≥3ρ.
But g1(x)≤1/2 everywhere. Before the first action the mode remains1; any later
STOP pays at most1/2, and any later RESET accesses B1(t−τ)≤B1(t). Nonnegative
active WAIT cost cannot improve this upper bound. Immediate RESET attains B1(t).
Thus U1=B1 at every x.                                            □

This proves that a continuation band and two contact boundaries need not exist.
It is an actual task result, not a perpetual-put analogue or a grid observation.

## G. What can be asserted about spatial free boundaries

At a fixed t≥ρ, the RESET contact set {x:U_j(t,x)=B_j(t)} is a closed lower
interval, possibly empty or all of I: U is nondecreasing in x and always≥B.
If B_j(t)≥g_j(b), the first-action bound in F proves U_j(t,·)=B_j(t) everywhere.
If B_j(t)≤g_j(b), then U_j(t,b)=g_j(b), since no later obstacle exceeds that
number. Neither statement proves a single upper STOP threshold.

The baseline local WAIT-after-STOP generator test is

    D g_j''−c = (σ²/2) a_j s² p(1−p)(1−2p)−c,
    p=sigmoid(sx), s=1.3.

For interior x≥0 it is strictly negative. On x<0 the cubic factor has maximum1/(6√3).
Atσ=.7 this maximum gives Dg_j''<.03 for both modes. Atσ=1 or1.3 it is positive
at p=1/5 and negative at sufficiently small p and near1/2 for both modes. These
signs identify places where a short WAIT is beneficial; a negative local sign
does not establish that every possible waiting/first-passage strategy is worse.

At the reflecting lower endpoint, g_j'(a)>0. The short-time expansion is

    E_a[g_j(X_δ)]−cδ
      =g_j(a)+σ g_j'(a) sqrt(2δ/π)+O(δ).

For smallδ this exceeds immediate STOP. Therefore the lower endpoint itself
cannot simply be declared STOP. Multiple STOP components or a lower reflection
layer are not excluded. We have not proved a general STOP graph, global smooth
fit, continuous/moving boundary regularity, or general certified narrow boundary
brackets. The one analytic admission bracket below does not settle these
claims. Contact nodes in existing numerical records do not settle them either.

### Proposition G2: one strict coarse RESET-boundary bracket

For the baseline task at t=ρ and every0<σ≤1.3, the mode1 RESET contact right
endpoint exists and satisfies

    −1/4 < b_RESET,1(ρ) < 5/4.                                (G.1)

This is one coarse analytic bracket, not a general narrow boundary error bar.

Proof. The cubic Taylor sum for exp(13/40) exceeds29/21, so
sigmoid(−13/40)<21/50. At x=−1/4, g1(x)<.268. The same Lipschitz/Doob
argument as E1 gives no-reset left value <.268+.1521=.4201, while B1(ρ)>.421.
Thus U1(ρ,x)=B1(ρ) at that point, with a strict left-value gap. Spatial
continuity preserves RESET in a neighborhood to its right.

For the other side, write a_n=(39/50)^n/n!. For n≥3 the successive ratios
are at most39/200<1/5 and a3<2/25. Therefore

    exp(39/50)<1+39/50+(39/50)^2/2+1/10
              =10921/5000 < 11/5.

Hence q=sigmoid(39/50)<11/16, and direct substitution gives

    B1(ρ)<12/125+(39/80)(11/16)=13797/32000.

The Taylor sum through n=5 for exp(13/8) is greater than5. Consequently
sigmoid(13/8)>5/6 and g1(5/4)>13/30>13797/32000>B1(ρ). This point and a
neighborhood to its left cannot be RESET. The already proved closed-lower-
interval structure, nonempty lower neighborhood and strict upper exclusion
give(G.1).                                                       □

## H. Review obligations and next executable work

A separate convergence theorem draft addresses the ideal jump-aware finite-
difference scheme, exact alignment and trace-aware interpolation. Finite-
precision algebraic residual scaling, quantitative errors, boundary nondegeneracy
and location brackets remain separate obligations. No new numerical profile or
boundary-location outcome will be opened until its executable source/protocol
is frozen and published. This draft is not a declaration that all user blockers
are closed.

External proof dependency: CIL(1992), Example1.7 and Theorem8.3, for the obstacle
operator and parabolic maximum lemma. Our positive-delay recursion, fold
application, rational task certificates and remaining obligations are specified
here and are not claimed to be ready-made conclusions of that paper.
