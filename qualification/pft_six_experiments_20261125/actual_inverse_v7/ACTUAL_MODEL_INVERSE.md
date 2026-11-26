# Actual SmallHCSN mapping and a frozen-readout inverse

## 1. Source and observation identity

This derivation follows the executed research source `original_model.py`,
20,658 bytes, SHA256
`aabc7a29ebfdaed592ebd4a16d7e4db927a6a88cb7247d4b334fd7299eab8576`.
The finite-volume dependency has SHA256
`a41e840088282586545b4f84cccbbf0fe22471dd158b45283cda8002fc25d876`;
the imported uniformization module has SHA256
`951dfb512ac721417f706631b0d12d62bc305c08fe4ce00ffc42feda61d0f1ae`.
Both dependency texts were retrieved from origin commit
`88414dda04443897def179754779aecdca6f0296` and matched the retained capsule
provenance, SHA256 `72194249d27b8af51cf95f89f5db494fa525e44c156eaf11b56e417ccc8c3b55`.

The instance is N=8, six spatial bins, three refractory stages, dense matrix
actions, float64, QVI boundaries, full messages and no feature normalization.
Each neuron retains a probability row and a signed-mark row on ten states.
The declared six edited coordinates are raw_cost[4], input_drive.weight[0],
input_mark.weight[0], recurrent.weight[96], readout.weight[0], readout.bias[0].
The observation is the final class-1 logit minus class-0 logit on each of two
fixed four-tick trajectories, with a fresh complete initial state.

Three numerical objects must be distinguished: the real-arithmetic model
with the exact QVI root; the finite-iteration QVI algorithm; and its floating-
point implementation. The proofs below state which object they concern.

## 2. The actual forward equations

Let S_t=(p_t,q_t,b_t,mu_t,c_t,m_t,t) denote probability, signed mark, boundary,
drift, cost, three-channel message and integer clock. With the synaptic mask
M fixed, the recurrent input is R_t=W_rec(m_t masked by message mode), using
OLD messages. Input drive D_t=pad(W_drive x_t+a_drive)+R_t and mark drive
K_t=pad(W_mark x_t+a_mark)+R_t enter different operations.

On even ticks, the source computes

\[
\mu_t=-0.2+0.15\tanh D_t,\qquad
c_t=0.15+0.02\tanh(a_{cost}+0.15D_t),\qquad
b_t=\operatorname{QVI}(\mu_t,c_t,r).
\]

On odd ticks these controls are retained. The grid width is h=1/3. Moving
boundaries transfer mass using clipped linear cumulative overlaps; lower
crossing mass enters the first refractory phase, and upper projected mass
enters the last spatial cell. Active signed marks are then updated by
q=(1-alpha)q+alpha*tanh(K_t)*p, alpha=1/2. The positive reset deposition uses
hat functions on the cell centres, with margin r-b_t.

The finite-volume spatial generator uses left rates
sigma^2/(2h^2)+relu(-mu)/h and right rates
sigma^2/(2h^2)+relu(mu)/h, with doubled diffusion at absorbing boundary faces.
The upper exit is reflected; lower hits enter a three-stage chain of rate
3/0.2, whose final phase returns to the reset deposition. An unused final
account completes the ten-state layout. Row probabilities evolve by exp(dt G).
An augmented exponential accumulates event counts and active occupancy.
The discounted value vector solves

\[
(\rho I-G)v=r_{reward},\qquad \rho=0.3.
\]

First-hit risk is obtained from a killed generator, including newly crossed
cohorts once. Receiver features are value, risk, signed event rate, event
rate and normalized first spatial moment. Their flattened length is 20.
The next message contains boundary and the two event rates. Finally,

\[
z_t=W_{out}\phi_t+b_{out},\qquad F_i(a)=z_{T,i,1}-z_{T,i,0}.
\]

Code locations are `forward` for controls and clock order, `_remap` for
boundary transfer, `_generator` for phase/reset transport, `_flow` for the
exponentials/resolvent/features, and the final `self.readout(features)` call.
Targets occur in the external objective and never enter this forward map.

This is a deterministic finite-state, discrete-clock population computation
conditional on its input and parameters. It propagates probability mass;
it does not sample a Brownian path or construct an adapted pair (Y,Z).
The resolvent has the exact finite-state identity
v=integral_0^infinity exp(-rho s) exp(sG) r_reward ds. This explains its
backward value equation without identifying it with the separate V6 FBSDE.

## 3. Two application hypotheses for the nominal real model

This section interprets the displayed decimal source constants as exact real
numbers, including rho=3/10, sigma=11/20 and the reset endpoints below.
The cached binary64 coefficients and Python's computed eta are not those
exact rational constants. The proof establishes the nominal exact-root
discrete model; certifying the implemented FP64 state conditions additionally
requires coefficient enclosures and numerical error bounds.

### 3.1 Upwind branch and QVI root

For all finite real drives, mu is strictly between -7/20 and -1/20 and cost
is strictly between 13/100 and 17/100. Thus the upwind ReLU branches never
cross zero in this configuration. The negative-mu formula used for k is
the same positive root as (mu+sqrt(mu^2+2 rho sigma^2))/sigma^2.

