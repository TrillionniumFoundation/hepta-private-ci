# Inventory checkpoint

This checkpoint preserves the complete read-only branch/PR enumeration collected on 2026-10-21 UTC and a later bounded refresh of the initial 35 non-draft PRs. It supports source navigation and audit review; it does not authorize a merge or qualify security, experiments or production operation.

- Initial enumeration: **2,864 unique branches; 2,967 PRs**, consisting of 1,637 open (1,602 Draft and 35 non-Draft) and 1,330 closed (323 merged).
- Pagination terminates explicitly: branch page 29 contains 64 records and pages 30/31 are empty; PR page 60 contains 17 records and page 61 is empty. Page URLs, row counts and collection timestamps are retained.
- Metadata coverage is complete for that paginated census. A file-by-file semantic review of all 2,967 PRs, review qualification and full runtime/runner qualification have **not** been completed.
- The later non-draft refresh now has **35 detailed PR reads, 35 complete check-run sets (42 pages) and 35 bounded head rechecks**. Thirty-four checked heads match the recheck; #2962 changes again and remains **OBSERVED_RACE**. Its old checks are not attributed to its new head. No merge candidate is qualified.
- This is not an atomic snapshot. Per-PR API base SHA and branch-census SHA are kept separately. #2962's successive heads are time-scoped observations. Concurrent changes after any read remain possible.
- #2968/#2969 were created after the initial census. `POST_SNAPSHOT_DELTA.json` preserves their first later observations and a subsequent observation of #2968 at `0cb77754` and #2969 at `ca276897`. These deltas do not revise the initial counts or establish final global counts.

## Reading and integrity

Start with [BRANCH_PR_DAG.md](BRANCH_PR_DAG.md). `BRANCH_PR_DAG.json` identifies every branch and PR shard, the complete refreshed compact check-run shards and 14 exact-SHA ancestor comparisons. Each PR preserves metadata, head/base identities, author and state, plus the original body UTF-8 SHA-256 and character count. Full bodies are omitted from compact shards. Branch records link every known head-ref PR number. Compare files preserve returned per-file statistics with API completeness limits; ancestry alone does not certify semantic absorption.

`NONDRAFT_GATES_INITIAL.json` retains the original partial screen, while `NONDRAFT_GATES.json` carries the later complete bounded refresh. Its branch GET summaries show main's two required app-bound contexts and four unprotected stack bases; full administration protection details remain inaccessible. The common-context screen is not a complete policy or review audit.

Every checkpoint file is below **400,000 bytes**, below the repository's 512,000-byte blob gate. `MANIFEST.json` binds the bytes and SHA-256 of every other staged file. Hashes identify the preserved bytes; they do not authenticate GitHub data or reconstruct omitted bodies. Recompute the manifest after any formatter or content change.

The 94 original census responses have a lossless compressed form in the local audit, originally 66,772,196 bytes and compressed to 5,800,560 bytes. They are not copied here. `RAW_SHA256_INDEX.json` retains original/compressed hashes and lengths, while `pagination.json` provides retrieval routes. Refreshed metadata/check response representations are separately indexed by `NONDRAFT_REFRESH_SOURCE_INDEX.json`; full raw responses are not bundled. Re-fetching a moving endpoint may return different content. `RAW_PAYLOAD_SCOPE.json` records this storage choice. Uncompressed originals reappeared after one compression pass in the shared workspace; no repeated deletion or compression cycle was performed.

No full-green repository claim, merge approval, real-model inference, experiment efficacy, production activation or change to SHADOW_ONLY / DENY_ALL / NO_GO follows from this checkpoint.

## Focused independent source review

[migration15-review.json](migration15-review.json) records the independent review of the existing #2743 two-line fixture correction. The reviewed candidate is byte-identical to that owner’s file and preserves the memory/citation and legacy-projection revocation assertions. This reviewer did not run the native tests; their execution belongs to the separate research qualification evidence.
