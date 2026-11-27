# V8 evidence archive tools

These tools preserve an explicitly approved evidence inventory. They do not run experiments, score candidates, grant scientific acceptance, change native owner state, upload files, or delete original evidence. No real V8 archive is created by the qualification tests.

## Approval and input contract

The host supplies a roots JSON document and its exact SHA256. Its schema is `hepta.evidence-archive-roots.v8`, with an absolute `workspace` and an explicit `roots` array. Each root has:

| Field | Meaning |
| --- | --- |
| `label` | Unique simple archive prefix. |
| `path` | Exact canonical directory inside the workspace. Roots cannot overlap. |
| `status` | `sealed`, `tools`, or `interrupted`. Running or unsealed work is rejected. |
| `purpose` | Human-readable reason for including this root. |
| `pins` | Relative file names mapped to externally approved SHA256 values. |
| `source_references` | Optional exact published source files to omit; each reference contains Git `repository`, full `commit`, `path`, and `sha256`. |

**For `sealed` and `tools` roots, `pins` must cover every retained file.** Pinning a seal document alone is insufficient. Construct the expected map from the original frozen inventory, approved final receipts, and explicit hashes for the inventory documents themselves. Do not rehash changed raw data and present those new values as an old seal. Unexpected files, missing files, or content mismatches reject the plan.

An `interrupted` root can have an empty prior pin map. Its complete current file inventory is still hashed and becomes part of the externally approved archive plan. This preserves a failed or incomplete attempt without claiming that it had a successful historical seal. Any supplied prior pins must match.

Only `.py`, `.rs`, `.sh`, and `.bzl` files may be replaced by exact Git source references, and local bytes must match the referenced hash. The tool validates local equality and immutable reference syntax; independent publication verification supplies the assurance that those bytes were actually published at the named Git commit. Raw JSON, NPZ, binary, XML, and log evidence cannot be removed through this mapping. Published evidence receipts remain archive contents.

An optional `prerequisite_archives` array records `{name, sha256, bytes, location}` for previous durable archives. Those external archives are not opened, copied, or silently added to the new archive. V5/V6 and the previous V7/V7b archive can therefore remain separately pinned prerequisites.

Whole Git worktrees, symlinks, device files and paths escaping approved roots are rejected. Cache/version-control directories, recognized encoder weight paths/formats and credential/private-key names are explicitly listed in `excluded`; excluded credential contents are not read. Filename filtering is not a content-level secret detector. The exact root whitelist and complete exclusion list require host review. There is no automatic directory discovery or automatic approval.

## Commands

Run the CLI with Python's standard library; no package installation or Rust build is required. Substitute real absolute paths and independently checked hashes only after the final input roots are frozen.

```sh
python archive_cli_v8.py plan \
  --roots /approved/roots.json \
  --roots-sha256 ROOT_DOCUMENT_SHA256 \
  --output /archive-output/approved-plan.json
```

Review the complete plan and retain its external SHA256. The plan records every retained file hash, source file fingerprint, original root, hardlink target, explicit exclusion, published source dependency and previous archive prerequisite.

Before committing disk space, the measurement command performs the exact compression stream into a bounded-memory counter and hash sink. It creates no archive file and rechecks all source contents.

```sh
python archive_cli_v8.py measure \
  --plan /archive-output/approved-plan.json \
  --plan-sha256 APPROVED_PLAN_SHA256
```

Use its compressed byte count to choose an explicit output budget and reserve. Output paths must be new and outside every approved evidence root.

```sh
python archive_cli_v8.py pack \
  --plan /archive-output/approved-plan.json \
  --plan-sha256 APPROVED_PLAN_SHA256 \
  --output /archive-output/cell-field-v8-evidence.tar.gz \
  --max-output-bytes APPROVED_COMPRESSED_BUDGET \
  --reserve-bytes 67108864
```

The writer records both `f_bfree` and `f_bavail`, uses effective UID to select the available space calculation, performs a real 64KiB write and fsync probe, and checks the reserve before each compressed write. UID0 may legitimately have usable `f_bfree` while `f_bavail` is zero. Output-budget or I/O failures retain a `.partial` archive and a failure receipt when writable space permits. No original input is removed.

The archive is gzip level6 with filename omitted and `mtime=0`; tar ownership and timestamps are normalized. Each unique regular file is streamed and hashed. Identical content with the same normalized mode uses an internal hardlink to the earlier verified regular member. Duplicate input files are still read and checked. No expanded temporary tar file is created.

After independent verification, the writer rechecks the approved plan, tool sources, complete inventory and fingerprints. It then creates the final archive path without overwriting an existing path. The fully written and fsynced receipt is published by a second no-overwrite atomic link, followed by a directory fsync.

**The final `.receipt.json` is the publication commit marker.** A final archive file alone is not publication success: a crash or receipt-publication error can leave a fully verified archive without a committed publication receipt. That case is reported as a failure; it does not become a scientific or experiment success. All partial files are preserved for inspection.

## Independent verification

The separate reader authenticates the external manifest SHA, the exact embedded manifest, each expected PAX/tar header, every regular file's full SHA, every hardlink, zero padding, the complete footer and gzip checksum. It rejects trailing tar data, appended gzip members, truncation and unexpected members. It never extracts an archive. It does not require original source directories, source inode values, or the archive writer's current source files.

```sh
python archive_cli_v8.py verify \
  --archive /archive-output/cell-field-v8-evidence.tar.gz \
  --manifest /archive-output/approved-plan.json \
  --manifest-sha256 APPROVED_PLAN_SHA256 \
  --archive-sha256 PUBLISHED_ARCHIVE_SHA256
```

`evidence_members` excludes the one embedded `MANIFEST.json`. `regular_evidence_members` excludes hardlink entries. `archive_logical_members` includes the manifest. `logical_bytes` counts all retained input file bytes; `stored_file_bytes` counts unique regular file bodies. Tar PAX extension headers are framing and do not represent additional evidence files.

Source inode/mtime/ctime fingerprints detect concurrent changes during planning and packing. They do not identify scientific data, prove the date of an experiment, or promise restoration of original timestamps. Scientific identity remains the externally pinned content hashes and existing scientific/audit receipts.

## Qualification scope

`test_archive_v8.py` creates small temporary fixtures only. It checks deterministic compression, long Unicode paths, complete content verification, real hardlink restoration, source-free verification, all corruption/truncation/trailing-stream failures, changed inputs, unsafe links, incomplete historical pin maps, raw-evidence Git omission rejection, capacity limits, retained interrupted attempts, mutation during verification, and interrupted receipt publication.

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest test_archive_v8 -v
```

Passing these mechanical checks does not approve an actual root whitelist, verify the contents of a scientific review, create a real archive or install a native candidate. Exact final roots and their externally checked maps remain a separate host decision.
