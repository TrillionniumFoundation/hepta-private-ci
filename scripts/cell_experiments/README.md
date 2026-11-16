# Cell experiments: engineering controls and research evidence

This package separates runnable experiment machinery from the evidence needed
to make a learning claim. Passing its CI job means the engineering integrity
tests passed. It does not qualify useful work, independent generalization,
native adoption, or production deployment.

## Package map

| Area | Implementation and guidance |
| --- | --- |
| Record admission and task verification | `data.py`, `data_builder.py`, [data contract](README_DATA.md) |
| Actual local causal-LM training | `coding_sft.py`; independently invoked LoRA training with model manifests and cost receipts |
| Frozen development campaign | `campaign.py`; explicit plans, controls, output interpretation, and original receipts |
| Multiple teachers, sparse composition, and source budgets | `composition.py`, numeric `composition_core.py`, [E3–E5 scope](README_COMPOSITION.md) |
| Selection and separate-process recovery experiment | `adoption.py`, [adoption evidence boundary](README_ADOPTION.md) |
| Bounded interaction and visited-state corrections | `interaction.py`, [interaction contract](README_INTERACTION.md) |

The current development scope uses newly authored maintenance tasks grounded in
fixed repository originals. Repository provenance does not turn those tasks
into historical user trajectories or independent confirmation data. Same-base
LoRA specialists can be real separately trained models, but they are not evidence
from outside AI services or proof of combining all foundation models' strengths.

The numeric composition experiment uses a frozen input representation and a
coarse output-domain classification target. Its one-hop logit mixtures do not
establish a growing native Neural Circuit or the necessity of Cell interactions.
The selection/recovery code owns an experiment journal; it does not integrate
the native CellOwner/agentd adoption path. FinalUse and settlement remain separate.

## Engineering integrity CI

The workflow `Cell experiments engineering integrity` runs on Python 3.12 with
an isolated virtual environment containing NumPy 2.3.5. It checks that the
`data`, `coding_sft`, `campaign`, `adoption`, `composition`, and `interaction`
test modules exist, then discovers every `test_*.py` in this package.
`test_sequence.py` is included automatically when present.

Run the same test discovery from the repository root:

```bash
PYTHONPATH=scripts python -m unittest discover \
  --start-directory scripts/cell_experiments \
  --top-level-directory scripts --pattern 'test_*.py' --verbose
```

The explicit top-level directory is necessary for package-relative imports.
The integrity suite uses authored fixtures, numerical LocalHeads, fake model
ports, and mocked child-process ports. It does not require torch, transformers,
PEFT, model weights, model-provider credentials, or network training. Installation
of the Python runtime and NumPy is an ordinary CI dependency setup operation;
the workflow sets model-library offline flags for the test step.

Real language-model training and fresh-process inference are separate,
explicitly invoked experiments. Their model bytes, frozen plans, actual outputs,
candidate-selection history, and cost receipts must be retained independently
of the unit-test logs.

## Qualification remains blocked

Engineering-mode observations preserve their missing evidence. They do not
clear independent-experiment, independent-confirmation, or production gates.
Repeated B/C evaluation is recorded as repeated access, not new confirmation.
Missing inputs, incomplete execution, and failed arithmetic remain distinct from
a completed keep-parent decision.

Before any stronger claim, the evidence must establish actual authorized source
identity, task/family isolation, temporal and external custody conditions,
appropriate controls, complete candidate accounting, and matched resource use.
Native adoption, external-teacher trajectories, distributed concurrency,
network scaling, and settlement are not established by this package's tests.

## Scope of the current development campaign

This is a development exercise requested by one operator. Its A panel has two
source-file groups; those are provenance groups, not two users. The tasks were
authored for this exercise from repository originals, not collected from real
production use. The number of independently authenticated users remains
`real_users_verified=0`. Neither the requesting operator nor copied teacher rows
may be counted as independently confirmed production-user evidence.

E3 is a same-base imitation experiment: numeric and Boolean specialists are
separately trained LoRA candidates on the same parent model. Their actual A
outputs provide class labels to student LocalHeads on one frozen input
representation. The target is `required_result_value_domain`: numeric-object
outputs, objects containing a Boolean, or invalid/out-of-domain outputs. This
is a domain classifier, not full-answer coding imitation or evidence from two
external foundation models. Empty actual output stays empty and belongs to the
invalid-output class; it must not be replaced or counted as a correct answer.

E4 compares one head, a fixed mixture, a random sparse mixture, and a learned
sparse mixture. An ablated edge is a **Cell-to-class-output contribution** in
this one-hop computation. Removing it is not a multi-hop Cell-to-Cell circuit
experiment. Cell removal, edge removal, routing changes, and their measured
cost differences must be reported together. The experiment does not qualify
graph necessity or emergent organization.

E5 requests 1, 4, 16, and 64 source groups under fixed-total and fixed-per-source
budgets. In run-v1, size 1 completed under both modes; 4, 16, and 64 each
remained `BLOCKED` because only two A source files were available. There is no size-2 arm in this
plan. These observations cannot form a user-growth, distributed-concurrency,
or scaling curve, and repeated sample exposure does not add sources.

## First development result and evidence locations

The frozen run-v1 campaign completed with seven actual LoRA training runs,
11 numerical candidates, all declared ablations, and two keep-parent decisions.
Independent scientific qualification remains BLOCKED. The
[result scorecard](../../qualification/cell-experiments-20261116/SCORECARD.md)
reports the actual success denominators and the limits of each experiment.

