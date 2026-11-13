## Problem and resulting behavior

A known failed metric could take precedence over missing applicable evidence, turning an incomplete evaluation into an `Ineligible` comparison and permitting a completed `NoUpdate`. This change gives missing applicable evidence precedence while retaining the known failed metrics. Complete eligible and complete negative comparisons retain their meanings. The learning-stage regression keeps the original Training cut at Evaluation when a future window is missing and prevents a NoUpdate receipt.

## Current revision and acceptance state

**Draft / HOLD.** The published source is **`cc57c7198db6293ccca562253c42fffbe2a04633`**, tree **`b7b357c07b5539769a068c6b9b009629f5612d1e`**, sole parent `246d8cb614770252ee42029a5c014f2a4904176a`. Its actual original formatter returned 0 with no further changed paths. Canonical alignment job `1a1d223a60b-2564-1ca3` then completed with normal exit 0, all three source/Git/input audits verified, and all 15,188 physical files unchanged. Root independently checked the complete result and its Git readback before publishing the source with an expected-old-SHA update and `force=false`. The PR remains a draft and unmerged.

**Fresh complete source qualification on `cc57c719` is not yet started at this update.** Exact input preparation is complete; the original source gate budgets remain 600 / 300 / 4,800 seconds with the original 7,200-second outer limit. Evaluator/focused/ordinary/Root qualification follows only a complete source PASS. The first canonical launch call returned a transport timeout; that original observation, the subsequent fixed-path absence, and the later same-request/same-key actual admission are retained separately. The actual admitted job had `reused=false`; no earlier admission is invented.

The complete source-gate run on the **parent `246d8cb6` failed**. Original job `1a1d1e83bd4-2564-1c86` completed normally with exit 1, no supervisor timeout, and complete durable output. Source closure failed, caller self-test passed, and full caller verification passed. Its complete origin physical inventory stayed byte-identical with zero extra entries. Those results remain historical records and are not transferred to `cc57c719`. [Original full run result](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/64b921b3f6031d515883a7ca506207932da3997f/qa/evidence/utility-evaluation-20261112-36fa/final-source-gates-246d-v1/source-handoff.ORIGINAL_RUN_RESULT.original.json), [original handoff result](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/64b921b3f6031d515883a7ca506207932da3997f/qa/evidence/utility-evaluation-20261112-36fa/final-source-gates-246d-v1/source-handoff.RESULT.original.json), [authoritative terminal](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/64b921b3f6031d515883a7ca506207932da3997f/qa/evidence/utility-evaluation-20261112-36fa/final-source-gates-246d-v1/SOURCE_STATUS_05.original.json).

## Changes retained in the candidate

- Preserve incomplete-evidence precedence and the four evaluator regressions while integrating the original-owner paths. A negative retention member cannot be substituted into an eligible primary comparison; complete primary-negative NoUpdate, missing-evidence refusal, fraud and payment remain separate.
- Preserve original authorization, task/source bijection, inclusive expiry and actual readback arguments. The legacy NextUse Trainer reference remains explicit to the conservative caller collector.
- Retain all 569 caller boundaries. The final protected-row inventory has 422 rows: 39 existing rows synchronized to the actual formatted owner interfaces, 10 additional rows, and the other 373 old rows unchanged. Existing forbidden markers and authorization flags are preserved.
- The parent revision retained all 184 existing QA methods across the complete 21-file inventory: 17 explicit interface migrations and 167 byte/AST-identical methods, plus 18 additional mechanism checks. Its 11-file non-Rust application covered CALLERS, its exact allowlist hash and nine QA files. The subsequent five-file repair described below preserves the complete method inventory.
- Preserve the independently discovered V1 scope gap as a failed coverage claim. V1's local 18-method PASS did not reach 21 of 34 scope guards. V2 adds a three-line loop in one existing new method; the same 18 methods then passed, and 234 actual observations covered all 34 scopes across 20 paths. The full source gate below remains the acceptance gate.

