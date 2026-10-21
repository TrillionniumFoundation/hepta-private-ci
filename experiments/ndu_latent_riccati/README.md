# Continuous latent NDU / Riccati mechanism experiment

This experiment implements the three-layer protocol discussed on 2026-10-21.
It is a new experiment, separate from `multimodal_output_portfolio`, whose
independent v1.1 primary result was negative. No previous positive exploratory
result is substituted for this experiment's registered endpoint.

## Questions that can actually be answered

1. Does the differentiable Riccati implementation agree with independent
   numerical solutions in a known joint generation/preference LQ system?
2. Can a continuous conditional generative field be trained through a joint
   generation/valuation controller, and does its inference benefit survive
   strong same-information, same-actuator and measured-cost comparisons?
3. What happens to true decoded facts, explicitness, tail failure, lawful
   diversity and actual compute when active valuation, cross curvature or
   dense curvature are removed?

General FBSDE existence and uniqueness does **not** imply Riccati closure.
The exact branch assumes a finite-horizon unconstrained risk-neutral LQ
problem with deterministic coefficients. The nonlinear generative branch
uses a receding-horizon local approximation. Neither branch establishes a
global theorem for an arbitrary neural generator.

## Layer 1: exact reference

`oracle/benchmark.py` implements a four-dimensional joint `(z,p)` system.
Preference has no intrinsic diffusion; its only motion is through costly
control. Nonzero generation/preference cross couplings remain. A continuous
Riccati solution is checked against an independent Pontryagin boundary-value
solver, an independently condensed quadratic program, grid refinement, forward
second-moment costs and finite-difference outer gradients.

Diagnostics compare full gradients, pseudoinverse reconstruction from exact
`Z`, fixed preference with the remaining controls reoptimized, removal of
cross blocks, and rank projections. These are engineered mechanism checks,
not evidence of neural performance or novelty. The additive-noise negative
control verifies that fully observed risk-neutral LQ feedback is independent
of exogenous noise covariance.

`oracle/local_control_audit.py` independently checks the **actual nonlinear
model's** affine Riccati subproblem, analytic Jacobians, Gauss–Newton first
derivatives and differentiation through the full rollout.

## Layer 2: raw multimodal generation

Each world has six continuous factual coordinates: initial position, velocity,
color and tone frequency. Text, acoustic tones, a 16×16 RGB image and four RGB
video frames disclose complementary information. Input nuisance/style is
independent of output style. Two output styles are lawful: reversed numeric
text order, opposite tone phase, and narrow/wide blobs with corresponding
video appearance. The task uses structured text and synthetic tones, not
natural language or speech.

Raw modality encoders fuse observations into a 32-dimensional context and a
six-coordinate fact estimate. A conditional flow operates on a seven-coordinate
continuous output state: six facts and one style. Learned neural decoders
produce actual text logits, wave samples, image pixels and video pixels; no
controller looks up the true target renderer at inference. The semantic
coordinates are deliberately supervised in known task units; this does not
demonstrate unsupervised discovery of a universal latent space.

The encoder supplies the factual initial condition, with fixed Gaussian noise:
`z_facts(0) = target_hat(c) + 0.5*epsilon_facts`, `z_style(0) = epsilon_style`,
and `p(0)=0`. All trajectory arms share these samples. Conditional Flow
Matching uses this same initial distribution when constructing its bridge.
It is not a masked diffusion language model or a score-based reverse SDE.
There is no claim that the initial diversity noise measures epistemic or
semantic uncertainty.

The shared 225,442-parameter decoder uses a learned time-conditioned frame
network for images and video. Physical frame time is separate from generation
time. Squared intensities and a raw-target mass/centroid/spread training loss
are explicit task-specific physical priors shared by every comparison arm.
Before any formal heldout evaluation, each seed's true-latent codec must reach
90% resolved outputs, 80% correct-and-resolved outputs, and 80% lawful,
crossmodally consistent styles on validation. This admission diagnostic is
not an inference policy. `review/CODEC_DEVELOPMENT.md` retains the failed
development attempts and the successful fresh training result.

## Joint generation and costly valuation

The augmented state is `x=(z,p)` with dimensions 7+6. Its drift is

```
dz_facts = v_theta(t,z,c)_facts + 1.25*tanh(p)*(target_hat(c)-z_facts) + a_facts
dz_style = v_theta(t,z,c)_style
dp       = -0.25*p + nu
```

The local state cost is

```
0.5 * sum(exp(0.5*tanh(p)) * (z_facts-target_hat(c))^2) + 0.025*||p||^2
```

with control cost `0.125*||a||² + 0.05*||nu||²`. Thus `p` changes both bounded
internal valuation and correction gains, and `nu` is an actively chosen,
costly control. This is an operational valuation/gain model, not a claim that
all psychological preference semantics have been captured. The external
truth-based evaluator is fixed and cannot be redefined by `p`.

