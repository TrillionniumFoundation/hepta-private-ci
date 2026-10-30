# Execution05 admission and root ACK runbook

This is an independently checked operating sequence, not an execution receipt. The review read current source and current official Library API/skill contracts. It did not initialize production RAW/OPS, start a supervisor, create a service folder, upload, materialize or publish an ACK. Actual private folder paths and IDs remain in the private handoff and are intentionally absent here.

## 1. Use the actual initialization result

The current initializer writes:

- `OPS/registrations/initial/PIPELINE_CONFIG.json`
- `OPS/registrations/initial/INITIALIZATION.json`, whose `pipeline_config` is the exact path/bytes/SHA descriptor
- the materialized A17 receipt under RAW/imports/execution04/A-17, producer map/config, current profile, both OPS freezes, initial four-job canonical queue and postseal plan

Here OPS is `/workspace/scratch/178ced6a501f/fullstudy_execution05_ops`, RAW is its registered `fullstudy_execution05_durable_raw` sibling, and SOURCE is `fullstudy_recovery05_git` under the same base. The initialized CAS is empty. No worker starts during initialization.

Read the exact pipeline descriptor from the actual initialization output or INITIALIZATION.json. Both entry points use that same descriptor SHA. Preparation mode means **omit `--execute`**; neither script accepts a `--prepare` flag.

```python
# Root may run this after successful real initialization; it is not run by this document.
import json, os, subprocess
from pathlib import Path
base = Path('/workspace/scratch/178ced6a501f')
source = base / 'fullstudy_recovery05_git'
ops = base / 'fullstudy_execution05_ops'
venv = base / 'runtime_recovery_20261030/venv/bin/python'
config = json.loads((ops / 'registrations/initial/INITIALIZATION.json').read_text())['pipeline_config']
common = ['--config', config['path'], '--expected-config-sha256', config['sha256']]
for name in ('supervisor.py', 'wait4_launcher.py'):
    subprocess.run([str(venv), '-B', str(source / 'operational/parameter_field_recovery05' / name), *common],
                   cwd=ops / 'empty_cwd', env={**os.environ, 'PYTHONPATH': str(source), 'PYTHONDONTWRITEBYTECODE': '1'}, check=True)
```

Expected statuses are `CONFIG_AND_COMMITTED_ADAPTER_BYTES_VERIFIED_ONLY` and `MEASURED_LAUNCH_PREPARED_ONLY`, with zero workers. The supervisor preparation validates source/config/producer/import bindings. Actual execute additionally enforces the exact import-only RAW tree, empty CAS, fresh work directories and original admission gate.

The only intended real launch entry is the **measured launcher** with the same arguments plus `--execute`. Root detaches/owns that measuring parent as required by the execution environment. Do not launch supervisor separately and then try to attach accounting. After launch, immutable `OPS/supervisor_run/START_POLICY.json` supplies the single actual deadline and OOM baseline to every wrapper.

## 2. First A17 handoff

Wait for actual `OPS/STATUS.json` phase `await_durable_ack_A-17`. Its exact `awaiting_durable.request` must point to `OPS/durable/01_A-17/REQUEST.json` and its ack_path to that same stage's ACK.json. Preserve that complete three-field request descriptor in a private root input file outside the stage work directory.

A17 has been inherited, not rerun. Its new controller IMPORT/RESULT and old completion bytes must be the archive input. The existing episode folder or previously saved recovery metadata is not a stage ACK. A29 cannot activate until this new request has a genuine upload, independent readback, frozen verification and new supervisor-accepted ACK.

Use a new service subfolder for this actual stage under the already resolved episode folder. Current Library folder creation input is:

```json
{"operations":[{"operation":"create_folder","path":"<actual episode folder path>/01_A-17"}]}
```

Inspect the per-operation result and keep the **actual returned stage directory_id**. Preserve the complete response privately. No directory ID is derived from a path or reused from a different stage. The canonical root tool is `mcp__codex_apps__library_manage_library`; a known actual episode folder needs no new search solely to rediscover its identity.

## 3. Local bindings and the one actual ordered upload

Use these fixed programs:

- Metadata adapter: `SOURCE/operational/parameter_field_recovery05/archive_io.py`
- Measured external wrapper: `SOURCE/operational/parameter_field_recovery04/external_step.py`
- Official upload helper: `BASE/executor_recovery_20261030T1152/helpers/library_upload.py`
- Official transfer helper: the same helper directory's `library_file_transfer.py`
- Helper Python: `/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3`

Set stage work to `OPS/root_archive_io/01_A-17`. It must **not exist before prepare-upload**. Store request-input files and any measurement of this preparation under a separate `_requests`/`_engineering` directory, so measuring preparation does not accidentally precreate its stage work directory.

```text
VENV -B ARCHIVE_IO prepare-upload
  --request-descriptor ACTUAL_REQUEST_DESCRIPTOR_FILE
  --directory-id ACTUAL_RETURNED_STAGE_DIRECTORY_ID
  --work-directory OPS/root_archive_io/01_A-17
```

This creates BOUND_REQUEST.json and UPLOAD_REQUEST.json and makes zero remote calls. Bind/verify the actual number and order of REQUEST.items; the initial A17 fixture is five items, but the real REQUEST is authoritative for every stage.