The repository artifact root is
`qualification/cell-experiments-20261116/results/`.
Execution logs use
`qualification/cell-experiments-20261116/execution-logs/`.

| Evidence | Original path relative to `results/` |
| --- | --- |
| Campaign identity and frozen training plans | `CAMPAIGN.json`, `parent.json`, `plans/`, `COMPOSITION_PLAN.json` |
| Actual model training; E1 original B outputs | `models/<arm>/manifest.json`, `models/<arm>/training.json`; `models/final_answer/B.json`, `models/trajectory/B.json` |
| Frozen input representation and teacher output provenance | `FEATURE_BINDING.json`, `FEATURES.json`, `TEACHER_REGISTRY.json`, `teachers/<teacher>.json` |
| E1 retrieval control and later C readout | `RETRIEVAL.json`, `E1_C_READOUT.json` |
| E2 collection, B selection, and later C readout | `E2/E2_PLAN.json`, `E2/collection/`, `E2/B/<arm>/RESULT.json`, `E2/FROZEN_SELECTION.json`, `E2/C_READOUT.json`, `E2/C/<arm>/` |
| E3–E5 overall record and frozen selections | `composition/RESULTS.json`, `composition/PLAN.json`, `composition/INPUTS.json`, `composition/FROZEN_SELECTIONS.json` |
| Each composition attempt and selected C/ablation record | `composition/<attempt>/STARTED.json`, `RESULT.json`, `PARAMETERS.json`, `C_EVALUATION.json` within that attempt directory |
| E6 selection and process recovery | `E6/<arm>/DECISION.json`, `C_RECEIPTS.json`, `COLD_REQUEST.json`, `COLD_PROCESS.json`, `RESULT.json` within that arm directory |

The execution-log root contains `EXECUTION_PLAN.json`, terminal
`RESULT.json`, and each stage's `STARTED.json`, `RESULT.json`, `stdout.txt`, and
`stderr.txt`. A nonzero process exit, missing terminal receipt, or incomplete
stage must remain visible rather than being converted into a successful score.

Selected originals are readable at these paths; the complete originals are
retained in the evidence archives. The public base weight is pinned by revision
and SHA256. Raw receipts, tokenizer/configuration, and all seven adapters and
optimizer states are archived; see the
[restore guide](../../qualification/cell-experiments-20261116/RESTORE.md).
Model manifests retain their original relative paths; reconstructing
a runnable artifact root requires the exact pinned base/tokenizer materials
and archived trained artifacts at those paths, with all byte hashes checked.
Repository JSON files alone are not a self-contained model or a successful
cold-recovery demonstration.

## Fields required for an honest readout

| Question | Fields to retain and inspect |
| --- | --- |
| What ran, and what stayed blocked? | Overall and per-attempt `status`, E3/E4/E5 statuses/reasons, stage exit codes, errors, and incomplete receipts. Process completion alone does not clear a scientific gate. |
| Are identities and independence conditions preserved? | `plan_digest`, `input_digest`, `feature_binding_digest`, `group_isolation`, `time_ordered`, `evidence_gaps`, model/receipt hashes, and every qualification flag. |
| Did actual parameters update? | Training parent/candidate digests, `updates`, `attempted_updates`, losses, `examples_by_source`, `mac_by_source`, model-training parameter-change fields, and original checkpoint manifests. A changed parameter hash is not evidence of useful generalization. |
| Were candidates selected only on B? | Every candidate's B predictions and loss, `candidate_ids`, `selection_round`, `rule`, `chosen_attempt_id`, `chosen_digest`, and `B_panel_digest` from the frozen selection record. Losing and failed candidates remain part of the accounting. |
| What happened on C? | Each task's `target`, `prediction`, `logits`, loss, accuracy, and cost; `C_evaluations`, `C_ablation_evaluations`, and `C_total_evaluations`. Repeated C access is not a fresh sample. |
| What does an E4 ablation establish? | The complete `ablation.cells` and `ablation.edges` matrices, unablated result, `semantics`, resource measurements, `matched_active_resources`, and `necessity_claim`. Report observed differences without promoting unequal-resource sensitivity to circuit necessity. |
| What work was charged? | Specialist `preparation`, `training`, and `total_training`; B/C inference cost; frozen-encoder cost and teacher training/inference references; partial MAC/FLOP scope, CPU/wall time, and unknown costs. |
| Is E5 actually a larger-source experiment? | `requested_sources`, `available_sources`, selected `sources`, both budget modes, per-source consumption, `real_users_verified`, and `distributed_concurrency`. Source files must never be renamed into users. |

The original feature row carries a measured encoding cost and `shared_identity`;
teacher copies reference that encoding. Count the encoding once, while retaining
each actual teacher inference and its training-cost reference. Do not add copied
feature costs as if the encoder ran again. `linear_flops` is a declared partial
matrix-arithmetic convention, not total platform cost, and unknown energy or
provider cost must remain unknown.

Keep the actual success denominator and task identities beside every score.
Coarse classifier accuracy must not be merged with full-task verifier success.
Retain `independent_experiment_status=BLOCKED`,
`independent_confirmation_qualified=false`, `graph_necessity_qualified=false`,
`production_eligible=false`, and `full_cost_known=false` wherever emitted. A
successful CI run never replaces an experiment receipt or establishes learning
benefit, native adoption, external-teacher evidence, FinalUse, or settlement.

Second development round: [repository contract experiments](README_V2.md).
