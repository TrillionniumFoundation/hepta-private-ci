# ACT3 observed skill transitions and a negative advisory learning result

The engineering gate passes: the original TRAIN skill boundaries and UNKNOWN
handling are checked, and twenty models are actually fitted. The predictive
result is negative: both neural seeds are worse than both frozen baselines on
Brier and log loss. Fixed skills remain adopted and promotion is false.

## Exact execution and review stages

| Field | Original value |
| --- | --- |
| Loader and integrity controls | PR #6190, source `739342d869f0e5a21da7097379764c7d2a29e5bb` |
| Advisory learner and mathematical controls | PR #6195, source `20985f9b89bf72de1756bbc92246786614bd6908` |
| Exact-source qualification | PR #6196 |
| Tested code commit | `2c77000a6092f20eb28f7b65eef1940a33ac9b8b` |
| Tested complete tree | `2838a39764f31d191d91233acc2fcab6be47ab82` |
| Integrity/math tests | 14 planned, started and passed; zero skips/errors/failures |
| Qualified corpus fits | 20 retained initial/final model pairs, 200 updates each |
| Actual corpus optimizer updates | 4,000, all with changed parameter bytes |
| Gate wall time | 4.026531267 seconds |
| Probe campaign wall time | 2.860548181 seconds |
| Sum of fit wall / CPU time | 2.289778053 / 1.444386042 seconds |
| Before/after source identity | Same clean commit/tree and all Python/model hashes |
| Runtime | CPython 3.12.14, NumPy 2.3.5, Linux; full details in MANIFEST.json |

The evidence commit follows the tested code commit without changing code. Source,
tests, plan, labels, initial/final weights, update logs, predictions and checksums
are retained. Test controls include a separate thirty-update synthetic optimizer
exercise; it is not one of the twenty corpus fits or their four thousand updates.
Development test runs are also kept separate.

This is distinct from the prior 58-test joint-recovery record at c66ebe4. That
record's zero-new-fit statement describes its own run. Do not add the two test
counts and imply one common-source execution or new independent application tasks.

## Original ensure boundary and observation custody

Only the pinned ACT2 TRAIN archive is used: eighty original macro trajectories
contain ninety-six ensure decisions; eight trajectories have no ensure and stay
in the denominator. Each record binds the original task, goal, decision index,
initiation features, exact TRAIN line including LF, primitive events and later
actor readbacks. The complete ensure option is the existing optional stage then
apply. Its subsequent inspect is a separate policy action.

The original event stream does not directly log invocation IDs. The loader marks
the ID as derived from the pinned Destination.apply rule `task_id:index`.
Independent read-only custody checks separately verify all eighty original
database hashes and all ninety-six persisted operation IDs, payload hashes and
physical effect rows. That corroboration does not become a model feature or label.

Labels use the first available subsequent actor readback:

| Observation | Count |
| --- | ---: |
| Invocation goal observed satisfied | 80 |
| Invocation goal observed unsatisfied | 0 |
| Invocation outcome UNKNOWN | 16 |
| Whole task complete at subsequent readback | 56 |
| Whole task incomplete at subsequent readback | 24 |
| Whole-task label unavailable | 16 |

The invocation-goal target is degenerate among observed rows, so the advisor
forecasts whole-task completion at that later readback. At ensure entry the
existing complete input bit is always false; the target is not copied from an
already-complete feature.

Sixteen opaque cases lack actor readback. Independent physical custody shows
eight of those whole tasks actually completed, but all sixteen labels remain
null. Final oracle scores cannot fill online UNKNOWN. Tests poison terminal
complete/unknown/timing/database/oracle fields and retain identical extracted
labels. The public loader never reads RESULT, confirmation trajectories, models
or destination databases. The original frozen manifest includes confirmation
task definitions; that presence is explicitly disclosed.

The loader admits four independently pinned files: checksum catalog, manifest,
TRAIN gzip and original source ZIP. The source ZIP is absent from the original
checksum catalog and has its own immutable pin; its three source files are also
checked against the original manifest. No old artifact was changed.

Original at_ns records primitive call entry, not completion. The loader leaves
option_duration_ns null and only reports a clearly named call-start gap. This
record does not certify measured option termination or learned full-skill success.

## What was actually learned and compared

A small 10-to-8-to-1 tanh network predicts the later readback target using only
the ten original initiation features. It has no tool host, effect selector or
STOP authority. Adam, 200 updates, learning rate 0.025, L2 weight penalty 0.001 and
seeds 4101/4102 are fixed before qualified fitting. No seed or model is chosen
after viewing these results.

The descriptive split holds out one keys-length/fault configuration at a time,
keeping destination/schema/replicate copies and transitions from the same episode
together. There are nine participating groups, seven with observed evaluation
targets and two entirely censored groups. Eighteen fold fits plus two full-TRAIN
fits yield twenty actual fits. Their training inputs comprise eight distinct
ordered arrays but only six distinct supervised multisets; twenty fits are not
twenty independent datasets.

