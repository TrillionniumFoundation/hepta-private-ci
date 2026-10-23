# Notes receipt retirement qualification

Frozen source `0f7a96752529a7914b7c24d07fadd527c5bd7bce` passed the original
Memory owner scope: 59/59, including all six new retirement cases, followed by
33/33 original production/HOS2 shared read-path regressions. The positive run
explicitly rebuilt the actual Memory source. Scoped fix passed without source
changes; the committed range `just fmt --base 9b133c5f2e --check` passed. No
semantic tests followed the finish check.

The original negative source `0413d211b6657568d9a9fde5af6d00d269e6fb15`
retired one application receipt when zero retirements were required. That red
result remains. The first positive run reused an old negative Memory binary
from a shared target: its 53-pass/1-fail result is invalid as verification of
the fixed source and is retained separately. Updating only lib.rs mtime forced
a rebuild; its before/after SHA256 is identical and recorded in the receipt.

The fix holds the original read-only BEGIN IMMEDIATE transaction through exact
terminal observation, whole-owner Current acknowledgement and synchronous
application metadata retirement. It verifies the original live writer after
the final await. Unknown, cancellation and missing bound capability fence the
managed writer. Observation queries no longer dirty the owner cut. The race,
revocation and cancellation tests retain the original assertions.

These are explicit protocol-peer and application-observer fixtures. They do
not establish production Root fsync/adoption, HOS2 receipt retirement,
pre-effect entered-cut publication, crash recovery or physical device safety.
The publication preserves all original red, stale-binary, green, fix and
command/source records. The formatter result is recorded in the original
validation receipt; no separate formatter stdout is invented.

See [the module contract](../../NOTES_RECEIPT_RETIREMENT.md) and
[the complete publication manifest](publication.json).
