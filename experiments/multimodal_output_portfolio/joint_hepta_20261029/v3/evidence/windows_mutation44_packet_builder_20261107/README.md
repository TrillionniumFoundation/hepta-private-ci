# Windows44 packet builder revision

This unit publishes the final v2 builder, the root's source-only delta checker,
and the exact final v1-to-v2 patch. The original package remains rejected for
containing one 8,888-byte alias of a separately published final algorithm.
Its manifest, roster, INDEX, checks, and file identities remain available here;
the rejected archive is not republished.

The replacement roster has 183 files and 1,895,194 original bytes. All retained
roster objects are unchanged. The builder now compares every archive member with
all six separately published sources by complete bytes. This is an exclusion
boundary correction, not a new native result or a secret-disclosure finding.

The original builder can be reconstructed from the final builder and the exact
reverse patch. Pre-format snapshots are retained in the original local evidence
and recorded here by identity only. The root checker used those original paths;
this unit does not claim to supply every input for a direct rerun of that check.
Its actual execution result is preserved, with command and QA records in unit B.

Unit B publishes the independent packet auditors and the original FAIL and v2
PASS receipts. Unit C publishes only the approved v2 packet, together with the
Windows45 source review. Neither private console stream nor an execution ZIP
is included. The four algorithms already published in PRs 5279 and 5280 are
referenced by identity and are not duplicated here.

The two Windows production test failures, P0, and historical ACL migration
remain open. No builder, archived code, Windows API, or native test was executed
while preparing these publication groups.
