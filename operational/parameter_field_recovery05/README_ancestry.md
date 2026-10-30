# Execution05 A17 ancestry — context reconstruction

These six recovery05 ancestry/producer files were reconstructed from the retained conversation after the workspace continuity interruption. They are new source bytes, not files recovered from the original disk or the execution04 archive. Historical hashes and the earlier 23-test result must not be attributed to this reconstruction. Compute fresh descriptors, rerun tests, register the actual new source commit, and persist a checkpoint before scientific execution.

## Strict import contract

Only the completed execution04 A17 may enter `execution05_backpressure_20261030`. A29 partial work is not a resume point. All old science and seal bytes remain unchanged. The adapter imports only standard-library operational helpers; it neither imports scientific modules nor decodes arrays.

`load_pins(path, expected_sha256)` requires a SHA supplied by independent registration. Do not compute that expected SHA from the candidate file at admission. Known manifest, ACK, ACK_VERIFIED, config, A freeze, profile, runtime receipt and actual cleanup anchors are independently fixed in code. The verified manifest supplies the transitive complete stage inventory.

`validate_import(pins, old_raw, old_ops)` is read-only and returns immutable `VerifiedImport`. It verifies the old source closure, original scientific ancestor and input bytes, all pinned descriptors, the scientific → operation → controller completion chain, exact 282-file A17 population and 64 bounded state headers. It also streams the original archive parts, reconstructing every logical hash without extraction. State `runtime_sha256` and the environment receipt's `runtime_receipt_sha256` are separate identities.

The old ACK's two removed binary readbacks require the actual pinned cleanup plan, result and journal, exact ACK item/remote identities, actual absence and retained byte-identical original archives. Other readbacks and transfer receipts must still match. This validates historical evidence; it does not authenticate a remote service anew or weaken the original `verify_ack`.

`materialize_import(verified, fresh_raw, method="copy")` revalidates before creating the exact registered nonexistent root. Explicit `hardlink` is supported on the same filesystem. Neither mode changes source bytes or modes. Hardlinks share inode contents and require immutable-artifact discipline; logical byte accounting remains full. Existing targets are refused, including partial failed imports. Failures remain visible and are not automatically retried.

| Fresh RAW path | Meaning |
| --- | --- |
| `stage_A/seed-17/**` | All 282 original stage files, byte-identical |
| `operations/A-seed-17.COMPLETE.json` | Original execution04 operation seal |
| `imports/execution04/A-17/ORIGINAL_CONTROLLER_RESULT.json` | Historical controller seal outside the new controller directory |
| `imports/execution04/A-17/IMPORT_STARTED.json`, `IMPORT_RECEIPT.json` | New operational provenance |

The returned value is the exact descriptor of `IMPORT_RECEIPT.json`. It records `imported=true`, `executed_here=false`, zero new scientific work and the unchanged original descriptors. Import cost includes its repeated validation and copying/linking/hash checks; nested validation cost must not be added again. Final receipt serialization/write is outside that stated interval and belongs in the enclosing operations ledger. No historical START, PID or duration is represented as new execution.

## Producer-map API

`producer_map(import_receipt_descriptor, fresh_registration)` returns exactly keys `"17"`, `"29"`, `"43"`. Fresh registration contains `execution_episode`, `raw_root`, `source_root`, `registered_commit`, basic `source_freeze` and `profile` descriptors, `protocol_sha256`, `runtime_sha256`. The new registration must pin the resulting map file before consumers use it.

Each row contains phase, seed, kind, episode, RAW/source roots, actual registered commit, source freeze, profile, scientific ancestor, protocol and runtime. A17 also binds its import receipt and unique scientific cost owner. A17 uses the old execution04 producer; A29 and A43 use the new execution05 producer. The original scientific source closure is unchanged.

`verify_producer(seed, operation_descriptor, expected_map)` admits only this producer pair, checking the fresh RAW operation path, exact seed/source/profile identity, scientific ancestor and bound scientific completion. Imported A17 operation bytes must equal its original seal. Never build an expected producer row from the operation being checked.

The combined study counts original A17 once, with owner `execution04_durable_20261030:A-17`. Failed A29 work is additional cost, not a second A17 charge and not a credit against new full A29 execution. Unknown historical CPU remains unknown. Operational completion does not establish scientific benefit.

## Validation

Run `python3 -B -m unittest operational.parameter_field_recovery05.test_ancestry -v`. The synthetic fixtures cover a matching archive with wrong producer/seed/runtime or incomplete completion; source/stage/parts/retirement tampering; an unrecorded missing readback; existing targets; changes after validation; and interrupted hardlink materialization that refuses retry. Test-only monkeypatches replace anchors for synthetic files; production has no test-mode argument. No actual RAW materialization is performed by these tests.
