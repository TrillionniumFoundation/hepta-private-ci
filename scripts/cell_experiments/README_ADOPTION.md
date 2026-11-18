# E6: one candidate, explicit selection, new tasks and a new process

`adoption.execute(request, output_directory)` runs a research experiment. The
only model-loading entry point is the trusted repository module
`cell_experiments.coding_sft.load_predictor(manifest, artifact_root)`. It returns
an object with `model_digest`, `predict(record)` and `close()`. No task or model
manifest supplies a shell command, module name, executable or Python expression.

Run from the repository with its `scripts` directory on `PYTHONPATH`:

```sh
PYTHONPATH=scripts python -m cell_experiments.adoption --input request.json --output result-directory
PYTHONPATH=scripts python -m unittest cell_experiments.test_adoption
```

## Inputs

The request has `plan`, `parent`, `candidate`, `training`, `evaluation`,
`c_tasks`, and `artifact_root`. All digests use canonical JSON with sorted keys,
compact separators, UTF-8, `ensure_ascii=False` and no non-finite numbers.

**Model manifest:** `schema: hepta.experimental-model.v1`, `family`, `runtime`
(the fixed numeric/inference profile), `parent` (null for the initial version,
otherwise its complete manifest digest), and `files`. Each file has `role`,
`path` relative to `artifact_root`, `sha256`, and `bytes`. Base and tokenizer
roles are mandatory. Adapter/full-weight material has role `adapter`/`weights`.
Every file's actual bytes and size are checked, including inside the cold
process. The complete manifest digest identifies the version, not merely the
adapter filename. The loader must resolve these exact pinned materials.

**Plan:** `schema: hepta.e6.plan.v1`, `operation_id`, `frozen_at_ns`,
`training_owner`, `evaluation_owner`, `parent_model_digest`, `train_sources`,
`b_tasks`, and `c_tasks`. Each task declaration contains `task_id`, `source_id`
and `task_digest = data.record_digest(whole_record)`. A/B/C source groups and
B/C tasks must be disjoint. Optional `baseline_models` maps arm names to complete
model digests and must contain `parent`; by default only the parent is a
baseline. `minimum_gain` defaults to zero: candidate success must be strictly
greater than the strongest declared baseline plus this margin. Scoring averages
within source groups and then across groups. `cold_timeout_seconds` defaults to
120 and must not exceed 600.

**Training receipt:** `status: COMPLETE`, `owner`, `plan_digest`,
`started_at_ns`, `completed_at_ns`, `parent_model_digest`,
`candidate_model_digest`, positive `steps`, and Boolean `parameter_change`.
The parameter-change declaration must agree with the retained weight-artifact
digests. This checks the binding; it does not independently prove optimizer
execution or tensor semantics.

**B receipt:** `status: COMPLETE`, `owner`, `plan_digest`, `started_at_ns`,
`completed_at_ns`, and `rows`. There must be exactly one row per frozen B task
per candidate/baseline arm. Each row has `arm`, `task_id`, `source_id`,
`task_digest`, `loaded_model_digest`, Boolean `success`, and `output_digest`.
The evaluator's declared identity differs from the trainer, and the declared
timestamps must order freeze, training, then B. These checks do not authenticate
independent controllers or original execution. An upstream producer must retain
the actual forward/evaluation receipts and independently verify data rights,
source provenance, exposure and held-out assignment.

**C inputs:** the `c_tasks` request array contains the same metadata as the frozen
plan plus `record`. The whole record digest is checked. The selected model is
actually loaded and called, and `data.verify_answer(record, answer)` evaluates
each returned answer through a registered trusted verifier. A prediction includes
`answer`, `input_tokens`, `output_tokens`, `elapsed_seconds` and
`loaded_model_digest`. Token counts and elapsed time are recorded with their
original scope, without inventing energy or full physical cost measurements.

## Engineering scope versus independent E6

`plan.evidence_scope` defaults to `independent`. This coordinator does not own an
original-source/controller authentication mechanism, so independent mode returns
`BLOCKED` before selection or model use. Owner strings, distinct process IDs,
caller-supplied Boolean approvals and a directory named `confirmation` cannot
unlock it. An independently authenticated integration must be implemented and
qualified separately; this module does not invent that authority.

Development experiments must explicitly declare `evidence_scope: engineering`.
They can reach a mechanical `NO_UPDATE`/`ADOPTED` result, while
`independent_e6_status` stays `BLOCKED`. Results retain actual C record
`origin_kind`/`exposure`, the declared `time_ordered` value, and the missing
source, temporal, controller and prospective-C authentication gates. In
particular, `curated_development` / `exposure: development` remains development
evidence even when stored in the confirmation split. Upstream failures and
incomplete receipts remain failures/incomplete; no engineering completion
confers scientific learning qualification.

## Durable behavior and statuses

The SQLite journal commits the exact operation, evidence binding, decision and
selected complete model digest before C. Reusing the operation with different
evidence is refused. A completed operation returns its recorded result without
repeating C. An interrupted/failed selected operation remains selected and
requires explicit reconciliation; the runner does not silently repeat it.

