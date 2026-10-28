# Round 4: exact mixtures, public context and retention

## Two information experiments

The zero-context task preserves the original prediction information: one query
trajectory supplies six possibly missing sensor observations, their physical
times, masks and measurement variances. Its future latent states are scored at
horizons 0.5, 1 and 2. The inherited generator uses a Gaussian Brownian process
with drift 0.12 in the old environment and 0.32 in the shifted environment.
These law names are generator/scorer metadata and never prediction features.

The context task is a separately registered information experiment. Before
one query, eight distinct prior trajectories supply their public sensor
histories. A component/regime is fixed across this whole block; conditional
on it, all nine paths and their observation noises are independent. The eight
prior paths finish before the query begins. Their internal clocks restart at
zero for each path. The query receives no latent values, future targets,
regime label, window index or trajectory ID as a feature. Its externally
specified block boundary says which eight histories belong to this query;
it does not announce a regime change. Context selection is fixed by the task,
not selected by predictive success or access to the target.

Each context/query block is independent of other blocks. The same original
confirmation blocks are reused across the twelve retained checkpoints; those
reuses are not new independent observations. All query and public-context
arrays are retained in compressed NPZ files. Context files contain only
`obs`, `times`, `mask`, `occupied` and `obs_var`, without latent/future arrays.
A context arm's acquisition budget is nine histories per query, each with six
scheduled sensor slots. Its gain against the zero-context ablation cannot be
attributed to a new scalar activation or to computation alone.

The context and zero-context profiles have separate primary gates. Passing
with context never changes the zero-context result. These tasks do not model
an unannounced arbitrary mixture of unrelated query regimes, adversarial
context substitution, online change-point detection or indefinite retention.

## Conditional law and exact computations

Component `j` is an independently parameterized diffusion with initial
`X(0) ~ Normal(0,1)`, drift `b_j`, process variance rate `q_j > 0`, and positive
observation-noise multiplier `r_j`. The component remains fixed within a
block. Missing observations propagate physical time without a likelihood
factor; observed same-time sensors each contribute their own likelihood.

Let `ell_j(query)` be the observed-sensor log likelihood and let
`ell_j(context)` be its sum over the eight prior paths. For a fitted prior
`pi`, the posterior shifted-component weight is

\[
w=\operatorname{sigmoid}\{\operatorname{logit}(\pi)
+\ell_1(\mathrm{query})-\ell_0(\mathrm{query})
+\ell_1(\mathrm{context})-\ell_0(\mathrm{context})\}.
\]

The context terms are absent in the zero-context ablation. The endpoints
`pi=0` and `pi=1` use exact pure-component branches. Each component's filter
produces `m_j(h)` and `v_j(h)`. The forecast is the exact mixture

\[
p(x_h\mid\mathcal F)=(1-w)\,\varphi(x_h;m_0(h),v_0(h))
+w\,\varphi(x_h;m_1(h),v_1(h)).
\]

Posterior weights stay fixed across future horizons without a new observation.
Every component propagates its own mean and variance linearly in physical
time, so the augmented state `(component, X)` has the declared diffusion law.
No arbitrary horizon variance multipliers or moment collapse enter the exact
mixture. Marginalizing the latent component does not make `X` alone Markov.

Density NLL uses log-sum-exp of component log densities. Put, neutral and call
use log-sum-exp of stable Gaussian interval probabilities at thresholds
`-0.6` and `0.6`. An 80-iteration monotone bisection between component
quantiles gives the exact-mixture central 95% interval to numerical precision.
A pure component is a valid one-component serialized law. These are terminal
probabilities, not first-passage events or discounted option prices.

The public scalar transport schema is `hepta.conditional-law.v4`, with
positive serialized `weights`, `means`, `variances` and `semantics="terminal"`.
The array API also carries stable `log_weights`. It forms both posterior log
weights independently with `-logaddexp(0,+/-logodds)`; density and event-log
scoring consume those logs directly. This preserves physical far-tail scores
when a tiny posterior probability is invisible to subtraction from one, and
even when the linear probability underflows. Component log densities and
posterior log odds must remain finite in the numeric domain.

`law_at` omits only structural pure-component zeros whose log weight is minus
infinity. If a physically positive component has a finite log weight but its
linear weight underflows, transport through the positive-weight scalar schema
is rejected explicitly. The broader physical log-score domain is therefore
not silently equated with the runtime serialization domain.

## Fitting and matched controls

Five new training seeds are `1213,1427,1619,1823,2017`. No Round 1–3 fitted
model, development label or confirmation label is used for fitting. Each
seed first fits a fresh old-environment anchor on 512 training trajectories.
Its drift, process variance and observation-noise multiplier are optimized
by the inherited Gaussian conditional-NLL optimizer. Each subsequent window
fits an adaptive component on 256 fresh current trajectories and a replay
Gaussian on those same 256 trajectories plus 256 retained original rows.
The component optimizer uses all four declared training acquisition stages;
those stage/horizon labels remain correlated within each trajectory.

