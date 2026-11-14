# Conservative flow across changing boundaries

This independent scalar reference implements physical remapping between
piecewise-constant drift, volatility and boundary segments. When a boundary
shrinks, the active probability it covers fires immediately, receives its
physical-pressure reward, and enters reset/refractory state. Existing refractory
mass keeps its phase and remaining-delay law. Expansion preserves probability
and produces no immediate event.

The implementation is `moving_flow.py`; eight tests are in
`moving_flow_tests.py`. Final measurements are in
`results/moving_flow001/results.json`, also preserved under `final/`. Earlier
development measurements remain explicitly separated in `development_results.json`
and `development_projection_contract/`. No frozen neural-study file was changed;
no classification outcomes were read or generated.

This extends the fixed-boundary repair reference with **actual conservative
moving-grid dynamics**. It does not make the finite grid an exact continuum
solution, optimize a global free boundary, or integrate a content network.

## State and numerical contract

Each episode fixes the physical lower endpoint `L`, reset pressure `r`, mean
refractory duration `tau`, number of Erlang phases `k`, and affine firing reward
`a*x+c`. Drift `mu`, volatility `sigma` and upper boundary `b` may change at
specified segment boundaries. Every `b` must exceed `r`, and the initial/reset
pressure must be representable by the cell centers. The API rejects changing
the fixed parameters during remapping.

This file uses **cell-integrated probabilities**, not the active nodal
probabilities of `distributional_flow.py`. With `n` cells,

\[
e_i=L+ih,\quad h=(b-L)/n,\quad
C_i=[e_i,e_{i+1}),\quad x_i=(e_i+e_{i+1})/2.
\]

For remapping and moment projection, mass `p_i` reconstructs uniform density
`p_i/h` inside `C_i`. In particular, a cell's second moment is
`x_i**2 + h**2/12`. An initial delta or reset is injected by nonnegative linear
weights on neighboring centers, preserving its mean; it still has a finite
representation error. Existing nodal states cannot be passed to this API and
silently reinterpreted as cell averages.

Internal upwind rates are

\[
u=D/h^2+\max(\mu,0)/h,\qquad
d=D/h^2+\max(-\mu,0)/h,\qquad D=\sigma^2/2.
\]

The lower face reflects. The absorbing upper face is half a cell from the last
center, so its outgoing rate is `2*D/h**2 + max(mu,0)/h`. For negative drift,
upwind advection from outside has zero boundary density; adding a negative
advective exit would be wrong. The finite-volume approximation remains an
approximation, including in the zero-volatility transport limit.

An upper exit increments the expected event count, pays `a*b+c`, and injects
mass into refractory phase zero. The `k` serial phases have rate `k/tau` and
release mass at reset after an Erlang duration with mean `tau` and variance
`tau**2/k`. For `tau=0`, outgoing mass returns to reset immediately. Two augmented
generator rows integrate the expected event count and undiscounted firing reward.
`torch.matrix_exp` includes repeated events within each segment.

## Physical boundary remapping

For old cells `C_i` and new cells `C'_j`, the overlap matrix is

