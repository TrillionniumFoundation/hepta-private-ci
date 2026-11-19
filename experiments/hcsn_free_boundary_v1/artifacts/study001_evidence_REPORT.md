# Sealed study001 evidence archive

The complete sealed `results/study001/` tree is archived and verified. This includes the 244 main training runs, their saved initial/gate/128-update/selected checkpoints and predictions, all run and process logs, the primary analysis, the original secondary128 analysis, and their execution-cost receipts. No training or analysis was rerun for this archive. The separate `conditional001` and `equal_updates_core002` studies are outside its scope.

## Archive identity

| Item | Value |
|---|---|
| Manifest | `study001_evidence.json` |
| Contract | `hcsn-evidence-bundle.v1` |
| Member root | `results/study001/...` |
| Members | **6,443 regular files** |
| Original member bytes | **369,014,045 bytes** (351.92 MiB) |
| Compressed bytes | **146,869,744 bytes** (140.07 MiB) |
| Parts | **36** |
| Parts 0000–0034 | **4,194,304 bytes** each (4 MiB) |
| Part 0035 | **69,104 bytes** |
| Manifest size | **1,351,280 bytes** |
| Complete compressed archive SHA-256 | `7af65ff5c812bd0ab545c881608b4e4415be04a586ed3bda866bcc9669727d14` |
| Manifest SHA-256 | `7ec65c21984c53cc755821d4f44ab8240a41bc17b7d1fffaf3d45bc677b107f7` |
| Verification receipt SHA-256 | `82332c049c06e1327629d99095d466a6b75b653ede904de2048796676acac2af` |

Four-MiB parts were explicitly selected before packing to reduce publication calls. The existing auxiliary and original-data archives retain their original one-MiB segmentation. The manifest records each part's exact size, SHA-256 and Git blob SHA-1, plus the size and SHA-256 of every logical member. No extra staging wrapper appears in member paths.

## Included evidence

| Group | Files | Original bytes |
|---|---:|---:|
| `results/study001/runs/` | 5,429 | 352,703,715 |
| `results/study001/process_logs/` | 244 | 185,273 |
| `results/study001/analysis001/` | 9 | 2,035,290 |
| `results/study001/secondary128/` | 752 | 13,810,716 |
| Root identity/completion/progress, three analysis logs and three execution receipts | 9 | 279,051 |

The numeric NPZ inventory contains 488 `initial.npz` files, 244 `selected.npz` files, 1,891 saved `step_*.npz` checkpoints including 429 exact `step_000128.npz` files, 446 `test_predictions.npz` files, and 224 `ood_predictions.npz` files. These are counts of actual saved files. The original secondary evaluation and its incomplete-case records remain preserved as sealed; the archive does not replace them with the separate later equal-update diagnostic.

All regular files in the sealed source tree are included, apart from the archive utility's standard exclusion of bytecode and `__pycache__`. No symlink member was accepted, and no selection by model outcome was performed.

## Seal and authorized presentation erratum

The analysis owner explicitly confirmed that `analysis001/REPORT.md`, `secondary128/REPORT.md`, `SUPPLEMENTARY_AUDIT.json`, all original analysis/secondary prediction products, and the three analysis execution receipts were final, with no subsequent writes to `study001` planned.

Before inventory locking and packing, the root agent authorized exactly one Markdown table-header correction in `analysis001/REPORT.md`:

```text
Before: Minimum across runs of observed max |gradient|
After:  Minimum across runs of observed max absolute gradient
```

The unescaped vertical bars split a table cell. This correction changes presentation only; no numerical result, JSON audit, execution receipt, or frozen source was edited.

| Report version | SHA-256 |
|---|---|
| Immediately before the header correction | `97157186771a96e93eccdc6ea671723327824df5c43fbf4b63623e514ab6a40f` |
| Corrected version included in this archive | `fa213f83487703926fb73313ab7ca9ac021f5f8f9f07bac06daa70d31553a40c` |

The previous hash was reconstructed in memory by reversing the unique authorized text replacement. A literal search for that previous SHA-256 across the sealed `study001` tree found no existing hash binding. The analysis generator's owner also confirmed that `SUPPLEMENTARY_AUDIT.json` binds numerical analysis, CSV, completion/secondary records, execution receipts and generator source, but no REPORT content hash. The three execution receipts likewise contain no REPORT content-hash binding. Original numerical audits were preserved. The [verification receipt](study001_evidence_VERIFICATION.json) records the authorization, exact substitution, both report hashes, and binding-search method; the archive manifest binds the final presentation version.

## Verification and resource use

The new streaming archive implementation writes its continuous xz output directly to parts and does not create a second full compressed copy. Staging used hardlinks in an independent scratch directory. Packing finished successfully without an ENOSPC failure.

The complete archive was then passed to `archive.restore` with the existing package root as destination. All 6,443 destination members already existed identically. During this actual restore, `TemporaryFile` was explicitly prohibited; the verification still completed, proving that neither a concatenated compressed temporary file nor duplicate member copies were needed for this path.

The restore verified each part and the whole compressed hash before streaming extraction, repeated the part/whole checks while reading, and verified every declared member's type, path, size and checksum. A further independent pass checked every original member's size and SHA-256 against the archive manifest. All 6,443 source inodes, modification times and sizes remained unchanged. The physical source inventory still exactly matched the locked inventory. All 38 original frozen files also remained unchanged.

| Measured subprocess | Complete CPU seconds | Wall seconds | Peak RSS |
|---|---:|---:|---:|
| Streaming pack | 218.826745 | 219.008387 | 134,000 KiB |
| Restore verification against existing files | 7.848286 | 7.866614 | 39,424 KiB |

These are archive-process costs measured with `os.wait4`, separate from the scientific training/evaluation costs stored inside the archive. They do not include the driver's separate inventory/hardlink work and final independent hash pass. The task's hardlink staging directory was removed after successful verification. Original main evidence was not deleted or rewritten.

## Restore or reverify

From the repository root, with all 36 parts adjacent to the manifest:

```bash
python experiments/hcsn_free_boundary_v1/archive.py restore \
  --manifest experiments/hcsn_free_boundary_v1/artifacts/study001_evidence.json \
  --destination experiments/hcsn_free_boundary_v1
```

This verifies and reuses identical existing members. For a fresh restoration, choose a separate destination with space for the declared uncompressed files. Different existing contents are refused. The verification receipt records the exact actual API command, source-tool hash, phase exit codes and process measurements.

## Human-readable result entry points

After restoration, start with:

- `results/study001/analysis001/REPORT.md` — primary results, controls, costs and qualifications.
- `results/study001/analysis001/SUPPLEMENTARY_AUDIT.json` — supplementary numerical and provenance checks.
- `results/study001/secondary128/REPORT.md` — the original secondary128 results and their scope.
- `results/study001/analysis001_EXECUTION.json`, `analysis_report_EXECUTION.json`, and `secondary128_EXECUTION.json` — complete analysis-process cost receipts.
- `results/study001/runs/` and `process_logs/` — complete saved model/checkpoint/prediction and execution records.

The source and evidence archive were prepared locally. Publication is handled separately by the root workflow.
