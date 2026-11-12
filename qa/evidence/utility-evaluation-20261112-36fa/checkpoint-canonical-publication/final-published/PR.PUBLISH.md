## Problem and resulting behavior

A known failed metric could take precedence over missing applicable evidence, turning an incomplete evaluation into an `Ineligible` comparison and permitting a completed `NoUpdate`. This change gives missing applicable evidence precedence while retaining the known failed metrics. Complete eligible and complete negative comparisons retain their meanings. The learning-stage regression keeps the original Training cut at Evaluation when a future window is missing and prevents a NoUpdate receipt.

## Current revision and acceptance state

**Draft / HOLD.** The published source is **`246d8cb614770252ee42029a5c014f2a4904176a`**, tree **`d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087`**, sole parent `9c4a11f61d30e9cc352bf44d56c98909d202a55d`. Its complete native source was aligned and independently read back; the subsequent source-branch update used the expected old SHA and `force=false`. The PR remains unmerged. [Source publication and exact alignment evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ce82fdbdd257354aef4309548c3bf37191a2ad7c/qa/evidence/utility-evaluation-20261112-36fa/README.md).

**The first complete source-gate run on this exact revision failed.** Original job `1a1d1e83bd4-2564-1c86` completed normally with exit 1, no supervisor timeout, and complete durable output. All three original source entrypoints ran: source closure failed, caller self-test passed, and full caller verification passed. The origin source's complete physical inventory stayed byte-identical with zero extra entries. Native evaluator/focused/ordinary/Root qualification has not started. [Original full run result](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/96ca7c7728c7ac3944782abc0d219dd75a8b9f75), [original handoff result](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/110ab48579e159301900daa663d289964a63bc34), [authoritative terminal](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/bcc7b94d9f9f721f6592632db5a6408468014270).

## Changes retained in the candidate

- Preserve incomplete-evidence precedence and the four evaluator regressions while integrating the original-owner paths. A negative retention member cannot be substituted into an eligible primary comparison; complete primary-negative NoUpdate, missing-evidence refusal, fraud and payment remain separate.
- Preserve original authorization, task/source bijection, inclusive expiry and actual readback arguments. The legacy NextUse Trainer reference remains explicit to the conservative caller collector.
- Retain all 569 caller boundaries. The final protected-row inventory has 422 rows: 39 existing rows synchronized to the actual formatted owner interfaces, 10 additional rows, and the other 373 old rows unchanged. Existing forbidden markers and authorization flags are preserved.
- Retain all 184 existing QA methods across the complete 21-file inventory: 17 explicit interface migrations and 167 byte/AST-identical methods, plus 18 additional mechanism checks. The final non-Rust application covers CALLERS, its exact allowlist hash and nine QA files.
- Preserve the independently discovered V1 scope gap as a failed coverage claim. V1's local 18-method PASS did not reach 21 of 34 scope guards. V2 adds a three-line loop in one existing new method; the same 18 methods then passed, and 234 actual observations covered all 34 scopes across 20 paths. The full source gate below remains the acceptance gate.