Each output directory belongs to exactly one operation. A create-only admission
marker is made durable before creating the selection store. Recovery never
recreates a missing database, table or selected row. A marker without its original
store, or an occupied directory without a store, requires reconciliation. A
different operation cannot overwrite the original request, decision or result.
The request is detached from caller-owned objects before validation, and the
cold timeout is checked before any C execution.

Completed readback checks the original request, selection, decision, C receipts,
cold request, cold process output and final result. Missing originals remain
incomplete and changed originals fail; neither path dispatches another task.
Legacy completed directories without an admission marker remain readable only
when their original store and all required receipts agree. These are local
consistency checks, not a protected native owner or an external freshness anchor;
replacement of the entire directory and journal is outside this guarantee.

New completions bind the entire canonical cold-process object with
`cold_process_digest`, including stderr and any retained fields. A legacy result
without that digest can reconcile the return code, parsed stdout and recorded
wall time, but cannot establish the original stderr content. Canonical-object
binding does not authenticate the JSON file's whitespace or encoding choices.
No digest computed after a legacy run can retroactively supply that evidence.

The result has exactly one status:

| Status | Meaning |
|---|---|
| `BLOCKED` | Required input, material or declared independent source is absent. |
| `FAILED` | Invalid/tampered evidence or an observed execution failure. |
| `INCOMPLETE` | Partial upstream work, cold timeout, or a selected operation awaiting reconciliation. |
| `NO_UPDATE` | Complete B rejects the candidate, and the retained parent completes C and cold replay. |
| `ADOPTED` | Complete B admits the candidate, and that actual version completes C and cold replay. |

`model_decision` survives a later failure, so an adoption followed by a failed
cold process is `status: FAILED, model_decision: ADOPTED`, not a completed
adoption. Individual C answers can be wrong; completion means the execution and
evidence flow finished, not that the model's generalization was qualified.

Cold recovery starts a new OS process with the same fixed repository entry
point. It reopens the durable selection and rehashes/loads the selected model,
then repeats the last C inference input. The parent compares process identity,
model digest, answer and token counts. Elapsed time is retained but not compared
for equality. This tests loaded-version and deterministic-output continuity;
it is not an additional independent task, an agentd restart, or recurrent hidden
state recovery. Backend sampling must be fixed by the frozen runtime profile.

### Optional distinct D tasks after cold recovery

Freeze `plan.d_tasks` and matching request `d_tasks` together, with the same
metadata/record format as C. D contains 1–64 confirmation records; declared
sources must be disjoint from A/B/C, and task IDs/digests cannot repeat B/C or
another D task. Record hashes, splits and the complete panel are checked before
any C execution. These checks bind declared data; they do not authenticate
independent origins or prove that a development record was previously unseen.

The cold process reserves a create-only `COLD_ADMISSION.json` before model load.
It replays the last C input and checks the original prediction before running D
on the same selected model. Each completed D is retained in `D_RECEIPTS.json`.
An interrupted attempt cannot automatically repeat D, including by calling the
recovery entry point again. Missing D originals prevent successful readback.

`fresh_D_status: COMPLETE_ENGINEERING` means this distinct frozen panel executed
after cold replay. The independent E6 and native-owner gates remain blocked.
`execution_costs` separates hot C, cold C replay and cold D calls/tokens/reported
prediction time. Cold process wall time overlaps its inference time and must not
be added to it. Training/B costs and energy remain unknown; `costs_complete`
stays false. Omitting D preserves the original replay-only experiment behavior.

Each hot C, cold replay and D inference now retains a dispatch intent before the
call and its measurements immediately after return, before answer verification.
`C_INFERENCE.json`, `COLD_REPLAY_INFERENCE.json` and `D_INFERENCE.json` preserve
these observations even when verification fails or the cold child exits during D.
`inference_attempts` and `execution_costs` are retained for failed/incomplete
selected operations as well as completed ones. A failed or lost return leaves
phase totals null; `observed_complete_prediction_costs` gives only the measured
subtotal. An intent alone does not prove that the model began execution. Missing
streams remain unknown, and successful readback checks the original streams.

## Explicit qualification boundary

The experiment journal is not the existing CellOwner/agentd authority or a
HEPLCP checkpoint. This module does not weaken an existing owner's admission
checks, manufacture a native receipt, or authorize on-chain settlement. Every
result keeps `ordinary_daemon_qualification`, `independent_control_authenticated`,
`hepta_final_use_accepted`, `settlement_verified`, and `production_activation`
false, with `authority: DENY_ALL` and `qualification: HOLD_NO_GO`.
`native_learning_join_status` remains `MISSING_ORIGINAL_NATIVE_MATERIALS`.
Original native HEPLCP02/03 or HEPLCP04 materials require the corresponding
existing Chain readers; JSON from this experiment cannot substitute for them.

Tests use explicitly authored fixtures and model ports. Process recovery controls
include actual spawned OS processes, concurrent contenders and an abrupt exit;
the model predictions in those controls remain fixtures. They check status
separation, immutable selection, cold evidence consistency and refusal behavior.
They are not model-training or independent-user evidence.
