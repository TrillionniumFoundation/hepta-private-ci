# Dynamic modality allocation: the finite problem and the larger proposal

This document explains the problem registered in `protocol.json` at commit
`f10589f3df5d2da88b2b5d92e3686441ce982461`. It does not amend its parameters or
report experimental success. The broader continuous-time construction below is
a proposed model class, not a claim that its solver or natural-data training has
been implemented.

## 1. Three different objects

The semantic condition, compute allocation and emitted outputs have different
types and meanings:

| Object | v4 definition | Role |
| --- | --- | --- |
| Semantic condition `q` | Eight-class one-hot report of the executed text encoder | Conditions the anchor and gain network; fixed throughout a trajectory |
| Allocation action `a_t` | STOP or one of four `REFINE_m` operations | Selects which actual modality state receives the next unit of computation |
| Output bundle `y` | Four tensors produced by four trained decoder modules | Complete text/audio/image/video emission, evaluated jointly |

The eight numbers in q cannot be interpreted as four modality allocation
fractions. For a nonterminal action, an allocation vector can instead be written
as the four-dimensional basis vector corresponding to the selected modality.
The cumulative refinement allocation is the vector of actual executed counts
times 8,704 MAC, with each modality's mandatory decoder cost added separately.
The shared encoder/anchor cost is not assigned four times.

This is a restricted dynamic allocation problem. It does not implement a
continuous allocation simplex, portfolio mixtures of candidate outputs,
semantic redirection q_t, or joint source acquisition and generation control.

## 2. Forward generation and feasible decisions

For a revealed text input x, the frozen encoder produces q, and a learned map
produces the known anchor h(q). Four separate latent vectors are initialized:

\[
z_0^m=h(q)+\alpha_{jm}d_m,
\qquad m\in\{\mathrm{text,audio,image,video}\}.
\]

The registered artificial initial pattern j is never supplied as an online
policy argument; the actual four latents are observable. A refinement changes
only its selected component:

\[
z_{t+1}^m=h(q)+[1-g_\theta(q,z_t^m-h(q))](z_t^m-h(q))
             +\xi_{t+1,m},\qquad
z_{t+1}^{n}=z_t^{n}\quad(n\ne m).
\]

The gain network and all decoder weights are inherited and frozen. Its
architectural contraction and the known clean anchor are explicit assumptions.
The random innovation is obtained only after committing the action. Directions
are fixed by (source seed, global decision index, modality); the independent
branch draw is keyed by (source seed, world, global decision index, modality).
Thus alternative policies are paired without being given their future noise.

The state contains q, all four current latents, causal history, version, remaining
budget and refinement count. All four outputs are mandatory on STOP:

\[
y_m=D_m(z^m),\qquad
B=3584+2\cdot8704+330240=351232\ \mathrm{MAC}.
\]

Every refinement must leave enough budget for the complete 330,240-MAC emission.
At most two refinements are permitted. These are counted dense Linear operations,
not total FLOPs, wall time or energy. The full search, feedback, nonlinear
arithmetic and native/IPC costs are separately measured rather than called free.

## 3. Joint utility and the finite Bellman equation

Let L be the registered external loss: the average of four clipped normalized
prototype errors plus a cross-modal disagreement penalty. It is a single loss
on the complete output bundle. In particular, independently maximizing four
univariate modality values and summing them is not the same optimization.

For risk coefficient gamma=2 and lambda=0.015/8704, define

\[
C_\gamma(X\mid s)=-\gamma^{-1}\log E[e^{-\gamma X}\mid s],
\qquad R=-L(y)-\lambda C_{\rm actual}.
\]

After the common INIT charge, the finite recursion is

