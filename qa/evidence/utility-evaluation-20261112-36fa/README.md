# Real utility evaluation — exact-source evidence

**Draft / HOLD. Current source has a real source-closure failure; the next repairs are reviewed preparations, not executed source.**

This branch preserves evidence for [PR #6203](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6203). Source is **`e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd`**, tree **`b607ff5f50812c5e0f932d7dae18d4c74f1269cb`**, with ordered parents `19aa601fa09321f1b6d1b3ff3b4d422908004e48` and fixed dependency `726af8f4a345a2ffb148b971f3fa16c71436862d`. Evidence-only commits are separate from the source PR.

Checkpoint assembled at **2026-11-12 10:00:54 UTC**. [Previous checkpoint](checkpoints/README-dc15404d.md) preserves preparation and canonical-object details; [the earlier historical checkpoint](checkpoints/README-e672a185.md) preserves original failures, observations and lost-record limits.

## Fresh e8 execution results

| Check | Actual result and scope |
| --- | --- |
| Canonical checkout | All 14,741 source files matched by Git blob/mode; original canonical commit body imported and read back; no source-byte changes; clean e8 HEAD. |
| Scoped agentd + eval fix | Exit 0 on exact e8; clean before/after. |
| Formatting | Exit 0 on exact e8, empty raw output; complete source inventory unchanged. |
| Complete eval library | **163 passed, 0 failed, 0 skipped**, 09:35:08–09:35:39 UTC. Fresh JUnit contains all four incomplete-evidence regressions. |
| Source closure | **Failed**, original command exit 1 after 181.765s, not a timeout. Source stayed clean and complete before/after inventories match. |
| Caller self-test | Passed in the separate source-gate run; original records are being attached by its owner. |
| Full caller verifier | Running under the original 4800-second budget; no terminal result inferred. |
| Original focused / ordinary / Root native suites | Running. Helper build completed; the actual lib-test compilation/link is in progress. No behavioral pass count inferred from compilation. |
| Independent old-comparator control | Prepared, not yet executed on this source. |
| GitHub CI | Latest direct workflow/check observation returned zero new-head runs; no CI pass claimed. |

The [original eval execution JSON](native/e8/eval-lib.json), [fresh JUnit collection summary](native/e8/eval-lib.summary.json), [complete case-name coverage](native/e8/eval-lib.coverage.json), [original XML](native/e8/eval-lib.xml.gz) and [complete original raw output](native/e8/eval-lib.log.gz) are preserved. Both archives have exact base64 companions. [Independent root verification](native/e8/EVAL_LIBRARY_JUNIT_INDEPENDENT_REVIEW.json) decoded and hashed the original XML, checked all 163 unique cases, zero failure/error/skip elements, exact four regressions and unchanged clean source identity. These are new e8 executions, not old counts transferred to a successor.

The original [fix](native/e8/fix.json), [format](native/e8/fmt.json) and [EXACT_CHECKOUT](native/e8/EXACT_CHECKOUT.json) records retain actual commands and source identities. The preparation log and byte checks remain separately identified in the earlier checkpoint.

## Actual source-closure failure

The [unchanged original run record](source-gates/e8/source-closure.json), [complete 144,917-byte raw output](source-gates/e8/source-closure.log), [terminal gate-final record](source-gates/e8/source-closure-final.json) and [original retained-package manifest](source-gates/e8/source-closure-retained-manifest.json) retain the failed run.

Unittest reports **Ran 357 tests; errors=28**. The raw log contains **343 explicit `... ok` results** and **14 unique test methods producing 28 error records**, including subtest errors. The original runner's aggregate fields are `observed_passed_tests=329` and `observed_failed_tests=28`; those fields are preserved verbatim and are not represented as a count of 329 independently observed passing methods.

Every error points to the same strict required-order sequence for `cell_q24_training_model_lane.rs`. Two CALLERS entries still require nested `if owners` syntax after Clippy combined the existing conditions into `if source_bound && owners...is_err()`. The checks and short-circuit behavior remain present in the Rust source. A two-leaf marker alignment and exact large-blob hash allowance are under independent review; no QA assertion, caller set, protected condition or current execution is being changed. The full raw contains zero PermissionError instances; a temporary permission hypothesis was rejected by evidence.

The original source-gate [launch record](source-gates/e8/LAUNCH.json) binds the unique independent checkout/run identity. The current full caller run continues against unchanged e8; future repair results cannot overwrite this failure.

## Exact-source audit and separate retention repair

[ORDINARY_INTEGRATION_ADDENDUM_E8B6.md](ORDINARY_INTEGRATION_ADDENDUM_E8B6.md) supplies 58 exact-source references and a core object index. It updates the earlier audit: strict Root evaluated-retention 4/5/6 metadata authentication and return of the same original T/E connections are implemented. Actual ordinary Version/live-read/Selector/C profiles, startup owner assembly and semantic recovery routing still contain concrete fail-closed gaps.

The audit found a second issue: complete primary Eligible plus complete retention Ineligible can reach two composition boundaries that derive a positive result from the primary alone. No actual erroneous ordinary Adopt has been reproduced. The reviewed [two-file patch](repairs/retention-guard/PREPARED.patch), [manifest](repairs/retention-guard/PREPARATION.json) and [independent byte/diff review](repairs/retention-guard/INDEPENDENT_REVIEW.json) are **not yet applied to the source and have not executed**.

That preparation adds 22 lines inside the existing panel and final material-verification boundaries. It refuses an incompatible Qualified combination while preserving all original member results. It does not call a complete comparison missing data, fabricate an aggregate NoUpdate, rewrite frozen PrimarySuperiority roles, grant authority or infer fraud. A complete primary-negative NoUpdate and existing unknown-evidence refusals retain their meanings.

The existing original provider fixture honestly computes Ineligible. It has not been changed to manufacture a positive qualification or expose opaque seals. A full-signature positive-primary/negative-retention execution counterexample is not supplied by this preparation; current negative/unknown mechanism tests and independent predicate review have their stated limits.

## What remains unqualified

The external objective, predictor/policy/critic, signed observed outcomes and public reward contract remain distinct. A bundle digest and independent signing keys do not establish full deployment utility, strongest deployable comparison, lifecycle costs, institutional/training/task independence, causal identification, sustained material availability, legal authorization or actual consumption.

The current cost scope explicitly stops before final holdout/signature/publication work. The original deterministic action adapter does not establish changed-action support. The audit details the exact remaining contracts and source boundaries; no higher-level claim is inferred from the software test count.

**Complete real ordinary Adopt = 0. Complete real ordinary evaluated NoUpdate = 0. Complete real daemon + Root cold-recovery qualification = 0.**

Historical cloud 19aa terminal records remain Unknown, and the old cloud eval raw/JUnit remain Unavailable. Actual original desktop failures, recovered bytes and new executions remain separately attributable. Large original desktop inventories are retained by the execution drivers and are being exported; an unlisted archive is not claimed already present in this branch.
