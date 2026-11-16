# E1/E2 experiment data contract

`data.py` accepts JSONL `hepta.cell-experiments.record.v1`. It does not modify the
older `cell_repo_mdv` development contract. A new schema is not new evidence.
Authored examples retain `origin_kind=curated_development`,
`exposure=development`, and `teacher_id=null`. Unit-test fixtures are not a dataset.

## Required fields

| Field | Meaning |
| --- | --- |
| `record_id`, `task_id` | Record and real task identity; variants share task identity. |
| `lineage_id`, `family_id` | Related source lineage and semantic/template duplicate family. Seeds, parameter changes and renamed IDs do not create new families. |
| `project_id`, `source_id` | Project and source evidence group; do not split a source group to evade overlap. |
| `source` | `repository`, fixed Git `revision` for repository history, `path`, exact source-byte `sha256`. |
| `observed_at`, `available_at` | Nonnegative integer Unix seconds; availability cannot precede observation. Do not backdate curated examples. |
| `split` | `train`, `selection`, or `confirmation`. This is intended usage, not an independence certificate. |
| `origin_kind`, `exposure` | `real_repository_history`, `authorized_agent_run`, or `curated_development`; exposure is `development`, `previously_exposed`, or `unexposed`. |
| `authorization` | Explicit `training_allowed`, `evaluation_allowed`, `rights_basis`, `scope`. These are declarations whose original authorization must be retained. |
| `task` | Exact `input` string and `verifier: {name, version, parameters}`. Evaluator parameters and final answers must not enter model input. |
| `final_answer` | Recorded target artifact, never a substitute for a new student output. |
| `teacher_id` | Null unless actual teacher identity is available. Non-null also requires `model_digest` and `teacher_output_receipt_sha256`. |
| `trajectory` | Ordered `{index, actor, kind, content, executed, receipt_sha256}` events. Actors are teacher/student/environment/curator; kinds observation/action/correction. |
| `verified_outcome` | `success`, actual `receipt_sha256`, `verifier_name`, `verifier_version`. A recorded success does not score a later student. |

Executed student actions additionally require `policy_sha256` and
`receipt_actor=student`. Teacher events require original output receipts; authored
examples use `curator` with `executed=false`. These structural checks cannot
authenticate a dishonest receipt: the runner must retain and validate the original
action, process, model and observation evidence. No hidden chain of thought is
required: the trace consists of authorized visible actions and observations.

Optional `features` binds finite frozen feature values with `binding`,
`available_at`, and `preaction_at`; post-action features are rejected. Optional
`target` must be within `n_classes`. `target_name`, `model_digest`, and
`upstream_cost` can carry the corresponding declared manifests and measured costs.

## Separation and SFT

`validate_records(records)` rejects duplicate IDs and cross-split task, lineage,
family, source identity, source-byte or exact-input overlap. It reports project
overlap and chronological separation. It does not discover every semantic clone.
`assign_splits(..., train_before=..., selection_before=...)` uses explicit time
cutoffs and rejects groups crossing them; it never rewrites the originals.

`independent=True` additionally requires all three splits, disjoint projects,
strict time order, real and unexposed confirmation sources, and a `custody` record
with `receipt_sha256`, `frozen_at` before observation and
`exposed_to_training=false`. Passing checks declarations only: provenance remains
unauthenticated and production eligibility remains false. Independent custody,
original source retrieval and the freeze must be checked by a separate evaluator.

`build_sft_examples(records, mode="final_answer"|"trajectory")` only accepts
authorized successful training records. It preserves exact task input and returns
untruncated `segments`; observations have `train=false`, actions/corrections and
the final artifact have `train=true`. `target_text` is a readable concatenation,
not the masking contract. The trainer must use segments for labels and record
actual supervised/context tokens, updates, calls and runtime. Equal step counts
alone do not match the E1 training budget. Frozen arms have zero updates.

## Semantic evaluation

`register_verifier(name, version, callback)` registers trusted local Python code;
callback receives `(parameters, actual_answer)` and returns a dictionary containing
boolean `success`. Dataset records cannot supply shell commands or imported code.
`verify_answer(record, answer)` hashes exact input/output bytes, verifier parameters
and its source module, returning a content-addressed receipt. It permits a draft
without `verified_outcome` so the first real result can populate that field.

The fixed `json_artifact`, version `1`, adapter compares parsed JSON structure with
`parameters.expected`, rejects duplicate keys and nonfinite numbers, and never
executes model code. It is suitable for bounded JSON artifact/configuration tasks;
it does not claim general coding ability or real provenance. Repository repair
tasks require a separately registered semantic verifier with pinned source/tests,
and original execution receipts. Mere successful parsing/compilation is insufficient.

`record_digest(record)` is SHA256 of canonical UTF-8 JSON (`sort_keys=true`, compact
separators, `ensure_ascii=false`, nonfinite rejected). Input and answer hashes in
semantic receipts hash the raw UTF-8 string bytes. Persist the complete receipt,
not only its hash. E2 shadow outputs and controlled student executions must remain
separate; no teacher replay is counted as a student tool call or task success.

## Repository artifact development corpus

`data_builder.py` is a separate reviewed stage. It verifies both SHA256 and Git
blob identities in a fixed-ref `source-cache/retrieval.json`, then builds fourteen
new maintenance-summary tasks: seven training, four selection and three later
development probes. The source files come from the joint Cell/HIA run, the stem
study artifact index, and the Chain model-family contract. Entire source and
experiment lineages stay in one split; semantic families do not cross splits.
The two Hepta splits share a project and all new tasks are observed at their real
creation time. Therefore project/time independence is explicitly absent.

The `confirmation` filename indicates where a later probe is consumed; its records
remain `exposure=development`. This corpus has zero independent confirmation
sources, zero external teachers and zero original user agent trajectories. It
tests actual LLM parameter updates, generated JSON and semantic artifact handling;
it does not establish autonomous coding or online user learning.

Run from the repository root, with a new output directory:

```sh
PYTHONPATH=scripts python3 -B -m cell_experiments.data_builder \
  --source-cache qualification/cell-experiments-20261116/source-cache \
  --output qualification/cell-experiments-20261116/development-data
```

`oracle_answer(record)` derives its result from the exact model-visible input.
It never reads the verifier's expected answer. The full rule baseline and its
receipts remain in the comparison even when it saturates the tasks. That outcome
is a reason to withhold benefit/adoption claims, not to weaken the threshold.
