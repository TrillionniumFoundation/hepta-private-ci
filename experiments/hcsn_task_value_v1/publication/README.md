# Publication provenance

This directory records publication of the registered HCSN study to the public repository `TrillionniumFoundation/hepta-private-ci`.

- Draft PR: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4482
- Branch: `research/hcsn-task-value-execution-20261031`
- Registered baseline: `1d959d8d82091e6014b13c2191f62bf74e778561`
- Protocol SHA256: `643320e6d8e081df54e0ef8362de95d1eebddbd5b026f4e2373cf33d97a183c1`

`ROOT_CONFIRMED.json` maps the covered local commits to GitHub-created commits. The GitHub API chooses commit metadata, so local and remote commit SHA values differ. Every published tree was checked against its exact local tree SHA; the ordered parent chain is preserved. The receipt covers the implementation/evidence commits named inside it. A later commit publishing the receipt itself cannot include its own SHA without a recursive hash dependency.

`BLOBS_CONFIRMED.json` records binary and large evidence blobs whose returned Git blob SHA was checked against their local bytes. Other UTF-8 contents were checked through exact tree identity. `PR_CREATION.json` is the creation-time snapshot, not a promise that the head or base branch never moves.

`SOURCE_PUBLICATION_PARTIAL.json` and `FOUNDATION_BLOBS_PARTIAL.json` are retained early snapshots of interrupted publication attempts. They are superseded by the confirmed publication receipts and the visible branch; their early counts must not be used as the final publication status. `POST_STUDY_COMMITS.json` records the first four post-study local commit deltas, not every later documentation or portability commit.

## Evidence archives

| Archive | Members | Compressed bytes | SHA256 |
| --- | ---: | ---: | --- |
| foundations001 | 145 | 3435216 | `cfd7cd8a1f50635bfac30f1c32def69493b7c46a523f683d32f964a31a062adb` |
| study001 | 2444 | 23168296 | `bae75b038da8f361cf343d916d4465dd5007527b058d69f7911554a8a645bab1` |

Both archives were restored into new directories and every member was checked. The portability companion replays the archived measurements and statistics with an exact log-path relocation allowlist. It explicitly inherits the original filesystem chronology audit because deterministic archive restoration cannot reconstruct original selection-file modification times. It does not rewrite timestamps, retrain, run model inference, or replace the historical result.

This is a draft research delivery. The PR has not been merged, and publication is not a claim that all six scientific acceptance gates passed. The complete negative results and limits remain in the report.
