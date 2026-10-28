# V5 complete evidence: restoration and result boundaries

**Local preservation and exact artifact reanalysis passed. The original
scientific audit remains FAIL, and the V5 candidate is REJECTED.**

The machine-readable terminal record is
[ARCHIVE_AND_RESTORE_VERIFICATION.json](ARCHIVE_AND_RESTORE_VERIFICATION.json).
It updates only the local archive/restore work item `V5-A02`. The prearchive
[ledger](BLOCKERS.json) and [execution review](EXECUTION_REVIEW.md) are immutable
snapshots; their earlier archive-pending state is resolved by this separate
receipt. Original B01–B10 criteria and the unestablished B04 gain claim are not
rewritten.

## Exact package identity

| Item | Verified value |
| --- | --- |
| File | `hepta_field_bridge_v5_20261027_evidence.tar.gz` |
| Archive bytes | 239,369,112 |
| Archive SHA-256 | `58b00c94da32eec4565e49e66a72d98c38f619c6dd2baeeb8a4318a7984fcdc2` |
| Manifest SHA-256 | `38472bc9509495d08404c72212a0d2aaa3c9c3a9abab98a4f1d5b0aa3635d285` |
| Payload | 501 files, 246,121,150 bytes |
| Total regular tar members | 502, including the first `MANIFEST.json` |
| Compression | Gzip level 6, fixed timestamp, USTAR regular files |

The archive contains the entire sealed V5 run: 72 terminal checkpoints and
traces, 150 raw task/clean output files, endpoint arrays, six phase inventories,
execution logs, original failed audit, separate diagnostic and media audit,
required scientific sources and prior inputs, nine restored original assets,
and their restoration receipt. Repository-relative copies of the three current
audit receipts are also included so the current review links resolve.

It does not contain historical V2/V3/V4 complete raw archives, unrecorded
intermediate tensors, or a bundled Python runtime. The original 62,166,608-byte
asset download is not duplicated: its selected exact members and provenance
are retained. Historical review links can refer to earlier Git evidence outside
this package; this is not a complete repository or history export.

## Checks actually completed

- Every payload member was hashed and fully restored into a fresh directory.
- Outer gzip CRC was verified through physical EOF; all 80 inner gzip streams
  were verified. No unsafe members or exception allowlist were accepted.
- All 233 ZIP payloads passed member CRC checks: 156 NPZ and 77 PT files.
- Two isolated Python processes loaded scientific code only from the restored
  repository. Actual imports and executed repository files were checked against
  the manifest; fixed Python, NumPy and Torch were explicit external dependencies.
- The restored frozen auditor exited with its original failure, reproducing the
  same 213-byte `AUDIT.json`, SHA-256
  `35af3341f3fc283c41beda469e5c9ff2531f7bf01d537cb4dcc9c4a7fd6b42df`.
- The restored diagnostic exactly reproduced all 72 paths, seven comparisons,
  resource records and admission checks. Only `diagnostic_cpu_ns`,
  `diagnostic_wall_ns` and `source_registration` were removed at the top level
  before comparison. No numeric tolerance was used. Both normalized results
  have SHA-256 `bc65d6f91c9c33d3fab9df55139b1402b0cd459b57fca4574b099b10badbd2df`.
- The restored input tree remained unchanged. Literal reanalysis performed no
  neural model calls, training, endpoint regeneration or new holdout access.

The initial external harness attempt misclassified the relative filename of a
Torch virtual module. Its [failed receipt](postpackage/literal_attempt_1/LITERAL_REANALYSIS.json)
and logs are retained. The correction recognizes only the two observed virtual
objects and binds their actual runtime implementation files. The
[successful receipt](postpackage/LITERAL_REANALYSIS.json) preserves the original
scientific FAIL. No scientific source, data, threshold or archive byte changed.

## Reproduce the restoration

Use Python 3.12.14, NumPy 2.3.5 and Torch 2.8.0+cpu. The supplied runtime is
external to the archive. Run from a checkout containing the reviewed tools.
Choose fresh, separate directories for restored inputs and verification outputs.

```bash
V5_REPLAY_PY=/absolute/path/to/pinned/python
V5_ARCHIVE=/absolute/path/to/hepta_field_bridge_v5_20261027_evidence.tar.gz
V5_RESTORED=/absolute/path/to/new-restored-directory
V5_CHECKS=/absolute/path/to/new-verification-directory
mkdir -p "$V5_CHECKS"

"$V5_REPLAY_PY" experiments/multimodal_output_portfolio/field_bridge_v3_20261027_review/archive_integrity.py \
  --archive "$V5_ARCHIVE" \
  --expected-sha256 58b00c94da32eec4565e49e66a72d98c38f619c6dd2baeeb8a4318a7984fcdc2 \
  --expected-manifest-sha256 38472bc9509495d08404c72212a0d2aaa3c9c3a9abab98a4f1d5b0aa3635d285 \
  --restore-plan experiments/multimodal_output_portfolio/field_bridge_v5_20261027_review/postpackage/RESTORE_PLAN.json \
  --restore-dir "$V5_RESTORED" \
  --max-restore-bytes 246231142 \
  --output "$V5_CHECKS/RESTORE_VERIFICATION.json"
```

Then use `literal_reanalysis.py` with the new archive/root/receipt paths, a fresh
external output directory, the pinned Python executable, and registered harness
commit `b1352d6eb6de1a9b558fe4397fdeae26233ab5e7`. Supply the SHA-256 of your newly
created restore receipt with `--expected-restore-verification-sha256`; its local
paths and timings differ from the original receipt. `--registration-repository`
identifies the checkout used only to verify the harness Git blob. The scientific
children do not consult that checkout. The tool refuses existing output paths.

The full original commands and result identities are represented by the
[build receipt](postpackage/BUILD_RECEIPT.json),
[strict restore receipt](postpackage/RESTORE_VERIFICATION.json) and successful
literal receipt. A new machine is not assumed to provide universal bitwise
reproducibility; any new failure must remain visible.

## Scientific interpretation and durable custody

The within-run audit and independent media arithmetic passed. The original
historical endpoint regression still failed. Separately, all four same-guard
field comparisons were exactly zero, and the fixed numeric admission checks
failed. Explaining the historical discrepancy would not turn this candidate
into a passing candidate. The minimal missing historical artifact is
`development/17/original-task.npz`, SHA-256
`47ad388b03bf2109b01737107196019156c9f7cf0cebbbe71a92c060caa08c9e`.

Raw durable custody remains pending. No V5 upload has been attempted. Earlier
automatic approval review required user-authored permission naming the private
files and ChatGPT Library destination; generic continuation did not meet that
requirement. The exact new objects ready for that decision are:

- `hepta_field_bridge_v5_20261027_evidence.tar.gz`;
- `hepta_field_bridge_v5_20261027_archive_verification.json`, the same bytes as
  the terminal verification record linked above.

Local restoration and Git-backed review receipts do not substitute for durable
raw storage. No alternate raw-data transfer channel or blob-size exemption was
used. Authority remains `DENY_ALL`, with calibration required and native owner
integration disabled.
