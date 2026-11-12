# Utility evaluation evidence — exact e8 failures preserved

Checkpoint: 2026-11-12 10:58 UTC. Source candidate: `e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd`, tree `b607ff5f50812c5e0f932d7dae18d4c74f1269cb`. This branch carries evidence separately from source PR #6203.

## Current conclusion

**The published e8 candidate failed exact-head qualification.** Its source remains frozen and all actual failures are retained. A successor integrating fixed `b29869e856d08db1bfb066116a9c443376ccc57d` is being prepared. Prepared changes and scoped diagnostics are not passed source or native gates.

| Observation | Actual result |
| --- | --- |
| Exact-head fix / formatting | Both exited 0; full source unchanged and clean. |
| Complete eval library | 163 passed, 0 failed, 0 skipped. Full original fresh XML and raw output independently checked. |
| Native focused suite | Original just test exit 100; 100 actual cases, 76 passed, 24 failed, 0 skipped. Seventeen stack-overflow SIGABRTs, three 60-second per-test timeouts, four other failures. Whole command did not time out. |
| Mixed missing-evidence agentd regression | Actually passed in 4.587 seconds. |
| Whole native pipeline | Failed at focused prerequisite, terminal 10:08:49 UTC. All / ordinary / Root were not started. |
| Source closure | Exit 1, 181.765 seconds, no timeout. Original unittest says Ran 357 tests, errors=28. Raw counting: 343 explicit ok methods, 14 unique error methods, 28 error/subtest records. |
| Caller self-test | Passed. |
| Full caller verification | Exit 1, 1,696.925-second stage, no timeout. Unexpected original read-only Training caller requires exact registration/protection repair. |
| External corrected-marker diagnostic | 381 protected rows passed against unchanged e8 source; only a scoped diagnostic, not full source closure or full caller acceptance. |
| Independent old-comparator control | Four actual regression failures, zero passed, original just test exit 100. Only two production comparator files reverted; new tests retained. Ineligible versus InsufficientEvidence assertions are present in fresh XML. |
| GitHub CI | Recorded observation returned zero e8 runs/checks. Live base advanced to b298, and a merge conflict was observed. The earlier cached-base inference is explicitly retracted. |

## Readable evidence

- [Original full source-gate package](source-gates/desktop-e8b6fe2a-v1/README.md), including all 53 original records and seven complete source-inventory checkpoints.
- [Actual source-gate placement manifest](source-gates/desktop-e8b6fe2a-v1/package-map.json). The producer's [original placement manifest](source-gates/desktop-e8b6fe2a-v1/PLACEMENT_ORIGINAL.json) is retained unchanged. Only destination paths gained this branch's established qa/ prefix.
- [Native terminal result](native-e8b6fe2a-v1/RESULT.json) and [focused failure details](native-e8b6fe2a-v1/focused/FAILURE_OBSERVATION.json).
- [Original focused JUnit](native-e8b6fe2a-v1/focused/junit.xml) and [full original focused raw output, gzip](native-e8b6fe2a-v1/focused/focused.raw.log.gz).
- [Original helper archive](native-e8b6fe2a-v1/focused/helpers-evidence.tar.gz), including actual Cargo output, environment/manifest and helper binary. A UTF-8 base64 companion allows exact restoration through text-only transports.
- [Original old-comparator control result](countercontrol-e8b6fe2a-v1/RESULT.json) and [fresh control JUnit](countercontrol-e8b6fe2a-v1/junit.xml). The full original control raw, actual two-file patch and all 65 before/after source inputs are attached. The earlier prepared manifest retains its original 19aa provenance; the actual RESULT and source inventories bind this execution to e8.
- [Independent full focused/control XML review](independent-review/FOCUSED_AND_CONTROL_FRESH_JUNIT_E8B6.json).
- [Canonical e8 alignment inventory reconstruction](canonical-e8b6fe2a-alignment-v1/ROOT_RECONSTRUCTION_REVIEW.json), including original gzip parts and full byte/hash verification.
- [Fixed-b298 semantic merge review](integration-b298/SEMANTIC_MERGE_REVIEW.json).
- [Exact original b298 Git-object transport manifest](canonical-b298-original-objects/manifest.json): 11 original commits, 65 trees and 168 blobs; all object identities independently checked. Transport of original source is not qualification.
- [GitHub CI observation and cached-base retraction](github-ci/E8B6_OBSERVATION_20261112T102012Z.json).
- [Exact e8 ordinary integration audit](ORDINARY_INTEGRATION_ADDENDUM_E8B6.md), whose source-specific claims remain at e8.
- [Historical 103-file checkpoint README](checkpoints/README_103FILES_E8B6_RUNNING.md), preserving the earlier in-progress observation.

## Additional unexecuted preparation

[The seven-case non-stack source audit](nonstack-focused/e8-source-audit.json) preserves the original failures, source identities and unresolved causes. Independent review confirms four fixture postimages: two command waits cross the verifier's inclusive expiry second, one controlled provider clock uses checked expiry plus one, and one original task fixture bijectively aligns whole candidate definitions with immutable source order before signing/freezing. Production checks, signatures, assertions and deadlines are unchanged. These are prepared fixes, not observed native passes; the provider timeout and NextUse transport causes remain unproved.

[Readback caller preparation v1](readback-caller-preparation-v1/REVIEW.md) audits the real original owner/custody chain. Its six exact member additions and three protected rows preserve all prior boundary rows and all 95 original functions across nine QA modules. The local three-row check is a subset diagnostic only; the complete-source four-boundary diagnostic remains pending. A v2 is being prepared to additionally protect both new retention guards, including one previously unprotected model-material file.

[The fixed-b298 Rust overlay](diagnostic-preparation-fixed-b298/RUST_OVERLAY_MANIFEST.json) contains 25 exact in-memory replacements/additions over the complete e8 Rust source set, including seven new files. It is a diagnostic projection with no published source-tree identity. The physical frozen clone must remain unchanged, and the eventual complete gate will run independently on the final source head.

## Source closure and retention preparation limits

The original source-closure runner's 329 derived passed field is preserved verbatim; it is not substituted for the independently observed 343 explicit ok methods. All 28 errors reported two stale required-order markers in the same protected source. No PermissionError occurred; the disproved chmod hypothesis led to no driver or harness change.

The four-path e8 preparation packet is retained as preparation history only. Fixed b298 already contains the corrected marker leaves and additional protocol rows; its full CALLERS manifest must not be overwritten by that older packet. The two independently reviewed retention guards remain separate unpublished preparation: they reject primary Eligible plus non-eligible retention without relabeling complete comparisons as missing data or fraud. No signed positive-primary/negative-retention execution fixture has yet established that branch's behavioral coverage, and no erroneous real ordinary Adopt was reproduced.

## Ordinary utility qualification remains absent

Complete real authorized ordinary Adopt = **0**. Complete real evaluated NoUpdate = **0**. Complete real daemon plus Root cold-recovery qualification = **0**.

Fixed b298 contains additional original evaluated Selector/FinalUse attestation/recovery and measurement-support mechanisms. It still does not supply actual ordinary startup owner assembly, independently sourced B task outcomes, complete deployable-product cost evidence, identified changed-action outcomes, final owner authorization or real new-consumer adoption. Missing original authority remains a refusal. No source, diagnostic, mechanism test or content root substitutes for those observations.
