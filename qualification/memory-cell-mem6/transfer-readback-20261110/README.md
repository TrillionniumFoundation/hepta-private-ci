# MEM6 full raw-archive transfer and separate-host file restoration

**Result: FILE-BYTE RESTORATION VERIFIED; overall scientific acceptance HOLD / NoUpdate.**
This evidence-only successor to MEM7 #5809 records a later observation; it does
not overwrite the original partially transferred MEM6 checkpoint or retrospectively
convert #5809's earlier incomplete snapshot into a PASS.

## Pinned identity and original transport

- Frozen actor execution source: `8cf848babdd897e9f38642d5faf3ba0f72a1303c`.
  No actor, teacher, model, OCR, task or source rerun was performed.
- Origin: configured `ai395` at
  `/home/qq/mem6-attribution-20261110-484c/archive-v1/mem6-cas-001.tar.xz`.
- Origin archive version from the original checkpoint:
  `66306:102004015:61412948:1794317318863616657:1794317318863616657`.
- Read-only origin metadata/hash process `1a1c65b9630-5074-c6` returned
  size **61,412,948 B**, inode `102004015`, and the pinned SHA-256
  `f77acd9feb27fda3f8000b0d089dbdbe258a4adfb7acedcb2e0cd590cc4f361e`.
- A separate desktop SSH read-only probe `1a1c65d3926-5074-cf` authenticated
  to the original ai395 file and observed the same size/inode.
- A **single** source-to-desktop copy via authenticated SSH/rsync:
  desktop job `1a1c65ef68d-5074-d7`,
  idempotency key `mem6-20261110-original-cas-ai395-to-desktop-sha-f77acd-v1`,
  completed `succeeded`, exit 0, empty stderr.
  Its complete terminal stdout was:
  `MEM6_TRANSFER_SUCCESS bytes=61412948 sha256=f77acd9feb27fda3f8000b0d089dbdbe258a4adfb7acedcb2e0cd590cc4f361e remote_before=f77acd9feb27fda3f8000b0d089dbdbe258a4adfb7acedcb2e0cd590cc4f361e remote_after=f77acd9feb27fda3f8000b0d089dbdbe258a4adfb7acedcb2e0cd590cc4f361e path=/home/qian-qi/mem6-cold-custody-20261110/mem6-cas-001.tar.xz`.
  The final local archive was made read-only and separately checked via native
  file_info, with SHA-256 equal to the pinned descriptor.
- The old #5809 readback retained **804 chunks / 52,690,944 B** and a historical
  **8,722,004 B gap**, precisely `[51576832,51642368)` and
  `[52756480,61412948)`. These are now covered by the **new complete copy**;
  the old partial Git blob checkpoint was not changed or relabeled.

## Pinned strict restoration

Desktop job `1a1c6683fb4-5074-104` completed `succeeded`, exit 0,
empty stderr. Its CLI used the exact original
`qualification/memory-cell-mem6/run-001/restore_archive.py` from PR #5774,
Git blob `f308eb0f2b4ea4c9d50d812148db3d81cd9456e2` (13,764 bytes).

A first tool-materialization attempt appended one extra newline (13,765 bytes),
causing the pinned Git blob preflight to reject it **before restoration**.
The byte mismatch was independently identified; the original failed copy is
retained. A separate exact 13,764-byte script file was generated after verifying
its Git blob, with both target directory and receipt confirmed absent before
running the strict restorer. No unknown target was overwritten.

The restorer verified the compressed archive, manifest, strict tar members,
all **7,122 unique objects**, then wrote and reopened all **10,365 logical
files / 243,281,645 bytes** in an exclusive new destination.
Its original, unmodified JSON receipt is `RESTORE_RECEIPT.json`;
the desktop receipt SHA-256 is
`50e05ede42e15d3ac47da53a13dbdacfca80dea7a95fb54f51aed3047144f4d9`.

## Independent second implementation

`verify_restored_files.py` is the actual 4,323-byte independent post-restore
reader run on desktop (SHA-256:
`d07dc47ae573a3a864d9eea9b72694d2d787ddab50645a34761dd32c44fcfe34`).
It reopens the pinned XZ archive to read `MANIFEST.json`, verifies the original
archive and manifest SHA-256, independently reads and hashes every restored file,
checks exact path-set equality, rejects symbolic/special nodes and hardlinks,
and produces `INDEPENDENT_READBACK.json`. This second receipt has SHA-256
`1d78a698b0537493a806c233622a128bd993516e4388395df273ad430efce4dd`.

Independent verification finished **2026-11-10 17:05:54 UTC**, finding
**10,365 files / 243,281,645 bytes**, with no extra regular files, symlinks
or special nodes. Its ordered manifest catalog digest is
`196399012ba0132a7ea1a1f75587409b876029a28204cc1a083809b68a5b8e82`.

To reproduce **without running actors**, use the script in this directory:

```bash
python3 -B verify_restored_files.py \
  --archive /existing/path/mem6-cas-001.tar.xz \
  --root /existing/path/payload-restore-v1 \
  --receipt /existing/path/new-independent-receipt.json
```

The receipt path must be absent. This checks restored bytes, not a live owner.

## What remains open

The transferred material does **not** include all external runtime/OCR inputs,
source collection or model-owner authority and credentials, live effects or an
independently trusted provider. The second host is a different physical
machine, not an independently authenticated trust domain. These checks do not
establish atomicity under a malicious writer, production effect fencing,
physical erasure, complete cost coverage or real successor-task benefit.

MEM6 retention remains 30/84 versus 28/84 with source bootstrap lower bound
0.0; it does not satisfy the pre-registered benefit gate. No existing
actor/experiment denominators, task exposure/exclusions, frozen weights,
security assertions, sandbox or sealed roles were changed. The archived
partial-transfer evidence and every original failure/UNKNOWN remain preserved.
Required whole-repo CI and complete owner cold recovery are separate open gates.
No adoption or merge authorization is inferred from this evidence commit.
