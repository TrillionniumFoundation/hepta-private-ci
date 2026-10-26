# Reclaiming sealed partitions of closed joint output copies

`reclaim_closed_joint.py` is a narrowly scoped storage tool for the completed joint study. A complete, verified output **partition** can be sealed and its expanded copies reclaimed before the remaining study packet is packed. The tool has not been executed or used to hash the confirmation outputs during preparation.

## Mandatory evidence before use

The tool accepts the exact SHA-256 identities of a successful `hepta.advance.closed-evidence.v1` receipt and the checked collector's process receipt. It requires:

1. The complete partition archive's size and SHA-256, external manifest SHA-256, embedded manifest, every archived regular member and complete member census all match. Unexpected, duplicate and nonregular members are rejected. The archive retains the complete intended partition; it need not contain media from other partitions.
2. The exact `joint.confirm_checked` collector for `/tmp/hepta-ndu-advance-joint/confirmation-001` has `returncode: 0` in its process `receipt.json`. Its actual `-m` module and `--output` argument come from the sibling `started.json` field `argv`. Both process files, `CHECKED_RESULT.json`, `RESULTS.json`, `COMPLETENESS_AUDIT.json` and `ROWS.json` must themselves match their archived copies.
3. `CHECKED_RESULT.audit_passed` and the mandatory audit's `passed` are true; the audit and result bind the same current frozen protocol and complete 5,440-bundle / 21,760-file census. The original `CHECKED_RESULT.passed` scientific verdict is retained verbatim in the removal result. A scientific failure remains a failure and does not prevent safe storage reclamation after complete engineering verification.
4. The native final freeze resolves to all 5,561 dependencies. Every current advance `PROTOCOL` / `FROZEN` document and its referenced specification is read, and every absolute dependency identity is protected. A candidate matching any protected path blocks the complete reclamation. Protocol identities are checked again before and after removal.

5. The supplied definition matches the sealer receipt's `definition_sha256` and is itself an archived member. Its exact `generated_output_partition` object must agree with `--case-start` and `--case-end`. Only fixed consecutive 32-case windows are accepted, starting at 0, 32, 64, 96, 128 or 160; the final window ends at 170. Root consumes those windows in source order when storage is needed, never by observed results.

The root operator must run this only after model execution and source changes in the joint study have stopped. A running process, a partially closed partition archive, a merely successful model forward call, or a report from another run is insufficient.

The required definition field for the first partition is:

```json
"generated_output_partition": {
  "case_start": 0,
  "case_end": 32,
  "expected_generated_files": 4096,
  "total_cases": 170,
  "selection": "Consecutive registered case indices; no outcome selection"
}
```

The partition definition uses `trees: []` and exact file entries for its four-file outputs, the closed whole-study metadata/process receipts and the frozen confirmation protocol. It must include the same `CHECKED_RESULT`, `COMPLETENESS_AUDIT`, `RESULTS`, `ROWS` and collector process receipt, preserving their original paths in the member manifest. The sealer includes the definition itself. Extra output files from another case range or location, omitted files and duplicated original paths are rejected.

## Exact deletion scope

Only this registered Cartesian set can be selected:

`/tmp/hepta-ndu-advance-joint/confirmation-001/raw/case-NNN/ROUTE/ARM/output/NAME`

`NNN` comes from the declared half-open case window within the frozen 170-pair protocol, `ROUTE` and `ARM` from its four routes and eight actual arms, and `NAME` is exactly one of `caption.txt`, `image.png`, `audio.wav`, `video.mp4`. The partition must contain exactly `(case_end - case_start) × 4 × 8 × 4` such original paths: 4,096 for a 32-case window. Each expanded file must have the archived byte count and SHA-256, a stable inode/device/size/mtime/ctime, no symlink path and a single hard link. The last byte check occurs immediately before its optional unlink.

No directories are removed. RECORD, PUBLIC_DECISION, TARGET_FREE_OBSERVATION, input video, model, source, metrics, audit and process files remain. All authoritative compressed archives and their manifests remain. Each reclaimed partition is recoverable through its manifest's original-path/member mapping; remaining records continue to name the original media locations, which require archive restoration for a later byte-level audit. Root's final remainder packet must link every completed partition and verify disjoint total coverage of all 21,760 generated files. This helper does not declare that final whole-study custody task complete.

## Invocation

Run from the repository root, after root review and the archive gates above are satisfied. Substitute actual partition definition, receipt paths and exact hashes; use a new output directory outside `/tmp/hepta-ndu-advance-joint`.

```bash
/workspace/scratch/87e43aa872f5/ndu-next-env/bin/python -m experiments.multimodal_output_portfolio.advance_20261026.reclaim_closed_joint \
  --receipt CLOSED_JOINT_PART_000_032_RECEIPT.json \
  --receipt-sha256 EXACT_CLOSED_RECEIPT_SHA256 \
  --definition JOINT_PART_000_032_SPEC.json \
  --case-start 0 --case-end 32 \
  --process /tmp/hepta-ndu-advance-joint/confirmation-001-process/receipt.json \
  --process-sha256 EXACT_PROCESS_RECEIPT_SHA256 \
  --output /workspace/scratch/87e43aa872f5/ndu-evidence/reclaim-closed-joint-001
```

Without `--execute`, the same full verification runs and files remain. Root may add `--execute` for the authorized removal after deciding that space must be reclaimed. Do not rerun against a partly removed set as if it were a new complete run; inspect the existing ledger and restore exact archived members if recovery is needed.

The output retains `STARTED.json`, a complete `PLAN.json`, fsynced before-unlink and completed-unlink events in `LEDGER.jsonl`, and `RESULT.json` with partial-removal status on failure. File-parent directories are fsynced after deletion. Before/after actual filesystem free bytes, cgroup memory/events, process CPU/wall time, peak RSS and the ledger SHA are recorded. A crash between a logged intent and its completion can be reconciled using the path, inode identity and authoritative archive; absence of a completed event is not silently treated as successful deletion.