Four mixture/readout heads fit one prior logit using exactly the same 256 old
and 256 new labelled queries: exact zero-context, projected zero-context,
exact context and projected context. The context heads additionally condition
on the same retained eight public-only histories per query. The prior is
fitted by L-BFGS-B in `[-6,6]`, using an analytic derivative. Exact-mixture
heads optimize exact density NLL; projected heads optimize their own Gaussian
NLL. All fits retain initial/final parameters, gradients or objective traces,
dataset identities, optimizer outcomes and measured time. Component dynamics
and noise parameters are genuinely trained; hard pulse events are not claimed
to receive end-to-end surrogate gradients.

Every learned selected head then uses the same 256 old and 256 new development
queries and the same public contexts. There are 21 candidates per head. For
mixtures the candidate prior is `s*pi_fit`, with `s=0,.05,...,1`. This is an
altered prior under the same two-component block law, not an arbitrary
interpolation of final probabilities. The unchanged anchor is always feasible.
The replay baseline uses the same 21 strengths to interpolate the physical
parameters from anchor to replay fit. It receives the same available context,
though its single fixed component cannot distinguish a shared latent regime.
The projected context model is the stronger Gaussian baseline that actually
uses the same context likelihood evidence.

The selection rule is identical for all five fitted heads: old-development
mean density-NLL change plus `1.645 * paired SE <= .02`, then smallest
new-development density NLL; candidate index resolves exact ties. The reserve
is a selection heuristic, not a simultaneous or distribution-free confidence
bound. No confirmation label participates. Fitting counts and candidate counts
match, but architectures, optimizer work and arithmetic costs are not identical.
The frozen anchor is an intentionally non-adapting reference.

`mixture_classical` independently computes both sensor likelihoods and future
conditional moments by dense Gaussian covariance solves using exactly the
selected component parameters and prior. It is an equivalent classical
implementation, not a separate training algorithm. `moment_context` is fitted
and selected on its own Gaussian objective. `same_weight_moment` instead uses
the exact mixture's selected weights and substitutes its first two moments,
isolating mixture shape at fixed weights. Moment controls do not inherit the
exact mixture's augmented-state transition law.

The two Q24 profiles round learned component drift/noise parameters and the
prior before filtering, then recompute the conditional mixture. These define
coherent quantized component laws; their classical counterpart uses exactly
the same rounded parameters. This profile is distinct from the separate
runtime experiment, which quantizes forecast parameters, executes native
component heads, and projects final categorical counts. Native qualification
is not inferred from this predictive calibration test.

## Freeze, independent sampling and acceptance

Preparation creates all sixty checkpoints using training/development only.
Every source hash is checked at both preparation start and finish, every
checkpoint is actually reloaded, and its predictions must match. The parent
freeze binds source files and every prepared artifact before confirmation
construction. Confirmation rejects changed sources, changed prepared bytes
or a missing freeze binding. A study destination is created exclusively;
failed/partial attempts are retained explicitly rather than overwritten.

Training/development seeds use base 400000000 and confirmation uses base
500000000, plus `10000*training_seed + 100*window + code`. The actual code
mapping is in `registration()`. Context generation uses the corresponding
query seed plus 50. No confirmation seeds overlap the development-only
feasibility diagnostic at 4000000001/4000000002 or the formula smoke at
4000000101/4000000151.

Confirmation uses 256 original old blocks per seed, reused across twelve
checkpoints, and 256 fresh new blocks per seed/window. Thus there are 16,640
unique query blocks and 133,120 prior public histories, not 60 independent
trained systems. The three nonzero-horizon scores are averaged within a query
before a bootstrap. Resampling first draws training seeds, then whole blocks
within each fixed window; horizon observations and repeated old probes are
not sampled as independent rows. Five seeds and twelve fixed windows provide
an empirical bounded experiment, not a population or infinite-time theorem.

Retain the old empirical threshold: the worst seed-averaged old density-NLL
increase over windows must be at most .02, and final-new mean loss must be no
worse than the anchor. Efficacy additionally requires final-new NLL improvement
at least .005, improvement in every seed and a bootstrap upper endpoint below
zero. The two prespecified primary profiles use 97.5% two-sided intervals
(Bonferroni family of two); other arm/mechanism intervals are descriptive 95%.
Drift calibration requires pooled classwise ten-bin ECE at most .04 and 95%
interval coverage in `[.92,.98]`. The joint empirical gate requires retention,
efficacy and calibration together. Worst individual seed/window degradation
is also reported, independently of the registered seed-averaged gate.

There is no universal pointwise retention certificate. A context success does
not rewrite a zero-context failure. Equivalent classical results do not become
evidence of a new function class, and predictive calibration does not replace
actual paid-feedback utility, packet/latency accounting or runtime recovery.