The original scoped fix succeeded. Its formatter produced 43 Rust postimages, independently reviewed as formatting changes. After the final 11-file application, the original formatter ran again with its original 900-second limit and changed no further source files. The first final-format attempt was rejected by the unchanged active-build guard before application; that exit-1 result and all later transport observation failures remain preserved. [Final-format actual records and scope reviews](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ce82fdbdd257354aef4309548c3bf37191a2ad7c/qa/evidence/utility-evaluation-20261112-36fa/README.md#actual-outcomes-retained-in-this-increment).

## Historical complete validation on parent `246d8cb6`

| Gate | Observed result |
| --- | --- |
| Final original formatter | Return 0; no additional changed paths; complete source/Git/input audits verified |
| Canonical index/HEAD alignment | Normal exit 0; all three audits verified; 15,188 physical files, bytes and modes unchanged |
| Source closure, original 600-second limit | **FAILED, return 1**, no timeout or output limit. Command elapsed 372.612 seconds; unittest footer 368.255 seconds; complete outer stage 385.076 seconds |
| Caller self-test, original 300-second limit | **PASS**, return 0 |
| Full caller verification, original 4,800-second limit | **PASS**, return 0; complete outer stage 494.140 seconds |
| Entire source-gate run | **FAILED**, normal exit 1; source unchanged |
| Full eval / focused / ordinary / Root | **Not started** |

The complete raw source log contains 492 test methods: **488 explicit `ok` methods and four failed methods, producing six failure entries** because one method has three failed subtests. The original recorder's `observed_passed_tests=486` / `observed_failed_tests=6` fields remain unchanged; they are not relabeled as independent method counts. [Original source-closure receipt](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/64b921b3f6031d515883a7ca506207932da3997f/qa/evidence/utility-evaluation-20261112-36fa/final-source-gates-246d-v1/source-closure.original.json), [complete original log](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/64b921b3f6031d515883a7ca506207932da3997f/qa/evidence/utility-evaluation-20261112-36fa/final-source-gates-246d-v1/source-closure.raw.original.log).

### Source failures and the five-file repair in `cc57c719`

1. The observer constraint inventory includes `fn require_profile(`, while the old exact expected-function set omits it.
2. The Selection mutation still targets the old `None => OPERATION` spelling and does not reach its formatted target.
3. The read-only Training attack inserts `Host::recover_original_custody()` into three adapters, but the protected verifier does not reject those mutants. This needs a substantive protection review; it is not classified as only a formatting discrepancy.
4. The actual workflow selects 33 Root parents, while the older source test expects 32.

These failures remain preserved. The new revision makes five reviewed non-Rust changes: append the actual `recover_original_custody` identifier to the existing forbidden lists of all three Training readback adapters; append the exact new CALLERS hash to the allowlist; include the existing observer `require_profile` interface; adapt the Selection branch mutations to its current `if` / `else` implementation and add a same-length evaluated-domain mutation; and include the already-existing workflow Root parent in the expected set. Existing forbidden markers, closed caller boundaries, authorization flags, original Training mutations and all original test methods remain.

The four previously failed original source-check methods passed a local targeted diagnostic. Nine isolated custody probes were rejected by the protected-file verifier. These are scoped mechanism observations, not complete fresh source qualification or a compiled runtime authorization result. Actual application/formatting job `1a1d2107dce-2564-1c98` applied exactly the five reviewed files, then original formatting returned 0 with no additional changes. All original source gates must still run against `cc57c719`.

## Remaining qualification and utility limits

The reviewed repair is now applied and the exact source is frozen. Run the original complete gates on `cc57c719`. Keep source closure 600, self-test 300 and full caller 4,800 seconds; the source supervisor's original 7,200-second outer limit was recovered from the actual prior request. Preserve the original native 45,000-second outer request, all 14 phase limits, unfiltered eval inventory, four required regressions, focused/ordinary/Root order, 8 MiB stack, nextest defaults/overrides and zero retries. The actual workflow supplies the Root case inventory.

Historical `c0f…` results remain historical: evaluator 163/163 passed, focused native had 81 pass / 28 fail, source closure failed at its 600-second limit, caller self-test/full verification passed, and later ordinary/Root stages did not start. None is transferred to the new commit.

**Real qualified authorized A → original Training owner → independent B → Adopt or complete NoUpdate → new C → daemon and Root cold-recovery task chains remain 0.** Mechanism tests do not establish an external utility gain, strongest deployable comparator, independent real task evidence, deployed adoption, full cost closure or original authorization. Adopt, complete NoUpdate/Ineligible, InsufficientEvidence/Unknown and reproducible Objective Fraud retain distinct meanings.

## Evidence checkpoint

The latest published evidence checkpoint still describes the earlier completed source-run window; later `cc57c719` records are being appended separately. That checkpoint is **`64b921b3f6031d515883a7ca506207932da3997f`**, root tree **`111c1310c8b440afdba8e5ff4a302bf01d5d7399`**, with **2,841 files**. It adds the complete failed source-run core originals, independent readbacks, exact canonical inventory recovery and verified PR publication. The earlier 2,793-file checkpoint retains its original **2026-11-12 22:38:05 UTC** cutoff; later source results are appended here. [Complete source-result checkpoint](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/64b921b3f6031d515883a7ca506207932da3997f/qa/evidence/utility-evaluation-20261112-36fa/README.md).

All 2,792 previous non-README paths retain their exact blobs. The old README and previous PR body are archived. Exact postimage/inventory recovery matches original byte lengths, SHA256, Git identities, gzip bytes and parts; it is not claimed as a second native full read. Earlier failed attempts and Unknown observations remain intact.

At the dated 22:37:01–22:38:05 hosted observation, the exact head had zero check runs, check suites, status contexts and workflow runs, with combined state **pending**. That is not hosted CI PASS. [Dated hosted-CI evidence](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/ce82fdbdd257354aef4309548c3bf37191a2ad7c/qa/evidence/utility-evaluation-20261112-36fa/qualification-final/hosted-ci-246d/REVIEW.json).