The original scoped fix succeeded. Its formatter produced 43 Rust postimages, independently reviewed as formatting changes. After the final 11-file application, the original formatter ran again with its original 900-second limit and changed no further source files. The first final-format attempt was rejected by the unchanged active-build guard before application; that exit-1 result and all later transport observation failures remain preserved. [Final-format actual records and scope reviews](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ce82fdbdd257354aef4309548c3bf37191a2ad7c/qa/evidence/utility-evaluation-20261112-36fa/README.md#actual-outcomes-retained-in-this-increment).

## Actual validation on `246d8cb6`

| Gate | Observed result |
| --- | --- |
| Final original formatter | Return 0; no additional changed paths; complete source/Git/input audits verified |
| Canonical index/HEAD alignment | Normal exit 0; all three audits verified; 15,188 physical files, bytes and modes unchanged |
| Source closure, original 600-second limit | **FAILED, return 1**, no timeout or output limit. Command elapsed 372.612 seconds; unittest footer 368.255 seconds; complete outer stage 385.076 seconds |
| Caller self-test, original 300-second limit | **PASS**, return 0 |
| Full caller verification, original 4,800-second limit | **PASS**, return 0; complete outer stage 494.140 seconds |
| Entire source-gate run | **FAILED**, normal exit 1; source unchanged |
| Full eval / focused / ordinary / Root | **Not started** |

The complete raw source log contains 492 test methods: **488 explicit `ok` methods and four failed methods, producing six failure entries** because one method has three failed subtests. The original recorder's `observed_passed_tests=486` / `observed_failed_tests=6` fields remain unchanged; they are not relabeled as independent method counts. [Original source-closure receipt](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/081aa2fc65417aef3a6aa1306e30a7f12b9bfe2a), [complete original log](https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/f84b983ace7dfd3dbe8de0a3972274d0f8a930e3).

### Concrete source failures under review

1. The observer constraint inventory includes `fn require_profile(`, while the old exact expected-function set omits it.
2. The Selection mutation still targets the old `None => OPERATION` spelling and does not reach its formatted target.
3. The read-only Training attack inserts `Host::recover_original_custody()` into three adapters, but the protected verifier does not reject those mutants. This needs a substantive protection review; it is not classified as only a formatting discrepancy.
4. The actual workflow selects 33 Root parents, while the older source test expects 32.

These failures are retained as acceptance failures. The original attacks, budgets, scope and source-state checks remain in force while the smallest justified repairs are reviewed. No repair proposal is described as a passing run.

## Remaining qualification and utility limits

After the source failures are repaired and the exact source is frozen again, run the original complete gates. Keep source closure 600, self-test 300 and full caller 4,800 seconds; the source supervisor's original 7,200-second outer limit was recovered from the actual prior request. Preserve the original native 45,000-second outer request, all 14 phase limits, unfiltered eval inventory, four required regressions, focused/ordinary/Root order, 8 MiB stack, nextest defaults/overrides and zero retries. The actual workflow supplies the Root case inventory.

Historical `c0f…` results remain historical: evaluator 163/163 passed, focused native had 81 pass / 28 fail, source closure failed at its 600-second limit, caller self-test/full verification passed, and later ordinary/Root stages did not start. None is transferred to the new commit.

**Real qualified authorized A → original Training owner → independent B → Adopt or complete NoUpdate → new C → daemon and Root cold-recovery task chains remain 0.** Mechanism tests do not establish an external utility gain, strongest deployable comparator, independent real task evidence, deployed adoption, full cost closure or original authorization. Adopt, complete NoUpdate/Ineligible, InsufficientEvidence/Unknown and reproducible Objective Fraud retain distinct meanings.

## Evidence checkpoint

The published evidence checkpoint is **`ce82fdbdd257354aef4309548c3bf37191a2ad7c`**, root tree **`95478850d90c2738ef6f9d7a56f9db36c820bb10`**, with **2,793 files**. Its cutoff is **2026-11-12 22:38:05 UTC**: it covers final formatting, canonical alignment, source publication and initial qualification admission. The completed source-gate failure above is a later original observation whose raw objects are linked directly pending the next append-only checkpoint.

All 2,267 previous non-README paths retain their exact blobs. The old README and previous PR body are archived. Exact postimage/inventory recovery matches original byte lengths, SHA256, Git identities, gzip bytes and parts; it is not claimed as a second native full read. Earlier failed attempts and Unknown observations remain intact.

At the dated 22:37:01–22:38:05 hosted observation, the exact head had zero check runs, check suites, status contexts and workflow runs, with combined state **pending**. That is not hosted CI PASS. [Dated hosted-CI evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ce82fdbdd257354aef4309548c3bf37191a2ad7c/qa/evidence/utility-evaluation-20261112-36fa/qualification-final/hosted-ci-246d/REVIEW.json).
