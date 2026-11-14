# PERC-1: perception and evidence acquisition

## Question and scope

Does a perception Cell improve final task outcomes by preserving local representations,
by choosing additional observations, or through an interaction between those changes?
The first experiment is a 2 by 2 factorial design. It tests a perception interface and
observation policy under the same frozen base model and total resource envelope.

| Arm | Representation | Observation policy |
| --- | --- | --- |
| G-F | Global pooling of the frozen encoder output | Frozen reading sequence |
| D-F | Local tokens from the same encoder | The same frozen reading sequence |
| G-A | Global pooling of the frozen encoder output | History-conditioned acquisition |
| D-A | Local tokens from the same encoder | The same active policy family |

All four arms retain the exact raw evidence channel. Removing raw evidence from the
global arms would confound representation with access to information. The active
policy may use only its acquired observation history and the actor-visible inventory
of legal actions. It may not receive the answer location or an inventory filtered by
hidden evaluator truth.

This protocol is a research specification. A synthetic integration run establishes
mechanism coverage only. It cannot establish PERC-1 task benefit, a learned encoder,
production activation, or permission to adopt a model.

## Frozen identities

Before confirmation, retain the complete source commit and tree, base-model and
encoder checkpoint hashes, tokenizer and preprocessor identities, local token layout,
pooling operation, controller and downstream model identities, training code and
independent training seeds, dataset and source-group split hashes, teacher access
policy, evaluator identity, price table, resource envelope, and preregistered decision
rule. An unknown identity or measurement remains unknown.

The integration baseline for this implementation is main commit
`732e934ba496d90fbe042b8d41d479ef901643e5`, tree
`75dc1c1f65375c97da259d947c465a04f030461d`.
The Cell implementation dependency is candidate commit
`6ddfca2406e4d01416cd2f7ab1655a0dc16f8da5`, tree
`491eace326f335498334fb051c9e8f298ca7a04c` on
`fix/codex-v13-same-model-next-task-20261106`.
These are distinct identities. Building on the candidate does not merge or activate
it on main. The new PERC work must remain an isolated, reviewable extension.

## Observation contract

Each observation binds the task or Cell scope, immutable source version, source
digest, acquisition identity, availability time, encoder identity, and representation
mode. Evidence locators use source coordinates: exact byte ranges, original image
regions, video frames and time intervals, or explicitly identified asynchronous state
versions. A crop or resize retains a mapping to the original source. Upsampling a
blurred image is a transform of existing evidence; it is not new information.

The raw channel preserves bytes or a verifiable immutable artifact reference.
The learned channel carries bounded local latent values, their locations and times,
and the model that produced them. Prediction residuals, when available, bind their
own predictor. A missing residual is not zero. Hashes and manually authored feature
vectors may be used for protocol tests, but must not be called learned features.

Observation payloads are bounded and versioned. Invalid coordinates, unknown fields,
duplicate identities, altered source bytes, mismatched encoder pins and latent links
to absent evidence must be rejected. No implicit truncation may silently remove a
negation, amount, version or button state. The native Cell limit is 65,536 input bytes;
large image and video artifacts remain with their fact owner and require bounded
references or admitted slices.

## Acquisition and decision boundary

The perception Cell proposes a legal read, crop, frame, field query, wait, or stop.
The prediction Cell estimates the distribution of final task utility and cost from
the actor-visible prefix. The decision Cell chooses under its frozen NDU profile and
budget. A proposal is advisory and supplies no new read, write or execution authority.
Actual access remains subject to the existing source owner and runtime admission.

Reserve before the action, then settle the complete actual charge. Retain failed,
cancelled, rejected, stale, no-new-information and unknown outcomes. An unknown
outcome retains its reservation until reconciled; it is not a free retry. Replaying
the same operation returns its original result, and reusing the operation identity
with different arguments is a conflict.

## Task panels and ground truth

| Panel | Controlled challenge | Final outcome and exact fields |
| --- | --- | --- |
| Incomplete document | The initial legal view omits a relevant local span | Correct task answer; amounts, units, signs, negations and version strings |
| Blurred screenshot | A lower-resolution view leaves a UI detail unresolved | Correct action or abstention; button state, target and source-coordinate evidence |
| Asynchronous state | Event time differs from the time evidence becomes available | Correct decision for the available version; no use of future observations |
| Distractor video | Relevant event competes with unrelated frames | Correct event and temporal relation, with evidence frames from the correct source |

The dataset registry defines source groups before splitting. Pages of one document,
adjacent video segments, or related GUI states must not straddle training and
confirmation. Retain a separate out-of-source or time-forward panel where feasible.
Confirmation data cannot be repeatedly used to select policies, budgets or features.

