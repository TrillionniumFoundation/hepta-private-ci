# Multimodal output portfolio: first finite mechanism pilot

**Latest result: the independent new-heldout v1.1 evaluation did not confirm
the registered primary effect.** CVaR90 changed by -0.015166 versus the strong
static baseline (95% CI [-0.042590, +0.009443]); the required reduction was
0.020 and the interval was required to exclude zero. Dedicated-cloud execution
is also still unverified. See [the current results report](evidence/RESULTS_V1_1.md)
and [independent review](evidence/independent_review_v1_1.json).

This experiment tests a narrow, falsifiable part of the proposed Hepta/NDU
architecture: can calibrated, risk-sensitive evidence acquisition and actual
continuous output allocation improve a learned generator's quality/risk/cost
tradeoff? A negative result is preserved as a valid outcome. The preregistration
commit is `0b3958f8b70a7de742ef2f2f1e61a2f1c20dc98f`; the original implementation
commit is `3a3e7ef2e3c0b73840d62ac5f816f9c4ec4d66db`.
The v1.1 amendment and corrected implementation were published together at
`f44540ab59a0a8f013437ccbe8579db607fac03e` before producing new heldout evidence.
The original v1 evidence is retained, including its secondary static-baseline
support violation. The amendment fixes that violation and changes only the
heldout RNG namespace; training, calibration, primary selection, metrics,
budgets and success criteria remain fixed. The two rounds share three training
seeds and are not six independent model replications.

## What is implemented

The task has eight concepts: four colors crossed with two motion directions.
Each hidden world produces four raw observations: a short token sequence,
a synthetic acoustic tone, a 16x16 RGB image, and four 16x16 RGB video frames.
These are synthetic signals, not natural speech or open-domain visual content.
Independent errors, common-mode errors, missing modalities, and two heldout
correlation shifts are generated with independent random streams.

The **660,488-parameter** model has four trainable raw encoders, one shared
64-dimensional generation state, three applications of the same residual
refinement module, and four trainable neural output decoders. Encoder,
refinement, and decoder weights are updated by real AdamW optimization.
Generated outputs never call the world's renderer or look up a target image.
The generator is explicitly taught convex mixtures of eight canonical targets;
this is not evidence of discovering arbitrary semantic composition.

For exact finite control, encoder predictions are discretized into eight
semantic symbols plus an observable missing symbol. Text initializes the
public state. The controller can acquire audio, image, or video evidence and
stop with a quarter-grid convex combination of acquired semantic symbols.
This combination actually enters the shared neural generator. The controller
does not observe hidden truth, corruption identities, or future reports.

The bounded preference state `P` moves forward with public disagreement.
The recursive controller solves a locally nested entropic objective:

```
U(s) = max(stop_CE(s), max_a [CE_gamma(P)(U(next(s,a,O))) - 0.025 cost(a)])
gamma(P) = gamma_base * (1 + P), P in {0,1,2,3}
```

The full state includes observations, remaining budget, and preference.
Calibration estimates the joint distribution of truth and four *encoder*
reports; it therefore includes correlated failures. An independence ablation
keeps truth/sensor marginals but removes conditional joint dependence. The
loss of every portfolio is computed from actual generated raw outputs before
evaluation, with all possible canonical truth classes. Test truth never
enters this precomputed table or the controller.

This is an **NDU-inspired finite special case**. It is not the continuous-time
Merton closed form or a neural FBSDE solver. An independent bottom-up solver
must match the recursive solver on all 12,616 reachable augmented states.
That equality is required; it is not evidence that NDU outperforms Bellman.

## Frozen comparisons and costs

`protocol.json` fixes seeds 17/29/43, splits, losses, budgets, parameter grids,
validation selection, the primary comparison, and its acceptance conditions.
Each seed trains on 2,048 clean worlds for 400 updates, calibrates on 8,192,
selects on 768, and evaluates 1,536 IID plus 768 correlation-shift and 384
all-common-wrong worlds. Concepts are shared across splits; nuisance draws
are independent. This is not unseen-concept generalization.

