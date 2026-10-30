# Execution06 root archive metadata adapter

`archive_io.py` is a narrow port of the restored original adapter, SHA-256 `81d5adafc692013dfe29855c1d1d5e6fcc07527942e23c7b936d3308cc508183`. It only assembles and validates local metadata. Official Library calls and transfer helpers remain explicit root actions. This component performs no network call, science, automatic retry or automatic ACK publication.

## Locations and source binding

Runtime stage work is under `fullstudy_execution06_ops/root_archive_io`, outside the Git source tree. OWN is the new execution06 source directory. durable_archive.py and external_step.py remain the exact frozen execution04 files in the registered source tree. Their SHA pins are respectively `dfeee33870f3ca429284542cb8ca9ff8c9471a8fc8ff0339c3de251cabf260da` and `fb238cd0f28e331a2e9d4ada5950f436a2d31e579fa9fbd8c36cce70404c2b21`.

The current supervisor SHA is fixed in the adapter and must be updated and independently checked if that source changes before freezing. code_identity binds the adapter itself, current supervisor, both frozen helpers and all four actually restored official helper files: library_upload, library_file_transfer, library_hosted_apps and library_download. Their exact byte hashes are static pins; the stage binding rejects subsequent code drift.

The official helper directory is `executor_recovery_20261030T1152/helpers`. The primary Python helper executable and verified recovered venv retain their existing roles. Frozen external_step INTENT/WAIT4 receipts deliberately retain their execution04 engineering schema; they are not relabeled as historical science or as a different wrapper implementation. New local handoff metadata uses execution06 labels.

## Explicit sequence

1. `prepare-upload --request-descriptor ... --directory-id ... --work-directory ...` binds the current exact REQUEST, waiting supervisor identity, actual returned service directory, ordered items and helper bytes. Every stage requires a fresh work directory. Root separately executes the official uploader through the frozen measured engineering wrapper.
2. `prepare-readback --work-directory ... --upload-wait4 ... --upload-stdout EXACT_WAIT4_STDOUT_PATH` validates complete successful ordered upload results, actual file/version IDs, source bytes and Library xattrs, then writes materialization arguments. Version zero is valid. Unknown, failed or incomplete outcomes stop here and cannot trigger an automatic retry.
3. Root calls actual materialization. `prepare-transfers --work-directory ... --materialize-receipt ...` checks the complete tool result, unavailable items/warnings, identities/versions and destination, then prepares explicit measured official-helper argv. Root executes those helpers.
4. `ack --work-directory ...` validates all actual readback bytes, distinct inode/source identity, xattrs, upload/transfer/helper receipts and the frozen archive verifier. It produces and verifies a candidate only.
5. Only an explicit `ack --work-directory ... --publish-ack` rechecks the still-awaiting live supervisor, exact host PID namespace/identity and source pins, then creates actual ACK.json. Root owns this action and must supply genuine service receipts. The adapter does not authenticate the service independently.

All original byte, identity, version, ordered-item, independent-readback and liveness gates remain. The new request must belong to execution06 even if an old request was copied under new paths. A historical ACK cannot be substituted for a new barrier.

## Verification scope

The execution06 root behavior suite at `/workspace/scratch/178ced6a501f/execution06_recovery_20261030/measurements/root_behavior_checks01/WAIT4.json` actually passed all 51 tests across ancestry, controller import, producer, supervisor and archive metadata. The archive cases cover actual local source/helper pins, ordered preparation, duplicate work rejection, wrong episode/code, unknown upload outcomes, version zero, complete response envelopes and explicit publication. Test service identities are synthetic and provide no remote durability claim.

The older static comparison and test records remain under the frozen `parameter_field_recovery05` directory as historical evidence. Current episode durability requires its own actual ordered upload, independent same-version readback and accepted ACK for every barrier.
