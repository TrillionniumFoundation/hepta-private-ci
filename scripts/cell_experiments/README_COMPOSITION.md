# E3–E5: bounded Cell composition research

`composition.py` trains real float64 `hepta_cells.semantic.LocalHead` parameters
and, for the learned graph, a sparse router. It consumes supplied observations
and frozen input features. It does not manufacture task outcomes, teachers,
users, independent sources, or evidence of useful work.

The experiment is a **one-hop mixture of class logits** on one frozen
representation. It is not the native Rust Circuit, a distributed training
runtime, a general coding agent, or a foundation model. No ordinary daemon
adoption, HEPLCP FinalUse, settlement, or network transmission is performed.
All reports retain `production_eligible=false`,
`independent_experiment_status=BLOCKED`,
`independent_confirmation_qualified=false`, and
`graph_necessity_qualified=false`.

## Input and admission

Start with records admitted by `cell_experiments.data` and independently inspect
their source/verifier receipts. This module adds numeric and composition checks;
it does not replace that provenance, authorization, or task-verifier workflow.
Each row requires:

| Field | Meaning |
| --- | --- |
| `task_id`, `lineage_id`, `family_id`, `source_id`, `project_id` | Actual task, related lineage, duplicate family, source, and project identities. A new seed, filename, or copy does not create a source. `lineage_id` defaults to `task_id` only for already isolated tasks. |
| `split` | `A`/`B`/`C` or `train`/`selection`/`confirmation`. All three panels must exist. |
| `observed_at`, `available_at` | Observation and outcome availability timestamps. `timestamp` can substitute for `observed_at`. Finite Unix seconds or timezone-bearing ISO timestamps are accepted. |
| `features` | `{ "values": [finite numbers], "binding": "sha256", "available_at": time, "preaction_at": time }`. Feature availability must not exceed the recorded preaction time. |
| `target` | Integer class from the explicitly named manifest in the plan. Optional `n_classes` and `target_name` must agree with the plan. |
| `task.input` | Original observation whose canonical hash identifies duplicate input. An admitted `observation_digest` can supply that identity. |
| `verified_outcome` | Actual verifier outcome with Boolean `success` and nonzero `receipt_sha256`. Receipt integrity and target semantics are checked upstream. |
| `upstream_cost` | Original encoder/agent/tool/teacher cost evidence, when available. Missing evidence stays `null`; it is not assigned zero. |

A flat feature list is accepted only with `feature_binding_digest`. Prefer the
structured form because it carries feature timing. The binding must identify
the actual frozen model/encoder, pooling, dimensions, and numeric profile. The
encoder must receive only the preaction input, never `final_answer`, a verifier's
expected answer, future observations, or C-derived statistics. A hash identifies
an artifact; it does not prove that an arbitrary encoder obeyed this rule.

Source, family, task, and lineage overlap across panels is rejected in every
mode. The same observation cannot be renamed into another source or split.
Repeated observations for different evidenced teachers are permitted inside one
panel; E4/E5 deduplicate them and require matching features, targets, and family.
These checks do not solve semantic near-duplicate detection or authenticate IDs.

The default `evidence_scope="independent"` blocks admission when timestamps,
project separation, C exposure/origin, or C custody declarations are missing.
Explicit `evidence_scope="engineering"` permits the numerical development
exercise despite those independence gaps. It records the actual
`time_ordered`, group isolation, and `evidence_gaps`; it does not permit group
leakage or confer independent-experiment qualification. This process can read
the supplied C file before training for validation, so it does not enforce
external sealed-holdout custody.

One limited development target is `required_result_value_domain`: a JSON object
whose values are all numeric has label 0; an object containing at least one
Boolean has label 1; a model output outside those two forms has label 2.
Boolean values must be distinguished from Python integers. Gold labels come
from separately verified task answers, features only from the task input, and
teacher labels only from actual teacher outputs. This measures coarse output
domain routing. It does not measure answer content, code execution, tool use,
or general agent competence, even if the routing accuracy is perfect.

