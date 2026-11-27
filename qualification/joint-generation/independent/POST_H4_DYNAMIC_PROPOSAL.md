# After H4: boundary and an independent content-state study proposal

**Proposal only, 2026-10-23. No new data, model, training, timing probe or formal
evaluation has been run. This is not a frozen executable protocol.**

## Decision for the present task

Stop enlarging the current full/low critic and repeating its service timings.
[H4](../runs/codex-cloud-dynamic-train-headroom-h4/REPORT.md) filled the missing
current-weight TRAIN terms. Its free two-action raw oracle minus selected static
NDU/full averages -0.000213380872; NC/full has a +0.001140213533 content deficit
against NDU/full. Raw signs are (+,-,-). This empirical raw ceiling applies only
to these weights, these TRAIN inputs and these two potential output laws.
Lower raw utility does not exclude a net advantage from genuine cost savings.
The median-cost proxy is descriptive, not an additive complete-CPU bound; its
seed47 nonadditivity is material. The stopping decision reflects poor measured
prospects and content-training debt, not a mathematical proof of net impossibility.

There is presently no credible additional dynamic execution candidate within
finite12 supported by these results. Reconciliation of two finite codes is the
parallel content group's study; this document neither implements nor duplicates
that probe. Its terminal-law compilation comparison remains necessary. A larger
critic, continuous hidden state, or another timed implementation is not evidence
of new information or better content actions. The parent-reported dot probes
in [the earlier candidate note](DYNAMIC_ACTION_CANDIDATE.md) also failed to beat
a fairly optimized static implementation; they are not Cloud utility evidence.

## One explicit new task, rather than a relabeling of r2

