# Shared Cell research foundations

This directory adds bounded, executable research references for delayed credit,
temporal-kernel comparison, and continued plasticity. The references produce
measurements and immutable candidate updates. They do not select a production
artifact, change a running Cell, or replace Hepta's existing learning, artifact,
checkpoint, circuit, or evaluation owners.

## Source and integration boundary

- Main ancestor: `732e934ba496d90fbe042b8d41d479ef901643e5`.
- Exact research parent: `bb048cb811c2b755b7e54e97d24c63ec7ec8d1b7`
  (the unmerged PR #5343 HCSN stack).
- The six imported `qualification/hcsn_differentiable` Python files are checked
  against their exact SHA-256 values before the HCSN arm is constructed. They
  are inherited source, not a second implementation or copied new module.
- Existing requirements remain in
  `docs/learning/NEURAL_BIOMIMICRY_SPEC.md`. This reference does not advance
  N1/N2/N3, functional-biomimicry, real-task or production-adoption qualification.
- This branch does not combine the acceptance results of the separate Cell,
  Circuit, NDU, real-generation or HCSN candidates. Its scoped CI is a research
  execution check, not a new required global or per-Cell gate.

## Run the exact bounded roster

Use Python 3.10 or later, NumPy and CPU-capable Torch. CI pins NumPy 2.3.5,
Torch 2.8.0 and the repository-locked Ruff 0.15.13. Other native environments
report their actual versions; they are not silently described as the CI image.

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m qualification.cell_common_foundations.run_reference \
  --output /an/unused/output/reference.json
```

The runner freezes seeds 11, 29 and 47 and creates its plan and full 54-slot
roster before training. Each attempt has a create-only started record and a
separate terminal record. Missing, running, failed and cancelled outcomes remain
in the denominator. Existing output identities are refused, including a prior
plan whose final result was never written. This is an offline experiment record,
not a new runtime ledger. A new run is a new attempt and must not erase an older
failure. Test-only small training fixtures are listed separately in the test
inventory and included in the outer measured execution cost.

The final JSON binds every executed research source file before and after the
run, exact data/model/rule identities, actual work counts, original failures,
the test inventory, and observed runtime versions. `REFERENCE_EXECUTION_COMPLETED`
means the declared checks and attempts executed. Scientific acceptance remains
`HOLD`, including when every attempt completes.

## 1. Local plasticity and delayed credit

`credit.py` implements six independently selectable algorithms on one bounded
FP64 tanh recurrence: exact BPTT, chunk-detached tBPTT, ordinary three-factor,
type-specific modulation, diffusion and shuffled diffusion. This is a small
diagnostic model; it is neither the native Q24 runtime nor a reproduction of the
full PNAS spiking-network experiments.

The local eligibility recursion differentiates each unit's own recurrent path
and explicitly omits cross-unit derivatives. It is not an exact full-network
gradient. Seven declared type groups map at most eight modulation variables to
local parameter groups, with row-L1 bounds and an eligibility-L1 ceiling of four.
Execution weights and the credit graph are distinct. The credit graph uses
receiver rows and source columns with row-stochastic normalization: it preserves
constant signals and an infinity bound, not total signal mass.

All methods see the same initial weights, input/head, episode streams and
terminal feedback time. `all` versus `sparse` names the spatial availability of
local feedback, not dense versus sparse feedback timing. BPTT is the offline
full-gradient oracle. Comparisons record actual training observations and
updates, not only planned budgets. The ordinary three-factor map averages the
declared type maps; opposite signs can cancel. It is one fixed, untuned baseline,
not an optimal three-factor implementation.

The fixed panel contains 36 method/location/seed attempts, each with 12 bounded
candidate updates. Gradient diagnostics use the identical model, trajectory,
initial state and loss. Zero-gradient cosine is unavailable. Early-message
masking, replacement and delay rerun both forward computation and credit; they
also compare candidate changes. These synthetic effects do not establish correct
credit assignment in a real tool task.

Selected weights are never modified by a proposal. Actual rounded candidate
changes are checked against per-layer 0.5% and global 0.25% relative L2 limits.
Scale-safe norms prevent subnormal values from turning a nonzero violation into
a reported zero. Zero selected layers require NoUpdate. Native fixed-point,
quantization, sign, provenance and artifact-owner checks remain separate.

## 2. HCSN temporal roles and matched controls

`temporal.py` compares a GRU, diagonal continuous-time SSM, the real pinned HCSN
probability/content network, and a fixed LIF voltage/event-trace reservoir. The
LIF arm is not EventProp. All receive the same causal four-channel encoder and
the same zero-initialized 9-to-1 linear head, data splits and optimizer budget.
NDU is explicitly disabled for every arm under a fixed-sequence profile.

This first comparison freezes every temporal kernel. Only ten output-head
parameters train. Each of the twelve kernel/seed attempts fits short and long
cue recall, then adapts its long head to changed physical observation gaps,
using 40 updates per fit. Held-out original gaps measure retention after that
adaptation. This is not learned-delay EventProp, full-parameter temporal training,
timeout calibration, or a qualified fast-control/abnormal-event task.

The HCSN arm retains its original FP64 implementation, two layers and a coarse
6-active/1-tail/3-phase basis. Its native readout is a fixed identity to expose
nine content/physical channels to the common external head. Full state is
serialized, restored in an independently reconstructed same-identity kernel,
and consumed by the remaining sequence. A forged outer checkpoint identity
cannot change its frozen internal weights.

Frozen parameter/state counts are reported and differ across kernels. Equal
head updates do not imply equal total cost. The original finite QPR projection,
non-semigroup behavior and possible early refractory release remain numerical
limitations; this comparison does not qualify the missing renewal or free-boundary
solver. End-to-end energy is unmeasured. Process-lifetime RSS is not isolated
per-kernel peak memory and cannot support a memory-efficiency ranking.

## 3. Homeostasis and continued plasticity

`plasticity.py` monitors old-task retention per slice, new-task learning curves
and right-censored time-to-target, singular-value entropy effective rank,
activation-aware low utilization, representation drift/linear CKA, update sizes,
and finite-state bounds. Rank diagnostics declare centering, activation semantics,
sample/feature counts and the exact ordered probe identity. All-zero features
are explicitly degenerate, not a healthy rank-one representation.

It implements the objective `-alpha * ER(XW) + beta/2 * ||W||^2` and its analytic
gradient, checked by independent finite differences. This is a finite linear
reference; it does not claim to duplicate the paper's alternating optimizer or
all nonlinear-network theory. The ER gradient is unavailable at the declared
rank-deficient boundary. It does not invent a revival gradient with epsilon.

The six seed/method attempts compare one fixed graph with the same decaying
schedule and 25% old-task replay, with L2 alone or L2 plus ER. Each has three
tasks and 24 updates per task. The complete supervised data and task order are
bound. Extra ER/SVD work and actual wall time are counted; equal optimizer counts
do not mean equal computation. Retention uses the declared synthetic proxy
`1/(1+held-out MSE)`, not real production reward.

Sleep, regeneration, split and merge remain research proposals. Their gate
requires measured migration/relearning and complete cost/budget coverage, actual
per-slice retention evidence, and net benefit against a fixed graph with a
declared scheduler. Missing energy remains unknown and fails an energy budget
when one is requested. No structural transition is applied by this package.

## Evidence still required before broader adoption

The next experiments need independently sourced real tasks, an isolated evaluator,
future/retention splits, native candidate/owner consumption, full temporal-model
training with matched tuning opportunities, isolated memory and measured energy,
and actual structural migration/relearning costs. Confirmation data must be
frozen before use; a successful mechanism test cannot supply those outcomes.

## Primary research references

- Barretto-Bittar et al., [Diffusion of neuromodulators for temporal credit
  assignment](https://pmc.ncbi.nlm.nih.gov/articles/PMC13598169/), PNAS 2026,
  DOI `10.1073/pnas.2608831123`. The sparse-feedback benefit and limited dense-
  feedback benefit motivate separate controls. Shuffled diffusion is retained
  because the paper does not establish spatial alignment as universally necessary.
- Mészáros, Knight and Nowotny, [Efficient event-based delay learning in spiking
  neural networks](https://www.nature.com/articles/s41467-025-65394-8), Nature
  Communications 2025. [Author preprint v3](https://arxiv.org/html/2501.07331v3).
  EventProp weight/delay learning is a later explicit baseline; its implementation-
  specific speed and memory results are not HCSN performance measurements.
- Prakash et al., [Spectral Collapse Drives Loss of Plasticity in Deep Continual
  Learning](https://proceedings.mlr.press/v306/prakash26b.html), ICML 2026.
  Effective feature rank and L2 are a strong comparison, not a replacement for
  retention or a direct measurement of the complete Hessian spectrum.
- Bellec et al., [A solution to the learning dilemma for recurrent networks of
  spiking neurons](https://www.nature.com/articles/s41467-020-17236-y), 2020.
  The local tanh derivative reference here does not inherit exact e-prop semantics.