Every held group has exact entry features represented in other groups. The
ninety-six transitions contain only three distinct entry feature vectors, and
all groups form one connected component through feature overlap. Thus no
independent task-and-feature holdout exists here. Missing labels are also
condition-dependent. This descriptive reuse of known TRAIN cannot estimate
unconditional success or new-application generalization.

## Frozen comparison: neural forecasts are worse

Each row below scores the same eighty observed out-of-fold transitions; the
sixteen UNKNOWN predictions are retained but excluded from supervised scoring.
The two seed rows reuse those same observations. Lower Brier and log loss are
better; neither metric is operational task completion.

| Forecast | Correct / observed | Accuracy | Brier | Log loss |
| --- | ---: | ---: | ---: | ---: |
| Smoothed constant | 56 / 80 | 70% | 0.230915 | 0.661181 |
| Laplace exact-feature table | 32 / 80 | 40% | 0.333598 | 0.900554 |
| Neural seed 4101 | 32 / 80 | 40% | 0.375237 | 1.465871 |
| Neural seed 4102 | 32 / 80 | 40% | 0.375085 | 1.456665 |

Both baselines use only the remaining fold's observed training labels and the
same features. Their predictions and scores were independently frozen before
qualified fitting. The independently computed values match the retained results.
This forecast table must not be confused with the historical fixed workflow's
512/640 operational completion result: those are different tasks and outcomes.

The full-TRAIN fits genuinely learn: BCE falls from 0.688318 to 0.418598 for seed 4101
and from 0.702018 to 0.418640 for seed 4102. Those improvements do not overcome the
negative grouped forecast results. The original features alias multiple task
lengths/outcomes; adding optimizer updates or counting duplicate traces does not
add missing information. No learning advantage or operational adoption follows.

## Independent audits and retained artifacts

- INDEPENDENT_DATA_AUDIT.json checks source semantics, original row/DB custody,
  physical effect identities, labels, missingness and feature/group overlap.
- INDEPENDENT_BASELINES.json freezes no-fit baseline arithmetic and its original
  input witnesses before the qualified corpus campaign.
- INDEPENDENT_FIT_AUDIT.json checks the retained campaign without retraining:
  initial/final model tensors, actual update digest chains, directly recomputed
  neural probabilities, masks, metrics and source/data checksums.
- originals-and-source.tar.xz contains the complete frozen-run output, including
  all forty initial/final NPZ files, twenty optimizer logs, twenty fit reports,
  the full dataset, 192 seed-specific predictions, exact source and audit scripts.
- RESULT.json retains the wrapper result; PROBE_RESULT.json is the learner result;
  FROZEN_PLAN.json is the plan written before corpus fitting; TEST_PLAN.json lists
  every actually started/passed test identity.
- SHA256SUMS.json binds the original uncompressed output. FILES_SHA256.json binds
  the committed record. Archive contents are rechecked after packing.
- development-checks.tar.xz preserves the owning-formatter prepublication runs.

The retained-fit audit passes 1,174 checks with zero discrepancies. All 133 retained
file digests and 44 source Git blobs match. The 192 neural probabilities recomputed
directly from the saved tensors have exactly zero difference; 384 baseline values
also exactly match the independent pre-fit expectations. Twenty fitted model
artifacts contain 16 distinct final parameter snapshots; repeated data/fits are
not presented as distinct learned information.

On a clean checkout of the exact tested code with NumPy 2.3.5:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python scripts/act2_learning/qualify_skill_completion.py \
  --output /absolute/new-directory-outside-checkout
```

The output path must not exist. The runner rejects dirty or changed source,
missing/zero/duplicate/skipped/failed test plans, incomplete fitting, changed
dataset identity and any promotion or independent-task claim.

## Decision and remaining gates

DECISION.json records the negative comparison and promotion=false. The fixed
skill library stays retained; fresh original goal readback remains mandatory.
All new model artifacts are research forecasts with no STOP or effect authority.
No independent real task or confirmation episode was added.

The generic goal-checking host, full original Notes Root/AuthBus/FinalUse execution,
actual new boot/common rollback, grounded choice/composition of alternative
complete skills, and real new-application/version/fault same-host benefit remain
unqualified. A genuine next empirical stage needs the original authorized runtime,
actual application adapters, externally sourced frozen task roster and original
outcome/full-cost records. Historical ACT2/ACT3 efficacy findings remain unchanged.

CI_OBSERVATIONS.json retains current hosted states. The dedicated recurrent and
skill-advisory gates and native seed were queued when observed; v8-canary was
in progress. The completed local runs above are not claimed hosted passes.