At each generation step, analytic neural Jacobians form an Euler-linearized
affine model. A PSD Gauss–Newton expansion forms the local quadratic cost.
An exact batched discrete Riccati recursion supplies its first affine
feedback, followed by an actual nonlinear step and replanning. Within the
lookahead, the linearization and time are fixed. The first action is `-Kx-k`;
the continuous-time instantaneous formula is not incorrectly substituted.

The four-step lookahead changes physical duration when the outer integration
step count changes. The 4/8/16-step curves therefore compare complete inference
settings, not a pure convergence study. Cross-block removal and rank-3
projection are explicitly approximate ablations.

## Layer 3: training and comparison

Each seed first trains a shared codec and foundation field. The encoder and
decoder are then frozen identically. Continuations start from the same field
weights and use paired minibatches, FM noise and rollout noise:

| Continuation | Update |
| --- | --- |
| Continued Flow Matching | Ordinary distribution-fitting updates |
| NDU through Riccati | Backpropagate through local models, solves, rollout and decoded outputs |
| Free joint controller, equal updates | Learn unrestricted control with identical actuators |
| Free joint controller, matched time budget | Continue on the same data pool up to the NDU continuation's measured training time, with a fixed cap |

This tests NDU training of the vector field/controller; it does not claim
NDU joint training of every codec parameter. The time-budget continuation
records actual update count and checkpoint because load-dependent stopping
is not bitwise reproducible across machines. The equal-update checkpoint is
retained separately.

Inference includes ordinary flow, energy guidance, the free joint controller,
fixed-valuation MPC, full NDU, deleted cross blocks and rank-3 approximation.
A direct supervised decoder of the shared context estimate is also included:
if the small task is solved more effectively without iterative generation,
the comparison must reveal that. Guidance strengths and step counts are
selected only on validation. The primary comparator is the strongest eligible
validation candidate within the NDU CPU inference budget; a free joint-control
candidate must be eligible even if another arm wins selection.

The 2×2 matrix crosses ordinary/NDU field training with ordinary/NDU inference.
All comparison arms have the same observations, actual codec weights and
fitted public target predictor. Hidden facts, target raw outputs, corruption
identities and output style are never controller inputs.

## Outcomes and costs

Independent raw readback uses text bin values, acoustic sinusoid fitting,
image mass/centroid/color/width and video motion. Correct agreement on the
wrong fact still fails truth-based scoring. Invalid/nonfinite outputs receive
explicit failure loss. Text confidence, Gaussian shape fit and physical width
test explicitness; averaging the two lawful styles does not count as lawful
diversity.

The primary loss averages four generated draws **within each world**, then
computes the worst 10% mean (CVaR90), separately per training seed. The seed
CVaRs are averaged. Paired hierarchical bootstrap resamples seeds and worlds,
keeping all four draws together. Per-draw tail failure is reported separately.
Every arm also retains the actual raw text, audio, image and video outputs of
the first two worlds and all their draws, chosen by index before evaluation.
Conditional lawful style entropy is measured within each prompt, so different
prompts collapsing to different styles cannot pass the diversity criterion.

Inference costs include observed-input encoding, neural field/Jacobian work,
cost construction, all Riccati solves, rollout and every decoder. Wall and
process CPU times are recorded, with fixed batching and warmup rules. Timing
excludes the external scientific scorer. Training, validation selection and
warmup costs are retained separately. Operation counts are not represented as
complete FLOPs. A baseline fitting inside the NDU budget does not establish
that NDU is faster or Pareto dominant.

## Execution and evidence

The frozen protocol is `protocol.json`. Formal execution requires
`SOURCE_FREEZE.json` to match the complete implementation before preparation,
after preparation and before heldout generation. All seed selections are
locked before any heldout worlds are created. Checkpoints and selection,
training and validation records are hashed; tampering aborts evaluation.

```
python experiments/ndu_latent_riccati/run_experiment.py \
  --output /absolute/new/run --execution-tier local-preflight
```

`--smoke` is a short development-only integration run. `--development` uses
the full training schedule with a separate development seed. Neither can
satisfy the scientific success gate. `--stage prepare` and `--stage evaluate`
separate training/validation from heldout execution without changing evidence.

The cloud workflow reuses the already declared project runner route. A queued
job is not execution. Dedicated-cloud identity requires matching external
assignment, repository, branch, runner, source SHA and launcher receipts.
Source correctness, empirical superiority and actual cloud execution remain
separate evidence claims.

## Relationship to Hepta / NDU

The design follows the distinction between forward preference state, full
value gradient and BSDE noise projection in the author's NDU manuscript
(`TrillionniumFoundation/NDU`, `main.tex` at
`85ef03ef3ec871edd4ba8039e400169a14ec774f`). It is an isolated Python research
profile, not native `utility.ndu` or `learning.eval` qualification. In
particular, the degenerate-diffusion reference does not silently waive the
native implementation's separate covariance/support requirements.
