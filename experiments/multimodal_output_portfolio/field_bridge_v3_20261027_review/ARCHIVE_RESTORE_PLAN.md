# V3 selective restore and exact arithmetic replay

## Purpose and preserved scope

Keep the complete immutable archive. The selective restore creates a small working subset for exact statistical/arithmetic replay; it does not replace the complete evidence package or re-execute training, observers, native state transitions or reserved evaluations. This procedure is local and performs no upload or network request.

The archive uses `run/`, `repository/`, `freezes/`, `native/` and `assets/` member roots, with `MANIFEST.json` as the first member. The full archive retains checkpoints, optimizer state, media, traces, original assets, native binaries and earlier proof receipts. `ARCHIVE_SELECTIVE_RESTORE.json` specifies the exact sorted members and measured payload bytes to materialize. The selective payload must fit the explicit 80,000,000-byte limit; use the plan's measured total rather than treating an approximate size as an integrity claim. The manifest and output receipts are additional small files.

## Verification before publication of restored files

`archive_integrity.py` streams the **entire** archive. It checks the externally published archive and manifest SHA256 values, every manifest-listed member's exact length and SHA256, complete inventory coverage, the outer gzip CRC through physical EOF, and every inner `.gz` stream's CRC and termination. It rejects duplicate, unsafe, case-colliding or nonregular members, links, devices, sparse entries and unmanifested payloads. There is no invalid-gzip exception list.

Only planned members are written, using exclusive regular-file writes under a new `.partial` directory. All other members are still hashed and their gzip streams verified. The restored directory is published by rename only after the whole archive passes and restored files pass hash readback. A failed partial attempt is preserved; do not overwrite it or silently continue from its bytes.

Selective publication requires Linux `renameat2(RENAME_NOREPLACE)` and fails without an overwrite fallback if unavailable; full streaming verification without restoring files remains portable.

## What the small subset contains

- Frozen V3 protocol, allocation manifest and source identity registry.
- The exact archived pure NumPy arithmetic modules and the two archive verification/replay helpers.
- Development and runtime-audit freeze records.
- Three development `ENDPOINTS.npz` arrays, endpoint identities, START and completion metadata.
- Three frozen runtime-audit row streams and parent/selected completion metadata, plus frozen runtime readouts and fitting completion metadata.
- The already-completed endpoint, hard-score, runtime-media, runtime-fit and native-session proof receipts needed to bind those arrays and rows to the original verified evidence.

Large model/media/state artifacts stay inside the full archive and remain covered by its complete integrity receipt. The restore's exact member inventory is checked again before replay. Required but un-restored source and artifact identities are checked through the fully verified manifest, rather than substituted with files from the live workspace.

## Commands

Set the archive path and the two expected hashes from the independently published preservation receipt. Set `V3_REVIEW_TOOLS` to the published helper directory and `V3_RESTORE_PLAN` to the published exact JSON plan. Use fresh output/destination paths.

```bash
V3_ARCHIVE='/absolute/path/to/the-complete-v3-archive.tar.gz'
V3_ARCHIVE_SHA256='PUBLISHED_ARCHIVE_SHA256'
V3_MANIFEST_SHA256='PUBLISHED_MANIFEST_SHA256'
V3_REVIEW_TOOLS='/absolute/path/to/field_bridge_v3_20261027_review'
V3_RESTORE_PLAN='/absolute/path/to/ARCHIVE_SELECTIVE_RESTORE.json'
V3_RESTORE='/tmp/hepta-v3-selective-restore'
V3_INTEGRITY='/tmp/V3_ARCHIVE_INTEGRITY.json'

python "$V3_REVIEW_TOOLS/archive_integrity.py" --archive "$V3_ARCHIVE" --expected-sha256 "$V3_ARCHIVE_SHA256" --expected-manifest-sha256 "$V3_MANIFEST_SHA256" --restore-plan "$V3_RESTORE_PLAN" --restore-dir "$V3_RESTORE" --max-restore-bytes 80000000 --output "$V3_INTEGRITY"
```

After integrity succeeds, use the recorded integrity-receipt SHA256 as `V3_INTEGRITY_SHA256`. Invoke reanalysis from the **restored** helper path in a fresh Python process with NumPy available:

```bash
V3_INTEGRITY_SHA256='RECORDED_INTEGRITY_RECEIPT_SHA256'
V3_RESTORED_REVIEW="$V3_RESTORE/repository/experiments/multimodal_output_portfolio/field_bridge_v3_20261027_review"

python "$V3_RESTORED_REVIEW/archive_reanalysis.py" --restore "$V3_RESTORE" --integrity "$V3_INTEGRITY" --expected-integrity-sha256 "$V3_INTEGRITY_SHA256" --output /tmp/V3_ARCHIVE_REANALYSIS.json
```

## Replay acceptance and limits

Reanalysis imports `analysis_contract`, `endpoint_arrays`, `runtime_audit_support` and `runtime_results_audit` exclusively from the restored directory. It hashes those exact archived modules before import and refuses conflicting live-workspace modules. No generator, observer, native library or remote service is invoked.

Acceptance requires exact reconstruction of the existing development selection and all its numeric fields, the frozen runtime gate and bootstrap draw identity, endpoint/source alignment, selected-runtime resource arithmetic, policy identities and original proof bindings. The two negative qualification outcomes must remain negative. A differing result is a failed restoration proof, not an invitation to alter the protocol or rerun a scientific gate.

The new receipt establishes full-archive byte integrity and exact arithmetic reproduction from literal restored inputs. Existing hard-media, observer and native-state truth proofs remain bound and preserved; this small-subset replay does not claim to execute those expensive checks again. Retain the complete archive, the exact restore plan, the integrity receipt, the reanalysis receipt and their published hashes.
