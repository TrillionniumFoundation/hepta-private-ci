# Execution06 root archive barrier glue

`root_barrier_ops.py` is an external Linux engineering tool. It leaves the registered execution06 source, scientific arguments, resource gates and supervisor unchanged. Its CLI uses fixed production paths and literal source/helper pins. It imports no model or scientific runner. Root owns each invocation and every actual Library `create_folder` / `prepare_materialize` call.

The three phases are **upload → root materialization → readback/candidate → root review → explicit publish**. Each phase is reserved once. A failed or interrupted phase must be reconciled from actual receipts; the tool never resumes it or retries a remote helper. Starting a phase with an existing work/phase/step path is an error even when an earlier command appeared to succeed.

## 1. Read the current actual barrier

```bash
/workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python -B \
  /workspace/scratch/178ced6a501f/execution06_recovery_20261030/root_barrier_ops.py --status
```

This call is strictly read-only: it creates no OPS or receipt directory. It reports the actual STATUS descriptor and current `awaiting_stage`, exact REQUEST descriptor, phase receipts, any ACK/ACK_VERIFIED descriptors and the required upload stdout path. If the pipeline is not initialized, it says `ops_exists: false`. It never synthesizes operational progress or a successful ACK.

Use the returned actual stage, such as `02_A-29`; do not infer a stage from elapsed time or a prior episode. The supported 17 stages are the frozen order from `01_A-17` through `17_final_closure`.

Root calls actual Library `create_folder` for that stage and saves the **complete actual ToolResponse** as a local JSON file. Save the exact three-field current REQUEST descriptor as a second JSON file. Root retains the returned directory ID; the glue checks it against the full create_folder response and the stage basename. No directory ID is inferred from another execution.

## 2. Upload phase: one ordered whole batch

The following example contains placeholders which root replaces with actual saved inputs and actual returned identity. The required upload stdout path for a chosen stage is fixed, not a guessed output filename.

```bash
/workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python -B \
  /workspace/scratch/178ced6a501f/execution06_recovery_20261030/root_barrier_ops.py upload \
  --stage 02_A-29 \
  --request-descriptor /ABSOLUTE/ACTUAL_REQUEST_DESCRIPTOR.json \
  --folder-response /ABSOLUTE/COMPLETE_CREATE_FOLDER_TOOLRESPONSE.json \
  --directory-id ACTUAL_RETURNED_DIRECTORY_ID \
  --upload-stdout /workspace/scratch/178ced6a501f/fullstudy_execution06_ops/root_archive_io/_engineering/02_A-29_upload/helper.stdout.log
```

Both input files must be canonical regular metadata beneath `/workspace/scratch/178ced6a501f`. The tool preserves exact copies with original and saved descriptors, then does these measured operations:

1. Frozen `archive_io.py prepare-upload` through original execution04 `external_step.py`.
2. One official `library_upload.py` process with the entire ordered `UPLOAD_REQUEST.json` on stdin. It does not separately call prepare/finalize upload APIs, split the batch, reorder items, or retry.
3. Per-item inspection of actual upload stdout: exact local path/order, successful status, local metadata applied, unique actual Library IDs and valid version (including zero).
4. Frozen `prepare-readback`, always with `--upload-stdout` equal to the actual upload WAIT4 stdout descriptor path.

`STAGE_WORK` must not exist before prepare-upload. This is why its measurement directory and saved inputs are outside it, beneath `_engineering`.

Successful output includes the full path/descriptor and JSON value of `STAGE_WORK/MATERIALIZE_ARGS.json`. Root now calls actual Library `prepare_materialize` with exactly that value, once, and saves the **complete actual ToolResponse**. Do not reconstruct it from a shortened text view or discard warnings, unavailable entries, bindings, or transfer fields. The saved response can contain signed transfer URLs; keep it as private operational evidence and do not paste its full contents into chat.

## 3. Readback phase: exact planned helpers, then candidate only

```bash
/workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python -B \
  /workspace/scratch/178ced6a501f/execution06_recovery_20261030/root_barrier_ops.py readback \
  --stage 02_A-29 \
  --materialize-response /ABSOLUTE/COMPLETE_MATERIALIZE_TOOLRESPONSE.json
```

