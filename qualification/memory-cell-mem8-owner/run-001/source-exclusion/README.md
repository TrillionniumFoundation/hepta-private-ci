# MEM source exclusion evidence

This package freezes 69 known excluded source groups and a 16-group optimistic catalog remainder (7 development, 9 retention_validation). The remainder is not certified unseen; global exposure is UNKNOWN. The W 20/min4 gate and its historic 16/4 allocation are distinct from the separately required, numerically unfrozen E successor protocol.

Start with REPORT.md, EXCLUSIONS.json and CAPACITY.json. OFFLINE_AUDIT.json records the actually completed local offline audit, including the full original MEM6 CAS hash and selected metadata objects and the original MEM5 ZIP's PLAN/REQUEST.

## Reproduce without a host or model

All inputs required for the default audit are included:

```sh
python3 -B audit_source_exclusions.py --root .
```

To additionally repeat the full archive bindings:

```sh
python3 -B audit_source_exclusions.py --root . \
  --mem6-archive /path/to/mem6-cas-001.tar.xz \
  --mem5-zip /path/to/audit-core-5fa0d0e.zip
```

METADATA_INPUT_PINS.json identifies those external archives and all retained metadata. The whole archives are already preserved independently; this capsule does not duplicate them. It includes exact selected original metadata bytes plus the complete safe host stdout, start/status and four lossless ranges. It contains no keys, authorization tokens, service environment, raw task references or newly scored actor outputs. The earlier published aggregate is explicitly historical.

The embedded read_pinned_source_inventory.py is the exact script of the **already completed** single original-host job. It is retained for audit, not an instruction to rerun that job.

SOURCE_EXCLUSION_CAPSULE.json stores UTF-8 files under relative paths, each with byte length, SHA256 and Git blob SHA. Verify all three before writing into a new evidence directory. Do not treat file restoration as owner or effect recovery.

No qualified branch, source or owner reference was changed by this task.