\[
R_{ji}=\frac{|C_i\cap C'_j|}{|C_i|},\qquad
H_i=\frac{|C_i\cap[b',\infty)|}{|C_i|}.
\]

The physical lower endpoint stays fixed, hence every column satisfies
`sum_j R_ji + H_i = 1`, up to floating point roundoff. Surviving active mass is
`R @ p`. Covered mass `H @ p` fires immediately and joins phase zero, or reset
weights when `tau=0`. Existing phase probabilities are copied without change.
The phase-specific expected remaining durations `(k-j)*tau/k` therefore also
remain unchanged for that existing mass. No phase clock is restarted merely
because an input or boundary changed.

For affine reward, the immediate reward is integrated over the covered physical
density:

\[
\Delta N=\sum_i p_i H_i,\qquad
\Delta Y=\sum_i\frac{p_i}{|C_i|}
\int_{C_i\cap[b',\infty)}(a x+c)\,dx.
\]

A lowered barrier may cover pressures strictly greater than the new threshold.
Paying every covered trajectory at `b'` would therefore give the wrong reward.
The implementation integrates the first moment of the covered interval. The
default measurements use `a=1,c=-.4`; a separate regression uses unit reward and
verifies reward equals event count through both diffusion and boundary jumps.

An explicit partial-cell regression starts with active masses `.1,.2,.4,0` on
unit cells spanning `[0,4)`, plus `.3` refractory mass. Shrinking to `b'=1.5`
covers mass `.5`, physical first moment `1.175`, and reward `.975` for `x-.4`.
The implementation recovers these values and preserves all old phase entries.
The `.5` new event mass is added only to phase zero.

Remapping is exact for the **integrals of the reconstructed old density**. The
new uniform-cell representation loses subcell shape and introduces projection
error. For example, an expanding cell that straddles the old boundary can spread
its transferred mass within the larger cell; this is numerical diffusion, not
new probability. Repeated remaps are not generally reversible. They must not be
confused with relabeling old array entries at new physical coordinates.

The receipt records the physical mean after firing/reset, the mean after
projection, and their difference. Its absolute value is bounded by
`h_new/2 * surviving_active_mass`; the bound applies only to this remap's
first-moment projection, not to continuum error. In the measured scenarios,
maximum per-jump mean error decreased from `1.06e-3` and `7.75e-4` at 32 cells
to `5.13e-6` and `3.43e-6` at 512 cells.

## Independent exact-event Monte Carlo

The comparison simulates unbounded Brownian sample paths independently of the
grid. It reuses the read-only `_sample_hit` and `_sample_killed_endpoint` helpers
from `closure_audit.py`, with their source hash retained. Within every fixed
segment it uses:

- Inverse-Gaussian hitting clocks for nonzero drift; negative drift includes its
  defective eventual-hitting probability.
- Levy hitting clocks for zero drift.
- A killed-transition endpoint sampled conditional on survival when the next
  hit lies beyond the segment end.
- A newly sampled `Gamma(k,tau/k)` refractory residence after each hit, with its
  actual remaining duration carried across segment changes. A separate reference
  uses deterministic `tau`.
- Immediate firing at the next segment's start for eligible active paths already
  above the newly lowered boundary. Refractory paths remain ineligible.

There is no Euler time grid or missed intra-step bridge crossing in this
reference. Monte Carlo uncertainty remains. Reported intervals are pointwise
normal 95% intervals, not simultaneous intervals or numerical-error bounds.
Each of ten independent Monte Carlo configurations uses 50,000 paths: two
scenarios, four Erlang phase counts, and two deterministic-delay references.
The same 16-phase reference is reused across all spatial grids.

### Scenarios

| Scenario | Initial / reset / tau | Segment | Duration | mu | sigma | b |
|---|---|---:|---:|---:|---:|---:|
| A: shrink, expand, drift change | .15 / -.3 / .3 | 1 | .8 | .35 | .8 | 1.15 |
| A | same | 2 | .6 | -.25 | .65 | .48 |
| A | same | 3 | .8 | .15 | .75 | 1.05 |
| B: negative drift then shrink | .2 / -.25 / .45 | 1 | .9 | -.4 | .75 | 1.0 |
| B | same | 2 | .9 | .45 | .65 | .35 |
| B | same | 3 | .6 | -.15 | .6 | .85 |

All finite grids use `L=-5`. The following spatial comparison fixes `k=16`.

| Scenario A | E[N] | E[X] | Variance | E[reward] |
|---|---:|---:|---:|---:|
| 32 cells | .756402 | -.469957 | .523957 | .343050 |
| 64 cells | .752566 | -.455657 | .502806 | .336565 |
| 128 cells | .749040 | -.448517 | .493815 | .333290 |
| 256 cells | .747139 | -.444840 | .489674 | .331545 |
| 512 cells | .746174 | -.443052 | .487751 | .330686 |
| Exact-event MC mean | .749700 | -.445821 | .490022 | .333563 |
| MC 95% interval | [.744542,.754858] | [-.451957,-.439685] | [.483412,.496632] | [.330410,.336715] |

| Scenario B | E[N] | E[X] | Variance | E[reward] |
|---|---:|---:|---:|---:|
| 32 cells | .787468 | -.539985 | .420157 | .103554 |
| 64 cells | .774721 | -.520167 | .388830 | .093996 |
| 128 cells | .766448 | -.510015 | .376046 | .090160 |
| 256 cells | .761749 | -.504827 | .370014 | .088047 |
| 512 cells | .759240 | -.502228 | .367150 | .087014 |
| Exact-event MC mean | .755000 | -.498938 | .366099 | .084586 |
| MC 95% interval | [.748823,.761177] | [-.504242,-.493634] | [.360291,.371907] | [.082637,.086536] |

The 512-cell counts, means and variances lie within the displayed Monte Carlo
intervals in both cases. Scenario B's reward remains just outside its interval;
no universal agreement claim is warranted. Its spatial trend still shows a
remaining finite-grid bias, alongside Monte Carlo uncertainty. The finite lower
boundary is another error source; low final lower-cell mass is a diagnostic,
not a rigorous bound on the probability of ever reaching the lower boundary.

At the shrinking boundary, 512-cell immediate event masses are `.216253` and
`.120060`. The corresponding MC estimates are `.217780` with interval
`[.214162,.221398]`, and `.119000` with interval `[.116162,.121838]`. Expansion
produces exactly zero immediate event mass in the finite reference and MC.

### Refractory refinement remains a separate approximation

At fixed 256 cells, finite event counts for `k=1,4,16,64` are:

| k | Scenario A | Scenario B |
|---:|---:|---:|
| 1 | .754699 | .784486 |
| 4 | .749142 | .765276 |
| 16 | .747139 | .761749 |
| 64 | .746566 | .761629 |
| Deterministic-tau MC | .745020 | .756460 |

The JSON also records an independently sampled **matched Erlang law** for each
row, so spatial/remap error is not conflated with replacing Erlang by a fixed
delay. Deterministic-delay MC intervals are `[.739851,.750189]` and
`[.750311,.762609]`. Some matched-Erlang finite rows remain slightly outside
their MC intervals at 256 cells. Increasing `k` cannot remove upwind, domain or
remapping error.

## Conservation, composition and gradients

Across the ten spatial configurations and their segments, maximum absolute mass
error was `7.24e-12`; all reported probabilities were nonnegative. Same-grid
identity remaps preserve every state component to roundoff. Arbitrary
expansion preserves phase mass and remaining-delay expectation exactly.

Each segment propagates an augmented finite generator. Splitting all segment
durations into `1,4,16,64` pieces, while keeping physical boundary jumps at the
same times, changes the full final state by at most `6.11e-16`. This tests
composition of the stated finite operators. It does not eliminate spatial or
projection error or justify continuously moving boundaries between segments.

An interior boundary derivative at `b'=.637` includes overlap weights, swept
mass, reset injection, reward, subsequent propagation and moments. Autograd and
centered finite differences with step `1e-5` agree to relative error `1.13e-10`
for the combined objective, and `3.61e-12` for immediate event mass alone. The
latter derivative is approximately `-.516532590`, so the instantaneous event
channel has a real derivative rather than a surrogate step-gradient.

Overlap lengths and interpolation are piecewise differentiable. Gradients at
cell-edge alignment, reset knots, drift sign changes, or the zero-delay branch
are not certified by this interior check. The conservative swept-mass formula
is used directly; no soft threshold substitutes for physical mass accounting.

## A coherent value-projection interface

`projected_policy_values` evaluates the local fixed-threshold **finite-generator
policy**, solving `(rho*I-Q.T) J = reward_rate`. Thus refractory continuation
matches the same Erlang generator. An eligible active-state intervention value
is `G(x)=a*x+c+J_after_reset`. This evaluates a fixed policy; it does not solve
an optimal boundary or anticipate the subsequent input schedule.

The returned fields distinguish action eligibility:

- `continuation`: all active and refractory mass projected against `J`.
- `eligible_continuation`: active mass projected against active `J`.
- `eligible_intervention`: the same active mass projected against `G`.
- `eligible_continuation_gap`: active mass projected against `J-G`.
- `eligible_mass`: total active mass; refractory actions are disallowed.

Subtracting active-only intervention from all-state continuation would compare
different masses and should not be labeled an intervention gap. The explicit
eligible gap avoids that mismatch. Measured Bellman residuals were at most
`2.85e-14`. This is an interface demonstration, with no learned content network
or task-quality result.

## Cost, source identity and remaining scope

Final measurement used Python 3.12.14 and Torch 2.8.0+cpu, float64, one Torch
intra-op and one inter-op thread. The final numerical script took `2.3134`
process CPU seconds and `4.1036` wall seconds; cumulative peak process RSS was
`303740 KiB` on the same AMD EPYC 9V74 host used for the preceding references.
Other authorized work was running on the host, so wall time is not an isolated
performance result. Imports occurred before the script's internal timing;
the reported CPU interval covers its numerical experiment and measurements.

Three-segment scalar finite runs cost approximately 19 ms at 128 cells,
80–83 ms at 256 cells, and 479–515 ms at 512 cells. These are single-run CPU
measurements, not repeated optimized benchmarks. A 512-cell, 16-phase state
has 528 probabilities plus two accumulators and uses a dense 530-by-530
augmented matrix. Matrix exponentiation and value-system solves remain expensive
for many channels. No energy measurement or neural-network efficiency claim
is made.

Final source SHA256:

```text
moving_flow.py
698a7e621f89fcde4aee6f485575470ec04e2d11fe1021b2c5ce4e92e720a05c

moving_flow_tests.py
ae59cf2fcc2c9a7aff648373254af54b38a5fed2ee88d8add085d8bcf7cd9d68
```

The JSON also binds the reused sampler, unchanged `distributional_flow.py` and
unchanged frozen `model.py` hashes. The formulas, remapping, affine-reward
integration, phase preservation, projection mean-error bound, exact-event MC
loop and finite-policy linear system received an independent mathematical
review. All eight tests pass.

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/178ced6a501f/torch_runtime \
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m unittest experiments.hcsn_free_boundary_v1.moving_flow_tests

PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/178ced6a501f/torch_runtime \
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.hcsn_free_boundary_v1.moving_flow \
  --output NEW_EMPTY_DIRECTORY --samples 50000
```

The next neural integration would retain this distribution across inputs,
couple coherent eligible value projections to high-dimensional content, and
evaluate structured/sparse propagation costs before a new frozen benchmark.
Changing reset, refractory law or lower-domain support during an episode needs
a further physical contract. Continuous boundary motion, global optimality,
classification improvements and large-model scaling remain untested. This
reference does not retrospectively repair or replace the frozen mean-state
classification study.
