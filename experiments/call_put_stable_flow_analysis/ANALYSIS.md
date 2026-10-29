# Mathematical analysis and limits of the implemented Hepta flow

**Scope.** These are analytical statements about the new implementation frozen
in `research_evidence/hepta_stable_flow_20261029/formal_run001/`, whose protocol
SHA-256 is `f94ff6491a2e98c1288ee2476404943f920042800d468435eba46d5235c0197b`.
They do not recover or certify unavailable older checkpoints. The relevant code
is `call_put_stable_flow/{numerics,flow,memory,models}.py`. Unless explicitly
stated otherwise, proofs concern exact real arithmetic, fixed learned parameters
during a sequence, and the continuous equations; finite-precision and trained
checkpoint claims require their separate numerical evidence.

## 1. What the financial analogy actually supplies

He and Xiong's *Rollover Risk and Credit Risk*, *Journal of Finance* 67(2), 2012,
jointly models debt/equity valuation, debt maturity, market illiquidity and
rollover gains/losses. In particular, its equity cash flow contains newly issued
bond value minus maturing principal, and its bond PDE contains maturity and
liquidity terms; see equations (4)–(5) in the [author-hosted paper][HX].
The production neural equations contain no such bond-pricing/maturity system.

The implemented pair instead has the **reduced perpetual-put construction**

\[
\beta=\frac{\kappa}{1+\kappa},\quad B=\beta K,\quad
P(V;K)=\begin{cases}K-V,&V\le B,\\
(K-B)(B/V)^\kappa,&V>B,\end{cases}\qquad C=V-K+P.
\]

