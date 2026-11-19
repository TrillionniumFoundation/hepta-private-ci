# HEPTA branch and PR inventory

## Coverage and limits

Read-only GitHub API snapshot collected on 2026-10-21 UTC. See `pagination.json` for exact per-page timestamps, URLs and terminal-page witnesses. There are **2,864 unique branches**, and **2,967 unique PRs** (numbers 1–2967 without gaps): **1,637 open**, **1,330 closed**, **323 merged**. Open PRs include **1,602 draft** and **35 non-draft**. Branch pages 1–29 are nonempty (100/page; final 64); pages 30/31 are empty. PR pages 1–60 are nonempty (50/page; final 17); page 61 is empty.

This is complete metadata pagination, not a 2,967-PR file-by-file semantic review or exhaustive CI qualification. No PR is marked safe to merge from metadata. No remote branch was changed or deleted. Raw responses are losslessly gzip-compressed and SHA-256-indexed in `RAW_SHA256_INDEX.json`; compact records omit long PR bodies but bind their exact UTF-8 hashes. This committed checkpoint contains the response hash index; the original compressed responses are not bundled here.

Main branch: `f8c9419df6ddeb36ff8b522a50219981fb8d9345` (protected). PR base SHA fields may describe a prior comparison base; `base_branch_observed_sha` records the branch census independently. Pagination is not atomic. PR #2962 changed during collection: `8ce0cbdd` → observed branch `d29b9f7a` → first-page recheck `98793d7f`. Status **OBSERVED_RACE**; no write/overwrite attempted. First-page recheck found no other changes in its 50 rows; this does not freeze all other rows.

## Priority roots

