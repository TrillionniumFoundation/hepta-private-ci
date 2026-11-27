# CLEVR adaptation feasibility: do not start the proposed training study

2026-10-23, same saved Codex Cloud, starting from `ee74daffcdeb9b3f9e5ecad83c6770424d4275ed`.
This review used official source inspection and integer shape arithmetic only.
There was no dataset/asset download, rendering, model construction, training,
new evaluation or formal opening. The seven downloaded source texts total62641
bytes; their fixed identity and hashes are in the
[source manifest](../research/clevr-feasibility-20261023/official-source-manifest.json).

**Disposition:** do not advance the current full-scene-condition/32x32 proposal
into training. Its joint semantic target has a deterministic text realization
and a mandatory programmatic-renderer competitor; no unresolved conditional
action advantage has been established. Its pixel observation/evaluation is not
qualified, and direct low-resolution generation conflicts with default visibility
rules. This rejects this adaptation as the next dynamic-superiority experiment,
not every use of CLEVR or every dynamic architecture. The small model below is a
concrete conditional cost specification, not a recommendation to train it.

## Correct the budget interpretation first

The earlier [proposal](POST_H4_DYNAMIC_PROPOSAL.md) used the old10s/12B envelope as
an initial constraint. That was an internal proposal choice, **not a user limit
on all future research or a permission blocker**. Those caps, serving horizon,
reference and thresholds remain frozen for old finite12 studies. A new study may
propose a different fixed complete budget, equally available to all methods,
with its own claim, reference, data and review. It cannot inherit old acceptance.
No budget increase or experiment is executed here. The H4 publication's bound
files are kept unchanged; this review supersedes the proposal's budget wording.

## Official implementation and the static counterargument