## Frozen plan and invocation

Write the plan before running candidates. A small engineering plan is:

```json
{
  "schema": "hepta.composition-plan.v1",
  "evidence_scope": "engineering",
  "target_name": "required_result_value_domain",
  "classes": 3,
  "cells": 4,
  "active": 2,
  "seeds": [3, 7],
  "learning_rate": 0.05,
  "passes": 12,
  "max_examples": 128,
  "max_train_mac": 200000
}
```

```bash
PYTHONPATH=scripts python -m cell_experiments.composition \
  records_with_frozen_features.json composition_plan.json NEW_OUTPUT_DIRECTORY \
  --feature-binding ACTUAL_FEATURE_BINDING_SHA256
```

The output directory must not already exist. Optional `--teacher-registry`
points to the E3 registry described below. The CLI exits 0 only for
`completed_research_only`; that status means at least one numerical candidate
was evaluated, not that every experiment passed or any scientific claim was
established. Examine E3, every E5 size, every attempt, and the evidence flags.
The callable equivalent is
`run(records, plan, output_dir, feature_binding_digest, teacher_evidence=None)`.

Class count is bounded to 2–128, features to 1–1024 dimensions, seeds to 1–8,
and graph size to 2–16 Cells. The predeclared ablation matrix also requires
`cells * (classes + 1) <= 256`. Learned routing requires at least two active
Cells: a top-1 softmax has no useful within-route gradient in this implementation.

## E3: multiple teacher comparisons

Without at least two distinct hash-bound teacher model identities and original
output receipts, E3 records `BLOCKED`. Seeds and renamed checkpoints are not
teachers. Allowed producer kinds are `external_model` and
`same_base_domain_specialist`; the latter also requires the base-model digest,
training-receipt digest, and original training-source IDs. Those training receipt
and origin attestations must be verified upstream; the module does not train an
external teacher or authenticate a provider.

A registry maps each teacher ID to `receipt_path`, `receipt_sha256`, and
`model_digest`. The referenced regular file is read and checked against its
byte hash. Its JSON contains matching `teacher_id`, `model_digest`, `kind`, and
`outputs`, where each task ID maps to `{ "output": "actual text",
"teacher_target": class_integer }`. Every associated record must carry the
same model digest, literal `actual_output` (or `final_answer`), and
`teacher_target`. Changing a receipt or copying one model under two names is
rejected. These hashes bind producer claims; they are not cryptographic proof
that an external provider actually ran the claimed model. Test fixtures have
explicitly mock receipts and never establish two real teachers.

The predeclared comparisons are one student per teacher, pooled imitation,
domain-routed imitation, and composed student specialists. Domain routing chooses
the teacher with the highest verified class accuracy within each A family,
using only A. Each specialist first trains its own LocalHead against one
teacher's actual class outputs; those heads are then frozen while the sparse
router trains against the verified class target. Preparation and router costs
both count against the same candidate cap and appear in `total_training`.

This is offline hard-label imitation. It neither accesses hidden reasoning or
logits nor performs MOPD, on-policy distillation, RL, or parameter fusion. A
teacher's trajectories are not the student's on-policy observations. No result
here can show that a student combines every teacher's strengths.

## E4: graph controls and complete declared ablations

The four arms share the declared seed list and training caps:

| Arm | Computation |
| --- | --- |
| `single` | One trainable linear LocalHead. |
| `fixed` | Uniform mixture of the first `active` Heads in a fixed graph. |
| `random_sparse` | Uniform mixture over a seed-fixed random subset of Heads. |
| `learned_sparse` | Trainable linear router, top-k selection, selected-route softmax, and trainable Heads. |

All parameter changes are actual cross-entropy SGD through the existing
LocalHead API. The router differentiates through selected mixture weights;
top-k membership is piecewise discrete. It has no load-balancing objective,
multi-hop messages, latent compatibility learning, or topology growth.

