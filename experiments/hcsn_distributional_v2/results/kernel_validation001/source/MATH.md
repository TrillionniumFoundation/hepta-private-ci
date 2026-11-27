# Batched regenerative distribution kernel

This package addresses the state-closure defect identified in the frozen v1
study. The recurrent physical state retains all active-cell and refractory-phase
probabilities. Its scalar means are output features, never the default next state.
This document describes the finite model actually trained, its numerical error
contract and its local value semantics. It does not assert task Bellman
optimality, exact unbounded Brownian dynamics at a coarse grid, or a content
advantage.

Source: `distribution_kernel.py`. Independent audit: `kernel_tests.py`. The
development audit is retained at `results/kernel_development001/RESULTS.json`;
the final source-bound audit is `results/kernel_validation001/RESULTS.json`.

## 1. State and time contract

With a fixed physical lower bound L, n active cells partition [L,b). Their width
is h=(b-L)/n, and their centers are x_i=L+(i+1/2)h. The state is a row vector

\[
p=(p_0,\ldots,p_{n-1},z_0,\ldots,z_{m-1}),\qquad p\ge0,\quad\sum p=1.
\]

Active mass is interpreted as piecewise-uniform density within each physical
cell for remapping and moments. Refractory mass z_j has j completed exponential
stages and m-j remaining stages. All stages have rate nu=m/tau. In this v2 cell
the finite Erlang law is the declared refractory law: its mean is tau and its
variance is tau²/m. It is not a deterministic delay at m=2. A zero-stage grid
is a separately declared instantaneous-reset model.

The physical lower bound, number of cells, number of phases, reset position and
refractory law remain fixed within an episode. Reset and tau are learned
parameters shared across that episode; changing their learned values between
training iterations changes the entire next rollout. Drift, volatility and
boundary may be piecewise constant between input observations. Existing phase
mass is never restarted on receipt of a new observation.

An upper hit resets into phase zero, then releases at the interpolated reset
position after the last stage. With no phases it immediately reinjects at reset.
The affine reward is a*x+c evaluated at the actual instantaneous firing position.
At an ordinary diffusion exit this is a*b+c. When a lowered boundary covers old
active mass, the reward is integrated over that mass's old physical position,
which can exceed the new boundary. Events are expected counts and may exceed
one; they are neither Boolean spikes nor first-hit probabilities.

`initial_probability` accepts a represented subthreshold initial position.
`initial_state` additionally handles initial x>=b, returns one immediate event,
awards a*x+c and enters reset/refractory state. A zero time interval does not
suppress an initial or boundary-shrink event. It only suppresses subsequent
positive-time CTMC propagation.

## 2. Conservative finite generator

Let D=sigma²/2. The upwind finite-volume internal jump rates are

\[
u=D/h^2+\max(\mu,0)/h,\qquad
d=D/h^2+\max(-\mu,0)/h.
\]

At the lower cell the missing downward jump reflects. The upper absorbing face
lies h/2 from the final center, so the exit rate is

\[
e=2D/h^2+\max(\mu,0)/h.
\]

That exit enters the first refractory phase, or reset weights for m=0. Refractory
stages advance at nu and the final stage injects mass at reset. Linear
interpolation between neighboring centers preserves the reset mean. The finite
column generator Q has nonnegative off-diagonals and zero column sums.

The production implementation applies its sparse row action through positive
staying and incoming terms. It does not form a dense exponential or repair
negative states by clipping. Its pointwise event rate vector lambda has value e
on the last active cell and zero elsewhere. For a fixed segment,

\[
p(t)=p(0)e^{Q^Tt},\qquad
C(t)=\int_0^t p(s)\lambda\,ds.
\]

The count integrates all regenerative cycles within the interval. Multiplying
this count by a*b+c gives the segment's undiscounted affine firing reward.

Spatial upwinding, finite reflecting domain, interpolation and finite-cell
reconstruction remain approximations to a continuous diffusion. They are not
removed by refining only time. For a fixed finite generator, time composition is
instead controlled by the explicit propagation tolerance below.

## 3. Bounded uniformization, including event error

Choose a uniformization rate Lambda strictly above every gross outgoing rate.
The implementation takes a detached numerical maximum with a small positive
margin; Lambda is a numerical device, not an additional learnable parameter.
Then P=I+Q^T/Lambda is row stochastic, and with z=Lambda*dt,