Write s=gain/rho=8/3, eta=(50/51)^3, d=r-b, A=s/k and
B=s*r+gain*mu/rho^2-maintenance/rho. The exact QVI residual becomes

\[
R(d)=(1-\eta)B+c-sd+\frac{s}{k}(1-\eta e^{-kd}),\qquad
R'(d)=-s(1-\eta e^{-kd}).
\]

On d>0, -s<R'(d)<-s(1-eta)<0, so every zero there is simple and unique.
The nominal real reset values lie in [117/100,123/100]. Elementary bounds give

\[
\frac35<k<\frac{13}{10},\quad -1<B<4,\quad
0<1-\eta<\frac3{50}.
\]

For example k increases with mu. At the lower endpoint,
sqrt(0.304)>0.55, giving k>80/121>3/5; at the upper endpoint,
sqrt(0.184)<0.43, giving k<152/121<13/10. The extreme B bounds follow
directly by inserting the endpoints; the lower one is -371/450>-1.

Using 1-exp(-u)>=u-u^2/2 for u>=0 gives

\[
R(1/6)>-3/50+13/100-(8/3)(13/10)/72=59/2700>0.
\]

Dropping the negative exponential term and using s/k<40/9 gives

\[
R(11/6)<12/50+17/100-44/9+40/9=-31/900<0.
\]

The intermediate-value theorem and strict decrease prove a unique root
d* in (1/6,11/6). This interval is inside the code's original bracket
(0.0001,8), so its exact-arithmetic bracket check also holds throughout
the control box. Since |R'|<s, the root has conservative hull margins

\[
d_*-1/6>59/7200,\qquad 11/6-d_*>31/2400.
\]

Consequently the exact reset deposition is always inside the strict centre
hull for this configuration. The implicit root is smooth in (mu,c,r),
with a denominator bounded below by s(1-eta)>0. This proof concerns the
frozen constants above, not every ModelConfig accepted by the constructor.

### 3.2 Finite-state flow and the discounted solve

Hat deposition is a probability vector on that hull. The reflected spatial
generator and refractory/reset chain have nonnegative off-diagonals and
zero row sums. Hence exp(tG) is stochastic and

\[
(\rho I-G)^{-1}=\int_0^\infty e^{-\rho t}e^{tG}dt,
\qquad \|(\rho I-G)^{-1}\|_\infty=1/\rho.
\]

The discounted system is therefore invertible for every control in the
box, without a separately measured condition number. The remap is a
nonnegative mass-conserving transfer and the marked write is a convex
combination with |tanh K|<1. They preserve probability mass and |q|<=p
in exact arithmetic. Killed-generator first-hit probabilities lie in [0,1]
and are bounded by the corresponding expected counts. Together these facts
give a unique real-arithmetic forward trajectory for valid frozen initial
states and any finite number of ticks. They do not bound FP64 roundoff.

## 4. Where smoothness still needs a separate argument

| Operation | Relevant boundary or conclusion |
| --- | --- |
| `_deposit` | Hat-function knots at reset margin equal to cell centres; the strict hull proof excludes the domain edge, not these interior knots. |
| `_remap` | CDF clipping changes slopes at normalized displacements that are integers. |
| Odd control ticks | New and old boundaries are the same quantity, so displacement is identically zero. These structural knots alone do not obstruct differentiability of the composed map. |
| `_symmetric_clip` | Its midpoint AD slope at a knot is a convention, not proof of a classical derivative or a valid generalized-Jacobian chain rule. |
| `_QVI.forward` | It performs 56 bisections in float64. With fixed reset and fixed branch decisions, its returned midpoint is constant in mu and cost. |
| `_QVI.backward` | It uses the implicit derivative of the root residual evaluated at the returned midpoint, not the exact derivative of the finite bisection program. Second-order AD is explicitly disabled. |
| Upwind ReLU and residual's mu branch | They stay on their negative-mu branches for this frozen control box. |
| Uniformization planner | The retained backend is dense. In this model its alternative planner rate is configuration-derived, not chosen from the changing weights. |
| Diagnostics | Their max/abs operations do not feed logits. Strictly satisfied failure guards do not themselves change the local observation map. |

In exact real arithmetic, the 56-step midpoint approximates its bracketed
root within (8-0.0001)/2^57. This does not include floating-point errors,
and a tiny function-value error is not a derivative-consistency theorem.
The original parent failed its declared finite stencil; no cause is assigned
to one particular primitive by this source audit. The raw_cost parameter
enters tanh(raw_cost+0.15*drive), not abs(raw_cost).

For the exact-root idealization, composition is locally Lipschitz and is
smooth on regions with fixed nonstructural deposition/remap branches.
A quantitative inverse on such a region additionally requires informative
observations and a derivative variation bound. The actual aggregate
candidate `981304...` has no inherited derivative gate from `87ed31...`.

## 5. A directly invertible subspace of this actual readout