Teacher information is permitted only in the declared training path. The independent
evaluator can see full truth, but the deployment policy must receive a separate
actor-only object. Truth must not enter prompts, candidates, candidate ordering,
cost estimates, cache keys, errors or actor-visible logs. Canary tests should compare
two private truth assignments with identical public prefixes and require identical
actor inputs and proposals until a legal acquisition reveals new evidence.

## Resource accounting

Match total budgets and training opportunities, not only gradient steps or number
of model calls. Record acquisition, preprocessing and encoding, serialization and
communication, candidate construction, planning and critic inference, downstream
answer generation, waiting, retries, recovery and evaluation. Record wall time, CPU
or accelerator time, transferred bytes and any measured energy in their native units.
Use a frozen conversion table only when those units are aggregated.

Dense representations pay for additional tokens, communication and downstream use.
Fixed reading policies receive the same legal action inventory and resource ceiling;
their sequence and stop rule are selected on training/development data and then
frozen. Shared setup is handled identically across arms. Inclusive call envelopes
are reported separately from exclusive costs to avoid double counting. Missing
measurement is not recorded as zero, and an observed subtotal is not a complete cost.

The existing native Circuit completion currently reports model latency as actual
work. That field does not establish this experiment's full accounting. The experiment
ledger must retain the additional costs before any budget-equivalence claim.

## Endpoints and causal analysis

The primary endpoint is final task correctness under the resource envelope. Key-field
fidelity is a co-requirement or a prespecified noninferiority condition. Useful
secondary endpoints are necessary-evidence discovery, false localization, repeated
reads, no-information reads and evidence coverage. Representation probes and model
confidence are diagnostics only.

Report the dense main effect, active main effect, and interaction:

```text
dense = ((D-F - G-F) + (D-A - G-A)) / 2
active = ((G-A - G-F) + (D-A - D-F)) / 2
interaction = (D-A - D-F) - (G-A - G-F)
```

For replayable episodes, estimate the contribution of an extra observation using two
continuations from the same frozen prefix and world snapshot: acquire and continue,
versus skip and continue. Use matched random seeds and the same continuation policy.
Compare final task utility and charge the additional computation. An equal-cost sham
observation can separate information benefit from extra reasoning time. Evaluation
cost is recorded separately; it does not become free deployment compute.

If the world cannot be replayed, before/after answers are descriptive. A causal
estimate requires a declared randomized acquisition or skipping design with retained
assignment probabilities. Confidence increases alone are not causal task gains.

Use independent source groups and independent training seeds as sampling units.
Many rollouts from a single trained model do not supply many independent training
replicates. Preserve complete four-arm pairing. Report paired effects and intervals
that resample source groups and seeds at the appropriate levels. A dataset with
missing arms, selective failures or reused confirmation cases is not a valid
confirmation experiment.

## Decision rule and present qualification

Before viewing confirmation outcomes, freeze the primary comparison, practical
minimum improvement, allowable key-field degradation, cost ceiling, uncertainty
method and multiple-comparison handling. Pilot results inform sample size, not
retroactive confirmation thresholds. Unspecified thresholds remain a blocker.

| Result | Meaning |
| --- | --- |
| Contract tests pass | The tested parsing, identity, budget and replay behavior is implemented |
| Synthetic four-arm run completes | Integration and reporting paths execute; scientific status remains HOLD |
| Trace validation fails | The supplied experimental record is invalid and cannot support a benefit claim |
| Statistical threshold appears met | Descriptive evidence requiring frozen provenance, independent evaluation and complete costs |
| PERC-1 qualification | A separate decision based on a complete, preregistered real confirmation run |

No user-supplied flag, model name, hash alone, or probe score promotes an integration
fixture into a scientific pass. The initial implementation deliberately emits HOLD
for scientific qualification while allowing engineering validation to complete.

## Primary research sources

1. Heilbron and de Lange, *Higher-level spatial prediction in natural vision across
   mouse visual cortex*, PLOS Computational Biology, 2026-01-20.
   <https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1013136>
   Natural-image predictability is associated with cortical response after modeled
   controls. It does not identify a unique causal prediction algorithm in the brain.
2. Mur-Labadia et al., *V-JEPA 2.1: Unlocking Dense Features in Video Self-Supervised
   Learning*, arXiv:2603.14482, v1 2026-03-15; v3 2026-06-11.
   <https://arxiv.org/abs/2603.14482>
   Dense loss includes visible and masked tokens, with intermediate-layer supervision.
   The paper also changes tokenization, model and data scale; total cross-version gain
   cannot be attributed to dense loss alone.
3. Hu et al., *Real-World Reinforcement Learning of Active Perception Behaviors*,
   NeurIPS 2025; arXiv camera-ready 2025-12-01.
   <https://arxiv.org/abs/2512.01188>
   AAWR uses privileged training information for value and advantage estimation while
   the deployed policy uses its own partial observations. Its evaluation covers both
   simulation and real robots, not eight exclusively real-robot tasks.