For every selected multi-Cell E4 model, C is evaluated once with each Cell
removed and once with each declared Cell/class output edge zeroed. Learned
Cell removal reroutes to remaining heads; fixed/random removal drops the
selected head and renormalizes surviving weights. Edge removal zeros one
Cell's contribution to one class after its head was computed. No ablated model
is retrained. The complete matrix includes inactive edges/Cells, whose removal
can correctly have no effect. These are sensitivity observations with unequal
active resources, so `necessity_claim=false` remains explicit.

## E5: source-count and budget controls

The requested sizes are 1, 4, 16, and 64 observed A sources. The lexicographically
ordered source roster is frozen before candidate evaluation; no source is
chosen using B/C performance. A shortage produces a separate `BLOCKED` record
for that size. Copied examples do not create additional sources or users.

`fixed_total` retains the same total example and matrix-MAC caps at every size.
`fixed_per_source` multiplies the total caps by the admitted size and also
enforces each source's individual cap. Scheduling is deterministic round-robin
over source queues, with repeated passes charged as repeated observations.
Both modes report actual use, which can be below the cap. They run a local
single-head source-replay diagnostic; they do not emulate distributed workers,
network delays, concurrency, or user growth. `real_users_verified=0` and
`distributed_concurrency=false` are deliberate.

## Accounting, selection, and recovery artifacts

Training records include attempted/completed updates, losses, examples and MACs
per source, parameter digests, process CPU time, and wall time. Reported
`linear_mac` covers actual head/router projections and their parameter-gradient
matrix products; `linear_flops=2*linear_mac` is that explicitly partial convention.
Mixing, router sensitivity, softmax, bias arithmetic, comparisons, encoding,
tools, I/O, and provider work are outside it. Energy is unknown. Training caps
are equal, but actual FLOPs, parameters, examples, elapsed time, upstream cost,
and all candidate-selection cost are not declared equal.

Evaluation reports resident parameters, unique active parameters for the panel,
and repeated `active_parameter_uses`. `messages` and `message_bytes` describe
logical local Cell output vectors, with float64 bytes and zeroed output edges
excluded from the logical payload. They are not measured network traffic;
`network_messages=0`. Separate phase cost records should be retained instead of
advertising a partial MAC count as total useful-work cost. Every missing
upstream cost remains visible, and `full_cost_known=false` is never cleared.

`PLAN.json` and `INPUTS.json` are frozen before training. Each attempt saves
`STARTED.json`, `RESULT.json`, and exact `PARAMETERS.json`; failed or budget-blocked
attempts remain in the journal. `total_training` includes specialist preparation
when present. Actual B logits, predictions, loss, and costs are recorded for
every completed candidate. Within each experiment/arm, minimum B loss selects
the seed, with lexicographic attempt-ID tie breaking. Every candidate ID and
selection round is retained, including losing candidates.

`FROZEN_SELECTIONS.json` is written before any C model evaluation. Only its
chosen parameter digests receive C evaluation and the predeclared ablations.
There is no C-based model reselection, graph search, or best-arm declaration.
`C_evaluations`, `C_ablation_evaluations`, and `C_total_evaluations` disclose all
these panel reuses; none is a new independent confirmation sample.

`SparseCircuit.restore(parameter_record, expected_digest)` checks the complete
record hash, shape, and graph before reconstructing prediction state. This
allows a separately designed recovery experiment to consume exact parameters;
it does not itself establish fresh-process adoption. Missing data, invalid
evidence, exhausted budgets, and failed arithmetic produce explicit blocked or
failed statuses. A failed update is never relabeled as a valid `NoUpdate`.

Run the numerical and behavioral checks with:

```bash
PYTHONPATH=scripts python -m unittest cell_experiments.test_composition -v
```

These tests cover finite-difference gradients, real loss reduction, budget
enforcement, duplicate/group/time admission, receipt pins, both specialist cost
stages, exact reconstruction, ablation effects, and C-label independence from
B selection. Authored test tasks and mock teacher receipts are software tests,
not the experiment's observed evidence.