Official repository main was read with `git ls-remote` and pinned to
`f0ce2c81750bfae09b5bf94d009f42e055f2cb3a`. The
[scene writer](https://github.com/facebookresearch/clevr-dataset-gen/blob/f0ce2c81750bfae09b5bf94d009f42e055f2cb3a/image_generation/render_images.py#L255-L326)
records objects, directions and relations. Camera/light jitters are not saved as
complete render state. Object attributes, locations, rotations and projected
centers are recorded, whereas the visibility image is temporary and removed.
[The projection helper](https://github.com/facebookresearch/clevr-dataset-gen/blob/f0ce2c81750bfae09b5bf94d009f42e055f2cb3a/image_generation/utils.py#L45-L65)
provides a rounded center projection and depth, not an instance silhouette or
full camera calibration. These facts limit exact replay; they do not confer
new information on a learned feedback controller.

The [official image README](https://github.com/facebookresearch/clevr-dataset-gen/blob/f0ce2c81750bfae09b5bf94d009f42e055f2cb3a/image_generation/README.md)
describes base scene/mesh/material assets, Blender2.78c/Python3.5 and default
320x240 output. The installed Cloud executable reports Blender4.3.2; compatibility
has not been run. NumPy2.3.5/Pillow12.3.0 are present; Torch is not installed.
No renderer/model installation or port was attempted. Asset acquisition, any
port, process startup, scene setup, rendering, visibility retries and PNG encoding
would all have to be priced. Old published GPU timing is not this Cloud CPU cost.

| Task definition | Consequence for a fair comparison |
| --- | --- |
| Full render state/assets are lawful input | Deterministic renderer plus text realization is mandatory. Do not discard it because it is not learned. Measure its complete cost; it is not assumed free or proven cheapest here. |
| Object semantics/geometry/relations but incomplete nuisance state | Many images can satisfy the condition. A unique reference RGB/MSE need not define semantic correctness. Missing lighting cannot be inferred from a model's own draft alone. |
| Approximate the official renderer cheaply after training | Potentially an amortized-rendering problem, but a direct neural renderer, compiled joint generator and renderer/text program are strong static competitors. It is not yet evidence for dynamic content control. |

Text realization can enumerate the supplied object attributes and relation graph
in O(n+e) symbolic work. This is lawful input use, not leakage, but makes that
semantic text component trivial for a strong baseline. The official
[question engine](https://github.com/facebookresearch/clevr-dataset-gen/blob/f0ce2c81750bfae09b5bf94d009f42e055f2cb3a/question_generation/question_engine.py#L15-L173)
also operates on scene structures; executing it on the input JSON does not show
that generated RGB depicts anything. A renderer adapter may need to replay or
solve camera constraints and handle visibility. There is no verified ready-made
JSON replay path here and no proof of zero-cost perfect rendering. Neither that
engineering work nor missing nuisance state justifies excluding the baseline.

## Low-resolution observability fails the current readiness argument

The pinned [arguments](https://github.com/facebookresearch/clevr-dataset-gen/blob/f0ce2c81750bfae09b5bf94d009f42e055f2cb3a/image_generation/render_images.py#L67-L80)
use3–10 objects and200 minimum visible pixels. The
[visibility check](https://github.com/facebookresearch/clevr-dataset-gen/blob/f0ce2c81750bfae09b5bf94d009f42e055f2cb3a/image_generation/render_images.py#L475-L498)
counts n+1 colors, including background, each subject to the minimum. Thus a
necessary condition is `(n+1)*200 <= width*height`. At32x32, n>=5 is impossible;
at32x24 all default n>=3 are impossible. Repeated rejection cannot repair this
without changing the accepted distribution. The README says100, so the code and
actual arguments, rather than that prose number, must define a future protocol.

Downsampling a native accepted image is a different path. Simple area scaling
of200 native pixels yields the following coverage, **not a semantic guarantee**:

| Aspect-preserving active raster | Area scale | Equivalent coverage |
| --- | ---: | ---: |
| 32x24, optionally padded to32x32 | 1/100 | 2 pixels |
| 64x48 | 1/25 | 8 pixels |
| 128x96 | 1/6.25 | 32 pixels |

A direct32x32 resize has area scale1/75 (~2.67 pixels) and changes aspect ratio.
Antialiasing, occlusion and quantization can further obscure shape/material.
These calculations do not prove universal impossibility of semantic decoding.
They show that the existing visibility acceptance does not qualify32x32 scoring.
Increasing resolution must be a public new design decision before model results,
not deletion of difficult scenes or a post-result change of gate.

## A concrete conditional model, if a worthwhile task were later established

At maximum n10, use a608-dimensional condition: ten rows of
`mask1+attributes15+xyz3+rotation1+projected_xyz3` (230), four off-diagonal
relation matrices (360), and six direction vectors (18). Attribute widths are
8/3/2/2, from the pinned
[properties](https://github.com/facebookresearch/clevr-dataset-gen/blob/f0ce2c81750bfae09b5bf94d009f42e055f2cb3a/image_generation/data/properties.json).
No image ID/filename is an input. Give the same complete condition to every
method. Padded objects remain masked; the numeric cost inventory includes all
ten rows, rather than changing the source distribution.

| Tensor/module, batch axis omitted | Shape/equation |
| --- | --- |
| Condition | `c=tanh(C608 W[608,64]+b)` |
| Text content state | `T[10,32]`, init from `[c64, object22, index_onehot10]96 ->32` |
| Image content state | `I[8,8,32]`, init `[c64, grid_xy2]66 ->32` |
| Actual raster | Each image state projects32->48, a4x4x3 patch; concatenate to32x32 RGB |
| Bounded text | Per object32->15 logits, four categorical groups; a fixed grammar renders readable attributes |
| Relations | Ordered off-diagonal pair `[T_i,T_j]64 ->4` independent Bernoulli logits, not a four-way softmax: left and behind may co-occur |
| Paid text observation | `[T32, sampled_attribute_onehots15, outgoing_relation_bits36]83 ->32` |
| Paid image observation | `[I32, actual_decoded_RGB_patch48]80 ->32` |
| Feedback | Masked mean text32, mean image32 and c64 concatenate128->64 |
| Shared content update | `[state32,c64,feedback64,local_observation32,position2,modality1]195 ->32`, residual addition |
| Action T/I/J | Update10 text rows /64 image rows /74 rows, respectively; recompute changed outputs |
| Dynamic policy | `[feedback64,step1]65 ->16 ->3`, two decisions after the shared initial pass |

This yields real text/pixel changes, not a route name. It is bounded attribute
language, not an open-vocabulary language model. Two updates retain all nine
fixed sequences, direct/static deeper NDU, compiled/unrolled equivalents and
distilled alternatives. Static methods get all applicable output/feedback reuse
and can spend saved policy cost on useful content updates. Compilation is not
ruled out by continuous state. No action or observation accesses target pixels,
target residuals, evaluator answers or hidden scene data at serving time.

For a stochastic law, sample the categorical/Bernoulli text fields and RGB
Gaussian latents with prospectively fixed sigma, clipping and quantization;
include all action, latent and output randomness in the trace law. Four joint
samples would be a development starting value, not evidence that risk gradients
are accurate. Compare supervised weights identically:

    Lsup = CE(attribute/text fields) + lambda_rel BCE(relations)
           + lambda_rgb GaussianNLL(reference RGB | conditional mean, fixed sigma).
    U_rho = -log E_tau[exp(-rho R(decoded text, decoded RGB))] / rho.

The additive arm estimates expected decoded reward with a score-function loss;
an NDU arm can use detached normalized exp(-rho R) weights on trace log probability,
with the same supervised weights and joint-sample count. The resulting finite-K
ratio/score estimator is generally biased and variable; it is not an exact
entropic gradient. Fit/calibration of any baseline or critic is additional work.
Target RGB/masks/labels may supervise training and offline rewards only.
If nuisance state is not conditioned, single-reference RGB NLL needs a declared
conditional-distribution interpretation; it is not proof of semantic alignment.

## Operation and memory account: what is known and what is still unpriced

The executable [integer calculator](../research/clevr-feasibility-20261023/analytic_budget.py)
imports no arrays/model/data code. Its
[inventory](../research/clevr-feasibility-20261023/analytic-budget.json) contains
all affine shapes, per-sequence special functions, sampling counts and explicit
buffer formulas. These are algorithm inventories, **not measured hardware FLOPs,
CPU timing or a complete lifecycle cost claim**.

| Proposed mean computation | MACs/example |
| --- | ---: |
| Shared initial generation | 330944 |
| Paid feedback per decision | 198592 |
| Text update including feedback/changed decoder | 288832 |
| Image update including feedback/changed decoder | 696256 |
| Joint update including feedback/changed decoders | 786496 |
| Fixed TT / fixed JJ with observation reuse | 744768 /1903936 |
| Dynamic policy addition for two decisions | 2176 |
| All nine sequences with prefix/observation reuse | 5638144 plus nine external rewards |

An unchanged modality retains its previously generated sample and cached
observation; it is not resampled for free. At the second decision after T/I/J,
feedback costs34752/172032/198592 MACs in this specific graph. The first dense
inventory (TT908608, nine sequences5828544) is retained in
[the unreused arithmetic draft](../research/clevr-feasibility-20261023/analytic-budget-dense-unreused-v1.json)
and is not the required optimized static comparator. The graph still permits
further constant-term folding/fusion for every method; these figures do not
claim the lowest possible compiled cost.

There are66371 content and1107 policy parameters. FP64 parameters, gradients and
both Adam moments require2159296 bytes altogether; inference weights alone
539824 bytes. Explicit saved-state/packed-input buffers for B16,K4 plus equally
sized adjoints and optimizer arrays total72956608 bytes (~69.6MiB), before
framework tapes, BLAS workspaces, data, observers or simultaneous branch leaves.
Keeping nine final state arrays adds27417600 bytes. This is a specified array
inventory, not a certified peak-RSS bound. A NumPy/native implementation is
possible in principle; a general reverse pass, stochastic training and observer
are not implemented, tested or included for free.

Dense forward plus weight/input adjoints can be inventoried as at most three
times the affine forward MACs when every input adjoint is computed. With three
seeds, three LR candidates,256 updates, B16 and K4, the worst JJ+policy dense
inventory is733403676672 MACs after sharing the deterministic initial pass
across K samples. A512-source all-nine K4 screen for one selected checkpoint
adds11038588928 forward MACs plus18432 external reward calls; all three selected
seeds require33115766784 MACs and55296 rewards. A10000-request JJ+policy horizon
per selected seed adds57183360000 MACs across three seeds. These are upper
inventories for that dense adjoint construction, not a
reason to execute unused constant-input adjoints or pad any baseline's bill.

For K4/JJ, the same specified graph has40832 hidden tanh calls plus30888 sigmoid
calls,128 additional policy hidden tanh calls,1350 attribute and24 policy
softmax exp/div calls each. If sigmoid uses scaled tanh, the nonpolicy total
becomes71720 tanh calls. Sampling requires36864 Gaussian variables,4800 text/
relation uniform variables and8 policy draws. An explicitly chosen Box-Muller
backend would additionally need18432 each of log/sqrt/sin/cos; a different RNG
backend needs its own inventory. The existing content Adam convention gives
862903 scalar,199114 div,66372 sqrt,40 pow and2 compare operations per update;
the policy update is separate. Exact loss/scoring operators, derivatives,
clipping/quantization, packing, serialization and all external observer operations
remain additional. Old public prices omit some new primitives, so the old unit
denominator cannot silently become a complete new work price. The JSON keeps
unknown work explicitly unpriced, never zero.

A **planning envelope only**, if task value were first established, could be
1800 process/descendant CPU seconds per system,2GiB peak RSS,
256MiB retained output, with H10000 requests per selected seed charged inside the
complete lifecycle. An illustrative1e12-MAC neural allocation contains the
~0.8237e12 subtotal above and leaves~0.1763e12 for additional neural work; it is
not a full lifecycle work price or proof that missing phases fit. No CPU/MAC
conversion has been measured. Renderer geometry/ray tracing, scalar work and I/O
must be billed by complete CPU and their own inventories rather than hidden
under a neural MAC allocation. The same CPU/RSS/storage envelope applies to
renderer/static/dynamic arms; static savings buy useful work. A real serving
horizon must come from the intended use case,
not be chosen to make amortization favorable. Any future budget must include
common preparation in each arm and establish the missing costs before freezing.
This envelope is neither an approved experiment nor a recommended spend on the
currently rejected task. Old10s/12B are not a reason to request user permission.

## Pixel scoring and falsifiable observability prerequisites

An RGB-only parser or blinded annotator must first recover objects, attributes
and relations from the raster. Match instances up to legitimate permutations;
do not treat internal object indices as visible identity. Compare recovered
facts with the condition only after parsing. Count/attribute/relationship errors
and unknowns stay in the original denominator. Text and image must each satisfy
the condition, then agree with each other; two matching errors are not success.
Official front/behind is a world-direction relation, not image up/down.

Before any model-benefit study, a separately fixed qualification/control design
would need the following, without selecting sources by a candidate's errors:

- Cover all original object counts, sizes, materials and occlusion strata. Test
  missing objects, exchanged attribute bindings and changed relations while
  preserving attribute histograms; these are evaluator controls, not a favorable
  training distribution manufactured for a policy.
- Hold RGB fixed and alter attached IDs/JSON: pixel parsing must not change.
  A collision of required semantics after the exact quantization pipeline is a
  concrete nonidentifiability example; a weak parser's failure alone is not a
  proof that every parser must fail.
- Use exact discrete count/attribute semantics. Derive geometric tolerance from
  rasterization/projection/quantization, and uncertainty from independent controls,
  rather than inventing a natural0.95 threshold. Bound scoring error relative
  to a predeclared minimum useful effect; no trusted bound means no qualified
  claim at that resolution.
- Report actual raster errors separately. Pixel MSE/MAE is meaningful for
  aligned replay, but background dominance and valid nuisance alternatives can
  conceal or create errors. Use per-object/foreground scores or IoU only with
  independently obtained masks; center metadata is not a mask. Charge mask
  generation, parser training/qualification, human audits and every verifier call.

If the verifier enters the action loop, its full recurring cost is part of the
dynamic method and equally available to static methods. It cannot silently use
condition metadata to fill invisible content. At present no such qualified
pixel scorer or observability result exists for this proposed32x32 task. Thus
neither a complete numeric cost nor a useful effect can honestly be claimed.

## Scope and follow-through

The original [H4 conditional savings supplement](H4_CONDITIONAL_SAVINGS_BOUNDARY.md)
records the separately valid1.548783508 microsecond necessary runtime saving for
the old fixed-weight, input-level two-law comparison. Outcome-adaptive draft
selection can change those conditional laws and needs its own oracle. That
number does not transfer to this model,
task, horizon or budget. No further full/low critic/timing attempt is supported.
Keep content-group reconciliation and NDU-group training research independent;
this review does not duplicate their probes.

The next worthwhile research proposal needs a nontrivial generation need and
lawful observable action-value differences that strong static methods cannot
match cheaply in actual complete costs. Do not create missing inputs, route
noise or a selected easy dataset just to get that difference. The present CLEVR
scene-to-text/raster adaptation lacks that justification and should be archived
as a rejected training candidate, with its concrete implementation/cost lessons.
No new budget decision is needed to reject it.

[Access/scope record](../research/clevr-feasibility-20261023/scope-and-access.json):
the CVPR PDF read was denied403 Forbidden; two Blender documentation reads were
denied402 Payment Required. Those exact targets were stopped without retry,
alternate download or credential change. Compatibility remains unverified;
the successful pinned source reads support the narrow conclusions above.
