# RR-SNN V2 source preservation snapshot

This isolated archival snapshot retains 1,286 previously absent source objects from `RR_SNN_V2_Research_Package.zip`: 19,076,336 source bytes. Each object is stored under its Git blob identity, and `SOURCE_MANIFEST.json` maps it back to every recorded original archive member path.

The target is the existing **public** repository `TrillionniumFoundation/hepta-private-ci`. The original package explicitly pins that repository and upstream commit `f8c9419df6ddeb36ff8b522a50219981fb8d9345`. The same repository already retains the later RR-SNN V4 project at `research/rrsnn_v4/`; the manifest records that reference and the original package attribution.

## Layout and integrity

- `objects/`: exact source bytes, named by Git blob SHA plus the original source extension.
- `licenses/`: 91 original vendor license/notice paths (26 distinct objects), with original bytes and attribution preserved.
- `SOURCE_MANIFEST.json`: original package hash, source and license identities, byte counts, original member paths, repository attribution, and held candidate identities.

To reconstruct selected source paths, copy the object identified by each source record to its listed `original_members` paths after verifying its byte count, SHA-256, and Git blob SHA. Restore license records to their `original_member` paths. The source files were not executed during preservation.

## Scope

This is a source-only archival projection. Two notebooks containing outputs and 26 review/container candidates are held separately. Model weights, generated experiment data, binaries, rendered reports, and large execution logs are outside this snapshot. Dependency completeness and a complete reconstruction of every original package member are not asserted.

No experiment, manuscript, deployment, or scientific acceptance gate is qualified by this preservation step. HOLD_NO_GO remains in force.