\[
e^{Q^Tdt}=\sum_{k=0}^{\infty} w_kP^k,
\qquad w_k=e^{-z}z^k/k!.
\]

Let g=lambda/Lambda. Applying one uniformized step changes the probability to
pP and adds p*g to the expected event accumulator. Repeating that operation k
times computes both P^k and the expected cumulative events after k potential
jumps, including self/reset transitions.

The numerical approximation is the **conditional Poisson truncation**

\[
\widehat T=\frac{\sum_{k=0}^K w_kP^k}{\sum_{k=0}^K w_k}.
\]

The same normalizer is used for the accumulated event expectations. This is a
declared convex combination of stochastic maps; normalization is part of the
bounded truncation algorithm. It is not post-hoc normalization of an invalid
physical state. In exact arithmetic it preserves total probability exactly and
cannot generate a negative probability.

For a unit-mass starting state let delta=P(N>K), N~Poisson(z). Conditioning this
mixture changes its output distribution by at most 2*delta in L1. To compute a
simple rigorous majorant, put a=w_(K+1) and r=z/(K+2)<1. Then

\[
\delta\le\bar\delta=\frac a{1-r},\qquad
E[N1_{N>K}]\le\bar M
=a\left(\frac{K+1}{1-r}+\frac r{(1-r)^2}\right).
\]

Each potential jump contributes between zero and g_max=max(lambda)/Lambda.
A conservative absolute expected-count error bound for one conditional segment
is

\[
g_{\max}\left(\bar M+\frac{z\bar\delta}{1-\bar\delta}\right).
\]

The series length is chosen so both the state and unit-jump count bounds meet
the requested tolerance. It is capped explicitly; failure to certify raises an
error. Long durations are divided into s identical-generator chunks with
Poisson mean at most `max_poisson_mean`. The implementation returns state bound
2*s*bar_delta and the conservative count bound

\[
s g_{\max}\left(\bar M+\frac{z\bar\delta}{1-\bar\delta}\right)
+s(s-1)\bar\delta g_{\max}z.
\]

The second term covers previously accumulated distribution error changing
later event integrals. The affine reward error is at most |a*b+c| times the
count bound for a constant segment. These bounds exclude floating-point
roundoff, remapping/spatial approximation and errors already present in the
input distribution. The checked API rejects materially non-unit initial mass;
the unchecked model path relies on its registered valid initialization and
conservative recurrences. It does not silently rescale arbitrary input states.

Adaptive Lambda, K and s are numerical branch choices. Gradient checks are
local first-derivative checks with K/s unchanged in each finite-difference pair;
Lambda is allowed to change between the two finite-difference evaluations.
No differentiability across the integer branch boundaries is asserted.

## 4. Moving boundaries in physical coordinates

Old cell mass defines a piecewise-uniform physical density. The overlap length
between each old cell and each new cell, divided by the old width, gives the
surviving mass transfer. The old fraction above the new boundary gives an
instantaneous event and enters phase zero (or reset). Its first moment is
integrated exactly under the old reconstructed density, so an affine immediate
reward is also exact under that reconstruction.

The remap is row stochastic. Refractory phases retain their existing mass and
index. In particular, an expanding boundary adds empty domain and does not
stretch old pressure coordinates. An unchanged boundary gives the identity
map, up to roundoff.

After a genuine boundary change, replacing overlap-supported density by a
uniform density on the new cells creates finite-volume projection error. A
round trip to another boundary and back is not generally the identity. Splitting
one unchanged-generator time interval is fundamentally different from adding
new boundary changes. Neither the tests nor the training claim arbitrary
moving-input semigroup invariance. Spatial refinement is needed to control this
remapping approximation.

## 5. J/G evaluated for the same finite policy

The values use the actual finite generator and Erlang phases, rather than
projecting the old deterministic-delay formula onto incompatible phase states.
For discount rho>0 and firing reward b-K, let H_i be the finite active-chain
discounted first-exit transform. It solves the tridiagonal system

\[
(\rho I-A)H=\lambda_{active},
\]

where A is the backward active subgenerator with an absorbing upper exit and
reflecting lower boundary. `policy_value_vectors` solves this system with a
batched Thomas algorithm. Let H_r=sum_i w_i(r)H_i and