| PR | State | Draft | Exact head | Target branch |
|---|---|---|---|---|
| [#1500](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1500) | closed | true | `779d0c744d75c5b04404f3492a11d9e269afaf8e` | `main` |
| [#1501](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1501) | closed | true | `7941d7050c3432214c7af996ede65b6ed027a3bf` | `main` |
| [#1504](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1504) | open | true | `79db9bdc19d6960e8350fae310755db12938304b` | `main` |
| [#1468](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1468) | open | true | `8b8a1b74a9340ae0a40114bc1116945838e79be1` | `codex/hepta-bounded-inference-scale-20261009` |
| [#1508](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1508) | open | true | `aa0d5f9e863c0bd24b642b4eb2bb48528ea6220f` | `codex/hepta-production-gates-20261010` |
| [#1509](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1509) | open | true | `8032a73a83a71c9a99eba91eec8a4516515c91c2` | `codex/cell-split-ledger-trust-pins-20261011` |
| [#1452](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1452) | open | false | `81d9fcb36bddfcc6dc914f87697c642824273cc1` | `main` |
| [#1390](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1390) | open | false | `3589a2964d1aa5fd6119e2dd9a363ab4579a981b` | `fix/main-product-blockers-20261005` |
| [#1278](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1278) | open | false | `c142eae6fa3a6ef4da3074541a649d5241170d04` | `main` |
| [#1237](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1237) | open | false | `e3e4e650bd6f57aaf520193a6b2febab42e6f9d3` | `main` |
| [#1234](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1234) | open | false | `92f8715dc5d3ea0060447744312eb494e76babe4` | `main` |
| [#1001](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1001) | open | false | `18654890257ad54e628445731288df011f679361` | `main` |
| [#2695](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2695) | open | true | `74bbcc9b0bb330649cd54d9881ae3676d3968bae` | `main` |
| [#2688](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2688) | open | true | `55088dd78b4950407f77a43f054efed0816409cb` | `main` |
| [#2734](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2734) | open | true | `dc271d4f47028e941decce70cc8ef81fb24d2141` | `main` |
| [#2815](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2815) | open | false | `995b6fb9ef73ada7c3348b01deb28940a2c4a2d1` | `main` |
| [#2937](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2937) | open | false | `b58d870a2c38ebee0aa0b974d9f03767c888fa7e` | `main` |
| [#2959](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2959) | open | false | `8aa52b4a1d6dd004400500191d70b7b573b5a23f` | `codex/group-ndu-deterministic-20261017` |
| [#2961](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2961) | open | false | `c210d26350ac57e527b4ff59663e5c8d518ff95a` | `integration/v8-main-convergence-20261020` |
| [#2964](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2964) | open | false | `fad7f6b342e9a087bbc921862ba93f67b1873f51` | `integration/v8-main-convergence-20261020` |

## Verified ancestry comparisons

The source PR in the first column is the comparison base; the target PR is the comparison head. Ahead/behind counts describe commits, not quality or semantic completeness. An ancestor can have changes reverted later; these comparisons alone cannot authorize pruning.

| Source → target | Status | Target ahead | Target behind | Merge base |
|---|---|---:|---:|---|
| #1500 → #1504 | diverged | 1 | 2 | `e518fcdb6b25e2d6ef1320f80842d3bb8a606230` |
| #1501 → #1504 | diverged | 1 | 1 | `e518fcdb6b25e2d6ef1320f80842d3bb8a606230` |
| #1468 → #1508 | diverged | 1 | 568 | `d6c69adc5751568367f11e217f2028faaf76fcdd` |
| #1508 → #1509 | ahead | 2 | 0 | `aa0d5f9e863c0bd24b642b4eb2bb48528ea6220f` |
| #2695 → #2937 | ahead | 217 | 0 | `74bbcc9b0bb330649cd54d9881ae3676d3968bae` |
| #2688 → #2937 | diverged | 259 | 1 | `391b6a8d7202b3db7abe7d015947e0423a31d5b4` |
| #2815 → #2937 | ahead | 306 | 0 | `995b6fb9ef73ada7c3348b01deb28940a2c4a2d1` |
| #2883 → #2937 | ahead | 310 | 0 | `a8ce72907288d1836612446b87cb1d5c184993ac` |
| #2924 → #2937 | diverged | 240 | 3 | `f0765028a1317c210ba4c4bc4d8a16a525138086` |
| #2879 → #2937 | ahead | 234 | 0 | `dc28e90b782590d296f862d4e485a53b7c22ee68` |
| #2695 → #2959 | ahead | 75 | 0 | `74bbcc9b0bb330649cd54d9881ae3676d3968bae` |
| #2937 → #2961 | diverged | 24 | 3 | `ddf193c6bb46c2d1e4c6255639686b345ead10aa` |
| #2937 → #2964 | diverged | 1 | 3 | `ddf193c6bb46c2d1e4c6255639686b345ead10aa` |
| #1504 → #2937 | diverged | 317 | 126 | `78fdb0cf8537e3a84fc6e0a849707559c80881e8` |

Consequences: #1500/#1501 are already closed without merge, but #1504 diverges from them; their semantic absorption is not proved. #1509 includes current #1508, while #1508 lacks 568 commits present on current #1468. #2937 includes current #2695/#2815/#2883/#2879 ancestry but lacks one current #2688 commit and three current #2924 commits. #2961 and #2964 remain based on `ddf193c6`, three root commits behind current #2937. #1504 and #2937 are deeply diverged (317/126), so the old PON root is not declared obsolete merely because #2937 is newer.

## Non-draft merge-gate screen

The initial 35 open non-draft PRs were all refreshed, with 35 current metadata reads, 35 complete check-run sets and 35 bounded metadata rechecks. The original partial screen is preserved in `NONDRAFT_GATES_INITIAL.json`; `NONDRAFT_GATES.json` contains the refreshed screen. Full paginated compact check records are referenced by `BRANCH_PR_DAG.json`, and their raw response hashes and collection URLs are in `NONDRAFT_REFRESH_SOURCE_INDEX.json`.

Collection window: **2026-10-21T01:12:31Z to 2026-10-21T01:18:17.370Z**. The 42 check-run pages contain **2,448 latest-filter check runs**. Six heads report more than 100 runs and include a second page; #2566 has exactly 100 runs and an explicit empty second page. All reported counts match distinct returned check-run IDs. All 35 PRs remain open and non-draft. Thirty-four heads match their bounded recheck.

#2962 moved from `f41a16d05c26937253f9c2ff1cb90e0e9f3d1c55` at metadata retrieval to `f6748b35164bc26b8b9926fde5b76b5b91b4b42b` at bounded recheck. Its 25 check runs bind only to the first SHA; they are not applied to the later SHA. Status remains **OBSERVED_RACE**. No repeated pursuit or remote write followed.

The current main-branch summary requires `CI required` and `Architecture required`, both from app 15368, for non-admins. The other four observed stack bases report protection disabled in the branch GET summary. The table uses the same two contexts for comparison across all PRs; their presence does not establish that those contexts are enforced on every stack base. Full administration protection details remain inaccessible, and source semantics and reviews are not fully audited.

| PR | Checked head | Merge state at recheck | CI required | Architecture required | Head binding |
|---|---|---|---|---|---|
| #2964 | `fad7f6b342e9` | unstable | completed/failure | completed/success | same at recheck |
| #2962 | `f41a16d05c26` | blocked | MISSING | queued/pending | OBSERVED_RACE |
| #2961 | `c210d26350ac` | unstable | completed/failure | completed/success | same at recheck |
| #2959 | `8aa52b4a1d6d` | unstable | completed/failure | completed/failure | same at recheck |
| #2937 | `b58d870a2c38` | blocked | completed/failure | completed/success | same at recheck |
| #2883 | `a8ce72907288` | blocked | completed/failure | completed/success | same at recheck |
| #2882 | `b34cb44f06db` | blocked | completed/failure | completed/success | same at recheck |
| #2815 | `995b6fb9ef73` | blocked | completed/failure | completed/success | same at recheck |
| #2709 | `db3dca79d410` | blocked | completed/failure | completed/success | same at recheck |
| #2697 | `5810df76d82c` | blocked | completed/failure | completed/success | same at recheck |
| #2611 | `cc594bbb1494` | blocked | completed/failure | completed/success | same at recheck |
| #2607 | `bcce62f0c36a` | unstable | completed/failure | completed/success | same at recheck |
| #2606 | `28607454e2c6` | blocked | completed/failure | completed/success | same at recheck |
| #2605 | `5b943a0aeefd` | blocked | completed/failure | completed/success | same at recheck |
| #2599 | `924f96d71622` | blocked | completed/failure | completed/success | same at recheck |
| #2566 | `1b2a24b72751` | blocked | completed/failure | completed/success | same at recheck |
| #2406 | `fd3811f84f04` | blocked | completed/failure | completed/success | same at recheck |
| #2365 | `da3f14b9b16b` | unstable | completed/failure | completed/success | same at recheck |
| #2273 | `6b885ae432f5` | blocked | completed/failure | completed/success | same at recheck |
| #1682 | `e89570ddb8bd` | behind | completed/failure | completed/success | same at recheck |
| #1452 | `81d9fcb36bdd` | blocked | completed/failure | completed/success | same at recheck |
| #1390 | `3589a2964d1a` | unstable | completed/failure | completed/success | same at recheck |
| #1278 | `c142eae6fa3a` | dirty | MISSING | completed/failure | same at recheck |
| #1237 | `e3e4e650bd6f` | dirty | completed/failure | completed/failure | same at recheck |
| #1234 | `92f8715dc5d3` | behind | completed/failure | completed/failure | same at recheck |
| #1227 | `058c16cb7ade` | dirty | completed/failure | completed/failure | same at recheck |
| #1199 | `87f3d1d99029` | dirty | completed/failure | completed/failure | same at recheck |
| #1179 | `5b2ac550ba31` | behind | completed/failure | completed/failure | same at recheck |
| #1160 | `82c72395a64b` | dirty | completed/failure | completed/failure | same at recheck |
| #1140 | `2063e41e089b` | dirty | completed/failure | completed/failure | same at recheck |
| #1083 | `5e36ad2d4952` | dirty | completed/failure | completed/failure | same at recheck |
| #1069 | `5c0bbe30e4a5` | behind | completed/failure | completed/failure | same at recheck |
| #1038 | `b196e2dbec0e` | dirty | completed/failure | completed/failure | same at recheck |
| #1001 | `18654890257a` | behind | completed/failure | completed/success | same at recheck |
| #994 | `5fb67266c83b` | dirty | completed/failure | completed/failure | same at recheck |

No merge candidate is qualified. At the observed checked heads, `CI required` fails for 33 PRs and is missing for #1278 and the changing #2962; `Architecture required` succeeds for 21, fails for 13 and is queued for the changing #2962. `mergeable=true` describes whether Git can combine the trees; it is not evidence of passing checks or review approval. Nine current PRs report conflicting merges (`dirty`), five are behind, fifteen blocked and six unstable. No row reports a clean merge state. These observations do not classify any research PR as production-ready.

## Checkpoint representation

All branch and PR metadata records are split into files below 400,000 UTF-8 bytes. `BRANCH_PR_DAG.json` identifies the shards, the 14 verified exact-SHA ancestry comparisons and the observed race. `POST_SNAPSHOT_DELTA.json` preserves the first later observations of #2968/#2969 and adds a subsequent observation of #2968 at `0cb777545966333a96be265a69d03c9982231bc7` and #2969 at `ca2768978429a2c9a98641fa2d58a8f587b88874`. This does not revise the initial enumeration totals or establish final repository totals. `OWNER_CANDIDATES.json` records metadata leads for separate dependency and migration-fixture deduplication; titles and author-reported results are not semantic proof.