Freeze every parameter, buffer, configuration field, input and initial state
except readout.weight[0] and readout.bias[0]. Because readout is never fed
back into the state/message update, every feature trajectory remains fixed.
Let p_i=phi_(T,i,0), and let u and v be increments of those two coordinates.
For the real-arithmetic readout on these fixed feature values,

\[
F_i(u,v)=F_i(0,0)-p_i u-v.
\]

**Proposition.** Two targets with desired margin changes d1,d2 uniquely
determine u,v iff p1!=p2. In that case

\[
u=\frac{d_2-d_1}{p_1-p_2},\qquad
v=\frac{p_2d_1-p_1d_2}{p_1-p_2}.
\]

Subtracting the two observation equations proves the first formula; inserting
it in either equation proves the second. The data matrix is
A=[[-p1,-1],[-p2,-1]], with determinant p1-p2. Its exact infinity-norm
inverse is max(2,|p1|+|p2|)/|p1-p2|. Thus a perturbation of both desired
changes bounded by epsilon causes a parameter perturbation bounded by that
factor times epsilon. This is exact for fixed features and noiseless arithmetic.

For two positive weights w1,w2, each peer contributes

\[
G_i=w_i\begin{pmatrix}p_i^2&p_i\\p_i&1\end{pmatrix},\quad
h_i=-w_id_i\binom{p_i}{1},\quad c_i=w_id_i^2.
\]

The sum has determinant w1*w2*(p1-p2)^2>0 and solves exactly the same two
equations. No ridge is required. Exact rational addition makes aggregation
order irrelevant. A common accepted contribution set and identities are
still required; these equations do not establish privacy or peer honesty.

### Binding to the retained observations

The original parent is `0127a056...`; its state is `136026bd...` and source
binding is `3146e2c5...`. The two retained VJP rows have final columns
(-2.6215667982091095,-1) and (-2.698241377946342,-1).
Those columns arise from the direct linear readout, whose weight derivative
is minus the frozen feature and whose bias derivative is -1. No upstream
QVI or raw_cost derivative is needed to derive those two columns.
Their stored feature values are different, so the exact binary64-as-rational
frozen-feature design is nonsingular. This is not a new forward observation.
The archived baseline margin has already undergone readout and subtraction
rounding. The request treats that stored number as its exact affine intercept.
Its algebraic target residual therefore describes the declared cached affine
problem; a new physical output also includes the baseline/intercept rounding
difference, effective parameter-addition rounding and new readout arithmetic.

`READOUT_REQUEST.json` copies those feature values, original baseline margins
and original engineering targets into canonical binary64 hex strings. Its
SHA256 is `e6c8e04059737337d8cdde5db97d1358b2b3fcce908a1d5d7488fd309cddf07c`.
It binds the source, full reference state, candidate, coordinate layout,
task input, initial state and both original row-file hashes. Reviewers must
freeze this request before invoking `propose_readout_edit` with its digest.

The implementation solves this declared affine problem using Fraction
arithmetic, rejects singular or incompatible inputs and emits a proposal.
It reports the residual caused by rounding the two deltas to binary64;
that report excludes rounding when adding deltas to parameters and during
the actual physical forward. It never loads, modifies or exports a model.
A physical new candidate would require its own separately admitted execution.

## 6. Why this does not identify the full six-coordinate field

The retained affine six-coordinate surrogate has two rows; its data nullspace
has dimension four. Ridge selects an optimizer in that space and adds no
observational information. There is also a constructive nonlinear ambiguity:
write the other four body coordinates as q and the two unfixed readout
coordinates as w,b. For every admissible q with p1(q)!=p2(q), the equations
y_i=H_i(q)-w*p_i(q)-b determine one pair w(q),b(q). Distinct bodies can
therefore be compensated by these readout coordinates whenever they remain
admissible and have distinct features. On a continuous nondegenerate
neighborhood this gives a four-parameter family of equal endpoints.

For the unrestricted model, the synaptic mask supplies an even stronger
source-level obstruction: 48 recurrent weights at N=8 are multiplied by
zero. Changing finite positive values at those masked entries leaves the
effective matrix exactly unchanged. Margin-only readout observations also
have a common-row shift symmetry in real arithmetic. These null directions
must be fixed or quotiented before asking for unique parameter recovery.

## 7. Evidence status and execution boundary

This note closes the source-to-equation mapping, nominal real exact-root
control-box well-posedness, finite-state resolvent invertibility, and the algebraic
two-coordinate frozen-readout inverse under their stated semantics.
It identifies the exact place where the full nonlinear inverse needs further
observations, branch-aware regularity and numerical error control.

The existing `87ed31...` finite-stencil result, `981304...` aggregate/cold
results and V6 retention remain separate evidence. The proposed two-coordinate
edit is not either of those candidates. Real A-to-B acceptance, structure
advantage, learned circuits, continuing representation learning and total
training cost are unaffected by an exact fit to these two engineering targets.
This derivation and source preparation executed no model, AD, solver or test.
Root records subsequent pure-algebra execution separately from this preparation.
