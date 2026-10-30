# Retained-distribution joint content model

This study tests whether retaining the declared physical distribution, rather
than repeatedly reducing its active state to a mean, improves a jointly trained
sequence model. It is a new source identity after the v1 results. The original
v1 searches and their negative results remain unchanged.

## State and outputs

Each layer has a 32-dimensional deterministic content vector and eight physical
channels. Each physical channel retains eight active spatial-cell masses and
two refractory-phase masses, together with its previous boundary. The layer
state is therefore a collection of finite-state marginal distributions. It is
not a representation of every correlation in a stochastic high-dimensional
content network. There is no resampling or collapse in the distribution arms.

At each observation, the pressure process first undergoes the physical
old-boundary-to-new-boundary overlap map, including an immediate event for
covered mass when the boundary shrinks. It then evolves under a frozen local
finite generator for `0.1 * dt`. Repeated events, reset and passage through the
refractory phases are included. Event counts can exceed one and are never
relabeled as event probabilities. A zero-duration observation still applies a
boundary-jump event. It leaves the content vector unchanged because its content
update duration is zero.

Reset and the refractory mean are learned parameters, fixed within each
forward episode. Optimizer updates happen between episodes. Refractoriness
constrains the physical pressure process; the shared content vector is allowed
to update while some physical channels are refractory. It is a separate memory
state, not another stochastic coordinate in the scalar oracle. A layer passes
`input + output_projection(content)` to the next layer. Boundary, margin,
distribution and value fields are exposed as auxiliary outputs and gate
features; content is not compressed into a single boundary scalar.

| Output | Meaning |
|---|---|
| `probability` | Full active-cell and refractory-phase masses, last axis length10 |
| `flow_mass` | Sum of those masses; nominally one, audited to a declared floating-point tolerance |
| `activity` | Expected event count in this observation interval, including any zero-time boundary-jump event |
| `modeled_reward` | Expected undiscounted physical firing reward `x-K` in the interval |
| `cost` | `K * expected_events`, a physical-model cost component; not measured runtime, energy or owner read fees |
| `continuation` | Full-distribution expectation of the finite-generator own-policy value J |
| `intervention` | Full-distribution expectation of G: immediate intervention on eligible states, forced continuation on refractory states |
| `eligible_intervention` | Active-mass contribution to G, without renormalizing by active probability |
| `refractory_continuation` | Refractory-phase contribution shared by J and G |
| `margin` | Active-mass weighted `boundary - cell_center`, without renormalizing by active probability |
| `active_center_variance` | Active-mass weighted conditional variance of cell centers; excludes within-cell variance and refractory reset position |
| `content` | Deterministic content memory after the ordinary retention/write update |

The ordinary-feature arm does not use or report J/G outputs. It omits the
unused value-vector solve instead of paying artificial value-computation cost.
All other physical fields retain the same meaning.

## Boundary and value scope

The physical coefficients use bounded transforms:

| Parameter | Range |
|---|---|
| drift μ | (-0.3,0.5) |
| diffusion σ | (0.3,0.6) |
| discount ρ | (0.15,0.75) |
| firing cost K | (0.35,0.70) |
| reset r | (-0.3,0.1) |
| refractory mean τ | (0.3,1.2) |

Floating-point sigmoid saturation may reach the listed endpoints; the closed
bounds remain valid for the numerical-rate certificate. The fixed lower spatial
wall is -2. Two Erlang stages with mean τ have Laplace factor

\[
d=(1+\rho\tau/2)^{-2}.
\]

The free-boundary arm applies the existing implicit Brownian boundary solver
with effective deterministic delay

\[
\tau_{\mathrm{effective}}=2\log(1+\rho\tau/2)/\rho.
\]

That boundary is the optimal stationary boundary of the corresponding
infinite-domain Brownian/Erlang model. The physical content model instead has a
finite grid and reflecting lower wall. Its J/G vectors evaluate the actual
finite-generator threshold policy, using the exact finite-chain first-hit
Laplace transform and phase discounts. The analytic boundary is **not** asserted
to optimize the finite grid, the input-dependent sequence, or classification
return. The separate policy-gap audit explicitly measures this distinction.

The conditional ordinary threshold is

\[
b=K+.01+3.99\,\operatorname{sigmoid}(a+s\mu).
\]

Its gap starts at0.65 and s starts at zero. Bounding the gap keeps reset and the
initial value0 inside the cell-center interval for all declared raw parameters.
The two extra coefficients per physical channel add16 effective parameters;
they are not dummy padding.

## Numerical causality and gradients

The registered neural profile uses fixed uniformization rate8.1 and fixed21
Poisson terms per substep. For each token separately, it sets
`n=max(1,ceil(physical_dt/.36))` and composes `n` equal substeps by binary
powering. Boundary remapping occurs once before those substeps; events, rewards,
repeated resets and refractory transitions accumulate throughout them. The
explicit resource cap is1048576substeps. The declared parameter bounds imply
gross active rate below7.961 and phase rate at most6.667. Invalid rates,
nonfinite/negative durations and the resource cap are rejected. There is no
adaptive fallback based on the batch or future suffix.

Local transition, event, reward and value arrays are prepared over the complete
sequence because their coefficients depend only on that observation's causal
input and static learned parameters. The fixed rate/term count and per-token
subdivision prevent a future suffix or neighboring batch item from selecting
another token's numerical effort. Already completed items remain unchanged
while a longer item continues its binary composition. Probability and content
then recur over time. A
model-level test changes both an unseen suffix and a batch neighbor and checks
the untouched prefix bit-for-bit. Streaming/batched numerical comparisons also
remain explicit; cross-implementation or cross-platform bitwise identity is
not claimed.