Execute the whole prepared batch exactly once through the frozen measured wrapper:

```text
VENV -B EXTERNAL_STEP
  --directory STAGE_WORK/upload_step
  --cwd OPS/empty_cwd
  --stdin-file STAGE_WORK/UPLOAD_REQUEST.json
  -- HELPER_PYTHON -B OFFICIAL_LIBRARY_UPLOAD
```

The helper owns prepare, transfer, finalize, ordered results and source xattrs. Do not separately call prepare_uploads/finalize_uploads. The engineering WAIT4 must report command success, and archive_io must inspect every returned upload item. A timeout, unknown status or partial result is not permission to repeat the write. The fixed `.4` engineering schema remains valid because this is the unchanged original engineering wrapper, now measuring a new actual command.

## 4. Actual materialization and measured readback helpers

```text
VENV -B ARCHIVE_IO prepare-readback
  --work-directory STAGE_WORK
  --upload-wait4 STAGE_WORK/upload_step/WAIT4.json
```

`--upload-stdout` is optional: the adapter otherwise resolves the exact stdout descriptor from WAIT4. On success, read `STAGE_WORK/MATERIALIZE_ARGS.json` and pass that complete JSON unchanged to `mcp__codex_apps__library_prepare_materialize`. The actual tool supports the adapter's precise shape:

```json
{"items":[{"file_id":"<actual uploaded version file_id>","file_name":"<actual returned filename>","library_file_id":"<actual stable Library ID>"}],"destination":{"directory":"<exact STAGE_WORK/readback>"}}
```

These references came from actual upload results, so this is the resolved-reference materialization route. Keep file_id/file_name together to pin the uploaded content; do not switch to a latest-version-only lookup. The API permits 1–20 items. Preserve the complete raw tool result privately, including its structuredContent/content envelope and every transfer object. Do not print signed URLs or reduce a transfer to its URL.

```text
VENV -B ARCHIVE_IO prepare-transfers
  --work-directory STAGE_WORK
  --materialize-receipt COMPLETE_ACTUAL_TOOL_RESPONSE_JSON
```

Read READBACK_PLAN.json and execute each exact `items[].external_step_argv` once, in order. The plan already binds official helper argv, complete transfer-object stdin, expected path and fresh per-item WAIT4 directory. A returned workspace_path uses apply-xattrs; a signed transfer uses materialize. Do not download by another client or execute a returned URL. Source bytes and independent readback bytes must remain distinct inodes.

## 5. Candidate, explicit publication and supervisor acceptance

```text
VENV -B ARCHIVE_IO ack --work-directory STAGE_WORK
```

This writes/verifies ACK_CANDIDATE.json and ACK_CANDIDATE_VERIFIED.json and returns `actual_ack_published=false`. Review the actual candidate and frozen verification; all items must have actual service identities, exact uploaded versions, independent matching bytes, xattrs and measured helper evidence.

Only then does root use the explicit publication entry:

```text
VENV -B ARCHIVE_IO ack --work-directory STAGE_WORK --publish-ack
```

The adapter rechecks complete evidence, current awaiting request, pinned code, the live original supervisor and shared host PID namespace. It exclusively creates ACK.json and an ACK_PUBLISH_LIVENESS receipt. Publication alone is not supervisor acceptance: wait for that same stage's actual ACK_VERIFIED.json and the next STATUS/activation. Once actual ACK exists, do not rerun stage preparation or publication; reconcile the existing evidence.

Do not retire archive originals, RAW/CAS or readback evidence merely to clear space during this handoff. Any later duplicate-only cleanup needs the established retirement conditions and complete retained evidence; it is separate from the ACK protocol.

## 6. Repeat for the fixed seventeen barriers

| Sequence | Label |
|---:|---|
| 1 | A-17 |
| 2 | A-29 |
| 3 | A-43 |
| 4 | C |
| 5 | B-17 |
| 6 | B-29 |
| 7 | B-43 |
| 8 | W |
| 9 | R-17 |
| 10 | R-29 |
| 11 | R-43 |
| 12 | A_endpoint |
| 13 | B_endpoint |
| 14 | C_endpoint |
| 15 | controller |
| 16 | analysis |
| 17 | final_closure |

For each, root needs: the current exact REQUEST/STATUS binding, new actual stage-folder result, the generated ordered upload request, actual successful upload helper WAIT4/output, complete actual prepare_materialize result, all measured transfer results, candidate/frozen verification, explicit publication and actual supervisor ACK_VERIFIED. No upload result, old A17 ACK or earlier stage version can substitute for a new barrier.

The supervisor then writes primary COMPLETE and exits. The measured launcher writes the outer wait4 receipt; root subsequently closes terminal primary/wait4 metadata and postseal review. The seventeen stage ACKs do not by themselves establish that last terminal closure. Full supervisor wall already includes ACK waits; external root helper CPU is a separate scope from supervisor-inclusive CPU, while nested worker/driver/archive CPU must not be counted again.

## Reviewed limits

Current config field names, initializer paths, CLI argument shapes, shared start policy, archive adapter source pins and official management/materialization input schemas match. All adapter tests and static audits are in the component delivery record. This read-only review did not execute real initialization or verify an as-yet-uncreated production PIPELINE_CONFIG, source commit, supervisor process or stage request. Those concrete gates remain for root's actual run.
