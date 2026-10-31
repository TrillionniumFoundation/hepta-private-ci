# Raw-evidence task value and stopping surfaces

This is a finite, auditable content/control experiment. Its task is synthetic
binary classification from raw categorical and waveform observations. It is not
a production Hepta owner, a multimodal foundation model, or a proof of a
continuous-time optimal-stopping PDE. The controller learns task advantages from
the same frozen content model that is actually executed.

## Freeze and separation

1. Publish this contract and the policy/content/renewal source before formal fits.
2. Use the content experiment's fixed final `multimodal_evidence` checkpoints:
   ordinary and analytic backbones, width 16, seeds 11, 23, 37. Do not select a
   checkpoint using policy heldout results. Each backbone is frozen throughout
   its controller comparison; parameter shapes are identical across families.
3. Run `policy_run.py fit` with the real published protocol commit. The fitting
   process builds only train and dev graphs. Publish **all six** controller
   payloads and their hashes before any heldout policy evaluation.
4. Run `policy_run.py evaluate` with that real candidate commit. It verifies
   content checkpoint and complete source hashes against the frozen fit receipt.
   Outputs are created in new directories; existing evidence is not overwritten.

Formal fitting is deterministic on finite training histories, not a Monte Carlo
optimization. Development selection and heldout configurations are disjoint.
The raw finite alphabet is shared across splits; therefore this evaluates
generalization to new public parameter configurations, not unseen vocabulary.
Paired deployment worlds use separate fixed random seeds and never change any
model, ridge parameter, threshold, or controller choice.

## State and causal observation interface

There are six slots and a four-READ budget. The modality schedule and slot
durations are public. A observations are two-dimensional noisy bit one-hots. B
observations are eight-dimensional raw waveforms: an imperfect label signal plus
an independent nuisance direction. Two modality bits identify the input type.
The 12-dimensional raw inputs and their exact finite conditional distributions
come from `content_tasks.multimodal_support`; the model never receives a label,
Bayesian posterior, likelihood ratio, or future realized observation.

The runtime public state is `(hidden, slot, remaining_READ_budget, pending_dt)`.
Initial hidden state is the content model's zero state. No observation is read
before the first action.

| Action | Observation access | Content successor | Clock/budget | Abstract fee |
|---|---|---|---|---|
| STOP | None | Classify current hidden state | Terminates | 0 |
| READ | Current slot's raw observation only | Actual frozen `Model.step` | Advance slot, budget minus one, pending dt resets | Configured READ fee |
| SKIP | None | Hold hidden state | Advance slot, accumulate slot duration | Configured SKIP fee |
| Invalid request | None | Guard converts to STOP | No clock/budget change | 0.005 attempt fee |

On READ, elapsed time passed to the backbone is the accumulated pending duration
plus the current slot's duration. The teacher uses exactly this transition.
Between reads hidden state is held; pending time is applied at the next read.
This is an explicit observation-driven recurrent contract, not autonomous
unobserved membrane propagation. At the horizon only STOP is legal. Regular
controllers mask illegal actions and are expected to have zero guard fallbacks.
Negative checks explicitly request an invalid READ and retain its fee and lack
of observation access.

The objective is expected terminal classification correctness minus all READ,
SKIP and invalid-attempt fees. These fees are abstract, fixed tariffs. Measured
CPU/wall are reported separately; no tariff is called money, joules or energy.
The same external fees and budgets apply to both backbones and all controllers.

## Exact offline teacher

The teacher may use the generative likelihoods and **the complete already-read
history** to compute a Bayesian posterior. It never observes future realized
draws. For a fixed frozen content state, its STOP value is the true conditional
probability that that model's current argmax class is correct, not the
classifier's own confidence. For READ it integrates all possible current raw
observations, updates both content state and history posterior, and continues
optimally. SKIP advances time without an observation or posterior update.

Thus the Bellman equation is a causal expectation over legal successors. It does
not maximize after peeking at the future of one realized path. Teacher values
include full downstream action fees. The history teacher is an upper bound for
policies compressed to the chosen public feature vector; a gap can reflect
information lost by the backbone, controller fit, or both.

The primary task configurations are specified in `policy.configurations()`:

| Split/name | Modalities | qA | qB | READ | SKIP | Slot durations |
|---|---|---:|---:|---:|---:|---|
| train_a | ABABAB | .65 | .75 | .020 | .004 | 1 each |
| train_b | BABABA | .75 | .70 | .045 | .003 | .75 each |
| train_c | ABABAB | .70 | .80 | .060 | .004 | .5,1.5 repeated |
| train_d | BABABA | .60 | .65 | .015 | .002 | 1.5,.5 repeated |
| dev_a | ABABAB | .70 | .75 | .035 | .004 | 1 each |
| dev_b | BABABA | .68 | .77 | .040 | .006 | .75 each |
| heldout_a | ABABAB | .72 | .78 | .030 | .005 | .8 each |
| heldout_b | BABABA | .62 | .82 | .055 | .006 | .5,1.5 repeated |
| heldout_c | ABABAB | .80 | .60 | .025 | .002 | 1.2 each |
| heldout_d | BABABA | .70 | .75 | .080 | .004 | 1 each |

Every configuration has prior .5 and READ budget four. A six-slot ABABAB graph
has 2,547 history states; BABABA has 2,901. Across four train graphs there are
10,896 states, 2,388 legal READ advantage labels and 4,052 legal SKIP labels.
Terminal and exhausted-budget states remain in saved evidence.

