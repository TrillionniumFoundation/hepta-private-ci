# Packaging note for the preserved ordinary producer audit

REPORT.md, SOURCE_MANIFEST.json, VERIFICATION.json, MANIFEST.json and
verify_sources.py are preserved original audit artifacts. Their contents have
not been rewritten for this evidence package.

The original report refers to a local source/ directory and says to run
python verify_sources.py. Those statements refer to the original audit at:

/workspace/scratch/037c0371c195/candidate-ordinary-producer-audit-094/

At packaging time, its source/ directory held the 47 exact source files used
for the audit. The repository evidence package intentionally does not copy
those 47 source files or the additional upstream reports named by the original
MANIFEST.json. ARTIFACTS.json at the package root records the files that are
physically included.

To reproduce the source identity check outside the original scratch audit
directory, first retrieve each exact source_url / Git blob recorded in
SOURCE_MANIFEST.json for commit
094958b83a8fd19e3bc6d01a092793c0f420bb75. Recreate the listed relative paths
under source/ in an isolated copy of this audit directory. Match their byte
lengths, SHA-256 and Git blobs before using the preserved verify_sources.py.
The script expects that local source/ tree; it cannot run successfully against
this source-free evidence package alone.

This reproduces only the source identity and 22 recorded boundary-row checks.
It is not a source behavior test, native execution, ordinary producer
implementation, or ordinary qualification. The preserved audit reports
production changes 0, native UNRUN and ordinary qualification added 0.
