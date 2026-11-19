# Six reviewed Rust histories and current protected branches

Candidate `ca414120a713eaa0ecb9d5a75c21b9edf5c922fe` has tree `c2edb469712d59a01005c97be0009db02d7762b7`. Its six ordinary merges retain **1,733** original non-HIA branch heads, leaving **5,497** original heads for further review and merging. These counts use the original 7,294-head snapshot.

The independent API review checked all seven server commits: the format commit and each merge. Every tree and ordered parent list matched. A separate Git graph walk verified complete ancestry and the absence of all protected heads and both HIA markers.

## Source and parent preservation

The six histories contain seven unique original commits. Each original incoming tip remains the second parent of its merge. The complete tree remains byte-identical at every step, including the caller manifest storage format, security corrections, profile and test diagnostics, and all 164 existing audit files.

| Incoming tip   | Reviewed behavior already retained                                                                                |
| -------------- | ----------------------------------------------------------------------------------------------------------------- |
| `859b5e8d717b` | CLI recursion limit and the later implementation split.                                                           |
| `05d04b05dda8` | ZIP entry-name formatting, current diagnostics and symlink rejection.                                             |
| `f1a66c1453bf` | Real ZIP symlink fixture and the stronger missing-link assertion.                                                 |
| `4b967004619a` | Canonical Windows workspace and owner roots, with durable database fixture ownership.                             |
| `a37933f6f940` | Rama listener conversion and nonblocking behavior verified against the checksum-pinned dependency.                |
| `3ef15580c3b0` | Native child lifetime tests, issuer capacity and retirement assertions, and the complete transcript preview test. |

`branch-six-merge-plan.json.gz` contains the full unique-commit review, normal merge results, per-path resolutions, source identities and ordered parent plan. Its `steps[].semantic_proof` fields explain every retained source postimage. The local validation base maps to server format commit `5fed9dcb99feb6c3037e61eec0cc91c0db22dae2`.

`branch-review-session.tar.gz` preserves original merge output, the exact format-base validation receipt, and all seven GitHub API replies. Its original bytes and every member are recorded in the manifest.

## Current HIA protection

At `2026-11-16T14:42:35.038436+00:00`, the repository had **7,311** heads and **80** protected HIA heads. The 17 new `cell-experiments-v2` heads all descend from the protected Cell marker even though their names do not contain HIA. All original protected heads are ancestors of their observed current heads.

The complete protected vector and original `ls-remote` bytes are stored without alteration. All current protected heads, all 63 original protected heads and both markers are excluded from candidate and incoming ancestry. Later HIA advances must also be preserved.

## Restoration and graph verification

For each gzip artifact, decompress once and verify the raw byte length and SHA-256 in `branch-follow-up-manifest.json`. The session archive is a standard USTAR file inside gzip.

`branch-graph-extension.json` identifies the exact parent graph in the earlier immutable audit package and supplies every additional parent row required to walk this candidate. Reconstructing that graph independently reproduces the candidate closure and the 1,733 retained original heads.

## Validation scope

These six merges change no source, policy or evidence bytes. Their original blob-size check reports no changed files. Runtime and platform qualification remains attached to the exact source tree and its separate CI receipts; this package adds no new native execution claim.

This package records immutable commit objects and audit evidence. It does not claim that main was merged, that a remote ref moved, or that all remaining branches were consolidated.