This phase preserves the complete response, rejects error/warning/unavailable/partial results, and measures frozen `prepare-transfers`. It checks the full ordered READBACK_PLAN and all destination/identity/version/metadata bindings before the first transfer. Each saved `external_step_argv` is then executed **exactly once**, without shell interpretation or a second measurement wrapper.

The frozen READBACK_PLAN puts transfer receipts at `STAGE_WORK/readback_steps/NNN/WAIT4.json`. Those locations are intentionally retained. All newly composed metadata and uploader measurement directories are instead `_engineering/{stage}_{step}`. Do not rewrite the frozen argv to move its receipts, and do not wrap each plan command in another external_step; that would change provenance and invite duplicate cost accounting.

Official transfer stdout is a **plain-text absolute output path**, not JSON. Both materialize and apply-xattrs plans are supported. The glue validates the exact returned path and original WAIT4 before proceeding.

Finally, frozen `archive_io.py ack` runs **without `--publish-ack`**. It rechecks actual readback bytes, distinct inode, Library identity xattrs, full receipts and the original archive verifier, then writes `ACK_CANDIDATE.json` and `ACK_CANDIDATE_VERIFIED.json`. The phase returns their descriptors. It creates no actual supervisor ACK.

## 4. Review and explicitly publish

Root reviews the candidate and frozen verification. Only after that review, supply the exact candidate SHA256 returned by the readback phase:

```bash
/workspace/scratch/178ced6a501f/runtime_recovery_20261030/venv/bin/python -B \
  /workspace/scratch/178ced6a501f/execution06_recovery_20261030/root_barrier_ops.py publish \
  --stage 02_A-29 \
  --expected-candidate-sha256 ACTUAL_REVIEWED_64_HEX_SHA256 \
  --publish-ack
```

This measures the frozen explicit publication command. The candidate SHA must match the prior readback phase, all current bindings must still hold, and the frozen publisher rechecks the original supervisor/PID namespace before exclusive ACK creation. The glue additionally retains the full original supervisor parent identity and absolute 12-hour deadline in its read-only phase checks.

A publication success means that the actual ACK file was written with the reviewed bytes. **Root must separately observe the supervisor's actual `OPS/durable/STAGE/ACK_VERIFIED.json` and its accepted progression.** The glue neither waits for nor claims that acceptance. The supervisor can advance before the publish helper returns, so the glue does not require the old awaiting state after a successful publication.

## Evidence and stop conditions

For each phase, `_engineering/{stage}_{phase}_phase/` contains an exclusive INTENT, exact saved inputs, one ATTEMPT per helper, captured wrapper stdout/stderr, and a DONE or FAILED record. Each actual helper's original INTENT, START, EXIT, stdout/stderr and WAIT4 remain in its measurement directory. The phase journal is engineering evidence; it is not supervisor STATUS and does not add a scientific result.

On nonzero exit, partial/unknown upload, missing WAIT4, a mismatched full response, altered source pin, changed supervisor identity, expired deadline, existing directory, or unexpected output, stop. Preserve all files. An actual remote write or local ACK may have happened before an interrupted process was able to record its result; inspect the original receipts and current supervisor before deciding any next action. Reinvoking the same phase is not a recovery procedure.

All measurements are engineering-only. Their child cost ledgers can include nested child cost; do not add a measured parent and its included descendants twice. The glue does not manufacture cost, synthesize missing WAIT4, delete readbacks, change cache/resource settings, or restart science.

## Local verification scope

The first focused run passed 21/21 tests under a real original execution04 external_step. The tests use explicitly marked synthetic metadata/service/ACK fixtures beneath `root_barrier_ops_tests01/cases`; those fixtures are not remote durability evidence. They exercise the frozen metadata helper code in-process with fixture-only path rebinding. In the candidate/publication fixtures, the aggregate archive verifier is replaced by an explicitly marked synthetic result; these tests do not establish an actual remote archive verification. A separate real print-only subprocess verifies actual external_step WAIT4 and plain-text stdout handling. No production upload, materialization, publication or scientific launch was performed by the test run.

The actual suite measurement is `root_barrier_ops_tests01/measurement/WAIT4.json`. The formal source/hash and validation inventory is `ROOT_BARRIER_OPS_VALIDATION.json`. The external tool's source is intentionally outside the finalized execution06 Git source; its descriptor and all fixed dependency descriptors are bound into every actual phase journal.