\[
Q(s,\mathrm{STOP})=-L(D(z))-\lambda C_{\rm emit},
\]
\[
Q(s,\mathrm{REFINE}_m)
=-\lambda C_m+C_\gamma(V(s')\mid s,m),
\qquad
V(s)=\max_{a\in A(s)}Q(s,a).
\]

Subtract lambda times 3,584 once at the initial root. Child values already price
their future refinements and terminal emission; neither cost is subtracted a
second time. The resource constraint and utility price play different roles:
one forbids a trajectory, and the other values a feasible trajectory's cost.

There are 32 initial roots per fixed checkpoint, with 32, 384 and 4,608 nodes at
depths zero, one and two. All reachable action/branch histories can therefore be
enumerated. Monotonicity and deterministic cash translation of the entropic CE
justify backward induction. The finite nested CE also agrees with the CE of
the terminal return under a fixed policy: exponentiating each conditional CE
and applying conditional expectation gives the tower identity.

In exact arithmetic, a maximizing Markov/history policy is optimal within this
registered finite model. The common numerical rule chooses the first candidate
unless a later one exceeds it by more than 1e-12. Its per-decision score gap is
at most that tolerance; two decision layers can propagate at most 2e-12 in
utility under the monotone sup-norm Lipschitz CE. This is finite policy
optimality for fixed weights and laws, not global nonconvex neural optimality.

The reported J averages each root's conditional CE over the 32 roots and then
over the three fixed checkpoints. It is not one CE after mixing all roots or
training seeds. The bootstrap preserves this definition and estimates execution
sampling uncertainty conditional on these checkpoints.

## 4. Why the committed-plan comparison matters

A fixed allocation baseline first sees the same complete initial state. It can
choose any ordered sequence of zero, one or two modalities: 1+4+16=21 plans,
including repeated refinement of the same modality. Every plan is evaluated
under the identical utility, transition law and hard budget before selection.
This baseline is stronger than a globally fixed round-robin allocation.

The native owner binds that selected plan at INIT and permits only its next
prescribed refinement, followed by emission. It cannot change the plan after
observing an innovation. The dynamic owner receives genuine Bellman action
scores for every feasible action. The myopic owner receives genuine
one-refinement-then-STOP scores. Ineligible entries are zero placeholders masked
by the native feasibility rules; they are never fabricated utility estimates.

Every committed plan and the myopic policy are members of the dynamic policy
class. Consequently the finite dynamic optimum weakly dominates their exact
model values up to numerical tolerance. This inclusion fact neither guarantees
a strictly positive difference nor makes a Monte Carlo confidence interval
automatically significant. Exact model values and sampled execution results
must both be reported.

A meaningful realized allocation mechanism requires more than differing initial
priorities. The preregistered gate requires siblings with identical initial state
and first action, but different new innovations, to choose two different second
REFINE modalities. Both branches must actually execute in the confirmation run
for each seed. STOP-versus-REFINE alone does not pass this stronger gate.

## 5. Relation to Merton's formulation

Merton's original problem jointly chooses consumption and asset weights under
stochastic wealth dynamics, using dynamic programming; the explicit portfolio
rules require particular return and utility assumptions [1]. The useful analogy
here is choosing a feasible allocation process to maximize a terminal/recursive
utility. Neural latents are state variables and available computation is a
resource. No equivalence to a traded financial wealth process is assumed.

Replacing expected returns with a heuristic confidence and applying an inverse
covariance portfolio formula does not solve the generator's problem: its
transitions, decoder utility, stopping contract and action-dependent costs have
to appear in the control equation. The finite experiment specifies those objects
directly instead of transferring a financial closed form without its assumptions.

For a future continuous model, one may posit an observed Markov state S and
admissible allocations u with

\[
dS_t=b_\theta(S_t,u_t)dt+\sigma_\theta(S_t,u_t)dW_t,
\qquad dB_t=-c(S_t,u_t)dt.
\]

Under sufficient smoothness, integrability and a valid dynamic programming
principle, an entropic running-utility specialization would formally yield

\[
0=V_t+\sup_{u\in A(S,B)}\left\{
r+b_\theta^\top\nabla_S V-c\,V_B
+\tfrac12\operatorname{tr}(\sigma_\theta\sigma_\theta^\top V_{SS})
-\tfrac\gamma2\|\sigma_\theta^\top\nabla_S V\|^2\right\}.
\]

An optional stopping problem adds an emission obstacle and feasibility boundary;
the continuation equation alone is incomplete. The displayed equation is our
formal model extension, not an implemented general solver or a consequence that
has been proved for arbitrary neural coefficients. Partial observations require
a justified belief/history state; a single fused latent is not automatically a
sufficient statistic.

In the associated utility-sign BSDE convention,
`dU = -(r - gamma*||Z||^2/2) dt + Z dW`, the Brownian exposure Z differs from a
parameter gradient. The entropic specialization and its sign convention are
discussed in the v3 theory and primary reference [2]. A general nonlinear NDU
generator requires its own definition, conditions and numerical validation.

## 6. Training remains a distinct claim

For a natural shared generator, the intended practical training problem would
optimize encoder, transition, decoder and policy parameters against a declared
global utility, using licensed disjoint-source data and a feasible control
policy. Discrete actions require a declared estimator or a justified selected
branch/envelope derivative; differentiating argmax labels is insufficient.
The frozen finite simulator does not establish that a learned critic estimates
continuations accurately on natural data, or that optimization finds global
weights. v4 adds allocation control only; v3's refiner-gradient evidence remains
historical and must not be relabeled allocation-aware end-to-end training.

## Primary references

1. Robert C. Merton (1969), *Lifetime Portfolio Selection under Uncertainty:
   The Continuous-Time Case*, The Review of Economics and Statistics 51(3),
   247-257. [Original paper, university-hosted copy](https://www.sfu.ca/~kkasa/Merton_69.pdf).
2. Nacira Agram, Jan Rems and Emanuela Rosazza Gianin, *SIG-BSDE for Dynamic
   Risk Measures*, section 2.2.1. [Author preprint](https://arxiv.org/html/2408.02853v1).
   The v4 control construction above is our specified finite experiment, not
   a claim that either reference proves an all-modal neural architecture.