Propose a separate **multi-object conditional scene generation** study derived
from public CLEVR. The original [CLEVR paper](https://arxiv.org/abs/1612.06890)
is a visual-reasoning benchmark with diagnostic annotations. Its
[official generator](https://github.com/facebookresearch/clevr-dataset-gen)
provides image rendering, scene JSON and question/program generation. These
sources motivate an independently specified generation task; they do not report
the joint text/image task proposed here or a Hepta dynamic advantage.

Condition on a canonical serialization of the released scene's object attributes
and relations; generate both (a) a bounded, readable scene description and
(b) a newly generated RGB scene, initially at 32x32. The description and raster
must satisfy the same requested object bindings and relations. This is a
declared adaptation, **not official CLEVR benchmark performance**, open-vocabulary
photography, an edit of the old test, or a solution of r2. The low resolution may
make semantic scoring unreliable; that is a feasibility risk, not a reason to
change resolution after seeing favorable model scores.

Use the released training distribution, without choosing scenes by a model's
errors or action gains, dropping difficult object counts, injecting route-specific
noise, or constructing a distribution where one modality is deliberately broken.
Before any execution, fix the release/hash, canonical input fields, resolution,
source-group split/seed, sample count, distribution weights and bounded text
grammar. All views/crops of an original scene stay in one group. Public validation
is development data only; any later confirmation needs separate unused physical
scenes, explicit public-data exposure limits and a prospective registry. Nothing
is downloaded or split by this proposal.

## Minimal architecture and legal state

Use a single small conditional backbone with a learned RGB decoder and text
decoder. Share one initial content pass. Maintain actual draft text token/logit
state, spatial image-patch activations and their shared conditioning state.
Do not substitute a target scene ID or a twelve-entry raster lookup for image
generation. Freeze all decoder equations and their cost before comparison.
Initially permit exactly **two further content updates**, with actions:

| Action | Content transition | Information available at the decision |
| --- | --- | --- |
| Text update | Recompute a bounded text span and shared bindings from the draft image/text state | Legal condition, current text probabilities and paid image features |
| Image update | Recompute a bounded raster patch block from the draft text/image state | Legal condition, current image state and paid text features |
| Joint update | Apply one shared residual block to both draft states | The same legally acquired state; no target observation |

The image/text location rule is a fixed shared differentiable mechanism available
to every action and baseline; its training and inference are charged. No free
search over locations. Equal update counts do not mean equal work. This fixed
horizon excludes early stopping initially, isolating content-state feedback from
the old cheap/full stopping tail. All-modality transport/capability contracts stay
in place; only text and image generation are within scope.

An action must change decoded text probabilities or actual generated pixels.
Access to condition attributes is legal conditioning for every method; access to
the target raster, training-only labels, an evaluator's hidden observations or
ground-truth reconstruction residual is not legal serving feedback. An image
encoder/verifier can observe the generated draft only at its full measured cost.
Richer state alone creates no information. The hypothesis is that observed draft
errors predict which *different content transition* has greater value.

## What could change each observed deficit

| H4 limitation | Candidate mechanism | Evidence still missing |
| --- | --- | --- |
| NC learns fewer useful content updates because its labels/critic consume budget | Shared initial pass, shared update blocks, jointly trained small action head; reuse useful content transitions rather than a separate full/low label model | Actual total cost and whether the static system's saved policy budget buys better content; sharing does not cancel policy or branch costs |
| Full/low actions have little incremental content quality near saturation | Text/image/joint updates can repair different object bindings or spatial details in newly generated states | TRAIN action-quality crossing and positive free-oracle margin against the strongest fixed sequence, measured on the same checkpoint |
| Low hidden/instruction features poorly distinguish profitable continuation | Decision observes its actual draft text/raster and paid cross-modal features | Source-group out-of-fold predictability of value, including large wrong-action losses; no hidden-label features |

No row in this table is an achieved result. The parallel NDU variance-reduction
training improvement, if independently accepted, must also be given to static
NDU. Its success cannot be inherited as dynamic success.

## Strong static competitors and compilation

For the three actions and two updates, enumerate **all nine fixed sequences**
on the same backbone. Choose using development data with the complete search
charged. Also include the best direct joint NDU generator; a same-cost deeper
static residual generator; and a statically trained/amortized joint decoder or
distilled controller. Allow unrolling, fusion and exact compilation of the
dynamic computation wherever applicable. Include a legal deterministic renderer
plus text realization if the condition suffices: a known renderer cannot be
excluded just because it makes the proposed task easy for a static method.

This state is no longer just two finite code IDs, so the old 144-draft pushforward
table alone does not describe it. That **does not imply static compilation is
impossible**. A finite-horizon dynamic program can be unrolled; input-conditioned
computation, caching or distillation may reproduce its terminal law cheaply.
Charge construction, trained approximation, normalization, storage and serving
costs, and give all methods applicable fusion/codec optimizations. If a static
equivalent or approximation attains the same content law at no greater complete
cost, there is no demonstrated additional dynamic benefit. Do not define a
static family that artificially forbids this competitor, or declare input-aware
static content computation to be dynamic just to remove a strong baseline.

## Work required before any execution

1. Freeze the task semantics and a numerical budget ledger. Keep the old 10s/12B
   complete build envelope and its serving horizon/reference as the initial
   feasibility constraint; **no increase is authorized here**. This richer task
   is not known to fit. Cost data preparation/decoding, any common pretraining,
   all branches, policy/critic fitting, selection, observers, storage, compilation,
   encoding and complete serving. Record acquisition CPU/wall and external
   dependencies separately without treating them as free model work. If the
   envelope is infeasible, report that and stop; a different budget would require
   an explicit new-study decision, never reinterpret old qualification.
2. Specify a fixed TRAIN-only screen before running it: sample count, seeds,
   grouped folds, action checkpoints, all nine sequences, complete measurement
   order, oracle/predictability formulas, cost boundaries and terminal stop rule.
   No new screen is executed by this document. Estimate whether *any* oracle
   margin can pay real feedback/policy overhead and content opportunity loss.
   A raw-only ceiling and a median-cost proxy must stay separately labeled.
3. Train a policy only if the screen's predeclared action-quality, observable-value
   and full-cost criteria justify it. A selector must beat a useful constant
   action, then the best fixed sequence and direct static NDU under the actual
   complete budget. Retain all seeds, failed admissions and costly wrong actions.
   Do not perform repeated screens until an apparently favorable subset appears.
4. Keep content-control, NDU-training and dynamic-vs-best-static claims separate.
   Hold supervised weights/objective controls fixed and independently test both
   content and NDU contributions. Use a genuine decoded-pixel evaluator with
   predeclared failure/uncertainty handling; scoring internal scene IDs alone is
   insufficient. Preserve the original r2 and CORE gates and failures.
5. Any later formal study needs a new reviewable protocol/source freeze, all prior
   model-selection/confirmation history, independent sources and prospectively
   valid error control across confirmations. Existing 95% results cannot be
   retroactively placed in an alpha budget. No r2, CORE or new test opens now.

The immediate deliverable is this proposal and the H4 archive, not a claim that
changing the task will create a win. Main uncertainties are budget feasibility,
pixel-semantic evaluation, meaningful action crossing and whether an effective
static compiler/renderer already removes the proposed sequential advantage.
