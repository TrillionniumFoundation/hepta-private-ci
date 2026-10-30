# Proposed fresh repair study — not executed

Status: design only. No new training, sample generation, feature fitting or
heldout evaluation has been started for this proposal. The completed v1 source,
negative outcomes and gate remain sealed.

## Concrete defect to repair

The v1 learned readout receives only summaries of the current job's schedule.
It never receives the next job's public quality/price schedule, although the
full FIRE target depends on that schedule. Two public states can therefore map
to identical learned inputs and have different full FIRE values. This is
representational aliasing, independent of optimizer success. Infeasible-action
sentinels also consume regression capacity; the retained validation diagnosis
shows that masking them alone does not resolve the approximation failure.

## Smallest scientifically useful comparison

Keep the frozen inherited 6,217-parameter content decoder, packet generator,
two-job event contract, actual local READ/SKIP/FIRE/STOP backend, TRAIN-only
confusion calibration and cost definition.

Fit three controller families, using exactly the same complete public state,
parameter count, initializer, batches, update opportunities and model selection:

1. Full Bellman action-value targets, including post-FIRE continuation.
2. Ordinary action-boundary targets from the same full-DP teacher.
3. First-event value targets, setting post-FIRE continuation to zero.

The exact fitted-model DP remains an untrained reference in heldout execution.
No financial-specific or joint-content-training conclusion is attached to this
controller study.

### Full public state

Augment the existing 40 features with **all** public reliability and charged
price entries for both jobs, padded to the fixed maximum ten ticks, and the
four TRAIN-calibrated confusion probabilities. This gives 84 inputs. Existing
features retain posterior, remaining time, job identity and remaining read
budget. Padding is explicit and does not reveal any future realized payload or
label. With the fixed task contract, the encoded state can reconstruct the
public state required by the finite oracle. All three learned families receive
the same fields.

### Function class and feasible targets

A single tanh hidden layer of width 32 and four outputs has 2,852 coefficients
for each family. This is still a small controller, but it can represent
interactions omitted by a purely linear readout. Output targets are normalized
with one fixed declared scale. The squared loss includes **only feasible
actions**, with the identical feasible mask and normalization in all families.
An invalid action's numerical sentinel must never enter the fitted loss.
Deployment still masks infeasible actions before argmax.

The width increase is an explicit prospective redesign, not a reinterpretation
of v1. Since the ordinary and value controllers receive the same increase, the
new primary comparison remains matched. The new experiment will not uniquely
attribute improvement to state completion versus capacity versus masking; the
mathematical alias witness and retained validation diagnostic already identify
the respective defects.

## Freeze, budget and gates

- New source/protocol freeze before new cohort generation; five new seeds such
  as 127, 139, 151, 163 and 179, with a new RNG base and exact overlap audit.
- Per seed: 128 calibration packets, 60 TRAIN and 24 validation public schedules;
  12 belief/budget/time states per schedule. No test payload is constructed at
  this stage.
- One predeclared learning rate 0.003; 600 Adam updates, batch 64, for each of the
  three families. This is **15 new small neural-controller trainings**, not
  15 backbone trainings. Preserve intermediate checkpoints every 50 updates.
- Select checkpoints by the same validation **action regret under the full
  conditional DP**, not by incomparable value-MSE versus classification-error
  rules. Record value MSE and action disagreement as diagnostics.
- Before opening fresh test data, require the full-value and ordinary selected
  models to have mean validation regret at most 0.05, and no seed above 0.08,
  in reward units. Complete the entire declared development matrix even if
  an early seed fails. A failed gate stops confirmation and remains a result.
- If the development gate passes, construct 40 untouched heldout sessions per
  seed and run the three learned policies plus DP at the already designated
  primary price multiplier 1.5: **800 actual local-owner sessions**.
- Primary contrast: full-value minus ordinary-boundary realized utility, paired
  across the five independent cohorts/fits. Report its two-sided 95% interval;
  a claimed benefit requires lower bound above zero and mean at least 0.02.
  First-event and exact-DP gaps are secondary and cannot rescue a failed
  primary contrast. Preserve complete runtime/setup measurements.

## Cost and whether to execute now

The completed v1 runner took 93.045 wall seconds for 4,200 local-owner sessions,
640 calibration calls, oracle labels and small closed-form fits. The proposed
confirmation has less than one fifth as many owner sessions, but adds 15
gradient-trained controller fits and numerical/gradient parity checks. A rough
planning allowance is **1–3 CPU wall minutes plus shared-resource waits**;
this is an estimate, not a measured result or fixed completion promise.

This revision is worth executing as a small development-first experiment while
other research runs continue. It addresses an identified input-state defect
and tests an economical controller approximation. It should not consume a fresh
heldout cohort unless the validation approximation gate passes, and it does not
justify beginning multimodal backbone training. The current task requested
this proposal before execution, so all proposed work remains unstarted.