Training uses first derivatives. Upwinding, overlap remapping and reset
interpolation are piecewise differentiable. Neither higher-order derivatives
of the implicit boundary nor global smoothness of the hybrid system is
certified. The finite grid, finite lower domain and Erlang refractory law are
declared modeling approximations rather than hidden numerical fixes.

All five parameter groups—content, dynamics, boundary, reset and refractory—
receive task cross-entropy gradients and are audited for actual numeric changes.
An additional integration test detaches all direct physical-parameter gate
features and every analytic-feature input. Task gradients still reach all four
physical parameter groups through the retained probability propagation. This
rules out the narrower failure mode where parameters appear trainable only
because their raw values bypass the physical process into a gate.

## Comparators and information

The seven registered arms are:

| Arm | Difference from distribution free dual |
|---|---|
| `distribution_free_dual` | Full retained distribution, Brownian/Erlang boundary, finite-policy J/G features |
| `distribution_conditional_dual` | Same retained distribution/value semantics; ordinary bounded input-conditioned threshold |
| `distribution_free_ordinary` | Same distribution and boundary; replace J/G features by ordinary mean/variance transforms; omit unused value solve |
| `active_mean_collapse_free_dual` | After each propagation, collapse only active mass to a two-center representation of its conditional mean; preserve every refractory phase |
| `legacy_free` | Original v1 mean-pressure/cooldown mechanism, with active projections and a re-matched inner width; retrained here |
| `two_gates` | Independent ordinary gated recurrent network |
| `transformer` | Independent causal Transformer with the same public time inputs |

Every physical arm supplies its gate with the complete probability state and
the same μ,σ,ρ,K,r,τ,b. The ordinary feature control is therefore not deprived of
information used to compute J/G. All models share the frontend and readout
initialization and the actual minibatch prefix for each task/seed. Three physical
arms have exactly the same17936backbone parameters. The conditional arm has17952;
legacy_free17672; two_gates17770; Transformer18392. All are within3% of the target.

The active-mean ablation isolates loss of active distribution information. It
does not reproduce v1's first-hit-at-interval-end reset or mean-cooldown
approximation; the separate legacy comparator retains that broader difference.

## Registered study

`CONTENT002_PROTOCOL.json` fixes176searches and352LR candidates: seven models,
six tasks and three seeds, plus five mechanism arms on two fixed tasks and eight
seeds, with overlapping searches reused. Every candidate gets60training CPU
seconds; common primary validation checkpoints are15/30/60CPU seconds. A
complete update's overrun is charged. The maximum-update cap is65536 and is not
accepted as a substitute for the registered CPU budget.

The tentative20→40→60budget history was decided using train-only engineering
throughput, before any content001heldout evaluation. It is recorded explicitly,
and the corrected content002 retains those budgets, seeds, LR choices and gates.
Two learning rates (.001,.003) both finish before the validation-only selection
lock. A saved exactly128-update snapshot adds no primary selection opportunity.

The four mechanism comparisons use paired seed differences, first averaging
the two fixed tasks within each seed. Exact two-sided sign-flip p values share
one Holm family. A positive gate requires mean advantage at least1pp, Holm
p≤.05, and a positive lower endpoint of the nominal paired-t95%interval. The
three-seed six-task panel is descriptive; its2pp content screens are not
equivalence tests. These are previously observed v1datasets, so this is a
source-registered post-baseline study, not a new-test confirmation. Some heldout
outcomes also exist in the aborted content001; they are not reused here.

Workers retain numeric initialization/checkpoint files, all minibatch/gradient
logs, validation locks, heldout prediction coordinates and complete process
costs. Analysis reconstructs seeded initialization and every minibatch prefix,
checks all selection and checkpoint identities, independently recomputes
prediction labels/accuracy/CE, and replays the first four test examples from
every selected checkpoint. It enforces source, data, parameter-count and full
cost-ledger identities; failed or invalid runs cannot silently disappear.

Complete worker costs include imports, setup, both LR fits, validation,
checkpointing and heldout evaluation. Training CPU is nested inside that cost.
The scheduler's aggregate process-tree observation is kept separately from the
sum of worker records and its self CPU, so these overlapping scopes are not
silently added. Energy is not measured.

### Aborted content001 and the correction

The original `CONTENT_PROTOCOL.json` and its exact eight source files remain
sealed under `results/content001/source`. It incorrectly limited each observed
physical duration to0.36. The real timing generator normalizes32positive
lognormal gaps to a total32, so an individual observed `dt` can approach32.
The train-only duration audit found a maximum of4.95755148, already outside
the assumed limit of3.6. This was an input-domain integration error.

The scheduler stopped adding jobs after20searches started. All started workers
finished normally and were reaped with complete wait4 receipts:16completed and
4failed;156were never started. No worker was killed. Complete worker CPU was
2224.722337seconds, and the scheduler-tree observation was2227.408732seconds,
which includes those workers. Both evidence and costs remain in the research
ledger. Existing heldout predictions from the16completed searches are disclosed;
no comparative content conclusion is made from that partial matrix.

The repair uses token-local subdivision and does not depend on the observed
maximum. The new train-only preflight covers all six tasks and seven arms,
deliberately includes each task's longest training intervals, checks the
source-contract limit with an interval near32, and checks long sequences. The
new scheduler also honors `STOP_REQUESTED.json` and automatically stops adding
jobs after any worker failure; every active child is allowed to finish and its
cost is retained. Aborted matrices never produce a `COMPLETE.json` receipt.
Five simultaneous workers are used because the first study's measured peak
per-process RSS of961953792bytes exceeded the900MB engineering threshold.