\[
D_j=\left(\frac\nu{\nu+\rho}\right)^{m-j},\qquad D_0=D.
\]

For m=0, D=1. The regenerative policy value is

\[
J_i=H_i\frac{b-K}{1-DH_r},\qquad
J_r=H_r\frac{b-K}{1-DH_r},\qquad
J_{phase,j}=D_jJ_r.
\]

The feasible intervention channel is

\[
G_i=x_i-K+DJ_r\quad\hbox{on active cells},\qquad
G_{phase,j}=J_{phase,j}\quad\hbox{during forced refractory continuation}.
\]

Thus J_total=p*J and G_total=p*G have the same full-state mass semantics.
`G_eligible` is only the active mass weighted intervention value; `J_phase`
is the separately exposed forced continuation term. Their sum is G_total.
These are weighted expectations, not conditional-on-being-active means. The
phase states do not gain an illegal firing action.

This J solves `(rho*I-Q.T)J=(b-K)*lambda` exactly for the finite generator up to
floating-point linear-solve error. An independently assembled NumPy generator
and SciPy dense solve verify the Thomas/renewal result.

The content model may choose b using the continuous infinite-domain
Brownian/Erlang stationary free-boundary oracle. Its delay factor can be written
as exp(-rho*tau_eff), with

\[
\tau_{eff}=\frac m\rho\log(1+\rho\tau/m).
\]

This matches the Erlang discount factor, but the resulting b is not asserted to
optimize the finite reflecting grid. The finite J/G then evaluate that chosen
policy. Coefficients are frozen locally for this value calculation; future
input changes, finite task deadlines, content-reset consequences and real
execution costs are not magically included. In particular these channels are
not the classification or owner task Bellman values.

## 6. Efficient prepared operators and the collapse control

`step` applies physical remapping and sparse uniformization directly to the
current probability. `prepare_operator` applies the same propagation to all
basis rows and returns a small transition matrix plus event/reward/value
vectors. It can batch independent local coefficients over [batch,time,channel].
The content recurrence then performs only p@transition and scalar projections.

This preparation is causal only when the supplied segment coefficients depend
on current/past allowed information. It does not authorize using future inputs
to select current parameters. The sequential and prepared routes have separate
numeric and gradient equivalence checks. Prepared operators trade extra
temporary matrix storage/arithmetic for fewer Python dispatch loops; no
universal speedup is assumed.

`collapse_active_mean` is a controlled ablation. It replaces active mass by a
two-point interpolation at its active conditional mean, while preserving total
active mass and every refractory phase. It discards active distribution
information but retains finite-grid interpolation variance. It is not renamed
as the original v1 scalar pressure/cooldown model.

## 7. Validation and measured limits

The audit covers independent dense matrix exponentials for states, repeated
events and rewards; Poisson tail bounds against SciPy's Poisson distribution;
fixed-generator time composition; zero-time boundary jumps against independent
physical quadrature; initial atoms and refractory eligibility; independent
dense policy values; seven physical gradients; prepared/sequential gradients;
the active-collapse contract; and 64-step float32 conservation/rejections.

Additional references include a seeded 30,000-path event-driven finite-CTMC
sampler and Brownian zero-delay renewal moments on grids of 8/16/32/64/128 cells.
The eight-cell model remains a coarse spatial approximation. In the development
case, event error was approximately 0.0240 at 8 cells, 0.0291 at 16 and 0.00575
at 128. Refinement was not monotone at its first step. Accurate propagation of
the finite generator must not be confused with an accurate continuous Brownian
approximation at every chosen resolution.

The performance probe compares forward+backward computation only, for an
8-batch,16-step,4-channel synthetic input and 8 cells/2 phases. It does not run an
optimizer update and is not a whole content-training benchmark. The final
result records every repeat, both objectives, dtype, dimensions and measured
CPU time. No GPU or energy result is claimed.

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
python -m experiments.hcsn_distributional_v2.kernel_tests --output NEW_EMPTY_DIRECTORY
```

Requires the recorded CPU PyTorch/NumPy/SciPy environment and the preserved v1
independent renewal reference. Running into an existing evidence directory is
rejected. Earlier development results remain separate from the final bound
source; the original frozen v1 files are not edited by this implementation.
