# Exact-length read budget

The existing snapshot and payload read ports now reject a wrong file length
under their shared lock before seeking, reading, allocating or hashing content.
The byte reader is additionally limited to the declared length plus one sentinel
byte, within the existing global ceiling. Post-read length and full digest checks
remain mandatory; advisory locks do not establish immutable hostile storage.

The public types, byte formats, lineage rules and authority posture are unchanged.
An empty payload or a file above the global ceiling still reports `Capacity`;
other length mismatches remain `Corrupt` for snapshots and `PayloadMismatch` for
payloads. An oversized declared payload length is rejected at the same hard
capacity boundary before file access. No payload can exceed the global quota.

This is lane E private source preparation, not an authorized/current artifact
selector. The host still authenticates pins, ownership, purpose, current
revocations and new-process selection. `PINNED_LOAD.md` remains applicable.