## Shared public features and registered controls

Controllers see hidden state, model softmax, slot/horizon, remaining budget,
pending duration, public qA/qB, READ/SKIP fees, prior, full public modality
schedule and durations. They do not receive the teacher posterior or history.
With width 16 this is 38 scalar features. The same feature function is used in
fitting and actual execution.

The task-value controller fits the two advantages `Q_READ-Q_STOP` and
`Q_SKIP-Q_STOP` by ridge regression. Training-only feature mean/std define
`z`; std below 1e-8 is replaced by one. The fixed design is `[1,z,z*z]`, with
z clipped to [-20,20]. Ridge coefficient is 1; the intercept is unpenalized.
Each head uses all its legal train-state labels, with uniform state weighting.
There is no search over ridge coefficients, feature sets, epochs or heldout
outcomes. Its policy chooses the largest legal score from STOP=0 and the two
estimated advantages; ties prefer STOP, then READ, then SKIP.

The ordinary controls are STOP, fixed READ counts 1/2/3/4, and confidence
thresholds .50/.60/.70/.80/.90/.95/.99/1.01. Confidence means the maximum current
softmax. The best fixed count, best confidence threshold and best overall
lightweight control are chosen solely by mean exact return on the two dev
configurations. Both families use the same search budget and tie order.

The main 2x2 is ordinary/analytic backbone crossed with selected-lightweight/
task-value controller. All four individual ordinary controls remain visible in
the evidence: STOP, selected fixed, selected confidence and overall selected
lightweight. The history oracle is reported separately, not treated as a
deployable same-feature competitor. Report each seed and configuration; three
seeds and four configurations do not establish broad statistical superiority.

## Value surfaces and the meaning of boundary

For root and predeclared histories `()`, `(0,)`, `(-1,)`, `(1,)`, compute

`max(Q_READ,Q_SKIP)-Q_STOP`

over a 21-point public READ-cost grid from 0 to .5, reoptimizing downstream
actions at that same cost. If the continuation advantage changes from positive
to negative, locate its zero with 35 bisection steps. Otherwise explicitly
report no crossing. The cost-ray response should be nonincreasing within 1e-11.

These are task-value stopping surfaces in full observed-history state. They are
piecewise finite-action objects and may have kinks. They are not asserted to be
a unique scalar membrane threshold, a stationary financial default boundary,
or a solution satisfying classical smooth-pasting. Heldout advantage RMSE,
sign accuracy, chosen-action regret and exact policy gap quantify how much of
the teacher's decision surface the learned controller actually captures.
Record the learned public controller's scores and actions along the same cost
grid. For the first heldout configuration, if a root crossing exists, independently
execute the history oracle on all 1,024 raw worlds at root minus/plus 0.0001.
Save both side traces and compare their weighted actual values to the teacher;
also report the learned controller's actions and exact policy values there.
This diagnostic does not refit or select the controller.

## Actual execution, independent checks and resource evidence

For every model and heldout configuration, execute 128 paired raw worlds for
STOP, selected fixed, selected confidence, task value and history oracle.
World seed is `730000 + content_seed*100 + heldout_index`, identical across
families. Every decision saves requested and guard-executed action, before/after
state hashes, slot/budget/pending time, actual raw access, raw observed vector,
scores and all charged fees. World manifests are evaluator evidence and are
not passed to the actor. Saved source draws permit independent replay.

The first heldout configuration is additionally evaluated by exhaustive latent
world enumeration: two labels times 512 raw outcome sequences = 1,024 worlds
per controller. Independently run each world through the actual executor and
weight by its generative probability. This must agree with the dynamic-program
policy expectation within 2e-10; public successor states must agree within
2e-10. The actual execution does not reuse Bellman transition probabilities.
Occupancy-weighted action regrets must sum to the exact oracle gap within 2e-10.

Contract checks change the hidden label while holding all observed values fixed,
change all unread future draws, issue invalid READ, and SKIP without reading.
Actions and public state must be invariant to hidden-label/future changes;
invalid work must retain its fee. A three-slot development fixture is separate
from formal fitting and heldout evidence.

Sequential CPU/wall phases include initialization, controller, guard, actual raw
access, content step (including encoder and analytic/ordinary kernel), clock,
readout, evaluator and evidence hashing. Outer fit/evaluation clocks include
teacher construction, fitting, selection and evidence serialization through the
last reported checkpoint; receipts explicitly label their final-write boundary.
The caller should retain full process CPU/wall including import/startup and final
receipt I/O. Do not add overlapping wall times or interpret them as energy.

## Reproduction

Set `OPENBLAS_NUM_THREADS=1` for the declared small CPU experiment. From this
directory, run `python policy_audit.py --tiny` for the development-only fixture.
Formal stages require real previously published source/candidate commits:

```bash
python policy_run.py fit --model CONTENT_FINAL_NPZ --output NEW_FIT_DIRECTORY \
  --freeze-commit REAL_PUBLISHED_PROTOCOL_COMMIT
python policy_run.py evaluate --model CONTENT_FINAL_NPZ \
  --controller FROZEN_FIT_DIRECTORY/controller.json --output NEW_EVAL_DIRECTORY \
  --candidate-commit REAL_PUBLISHED_ALL_CONTROLLERS_COMMIT
```

The full finite task is deliberately small and known. Demonstrating causally
valid labels, real raw observations and exact execution does not establish
better long-context memory, Transformer replacement, biological fidelity,
natural audio/video generation, or large-model scaling.
