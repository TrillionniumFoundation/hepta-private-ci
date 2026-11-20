# Rust consolidation: protection, library roots and B4 row counts

Base: `0cee57ca617e0324e2df8e9447a2c075a6c76952`.
Initial repair: `4a5de714ce95889fca83abd3da33cbd74aaac748`.
This follow-up contributes three reviewed repairs to [PR #6293](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6293). The qualification index is [verification.json](verification.json).

## HIA protection

The previous default policy omitted 80 ordinary-named branches already retained by the published HIA audit. A concrete counterexample, `audit/toolchain-recovery-20261103`, descends from historical protected pin `c4a1bbed3a39beba43a6abf1a18b6f75c5725c21` while diverging from all three roots used by the previous classifier.

The updated production manifest preserves 483 protected names and 504 historical/current pins. Of those names, 391 do not contain `hia`. The implementation includes historical pins and current protected/HIA tips in complete-parent-graph classification, preserves accumulated observations, rejects incomplete or altered history, and records an exclusive application journal before any deletion request. A retained plan directory permits one application attempt. Existing backup, main ancestry, exact ref lease, atomic push and readback requirements remain.

The original 18 regression tests passed. Four new semantic controls fail against the original implementation. All 31 candidate tests pass normally and with Python optimization enabled. These tests use temporary local Git repositories; they do not delete GitHub refs.

### Full ancestry evidence

The [complete recorded audit](history/full-history-result.json) captured 7,654 refs and 78,730 commit objects, with no missing parents. Its before/captured/fresh ref maps matched. The [self-contained export](history/README.md) preserves the complete graph, exact refs, classification, policy and coverage maps, together with an offline verifier.

A later independent HIA advance, `c32019b...` to `5653790...`, is retained in the [single-tip refresh](history/refresh-565/README.md). Actual Git objects prove the new commit has only the old protected tip as its parent. The refreshed graph contains 78,731 commits, no missing parents, the same 483 protected names, and an observed policy with 505 pins. All ordinary coverage maps remained byte-identical. The original production policy remains a valid 504-pin input; the new observation explicitly retains the additional tip.

| Recorded target | Ordinary names included | Ordinary names pending |
| --- | ---: | ---: |
| main `732e934b...` | 0 | 7,170 |
| integration `0cee57ca...` | 2,826 | 4,344 |
| initial repair `4a5de714...` | 2,827 | 4,343 |

Every target has zero ancestor intersection with the 505 observed protected pins and current protected tips. These are ancestry results, not claims that all source conflicts or required checks are resolved.

## Cargo and Bazel library roots

Actual offline Cargo metadata enumerated all 200 workspace members: 194 explicit entries and six implicit members. Eight libraries use a non-default root. Five were already correctly represented by their BUILD files. The remaining three—extension-api, hepta-context-compiler and hepta-prompt—use `src/root.rs` in Cargo but previously selected `src/lib.rs` in Bazel.

The macro now accepts an optional library root at the end of its parameter list and forwards it to both product and test-library rules. The three BUILD files choose their existing Cargo roots. No Rust source, Cargo dependency, lock file or CI workflow changes are included.

Native configured queries confirmed all three wrong roots before the patch and the three correct roots afterward. The [source record](bazel/four-file-source-record.json) binds all 200 manifests and the four exact postimages. The [query proof](bazel/root-query-and-census-proof.json) records actual commands, outcomes, cache use and the initial wrapper-log quota warning.

The Linux Bazel job [136026289154](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44656939483/job/136026289154) reports **eight relevant test targets PASS**: three crate unit-test targets and five extension-api integration targets. Its synthetic merge `3ac734f1...` has exactly the same complete tree `f289a1e9...` as published repair `4a5de714...`; both Git objects were independently checked. Five Windows-cross targets were skipped in that Linux job and are not counted as passed. See [final qualification](bazel/final-qualification.json) and the [complete log index](bazel/publication-logs/index.json).

The complete CI job still failed elsewhere. Local cold-build attempts are retained separately and are not counted as successful builds.

## B4 canonical row counts

The packaged manifest loader requires one protected-file row per path. Five source-closure test files retained obsolete expectations for duplicate rows. The patch changes four expected-count expressions to one and removes two duplicate-count overrides. Every other test byte, mutation case and verifier call remains intact.

The native baseline ran 32 tests and produced 74 failed subtests plus one class setup error. The candidate runs all 39 original tests successfully; the extra seven were previously blocked by that setup error. [Qualification details](b4/qualification-summary.json) and full candidate logs are retained. Exact failing baseline logs and the minimal patch are available as deterministic gzip archives under `b4/compressed/`; their raw identities are recorded in the [representation index](b4/representation-index.json).

The [guard comparison](b4/b4-guard-proof.json) verifies all 856 original rule records across 25 protected paths remain present, with zero lost records. The current manifest additionally contains 22 function-order records and three empty order fields. The manifest, production verifier and Rust sources were not changed by this test repair.

The original full B4 suite had 1,343 tests, 83 failures and six errors. The [remaining 14 diagnostics](b4/remaining-b4-diagnostics.json) are independently enumerated as nine failures and five errors outside the five repaired modules. This work does not claim the complete B4 suite passed.

## Final formatting and integration boundary

The historical B4 qualification summary's pending-formatter note is superseded by the final formatting receipt below.

The original `just fmt` passed after assembling all 13 changed production/configuration/test/readme files. Every source byte remained unchanged; see [the final receipt](format-final-result.json). Earlier missing-tool and successful initial formatting receipts are preserved separately.

Main and the existing integration branch were not moved by this review. No HIA ref was written and no real branch was deleted. The initial repair head `4a5de714...` has completed with `CI required` FAILURE ([job 136040737571](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44656939483/job/136040737571)) and `Architecture required` FAILURE ([job 136027922992](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44656939517/job/136027922992)). These are initial-head results; the follow-up commit requires its own checks. Main still requires the complete ordinary-source integration and actual successful required checks. Existing unpublished work remains with its current owners; the separately held C2D repair was not applied or retried.
