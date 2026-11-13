# cc57 canonical alignment preparation

This package contains ten authenticated Git objects: the five reviewed source
blobs, four changed trees, and the exact raw bytes of official commit
`cc57c7198db6293ccca562253c42fffbe2a04633`. Its sole parent is
`246d8cb614770252ee42029a5c014f2a4904176a`; its tree is
`b7b357c07b5539769a068c6b9b009629f5612d1e`. The root agent created that commit.
This preparation performs no native command, commit creation, branch update or
qualification run.

The five source blobs were created and fully read back. Each changed tree was
created and fetched through the Git data API, and every returned path, mode,
type, SHA and entry order matched the complete locally encoded tree. The raw
commit reconstruction was accepted only when its complete Git commit SHA
matched the already-observed official identity. Its original timezone is -0500
and its message has no terminal LF, as authenticated by that match. The recovery
is not a new raw server read.

The original apply-and-format job `1a1d2107dce-2564-1c98` completed normally.
The original `just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f`
returned 0 within its unchanged 900-second budget, and produced no further source
changes. All three final audits were verified. These maintenance results do not
replace the failed original 246d source-closure result or the qualification
that must run on the new source.

The complete actual dirty inventory was reconstructed from the complete prior
inventory and the five actual source rows. The resulting 5,611,436 bytes match
the original native bytes/SHA256/Git identity exactly. Its gzip and all five
encoded parts also match every original ARTIFACTS identity, including decoded
offsets and hashes. The same original bytes occurred at six recorded inventory
paths; the recovery report maps those paths to one preserved set of parts.
This is exact-byte recovery, not another native full read.

`CANONICAL_CLEAN_INVENTORY.expected.json` is a **prediction** for the unchanged
physical source after the native index/HEAD alignment. It has 15,188 leaves,
5,611,184 bytes, SHA256
`13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9`
and Git blob `7f94788b70546a8b8030dfd2b9182a7d9287c537`.
Only the HEAD/tree/status and index-facing fields change in this projection;
all physical bytes, modes and paths remain identical. Native alignment must
independently produce these exact bytes before it is called observed clean.

The canonical packet retains the original
`hepta-final-canonical-source-alignment-packet-v1` schema. Its before endpoint
binds the actual dirty inventory and actual final Git state; its after endpoint
binds the official new commit and expected complete clean inventory. Every raw
object is checked by type, byte count, SHA256 and canonical Git object SHA.

For any preserved part set, base64-decode the listed parts separately in order,
concatenate the decoded bytes, verify the gzip identity, then gunzip and verify
the original raw identity. The predicted inventory is separately labelled from
the recovered actual dirty inventory. All evidence files in the placement are
below 500 KB; the larger raw payloads are losslessly represented by the parts.
No genuine authorized A/B/C task chain is established by this preparation.
