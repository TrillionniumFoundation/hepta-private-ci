# Round6: acquired feedback, trained controls and actual native execution

## Scientific scope and fixed identities

This is a new execution following the negative Round5 result, not a replacement
for its confirmation or a reconstruction of missing Round4 final records.
The parent research commit is `d6a828eac92cc8df03f3ccce0a6d2fc04c7ce9f6`.
The machine-readable prospective design is `registration.REGISTRATION`.
Confirmation is constructed only after source, prepared data, model, native
binary and environment freezing and verified remote publication.

The recovered native binary is exactly
`b519cae26325f818d9596aab34504490a0b5355b9eb633369878e6f07a50e179`, built historically
from `0acfd9b27db910c180b0d8911f39aea469b7f864`. Its original build receipt is retained.
This round runs that binary; it does not claim a new Rust compilation. The sparse,
neuron runtime and types sources match the observed current main mechanism.
The experimental local owner does not activate Agentd or grant authority.

## State, event, time and conditional information

Each case has delivered initial output A, private constant residual E and target
Y=A+E. At stage one, a noisy sensor of Y is acquired. A paid wait acquires one more
independent sensor; then only stop or repair is available. Stage is the number of
acquired observations. E does not diffuse between these stages. A schedule slot,
communication increment and physical first-passage time are different objects.

Given acquired history F, the runtime law is a positive one/two-component Gaussian
mixture for E. At the public repair cost c its three events are
E<=-sqrt(c), -sqrt(c)<E<=sqrt(c), and E>sqrt(c). Call and put are directional tails
of that one law. The existing strict finite positive-variance schema is retained.
The study has no missing sensor draws; missing, unobserved future information,
zero transport increments, survival and physical reset are not relabeled as each
other. Existing typed first-passage/reset interfaces remain separately scoped.

The policy worker does not load private DATA.npz. A separate broker process owns
the target and potential second observation. Start returns acquired public fields
only; wait returns the second observation only after the action. A model receives
only the six-field public Owner schema. Terminal delivery is actually written,
flushed and reopened through the existing text/PNG transport. Private scoring
occurs after final readback. This is program information separation, not a hostile
same-UID security claim.

## Learned operators, controls and intervention

Five fresh training seeds use 256 nominal training and 128 development cases each.
The latent nominal prior is a two-normal mixture; the actual Gaussian sensor
noise multiplier is 1.75. The model fits mixture prior parameters by 80 actual EM
updates and noise scale by supervised maximum likelihood. A one-normal prior is
fit to exactly the same training residuals. Analytic, numeric/raw-sparse and
history readouts each have 63 weights and the same three ridge candidates, 600
gradient steps per candidate and five development offsets. Development selection
uses complete two-stage realized outcomes. Candidate weights and changes persist.

Nine arms are fixed: event, direct, float, gaussian, probit, analytic, numeric,
history, uncalibrated. The first three share a learned mixture and differ only in
transport. Gaussian and probit express the same fitted one-normal conditional
law using precision and independent dense conditioning. Analytic supplies actual
native CDF-derived drives to the original sparse kernel. Numeric supplies public
numeric drives to that same kernel; it is the original sparse feature control,
not a numerical-CDF implementation. History uses a matched 63-dimensional
polynomial/RBF representation. The uncalibrated arm shares the fitted mixture
prior but fixes noise scale to one. Prior and noise fits are shared costs.
The noise-scale contrast is float-minus-uncalibrated: both use the same FP64
transport, so the learned noise intervention is not mixed with a codec change.

The arms share task information and readout candidate budgets where applicable.
They do not all have equal architecture, parameter counts or arithmetic costs.
The common law also supplies repair amount and continuation for learned controls;
the primary contrasts isolate feature transformation within that shared scaffold.
They do not establish universal neural architecture superiority.

## Continuation and actual task utility

Repair amount a is the received law's mean rounded to Q24; its conditional gain
is 2*a*E[E|F]-a^2-c. For a paid sensor Z=E+noise, continuation evaluates
E[(E[E|F,Z]^2-c)+|F]-w. For one Gaussian this has the normal truncated-moment
formula. For a mixture, posterior mean is strictly increasing because its
derivative is posterior variance divided by sensor noise variance. Two roots at
plus/minus sqrt(c) separate the positive-payoff regions.

The primary integrator uses those roots and adaptive quadrature in each
component's standardized sensor coordinates over [-12,12]. Its Gaussian tail
truncation bound is derived separately from SciPy's estimated quadrature error.
The latter is not a rigorous interval certificate. Rounding continuous optimal
repair to Q24 loses at most 1/(4*2^48) in squared-error gain. This bound excludes
future law transport/parameter quantization and deviations of the learned future
repair readout. The shared continuation is thus a declared planning approximation;
actual actions and delivered outputs, not this approximation, determine scores.

Utility is 1-(delivered-Y)^2-c*repair-w*wait. The final value is scored from actual
readback. Task costs are utility units. Full process wall/CPU, requests, original
sparse ticks, packets, bytes, training and replay costs are separately measured;
there is no assumed conversion from time/energy/currency to task utility.

## Confirmation and independent acceptance

Fresh confirmation has 128 cases per seed in nominal, drift and standardized
Student-t5 latent domains: 1,920 independent trajectories, 17,280 arm executions.
Models are frozen across domains. Shift domains are labeled only in the private
generator and scorer; the model does not receive a regime identifier.

Two primary nominal contrasts are analytic-minus-numeric and analytic-minus-history
actual utility. Each requires mean gain >=.005, every seed mean positive, and the
lower endpoint of a nominal 97.5% hierarchical bootstrap interval above zero.
The family has two comparisons, 4,000 replicates and five training clusters.
Paired trajectories, not arms, stages or repeated readbacks, are sampling units.

Codec equivalence/noninferiority, gaussian/probit equivalence and noise-scale
intervention are reported separately. Domain-shift contrasts are descriptive.
Calibration is evaluated on the common first acquired stage for every arm/domain:
ten-bin classwise ECE<=.04 and 95% interval coverage in [.92,.98]. Selected second
stages are separate diagnostics. These empirical gates do not form a simultaneous
population certificate. A failed gate remains failed; confirmation is not reused
for fitting, retuning, seed replacement or relabeling a secondary result as primary.
The joint research indicator combines both primary utility gates with nominal
analytic calibration. Codec/runtime and shifted-domain qualifications retain
their own separate results.

All native component and sparse calls, original packets, delivery files and owner
states remain replayable. Independent checking reconstructs dense posteriors,
decodes PNGs, verifies acquired-information order, replays native calls, recomputes
choices and scores and audits inference separately from training/replay cost.
Native confidence, abstention and DENY_ALL posture remain unchanged. Partial
cross-owner transactions require reconciliation. Production promotion is false.