For example, the continuation ansatz \(P\propto V^{-\kappa}\) solves the reduced
GBM valuation ODE
\(\tfrac12\sigma^2V^2P''+\mu VP'-rP=0\) when
\(\tfrac12\sigma^2\kappa(\kappa+1)-\mu\kappa-r=0\).
Value matching and \(P'(B)=-1\) give \(\kappa(K-B)=B\), hence the stated boundary.
This explains the boundary relation; it does not establish that a trained
neuron follows that GBM or that its learned boundary solves a financial or
task-specific optimal-stopping problem.

Here \(C\) is an equity-like residual, not a separately exercisable perpetual
American call. The actual channels are \(a=C/(K+C)\) and \(p=P/K\); \(p\) is
not a calibrated default or spike probability. These distinctions follow from
the implemented definitions, independently of any financial interpretation.

## 2. Channel geometry, regularity and redundancy

Let \(v=\log V,q=\log K,x=v-q-\log\beta\). Thus the actual log boundary is
\(q+\log\beta\), not \(q\). For fixed \(\kappa>0\),

\[
p(x)=\begin{cases}1-\beta e^x,&x\le0,\\
e^{-\kappa x}/(1+\kappa),&x>0,\end{cases}\quad
a(x)=\begin{cases}0,&x\le0,\\
1-(1+\kappa)/D(x),&x>0,\end{cases}\quad
D=\kappa e^x+e^{-\kappa x}.
\]

For \(x>0\), \(D(0)=1+\kappa\) and
\(D'=\kappa(e^x-e^{-\kappa x})>0\). Consequently \(0\le a<1\),
\(a_x\ge0\), \(0<p<1\), and \(p_x<0\) at every finite margin.
The one-sided boundary derivatives are

| Quantity | Left limit at zero | Right limit at zero |
| --- | ---: | ---: |
| \(a\) | 0 | 0 |
| \(a_x\) | 0 | 0 |
| \(a_{xx}\) | 0 | \(\kappa\) |
| \(p\) | \(1/(1+\kappa)\) | \(1/(1+\kappa)\) |
| \(p_x\) | \(-\beta\) | \(-\beta\) |
| \(p_{xx}\) | \(-\beta\) | \(\kappa\beta\) |

For Call, this follows from
\(a(x)=\kappa x^2/2+O(x^3)\) as \(x\downarrow0\).
Both channels are **C1 and not C2** at the boundary. First-order ordinary
backpropagation therefore needs no surrogate spike derivative there; a general
second-order smoothness claim would be false.

At fixed parameters their state Jacobian factors as

\[
\frac{\partial(a,p)}{\partial(v,q,z)}
=\begin{pmatrix}a_x\\p_x\end{pmatrix}(1,-1,0).
\]

Its rank is one. Since \(p\) is strictly decreasing, \(a\) is also a deterministic
function of \(p\) at fixed \(\kappa\). Two channels provide two nonlinear
feedback functions, not two independent state measurements. This does not
reduce the full dynamical state to one scalar: equal current margins can have
different \(v,z\) and different future trajectories, and the associative matrix
is additional state.

The matched control preserves these boundary values/slopes and Call right
curvature but changes global shape. The sigmoid control instead satisfies
\(a+p=1\), so its boundary feedback combines as
\(g_C(a-a_*)+g_P(p-p_*)=(g_C-g_P)(a-a_*)\). Equal tensor counts do not imply equal
functional parameter freedom.

## 3. Feedback signs and local stability

The implemented ODE is

\[
\begin{aligned}
\tau_v\dot v&=-v+I_v,\\
\tau_q\dot q&=-(q-q_*)+g_C(a-a_*)+g_P(p-p_*)-(z-z_*)+I_b,\\
\tau_z\dot z&=-z+g_zp,\\
q_*&=-x_*-\log\beta,\qquad z_*=g_zp(x_*).
\end{aligned}
\]

Initial state is \((0,q_*,z_*)\). Its parameter dependencies, including the
reference channels and \(\kappa\to\beta\), remain in the BPTT graph.
For a fixed external drive, put \(\alpha=a_x\ge0\), \(s=-p_x>0\). The q/z block is

\[
J_{qz}=\begin{pmatrix}
(-1-g_C\alpha+g_Ps)/\tau_q&-1/\tau_q\\
g_zs/\tau_z&-1/\tau_z
\end{pmatrix}.
\]

Call contributes negative q self-feedback, Put contributes positive q
self-feedback, and the q-to-z-to-q loop has opposite off-diagonal signs.
However, total stability depends on

\[
\operatorname{tr}J_{qz}=\frac{-1-g_C\alpha+g_Ps}{\tau_q}-\frac1{\tau_z},\qquad
\det J_{qz}=\frac{1+g_C\alpha+(g_z-g_P)s}{\tau_q\tau_z}.
\]

For this real 2-by-2 block, negative trace and positive determinant characterize
local linear asymptotic stability. At the boundary \(\alpha=0,s=\beta\).
The full state Jacobian is block triangular with the additional eigenvalue
\(-1/\tau_v\), because v does not depend on q/z in this implementation.
These are fixed-input local statements, not a stability certificate for arbitrary
time-varying inputs or all trained parameters.

For constant currents, \(v=I_v,z=g_zp\) at equilibrium. If \(g_z\ge g_P\), the
remaining q equilibrium function has derivative
\(-1-g_C\alpha+(g_P-g_z)s\le-1\), and tends to opposite infinities as q tends to
opposite infinities. It has exactly one root. **Unique equilibrium does not imply
stable equilibrium.** The production parameterization does not enforce
\(g_z\ge g_P\).

## 4. Boundary-state boundedness and what ETD2 preserves

Assume \(|I_v|\le U_v,|I_b|\le U_b\), nonnegative gains and positive time
constants. Set \(R=g_C+g_P+g_z+U_b\). The rectangle

\[
|v|\le U_v,\qquad |q-q_*|\le R,\qquad 0\le z\le g_z
\]

is positively invariant if the initial state is inside it. **Proof:** each
coordinate has the form \(\tau\dot y=-y+T\). Its target lies in the corresponding
coordinate interval: \(T_v=I_v\), \(T_z=g_zp\), and
\(|T_q-q_*|\le g_C+g_P+g_z+U_b\). On each face the vector field points inward or
tangentially. The C1 state vector field gives uniqueness; the compact invariant
set excludes finite-time escape. Bounded piecewise-constant currents preserve
the result across external ticks.

The production bounds \(U_v=U_b=3\), gains at most 4, and
\(x_*\in[-0.5,1.5]\) give the uniform rectangle
\(|v|\le3,|q-q_*|\le15,0\le z\le4\) and margin
\(-18.5\le x\le19.5\). Prescribed learned initial states lie inside it.
The proof holds with parameters frozen during each sequence; carrying state
through parameter updates would require a separate argument.

For exact ETD2, let \(r=h/\tau\ge0,e=e^{-r}\),
\(w_1=1-e\), \(w_2=(e-1+r)/r\), with zero-step limits. Then

\[
y_p=ey+w_1T(y),\qquad
y_+=ey+(w_1-w_2)T(y)+w_2T(y_p).
\]

Both are coordinatewise convex combinations: \(w_2\ge0\) from
\(e^{-r}\ge1-r\), and \(w_1-w_2=[1-(1+r)e^{-r}]/r\ge0\) from
\(e^r\ge1+r\); coefficients sum to one. The same rectangle is therefore
invariant for this exact-arithmetic integrator at every nonnegative step.
The implemented Taylor/quotient kernels and floating-point operations
approximate these coefficients. This argument is not an exact floating-point
invariance, accuracy, Jacobian-contraction or equilibrium-stability proof.

## 5. A rigorous periodic-orbit existence example

This section concerns only the **ideal continuous, untrained phase fixture**:
zero currents, \(v(0)=0,\kappa=1,x_*=0,g_C=1,\tau_q=1,\tau_z=6\), and
\(g_P=g_z=3\). The plane \(v=0\) is invariant. With \(Q=q-\log2\),

\[
\dot Q=-Q+a(-Q)+3p(-Q)-z,\qquad
\dot z=(-z+3p(-Q))/6.
\]

1. The rectangle \(\mathcal R=[-4,4]\times[0,3]\) is strictly inward pointing.
   At \(Q=4\), \(a(-4)=0\) and \(\dot Q<-1\); at \(Q=-4\),
   \(\dot Q\ge1\). At z=0 and z=3, strict inward signs follow from \(0<p<1\).
2. At equilibrium z=3p, so \(Q=a(-Q)\). For Q<0 the right side is positive;
   for Q>=0 it is zero. Thus the only equilibrium is \((0,3/2)\).
3. In centered coordinates \(y=(Q,z-3/2)\),
   \[
   J=\begin{pmatrix}1/2&-1\\1/4&-1/6\end{pmatrix},\quad
   \lambda(J)=\frac16\pm i\frac{\sqrt5}{6}.
   \]
   Define
   \[
   P=\begin{pmatrix}37/16&-21/8\\-21/8&51/4\end{pmatrix}.
   \]
   Its leading minor and determinant \(723/32\) are positive, and
   \(J^TP+PJ=I\). Since the vector field is C1, write
   \(F(y)=Jy+r(y)\) with \(r=o(\|y\|)\). In a small enough neighborhood,
   \(\|r(y)\|\le\|y\|/(4\|P\|)\), so
   \(\dot W\ge\tfrac12\|y\|^2>0\) for \(W=y^TPy\), y nonzero.
4. Remove a sufficiently small open ellipse \(W<\epsilon\), entirely inside
   \(\mathcal R\). The remaining compact annulus is positively invariant and
   contains no equilibrium. Its forward trajectories have nonempty compact
   omega-limit sets. The C1 planar Poincare–Bendixson theorem then supplies at
   least one periodic orbit; see the theorem reference [PB].

This proves **existence of a periodic orbit** for that continuous fixture. It
does not prove uniqueness, isolation, orbital/exponential stability, a specific
period, persistence under arbitrary inputs, or oscillation after training.
It is not a classical Hopf-bifurcation proof: at the equilibrium the channels
are C1 but not C2, so one cannot simply invoke the usual higher-smoothness
Hopf hypotheses from trace crossing. [PB] formalizes the general theorem, not
this application.

The same existence argument applies to `matched_c1` at these parameters: it
uses the shared boundary first derivatives, channel bounds, nonnegative Call,
and the zero-Call stopped branch, all of which that control preserves. Periodic
orbit existence therefore does not identify an advantage of the analytic
financial function's global shape.

The separate `phase_dynamics001` numerical evidence reports mean peak spacing
15.075 and tail margin range 0.896004 for this hand-selected regime. Over the
entire sampled interval \([0,180]\), the maximum scaled q/z error is 0.0133164
at h=1/16, exceeding its registered 0.005 gate; h=1/32 gives 0.00338628. These
are maximum-over-interval errors, not just endpoint errors. The result neither
changes formal training h nor certifies trained spiking, resets, event sparsity
or biological fit.

## 6. Exact conditional matrix memory and contraction

For one head let \(M\in\mathbb R^{d_v\times d_k}\), value vector u, key k,
\(\rho=\|k\|^2\), nonnegative leak/write rates \(\lambda,\gamma\), and duration
\(\Delta\ge0\). The implemented conditional equation is

\[
\dot M=-\lambda M+\gamma(u-Mk)k^T=-M A+\gamma u k^T,\qquad
A=\lambda I+\gamma kk^T.
\]

Holding k,u and both rates fixed throughout the interval, variation of constants
and the rank-one eigenspaces give

\[
M_+=e^{-\lambda\Delta}M+
\big[\gamma\Delta\phi_1(-[\lambda+\gamma\rho]\Delta)u
-e^{-\lambda\Delta}\gamma\Delta\phi_1(-\gamma\rho\Delta)Mk\big]k^T.
\]

This is the code's division-free formula and remains well defined at k=0,
gamma=0 or Delta=0. Exactness refers to the mathematical phi function; its
floating implementation is separately checked.

For two initial memories with the **same** held inputs/rates,
\(\delta M_+=\delta M e^{-A\Delta}\). The multiplier has eigenvalues
\(e^{-(\lambda+\gamma\rho)\Delta}\) along k and
\(e^{-\lambda\Delta}\) on its orthogonal complement. Therefore

\[
\|\delta M_+\|_F\le e^{-\lambda\Delta}\|\delta M\|_F\le\|\delta M\|_F.
\]

It is strictly contractive when \(\lambda\Delta>0\), but no uniform rate follows
over unconstrained learned rate-head parameters. Across held-input ticks, the
same conditional bound multiplies even if successive keys are not parallel.

**This does not make full BPTT contractive.** Flow perturbations alter rates and
the memory forcing; parameter perturbations also alter keys, values and the
readout. Differentiating an affine update \(M_+=ME+b\) gives
\(dM_+=(dM)E+M(dE)+db\), whose last two terms are not controlled by the
memory-to-memory contraction. The full flow itself can have a positive-real-part
eigenvalue as proved above. Readout/rate-head gains and key normalization can
also amplify sensitivity. A bounded state is not a bound on its derivatives.

The production controller advances first; its **post-flow** rates are then held
constant for one external memory update. Consequently, internal v/q/z refinement
converges toward this defined tick map, not an exact solution of an alternative
joint continuous system whose rates vary continuously during the memory interval.

More precisely, with external key/value/event controls held fixed, define the
joint-ODE subfields \(A=(F(v,q,z),0)\) and \(B=(0,G(M;v,q,z))\). Advancing A for
an external duration \(\Delta\), then B for \(\Delta\), is a **Lie-type sequential
splitting**. The implementation additionally approximates A by internal ETD2.
Sending the internal h to zero removes that approximation but leaves the
outer splitting/rate-freezing step at \(\Delta=1\) in the formal tasks.

Even the non-writing case shows the distinction. If a continuously varying
leak has \(\lambda(t)=\lambda_0+ct+o(t)\) on a tick, the joint equation
\(\dot M=-\lambda(t)M\) has log multiplier
\(-\lambda_0\Delta-c\Delta^2/2+o(\Delta^2)\). Freezing the exact endpoint rate
gives \(-\lambda_0\Delta-c\Delta^2+o(\Delta^2)\): an outer local discrepancy
that survives internal h refinement. The endpoint rule is part of the model
when it is defined as a causal tick map; an interpretation as a joint continuous
ODE must account for this additional discretization. The registered h/2 and h/4
appendix tests internal-mesh sensitivity of the tick map, not accuracy against
that fully coupled continuous system.

## 7. Differentiation and sampling scope

Each sample uses \(N_i=\max(1,\lceil\Delta_i/h_{\max}\rceil)\) and
\(h_i=\Delta_i/N_i\). Completed examples are masked, so another sample's larger
duration does not change its mesh. Counts are detached scheduling metadata.
For fixed observed durations and parameters, BP/BPTT differentiates the actual
chosen discrete map, including learned reference states and coupled time
constants. This is the registered parameter-gradient scope.

A time derivative computed through this graph is conditional on N remaining
fixed. At a duration where N changes, two finite-step approximations need not
agree; the approximate map can have a discretization-sized jump. There is no
general derivative guarantee across that scheduling switch. The formal tasks
use duration 1 per distinct token and do not train the duration input.

The complete task model also includes observed-role comparisons, integer
counters and an epsilon-floor in key normalization. The statement that the
Call/Put boundary is C1 does not make every operation in the full architecture
globally smooth with respect to every input.

Finally, duplicating a token with halved duration is not automatically a valid
resampling experiment: it can repeat a write event, change a causal counter and
change the held post-flow rate. Sampling invariance requires a separately
defined continuous input/event contract. Continuous channels, conditional
memory exactness and ordinary first-order training alone establish no advantage
in task quality, energy, multimodality or scaling.

[HX]: https://www.princeton.edu/~wxiong/papers/rollover.pdf
[PB]: https://isa-afp.org/entries/Poincare_Bendixson.html
