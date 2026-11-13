# Original retained ELF transport evidence

This directory preserves all 166 files and 148 distinct Git blobs from the original orphan evidence branch at commit 860dc2d8045f18808b9c5516f86edaef6e830734 (tree ba8da0b1dad8ba8777c0be85bbdc3ae8d1c0cb26). Its original commit is a real merge parent. A separate relocation commit moves the complete tree here without changing any original file bytes or modes. The relative paths inside the transport index remain intact.

## Scope of this audit

SOURCE_CUSTODY.json maps every original path to its preserved path, Git blob, byte length and SHA-256. CROSS_BINDING_REVIEW.json records the cross-check of the three compressed archives, their member inventories, original completion records, source maps and observed image hashes. The 39 archive members are regular files; 23 are retained ELF images. The audit read and hashed those bytes without running the archived programs or reconstructing missing binaries.

The original evidence is under archives/ and transport-index.json. The original transport index and completion records retain their original timestamps, source identities, destinations and limitations; they describe the historical run. Their relocation does not make them a receipt for the current repository head.

## Original results remain failed

| Original phase | Retained result and limitation                                                                                                                                   |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| H1             | FAILED: 65 selected cases passed and two failed. Three selected processes were not individually captured. Follow-up gates were not run.                          |
| H2             | FAILED: 70 selected cases passed and one timed out. A retained prefix does not establish a complete second-daemon process binding. Follow-up gates were not run. |
| H3             | FAILED: the required exact per-case final-use image correspondence was missing, despite recorded passing test outcomes.                                          |

Archive integrity is verified. The historical execution environment and observations were not independently reproduced. This archive grants no production or scientific qualification, deployment approval, recovery authority or replacement for current CI.

## Byte preservation

The existing blob-size policy retains its default limit. Its new exceptions name only the exact SHA-256 and destination of each oversized original part. A changed part must satisfy the policy again. Formatting, spelling and line-ending conversion exclude only the original evidence payloads so their historical hashes remain valid; this README and the new custody manifest remain ordinary reviewable files.