All seven arms use the same frozen model per seed:

| Arm | Purpose |
| --- | --- |
| Validation-selected fixed portfolio | Strong static acquisition/weight baseline |
| Risk-neutral DP | Average-return dynamic control |
| Fixed-risk DP | Risk sensitivity without preference dynamics |
| NDU recursive DP | Forward preference plus full recursive planning |
| NDU myopic | Same preference, one-step lookahead |
| Best single candidate | Restrict terminal output to one acquired concept |
| NDU independent-error ablation | Remove joint error dependence |

The single-candidate baseline is not independent stochastic resampling from a
diffusion model. The study contains no diffusion-model performance baseline.

The primary external loss is normalized raw reconstruction error plus 0.25
times cross-modal contradiction. Discrete correctness, attribute correctness,
ambiguity, and resolved correctness are separate metrics. Consistent shared
errors still incur loss. A reduction in raw MSE alone does not prove improved
semantic understanding; mixtures can be ambiguous or blurred.

Budgets 2/4/7 apply after initial text. Acquisition proxy costs are text=1,
audio=2, image=1, video=4. These units are not measured FLOPs. The experiment
also reports standalone dense Linear MAC, actual model calls/examples,
execution time, and all offline training, candidate evaluation, calibration,
selection and compilation time. Linear MAC excludes activations, transfers,
CPU control and optimizer work. A cost frontier using it must retain that
qualification. Inference encodes only acquired modalities; no future encoder
calls are free. Policy compilation is checked complete before audit and test.

Validation chooses static portfolios and each dynamic arm's gamma. Selections
are written before any heldout world is produced. The primary endpoint is
the three-seed mean of per-seed CVaR90 differences at IID budget 4, NDU minus
the selected fixed portfolio. A hierarchical paired bootstrap resamples
seeds and independent worlds within seed. Three seeds still provide limited
information about training variability. Quality tolerance is a point-estimate
gate, not a statistical noninferiority test.

## Run and replay

Use Python 3.10-3.12, NumPy 1.26.4 and PyTorch 2.5.1. No model download, API key,
GPU, Transformers dependency, or native Rust build is required for the pilot.

```bash
python experiments/multimodal_output_portfolio/run_experiment.py \
  --output /absolute/new/evidence-directory \
  --execution-tier local-preflight
```

`--smoke` uses a separate development seed and reduced data; it cannot satisfy
the registered effect claim. Existing evidence directories are rejected.
Each run saves checkpoints, train hashes, frozen validation decisions,
calibration tables, full independent audits, per-world output scores and
public acquisition traces, runtime/source receipts, and an evidence manifest.
All raw outputs can be replayed from the checkpoint and logged portfolio.

For the project's existing self-hosted desktop runner, the narrow workflow
`.github/workflows/ndu-output-portfolio-pilot.yml` is triggered only when
`CLOUD_RUN_REQUEST.json` is pushed on this research branch. It invokes
`run_cloud.sh`, verifies the actual runner identity and source SHA, prepares
an isolated pinned environment when needed, and uploads complete or partial
evidence. A queued job is not proof of execution; reconcile the receipt with
the external Actions job's actual runner assignment.

## Claim boundaries

This is a standalone Python research prototype of shared encoder/generator
ownership and episode-level control, not integrated native Hepta Neuron or
`utility.ndu`. NDU controls evidence acquisition and terminal allocation;
the internal three refinement steps are fixed, not individually controlled.
The generator is frozen during control comparison. There is no NDU joint
training, denoising/score-matching objective, reverse diffusion process,
open-domain multimodal benchmark, or foundation-model checkpoint here.

Observed non-dominated points are an empirical finite comparison, not a
globally proven efficient frontier. Source/implementation success, scientific
effectiveness, and verified dedicated-cloud execution are separate gates.
