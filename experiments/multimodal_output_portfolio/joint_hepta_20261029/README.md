# Joint Hepta multimodal generation research

This package implements the five requested work packages on the immutable
`a50c8974ac23c20c5174f7c3ad542a96e5652854` research baseline. It adds a real,
trainable four-output mechanism, a dynamic controller, actual file readback,
source-isolated natural diagnostics and an unchanged native owner guard.
Existing v6/unified networks, evidence and failed research gates remain intact.

**Implementation is not an efficacy result.** The tensor model is a small
restoration mechanism with 16x16 images, four video frames, 1,024 audio samples
and two categorical text labels serialized as UTF-8. It is not an open-domain
foundation model. The original NDU definition is not replaced by a new acronym:
this experiment inherits its already-registered finite-horizon, undiscounted,
population exponential-utility profile at gamma=2. General recursive preference
drivers, a task-value neuronal free boundary and large-scale semantic generation
remain research extensions.

## One task contract

`JointGenerationProfile` extends `unified_20261028/profile.py` rather than
changing it. The same exact object is supplied to trajectory execution, training,
critic planning, final scoring and checkpoint validation. It binds:

| Contract field | Executed meaning |
| --- | --- |
| Public input | Image/audio/video observations and masks; instruction tokens; no target fields |
| Required output | PNG, mono PCM WAV, timed GIF and UTF-8 label text, all written and reopened |
| Randomness | Joint categorical action; Gaussian media latents; categorical text; separate named action/emission streams |
| Time | Decision index, per-modality transition counts, measured compute time and explicit media clocks |
| Cost | Actual CPU plus wall tariff and registered executed action service tariff; failed work charged |
| Outcome | Independent fixed post-codec restoration score; separate natural semantic qualification gate |
| Continuation | Executed recurrent generator/controller, including STOP and actual buffered delivery |
| Identity | Source code, exact inputs, frozen selected model, actual policy configuration and readback file hashes |

`validate_episode` checks a complete immutable state/event chain, selected joint
propensities, monotone progress, no mid-episode parameter changes, immutable
committed files, exact cost identities and budget conservation. Hashes establish
identity, not observer competence or cryptographic authenticity. Runtime
whitelisting is structural; source separation and feature construction are also
checked. This implementation commits one final bundle; it does not silently
claim an append-only streaming output contract.

Every continuation and generation transition is charged once. Native child CPU
is included after actual `wait4` reaping; its receipt subtotal is not added twice.
During a live child, budget accounting is delayed until reap. Physical CPU time
has no proven worst-case tail bound. The recorded cost scope includes encoding,
policy/planner, verification, generation, codecs, observation and a genuinely
written/validated audit draft. The final immutable audit seal is metered
separately and reported as a sensitivity analysis. Training, installation, cold
model loading and distillation costs are reported separately; inference savings
alone do not establish lifetime savings.

## Generation backbone and dynamic policy

`model.py` creates learned modality encoders, a shared semantic state, four
modality states, a high-dimensional `HeptaCore` and trainable output heads. Hepta
content affects the actual emitted bytes. State is initialized from the encoder
with its gradient path retained. No final-state labels are provided to the actor
or verifier.

`hepta_core.py` derives from the source HCSN implementation at
`68eb16caa9c14c7b5729585c86d9c293018a987c`. It preserves dual recovery/regeneration,
adaptation, positive diffusion, first-passage probability, killed first moment,
and content recurrence. Its declared approximation freezes coefficients over
an interval and resets hit mass at the interval end. It is not an exact
continuous renewal/refractory simulator. Event probabilities are not relabeled
as sampled spike counts. `ordinary` is a parameter-identical sigmoid-gate
control; `single`, `no_adaptation` and fixed/direct boundaries are also available.
The existing ordinary v6/unified models remain unchanged on the parent branch.

The actor chooses among `shared`, `image`, `audio`, `video`, `text`, `verify` and
`stop` after each executed transition. There are at most six continuation
decisions, followed by compulsory STOP and actual delivery. `verify` computes
public observation consistency. Its deterministic dependence on model
parameters is retained in the joint probability graph. A feedback intervention
test changes both subsequent selected actions and real output file hashes.
This proves an active causal route, not that a learned policy already uses it
optimally.

The planner performs bounded one-step public-state lookahead using a learned
log-moment critic. A separate delivery critic is trained on actual terminal
emission/readback returns and supplies the STOP value. It is an approximate
policy-improvement heuristic, not an exact HJB solver or a proof of optimal
portfolio selection. Its extra candidate transitions are physically metered.

## Joint learning

For a complete observed net return R, evaluation uses

\[
J=-\frac{1}{2}\log\mathbb E[e^{-2R}].
\]

The risk learner minimizes the equivalent unnormalized population moment

\[
\mathbb E[(e^{-2R}-1)/2].
\]

`learning.py` forms a score estimator from the sum of all selected action log
probabilities, the final Gaussian latent log probability and both categorical
text log probabilities. Codec/readback returns are detached; no duplicate
pathwise reward term is added. Independent leave-one-out baselines reduce
variance. There is no self-normalized minibatch risk gradient. Mean controls use
gamma=0 for training, while all primary evaluations retain gamma=2.

The critic loss is `exp(v) - exp(-gamma * actual_suffix_return) * v`, whose
conditional optimum is log E[exp(-gamma R_suffix)]. It does not regress the log
of an individual sample as the log of an expectation. Critic features are
detached. Tests compare discrete score gradients and Gaussian quadrature with
independent analytic/finite-difference answers.

