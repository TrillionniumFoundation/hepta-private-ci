# MEM6 archive transfer checkpoint

Status: **PARTIAL / PAUSED_SERVICE_UNAVAILABLE**. The experiment is complete;
the second-environment transfer and full raw-file restoration are not.

The ai395 archive writer verified the complete archive and its members. During
bounded transfer, the h service returned `-32603 Internal error`; bounded
retries, reduced concurrency and a later single read did not restore service.
A separate effective-config probe also failed without accessing a host file.
No successful local full-archive restore receipt is present.

## Persisted bytes

`ARCHIVE_INDEX.json` maps the 52 published binary parts to original archive
offsets, lengths and SHA-256 values. It contains:

- 49 parts making the continuous first 24,117,248 bytes;
- 3 additional 65,536-byte chunks at offsets 24,182,784, 24,248,320 and
  24,313,856;
- a total of 24,313,856 verified bytes from the expected 61,412,948-byte file.

The parts are binary Git blobs, each at most 500,000 bytes. No allowlist or blob
policy was changed. `TRANSFER_CHECKPOINT.json` preserves original chunk
receipts, paths at observation time, transport errors and the final probe.
Use `ARCHIVE_INDEX.json` for portable paths within this repository.

The only missing byte ranges, expressed as half-open intervals, are:

| Start | End exclusive | Bytes |
| ---: | ---: | ---: |
| 24,117,248 | 24,182,784 | 65,536 |
| 24,379,392 | 61,412,948 | 37,033,556 |

## Resume contract

Use the existing configured `ai395` host through the authorized runtime. The
source path is:

```text
/home/qq/mem6-attribution-20261110-484c/archive-v1/mem6-cas-001.tar.xz
```

Every resumed read must bind this exact version:

```text
66306:102004015:61412948:1794317318863616657:1794317318863616657
```

Reject a changed version or inconsistent size/path. Verify each returned
chunk's byte count, SHA-256, offset, next offset and EOF. Existing bytes are
immutable; do not replace an earlier chunk with different content. Reassemble
by original offsets, including the three already-saved later chunks. Do not
append them immediately after the continuous prefix: there is a missing chunk
between them.

The complete file must be exactly 61,412,948 bytes with SHA-256:

```text
f77acd9feb27fda3f8000b0d089dbdbe258a4adfb7acedcb2e0cd590cc4f361e
```

Only after full size and SHA verification, run:

```bash
python qualification/memory-cell-mem6/run-001/restore_archive.py \
  --archive /path/to/mem6-cas-001.tar.xz \
  --destination /existing-parent/new-restored-directory \
  --receipt /existing-parent/RESTORE_RECEIPT.json
```

The destination and receipt must be absent. The restore tool validates the
entire archive, the pinned manifest and every CAS object before creating the
destination. It then copies and reopens all 10,365 logical files to verify their
243,281,645 original bytes. An interruption retains an incomplete destination;
the tool never silently resumes or overwrites it.

## Interpretation boundary

Completed objects from the verified prefix supported a partial raw audit of
one memory-winning pair. That audit is documented in
`raw-trajectory-audit.partial.json`; three other targeted pairs remain
incomplete. Complete report-level statistics are available independently in
the two actor reports.

Finishing this transfer establishes file-byte reconstruction in another
environment. It does not authenticate a new trust domain, reconstruct the full
external runtime/material collection, restore owner credentials and effects,
or prove unseen successor-task benefit. Those remain separate gates in
`BLOCKERS.json`.
