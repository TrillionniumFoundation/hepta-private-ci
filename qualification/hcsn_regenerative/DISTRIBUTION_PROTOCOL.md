# Distribution continuation qualification, FV v1

This is the independent candidate `hcsn-regenerative-distribution-fv-v1`.
Its point-kernel parent is the published V4 source at
`d9bff7b92965e372db9bcbaf4d1a20c42d688603`. V4 results do not qualify this
candidate. The original 170-run campaign, Hepta × NDU factorial experiment,
external-task mechanism benefits and production recovery remain separate.
This protocol is written before the first complete FV qualification run.

## Process and represented state

The physical process is dX = mu dt + sigma dW on X>0, killed at X=0.
An event enters a refractory state for exactly d physical seconds, then
releases at fixed positive log-margin a. The threshold and generator are
fixed throughout a trajectory, including between training blocks. The V4
domain remains abs(mu)<=2, .05<=sigma<=4 and .01<=q<=4. This candidate has
1e-4<=dt<=d<=8, 0<a<=8 and fixed scalar parameters. It does not implement d=0,
QVI boundaries, observation-conditioned drift or generator gradients.

The explicit `DistributionState` contains unconditional masses of uniform
active cells [lo,hi), one exponential upper-tail density
lambda exp(-lambda (x-L)) on [L,infinity), and uniform refractory
remaining-time cells (lo,hi]. Active and refractory Dirac atoms are separate
and coalesced without projection. The boundary atom x=0 triggers an immediate
hit; a phase atom at remaining time dt becomes a reset atom at the endpoint.
The upper tail is propagated through the same killed process and can return
below L or hit. It is never an absorbing escape category.

Active grids have at most 256 cells and .25<=L<=8; refractory grids have at
most 64 cells and end exactly at d; .25<=lambda<=8. Grid edges, atom positions,
quadrature order and durations are fixed configuration, never trainable.
States expose exact dimensions, batch shape, masses, atoms, generator identity,
completed steps and physical elapsed time. Each batch shares one clock and
duration. Decimal duration data are accumulated as rational numbers, so
.04+.07 equals .11 exactly; durations need not be equal ticks.

## Q P R continuation and numerical contract

Each call lifts the supplied density coefficients (R), evolves under the
same process for physical dt (P), then projects back to the declared cells
and exponential tail (Q). The supplied state is used directly by the matrix
and atom paths. No origin-based recomputation or fresh point initialization
substitutes for continuation. Because dt<=d, each active portion has at most
one hit in the step. Incoming phase mass may release and hit once. Repeated
hits over successive steps remain represented.

Construction explicitly uses FP64 fixed kernels and outer Gauss rules at
orders n and 2n, n in {8,16,32,64}, followed by declared FP32 or FP64 execution.
Finite cells use uniform-node integration; tail and release coordinates use
squared uniform transforms to resolve endpoint structure. Construction rejects
negative/nonfinite coefficients, row L1 order differences over 2e-7, scaled
reward order differences over 2e-7, or conservation residuals over 3e-10.
The occupation reward comparison is scaled by dt. FP32 materialization
requires row residual at most 3e-6. State total mass must remain within 5e-5
for FP32 or 5e-10 for FP64. No transition normalizes, clips or repairs mass.
Construction, materialization, source and execution dtype are recorded.

These checks are numerical rejection rules, not proofs of accuracy over the
whole parameter domain. Positive probabilities lost to FP32 materialization
are counted with their source FP64 mass. Relative/log-tail accuracy is not
qualified. Materialization counts do not detect probabilities already lost
to underflow during FP64 construction. There is no finite-domain truncation: the explicit tail covers the
whole half-line. There is no renewal truncation under dt<=d. Those zero
truncation fields do not mean zero projection or quadrature error.

Each receipt reports componentwise local transport-distance bounds: at most
mass times half-width for uniform active and phase cells; for tail projection,
an upper bound on unprojected excess beyond L plus tail mass/lambda. A free
Gaussian positive-part bound gives the excess bound. These are conservative
analytic diagnostics, not floating-point interval certificates. Accumulated
fields sum local active-distance and phase-time diagnostics separately; they
are not certified global error bounds or total-variation bounds. In
particular, repeating projection at a fixed spatial grid while dt tends to
zero can add artificial diffusion. The audit therefore refines active and
phase cells together with dt and records the semigroup defect.

`condition_on_likelihood` performs a separate, explicit Bayes update with a
nonnegative cellwise/atomwise constant likelihood. It returns its evidence
and requires an observation identity. This observational normalization is
never invoked by `advance` to hide transition errors. Gradients through state
coefficients, likelihood weights and readout are supported; generator, grid,
duration and atom-location gradients are outside this candidate.

## Prospective gates

The unit suite covers independent adaptive FP64 uniform-cell and infinite-tail
integrals, tail return, batch state gradients, actual state dependence, exact
boundary/release atoms, full state serialization, observation gradients and
invalid configuration rejection. CPU/CUDA FP32/FP64 are covered when CUDA is
available. Absence of CUDA is not recorded as GPU qualification.

The independent audit uses fixed mu=-.1, sigma=.3, q=.15, a=.25, d=.11,
point x=.35, endpoint L=1.6 and total time .32. Coupled grids are active
32/64/128 cells, phase 8/16/32 cells and dt .08/.04/.02 respectively. It
compares against direct adaptive FP64 continuous-process propagation on the
common coarsest bins, and records undiscounted hits, discounted hits and
active occupation. Prospective gates require fine-state L1 error <=.04,
fine error less than coarse error, and fine scalar reward errors <=.01.
These are only bounds for these named fixtures. The fixed-grid semigroup
defect is recorded without treating exact composition as an expected result.

Recovery executes learned observation likelihood and readout with Adam, a
dedicated data RNG, full active/tail/phase measure, physical clock and a
predefined unequal duration schedule. It checkpoints after one block and
executes the next block both uninterrupted and in a fresh Python process.
State is detached at each block boundary in both paths: this is explicit
truncated backpropagation, not serialized autograd graphs. The next block
must agree exactly in observations, predictions, loss, gradients, model,
optimizer, RNG and final probability state on the same dtype/device.
Source hashes and every fixed operator matrix/reward hash must match.

Negative controls keep restored model, optimizer, RNG, physical clock and
schedule fixed while replacing the whole measure, moving phase mass into an
active cell, or moving tail mass into an active cell. They must preserve data
hashes while changing predictions and the learned next-block parameters.
This establishes that the stored measure, including phase and tail, is
consumed. It does not establish production fault tolerance or external task
gain. All failures and repeated attempts retain independent source identities.

## Cost and scope

Report construction wall time, matrix storage, replay/negative-control optimizer
updates, complete job wall time and available memory statistics. CPU clocks
exclude children unless explicitly stated. Encoder/decoder and observation
costs belong to subsequent task experiments and cannot be omitted from their
budgets. Physical energy remains unknown without actual full-machine
measurement. Never substitute TDP or theoretical arithmetic energy.