Supervised pretraining and a separately declared 0.05 supervised anchor stabilize
joint learning. These additions change the pure NDU optimum. Gradient clipping
changes the optimizer update as well. Consequently the full-versus-actor-only
contrast tests joint training with supervised anchoring; it does not isolate
all improvement to reward feedback. Score-only gradient coverage is recorded
separately from total-loss coverage, and a real-file integration test excludes
all supervised terms. Physical timing is charged to returns, but its direct
parameter derivative is not modeled; the score estimator treats the conditional
timing law as parameter-exogenous.

`training_protocol.json` freezes seeds 17/29/43, widths 32/64, 384 supervised
updates per initial core and 64 joint updates per arm, with eight independent
draws per update. Six arms separate risk preference, dynamic allocation,
first-passage structure and joint generator training. Two draws for each of 64
test source identities give source-paired comparisons. Bootstrap resamples
sources, not repeated draws; seed uncertainty is reported separately. Empirical
CE estimates have finite-sample plug-in bias. A positive point estimate is not
a passed research gate.

The distillation teacher is the bounded critic planner. The student actor learns
its decisions from development sources only, then both perform actual test
trajectories. Cost change, CE change and distillation training cost are retained.
Neither teacher superiority nor student savings is assumed.

## Checkpoints and the existing owner

`checkpoint.py` stores only tensors and safe primitive containers and loads with
`weights_only=True`. The `.pt` and `.pt.manifest.json` must be kept together.
The manifest binds weights, config, high-dimensional content/voltage/adaptation/
event state, modality state, feedback, step/STOP state, input/profile identity,
RNG, code and runtime. An episode anchor detects a selected model changed after
generation begins. A new-OS-process test compares continuation states,
probabilities, actions and emission exactly under the same declared logical
budget. It is an inference checkpoint, not an optimizer or saved autograd graph.
Real CPU/wall clocks across process starts are measured anew.

`native_build.py` extracts the three unchanged native crates and original
`AgentdNeuronOwner` host from the pinned Git objects. The isolated build preserves
every original dependency name, version, source and checksum before compilation.
No production Rust source or gate is changed. `native_bridge.py` performs actual
gate/feedback/hold ticks, journal reopening, expiration and STOP around the real
Python generation dispatcher. Failure cleanup is bounded, reaps only its own
child and retains failure/CPU receipts. Native abstention prevents further
dispatch. Actual output file hashes and tensor-state identities are bound into
the native event receipts.

The owner retains `DENY_ALL`; the permission is a bounded local research
dispatcher permit. The small constant native readout is explicitly a diagnostic
head. It does not execute or select the trained PyTorch policy, and native
confidence validates only its registered finite input alphabet. Model-quality
qualification does not follow from successful owner ticks.

## Natural sources and the independent observer

`natural_data.py` verifies the original portable archive and source roles before
any new media access. The eight recovered observer-training sources are never
reassigned to generator training. Eight distinct original generator-training
sources support a small, separately named real-media mechanism. They retain
their original role and do not become a fresh qualification set.

The low-resolution generator preserves the natural target's two-second clock:
four frames at 500 ms and 1,024 audio samples at 512 Hz after anti-aliasing.
This is a deliberately bandwidth-limited diagnostic. Verification compares
available context, not unavailable target pixels. Target labels are only
available to supervised training and the final scorer.

`natural_eval.py` trains a separate observer on 64 original observer-training
sources. All events remain clustered by source. It uses complete five-fold
source cross-validation, a frozen ontology of 63 action and 17 sound classes,
and registered ridge/MLP candidates. Both action and sound must reach at least
60% and strictly beat the source-weighted majority control. The admission gate
recomputes these facts from complete OOF predictions and original source labels;
success flags cannot bypass it. Only then can a frozen observer access 64 new
calibration sources. All original policy/calibration/qualification sources are
excluded. Consumption is logged before the first fresh media read. A consumed
fresh cohort cannot be relabeled fresh after a new run directory or head change.

Even success on original-media calibration does not establish reliability on
generated media. Semantic claims remain closed until that reliability is
demonstrated. A network failure is an incomplete run, not evidence against the
scientific hypothesis. Prior failed observer/NDU results are retained.

## Running the registered work

Use Python 3.12.14 and the exact CPU versions in the workflow. The source gate
collects unittest and pytest tests with namespace-aware import mode:

```bash
python -B -m unittest experiments.multimodal_output_portfolio.joint_hepta_20261029.test_contract \
  experiments.multimodal_output_portfolio.joint_hepta_20261029.test_runtime -v
python -B -m pytest -c /dev/null --rootdir=. --import-mode=importlib \
  -p no:cacheprovider experiments/multimodal_output_portfolio/joint_hepta_20261029/test_hepta_core.py -v
python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.train \
  --smoke --output /tmp/joint-hepta-smoke
python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.train \
  --seed 17 --width 32 --output /tmp/joint-hepta-17-32
```

Each output directory must be new. Every actual episode contains its four
emitted files, audit draft and `TRAJECTORY.json`; checkpoints, source identities,
protocols and complete results are retained. The six large mechanism jobs only
start on an intentional `[joint-study]` commit tag. Natural tasks use
`[joint-natural]`, and the independent actual-native workflow uses
`[joint-native]`. Routine code fixes run the source gate and all-arm smoke test
without silently re-consuming a natural calibration cohort.

The exact CI run IDs, tested commits, failed gates and measured findings belong
in the evidence report after execution. A successful workflow means its
implemented checks passed; it does not override the research qualification
fields in `RESULTS.json`.
