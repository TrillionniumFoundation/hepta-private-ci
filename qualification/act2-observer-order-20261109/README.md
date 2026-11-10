# ACT-2 attached Notes observer order

**Scoped native qualification passed on the original tested source. Full ACT-2 promotion remains HOLD.**

[Implementation PR #5591](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5591)
adds one shared in-memory revision/content fence across clones of an attached
Notes document observer. [Run 42744390844](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42744390844),
attempt 1, completed successfully. The original artifacts and source distinction
below replace the earlier pending status; the original queued snapshot is
preserved in [RUN_QUEUED_SNAPSHOT.json](RUN_QUEUED_SNAPSHOT.json).

## Exact source and maintenance

| Role | Commit | Tree |
| --- | --- | --- |
| Actual test source | `111d5773145dbe4add99a28b2d1111916a3dbd3b` | `cd6ea40d7bad36bc1149cdca4137e85f9798f5fc` |
| Official formatter successor | `8b1c1789916514471c6cacdf0f6c45467255fef9` | `b9879a77f0b7a7d8f766aaf2308b719e6bcaa29e` |
| Pinned Session/App companion | `fd8d56c52b971c2d5d0e6430f296803b43ef60a3` | `347fbb7e9931006c749b5bef0e1550c54bc08f27` |

All five command records bind their clean before/after source to the tested
commit and tree. Scoped `just fix` changed no source. The final official
formatter did change one string-expression line break in
`notes_document_observer.rs`. Its patch is byte-identical to the independent
formatter job's patch: 795 B, SHA-256
`1580b37b40bd9a42bacc74a459f26411eca7f6e48685ab0fc11e6a8072ce2881`.
The successor commit contains exactly that one-file delta; its complete file was
read back and matched the formatter's complete postimage, Git blob
`af5e5213a54f5e14803dca46f9d6a35e4ecb7960`.

No behavior tests ran after maintenance in this original run. Counts below
belong to the actual test source, not a newly claimed rerun on the successor.
The successor's own CI is separate and has no inherited pass here.
[MAINTENANCE.json](MAINTENANCE.json) preserves the exact mapping.

## Observed execution

| Scope | Original result | Command elapsed |
| --- | --- | ---: |
| Automation package | 169 passed, 0 failed, 2 skipped | 285.427 s |
| Notes observer, projection and original owner | 10 passed, 0 failed, 778 skipped | 499.216 s |
| Pinned Session/App locked build | exit 0 | 118.753 s |
| Selected real Session/App test | 1 passed, 0 failed, 787 skipped | 4.510 s |
| Scoped lint/fix | exit 0, source unchanged | 313.268 s |

Both new tests appear individually as PASS in the Notes original log:

- `notes_document_observer_clones_fence_revision_and_content_without_writing_effects`
- `notes_document_observer_clones_do_not_queue_behind_an_inflight_exchange`

The first uses freshly nonce-correlated socketpair responses across clones:
revision 8, receipt retirement at 8, revision 9, rejected revision 8, rejected
changed content at 9, and continued valid reads at 9 and 10. The second holds a
real in-flight response, checks immediate concurrent refusal and verifies that
no extra datagram was queued. Both verify no effect-channel writes.

All command logs' byte counts and SHA-256 values were checked against their
original command records. No command timed out or exceeded its output limit.
Skipped cases are not passes. Elapsed values include compilation/runner work;
they are not policy performance comparisons or independent completion-time
samples. Existing warnings remain in the logs.

## Actual App re-observation

This candidate also reran the same real Session/App lifecycle. The first goal
was terminal/succeeded at revision 1; after later real edits reached revision 3,
its historical applied receipt remained but its current goal was unsatisfied
and runtime UNKNOWN. The recovered third operation was terminal/succeeded at
revision 3. Three further fresh observations produced equal complete status
values without additional effects or grants. After the owned App was actually
closed, new readback returned Connection refused; the original owner remained
Committed with its applied receipt, while current document/goal/runtime became
missing or UNKNOWN.

The lifecycle still records three effect attempts and four issuer requests
across three operations, including the deliberate denial. Recovery flags
`recovery_effect_replay` and `recovery_requested_new_grant` are false. These are
correlated observations in one App lifecycle, not independent trials. This does
not exercise an actual App checkpoint rollback or the complete model-facing
handler. [notes-actual.json](evidence/notes-actual.json) is an exact copy of the
original native artifact member.

## Original evidence

- [Native artifact](evidence/act2-native-42744390844.zip): 72,992 B; SHA-256 `ac8a9e15832ed9c5d2ed9f9cf0ac4da4dccc1a371b272382f1efff8c35fd1295`.
- [Formatter artifact](evidence/act2-format-42744390844.zip): 39,629 B; SHA-256 `1a2cb5eb28775bb1f7ffbfe5c00a548575f6e10978d4faee0e7c1cde04894918`.
- [Readable official patch](evidence/official-format.patch), [RESULT.json](RESULT.json), [original publication identity](PUBLICATION.json), and [original static review](INDEPENDENT_REVIEW.json).

ZIP bytes match GitHub artifact digests and are not repacked. RESULT retains
archive-member hashes, full command records, log hashes, exact source identities,
recorded lock and Session/App executable hashes, observed assertions and limits.
The executable hashes match the actual App JSON and build record. The artifacts
do not contain complete lock/executable bytes or a standalone Hepta test-binary
hash; this review does not independently recompute those complete-file hashes.
The static review's earlier pending wording remains a historical record.

## Remaining gates

The fence orders accepted document exchanges within one attachment. It does not
order later asynchronous status delivery or persist across restart/reattachment.
Durable rollback protection, actual App rollback qualification, destination
tombstones, cancel/commit races, late-commit exclusion, real long-running/network
wait adapters, full model-facing handler qualification, production authority,
native kernel/pixels, complete repository CI and independent learned-hierarchy
benefit remain open. No full caller scan, main merge, deployment or scientific
promotion is claimed by this scoped result.

The parent's successful App-fault evidence stays separately in
[PR #5589](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5589).
Its counts were not transferred to this candidate.

## Required repository CI audit

[The retained audit](required-ci/README.md) preserves nine complete job logs in
bounded ZIPs, exact checkout identities and separately classified Mac/Windows
failures. The local Notes formatting error has an exact official maintenance
postimage above. Owned temporary-root fixture normalization is a separate
pending candidate in [PR #5618](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5618).
It does not establish a unique historical root cause or resolve separate
permission, file-lock, sandbox and other repository failures.
