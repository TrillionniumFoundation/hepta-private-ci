# Two-Cell consolidation with explicitly retained old tasks

Continuation of PR #1654 at `f30abc25b0c00417c57765743905ccdc3a9b2d99`.
This is an additive research study in the existing qualification directory,
not a new runtime, persistent memory service, model selector or live base update.
The original five-arm study and all existing CI gates remain unchanged.

## Registered task and knowledge transfer

The eight-way action schema is fixed. Old classes are indices 0..3
(alarm/calendar/date/reminder); new classes are 4..7 (time/timer/todo_list/weather).
These are research-defined class-incremental tasks, NOT chronological observations.
All original protected-content-group CLINC rows and conflicting labels remain.
Input/question/options remain identical across methods. No task ID or correct
old/new class membership is available to any predictor at inference.

The previous verified BGE raw feature matrix is read via the existing full
replayer. The previous fitted Heads and previous normalizer are NOT inherited.
A NEW FiLM Head from model_runner.build_head learns only the 160 old-class base
rows for 200 steps. Its eight-class logits include untrained new-class outputs.
A copied new-task Cell learns only the 120 new-class adaptation rows for 200
steps. Neither modifies the frozen Encoder or the old teacher. Each Head has
3,848 parameters / 15,392 FP32 weight bytes at width 384. This differs from V6's
2r+1-coefficient Cell: these are still lightweight full FiLM Heads, not an
assertion that 17 private scalars achieved this learning result.

Exactly eight old base examples per class are selected by content fingerprint,
one per source group, before evaluation: 32 old replay rows. All adaptation and
extra rows unused by this task remain in the source corpus; no hidden relabeling.
The new normalizer uses ONLY the 160 old base rows. The class assignment, replay
budget, temperature, steps and retention thresholds were fixed before first scores.

## Six explicit inference rules and strong controls

- frozen: preserve the old teacher.
- new_only: use the copied new-task teacher, exposing catastrophic forgetting.
- label_replay: fit a copy of the old teacher on old memory labels + new labels.
- distilled: fit the same-size copy on OLD teacher probabilities at old memory
  inputs, and NEW teacher probabilities at new training inputs. Gold labels
  partition training only; the student never receives a task ID at prediction.
- all_old_replay: supervised replay with all 160 old training rows, an explicit
  larger-memory control rather than a falsely equal resource comparator.
- teacher_mean: arithmetic mean of the TWO teachers' probabilities, not an
  oracle selecting which teacher is correct. It uses twice the Head weights and
  two Head forwards, but still only one shared Encoder feature per input.

The three consolidation students use the SAME original Head initialization,
AdamW lr=1e-3 / weight_decay=.01, 200 steps, and 16-old/16-new minibatch schedule.
Label-replay and distilled additionally use identical replay IDs and indices.
Distillation minimizes T^2 KL(teacher || student), T=2, with batchmean reduction.
Teacher targets are detached and neither teacher's parameters change. These
operators do not update the old selected snapshot in place.

Teacher learning, target construction, copies, new learning and each student
fit are separately timed. Total experiment optimization is 1,000 steps, not 200.
Replay features occupy 49,152 packed FP32 bytes versus 245,760 for all-old replay;
labels/IDs and temporary tensors are additional. The full research process keeps
the original corpus and all candidates for comparison: this is NOT bounded RSS
or a measurement of an isolated deployed student's whole lifecycle. Two teachers
cost 30,784 Head weight bytes versus 15,392 for one student; it is not a 50%
reduction in total Encoder+Head storage. No new Encoder is run by this script.
The existing physical CI job calls it after fresh encoding and separate replay.

## Retention and sealed evidence

Training receives ONLY base/adapt label mappings. Calibration truth is used later;
held-out labels enter only the separate reviewer. Scores report each of all eight
classes, then class-macro old/new means. Repeated identical source-group rows
count once within each class. Content groups are NOT independent-speaker proof.

A candidate must have new-class accuracy higher than frozen AND each old class
must lose no more than .02 accuracy and increase Brier by no more than .02 on
calibration. Among survivors minimize macro old/new Brier; frozen remains the
fallback and wins ties by fixed order. These are EMPIRICAL calibration thresholds,
not confidence bounds or a production/NDU acceptance. They are not loosened after
observing the result. Public test data have already been inspected in earlier
studies; the following is descriptive retrospective evidence, not a fresh test.

The plan is written first, then five candidate checkpoints and the normalizer,
then calibration decision, then six paired sets of label-free predictions. Files
are create-only and failed runs stay failed. A separate process binds source and
all artifacts, reconstructs the FiLM/ensemble formula without model.forward,
checks old-only normalization and replay membership, and recomputes retention
before reporting held-out scores. The metric/selection primitives are shared
with the producer; only forward reconstruction is independently implemented.
A mutually fabricated source bundle still requires external execution evidence;
the reviewer does not authenticate hardware clocks or replay optimizer steps.

## First observed local result

Using the authenticated hosted f30abc25 BGE artifact (11779509140), not synthetic
vectors: frozen/new_only/distilled old held-out accuracy is 120/120, 109/120,
117/120; new accuracy is 0/120, 119/120, 119/120. Label replay gives 116/120 old,
119/120 new; all-old replay gives 117/120 old, 118/120 new. Two-teacher mean gives
119/120 old, 117/120 new. These are descriptive counts without a significance claim.

Calibration retained frozen. Distillation reduces measured forgetting but does
NOT meet the registered per-old-class retention thresholds. No consolidation is
promoted, and no later test result changes the calibration decision. All 2,406
calibration+test predictions reconstruct with zero observed error/argmax reversals.
There are 240 distinct held-out inputs, not 1,440 independent held-out samples.

217 explicit tests passed locally (197 existing + 20 new), using the complete
original qualification modules, not function extracts. New tests use explicitly
synthetic features; the run above uses real previously computed BGE features.
New exact-head/merge and physical CI outcomes must be read for the final SHA;
a passing parent is not evidence that the new source passed. Rust/global/native
owner CAS/WAL/final-use and independent future/multimodal quality remain separate.

## Reproduce and primary method references

```sh
PYTHONPATH=qualification/stem-cell-v1 python3 -m unittest -v cell_consolidation_checks
PYTHONPATH=qualification/stem-cell-v1 python3 qualification/stem-cell-v1/cell_consolidation_study.py \
  --source-run /verified/study --dataset /verified/inputs/dataset.jsonl --output /new/consolidation
PYTHONPATH=qualification/stem-cell-v1 python3 qualification/stem-cell-v1/cell_consolidation_study.py \
  --source-run /verified/study --dataset /verified/inputs/dataset.jsonl \
  --review-run /new/consolidation --output /new/scores.json
```

Hinton, Vinyals, Dean, *Distilling the Knowledge in a Neural Network* (2015),
https://arxiv.org/abs/1503.02531. PyTorch KL input/reduction contract:
https://docs.pytorch.org/docs/stable/generated/torch.nn.functional.kl_div.html.
The present protocol, retention thresholds and observations are repository
research design/results, not guarantees asserted by those references.
