# CI matrix: latest repair heads and earlier failure evidence

Latest later observation: see [FINAL_CI_ADDENDUM.md](FINAL_CI_ADDENDUM.md) and [final-ci-checkpoint.json](final-ci-checkpoint.json) for 16:24-16:25 UTC exact-source results. Earlier rows below retain their original head and observation time.

## Pushed source heads, second observation

Observed 2026-10-18 15:37-15:38 UTC. Source identity, pagination totals and latest attempt 1 were checked.

| PR | Source head | Base observed | Runs / checks / jobs | Current observed state |
|---|---|---|---:|---|
| #2599 | 19c5cd41c17dd42da7afac96203a4bc7901e23a6 | f8c9419df6ddeb36ff8b522a50219981fb8d9345 | 4 / 11 / 11 | All jobs queued |
| #2714 | f191cd081ba16fed8827a18093b5a5b39e9a36cd | e08323af4805ed9a8d14afabf2212923195f2156 | 5 / 6 / 6 | All jobs queued |

The 9 runs consist of 8 queued and 1 pending. CI required and Architecture required have not been generated; absence is not success. No execution event occurred between the first and second observations.

Current prospective merge objects have the expected source/base parents and trees equal to the source trees. Their merge commit SHAs differ from source SHAs by design; full identities are in ci-evidence.tar.gz.

## Actual local validation

| Scope | Result | Qualification limit |
|---|---|---|
| #2714 final package | 109 tests pass, 0 fail/error/skip | Synthetic Python contracts, no model inference |
| Independent frozen stages | 98 and 102 tests pass | Separate overlapping stages, not added to 109 |
| Independent final repairs | 5 calibration + 10 harness focused tests pass | Verified original negative cases are rejected |
| #2599 formatting / diff / derived check | PASS | Rust 1.95.0 and canonical just fmt; no native compiler qualification |
| Four repaired source maps | PASS | Strict source identity/object checks |
| All module-map qualification | FAIL, 26 modules | main 29 -> source-only 30 -> final 26 |
| Native Cargo/Clippy/three platforms | BLOCKED_EXTERNAL, not started | No available native build disk |

Required main contexts observed through the branch summary are CI required and Architecture required (app 15368). The full protection endpoint returned 403, so no unseen rule is assumed satisfied. The local strict qualification profile is separate from current workflow development gates.

## Earlier selected-subject evidence

The following source report retains its original timestamps and HEADs. It is not an all-PR or full-history CI inventory.

# Hepta P0 CI matrix

Observed via GitHub plugin during 2026-10-18 14:19–14:26 UTC. This is the assigned scoped audit: main plus PRs 2688, 2695, 2815, 2789, 2790, 2813, 2805, 2812, 2814. Repository-wide enumeration is owned by the inventory agent. A changing live snapshot cannot be presented as one atomic repository state.

## Required contexts and access

The main branch endpoint reports protected=true and required contexts `CI required` and `Architecture required`, each app_id 15368, enforcement_level non_admins. Full protection GET returns 403 (integration access); rulesets collection returns []; runner endpoint is outside connector allowlist (400), with no native runner inspection tool available. Organization concurrency, groups, online/busy inventory and policy cannot be verified through this connection. See `access-limitations.json`.

## Exact subject snapshot

| Subject | HEAD | Base | Draft | CI required | Architecture required | Check count |
|---|---|---|---|---|---|---:|
| main | f8c9419df6ddeb36ff8b522a50219981fb8d9345 | — | — | failure (job 117341361996) | ABSENT | 102 |
| 2688 | b5e61ecb07adcc7e41928a3ba27ca78dcde03aaf | f8c9419df6ddeb36ff8b522a50219981fb8d9345 | true | ABSENT | ABSENT | 6 |
| 2695 | 29fceb086d0f8cc9073664f38ae6dd419a933f03 | f8c9419df6ddeb36ff8b522a50219981fb8d9345 | true | ABSENT | queued (job 117693251117) | 57 |
| 2815 | 2be5fc052ae7b2e9fb08c68a3ae7e5a218ad37d5 | f8c9419df6ddeb36ff8b522a50219981fb8d9345 | true | failure (job 117680130373) | success (job 117664527740) | 24 |
| 2789 | 59ed05c0c79ebc73834aa48ace640a86a710843b | 42d9242f2a92759948344036782cfca60596e8e9 | true | ABSENT | failure (job 117691258485) | 52 |
| 2790 | 55ad95747cec6d7bf122b1e825eda25fc08f4b36 | 80ae29ceee332b671567a8e6fae9920291740b3b | true | ABSENT | ABSENT | 48 |
| 2813 | 88994f6bf50e4336beca3d5ce2c760192ea523a6 | f8c9419df6ddeb36ff8b522a50219981fb8d9345 | true | ABSENT | success (job 117683580571) | 50 |
| 2805 | e29db69ff115d1dcf5778e84ba5ff8e715fc472b | 1ead6fff98e7dc84674068203a3fc575538d88c4 | true | ABSENT | ABSENT | 6 |
| 2812 | 20b3162b653f34bb3a0e3505b14c5fa1ecf68b89 | 1237f261ccaa959c41ec9e0cd5a1a16b364697a5 | true | failure (job 117672792680) | success (job 117646356147) | 44 |
| 2814 | 8f6391412a53f60a215ed2a08153fce3d2fdde10 | 4b4d8a1792b3489c389d695012099e034aabe51b | true | failure (job 117661252226) | success (job 117645391734) | 18 |

All nine audited PRs remain open/unmerged/draft. No subject has completed the user’s full exact-head acceptance. The main branch has a failing blocking-ci run 38827238859 (attempt 2) and failing postmerge-ci run 38827238622 (attempt 2).

## Workflow/run enumeration

Runs were fetched with head_sha, per_page=100, page=1, without event filtering. Each exact-head returned total_count below 100, so every run for each requested head was obtained. main returned 18 runs including 15 scheduled skips; each PR returned 3–5. Check runs used per_page=100 and explicit page; main total_count=102 required page 2 (2 rows). Other check collections each fit one page. Every non-schedule run's latest-attempt jobs was fetched with filter=latest, per_page=100, page=1; each total_count matched the returned length. Legacy commit status API returns state=pending with total_count=0 for all ten subjects, which is absence of legacy statuses, not a replacement for check-run results.

| Subject | Workflow | Run ID | Event | Run status at retrieval | Conclusion | Latest jobs | Job conclusions/statuses |
|---|---|---:|---|---|---|---:|---|
| main | Push on main | [38827238382](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38827238382) | dynamic | completed | success | 5 | {"success":5} |
| main | blocking-ci | [38827238859](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38827238859) | push | completed | failure | 37 | {"failure":6,"cancelled":12,"success":17,"skipped":2} |
| main | postmerge-ci | [38827238622](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38827238622) | push | completed | failure | 45 | {"cancelled":3,"failure":26,"success":11,"skipped":5} |
| 2688 | Hepta architecture convergence | [39134607112](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39134607112) | pull_request | pending | — | 0 | {} |
| 2688 | v8-canary | [39134607103](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39134607103) | pull_request | queued | — | 1 | {"queued":1} |
| 2688 | blocking-ci | [39134607134](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39134607134) | pull_request | pending | — | 0 | {} |
| 2688 | PR #2688 | [39134605111](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39134605111) | dynamic | queued | — | 5 | {"queued":5} |
| 2695 | Hepta architecture convergence | [39130704956](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39130704956) | pull_request | queued | — | 3 | {"success":2,"queued":1} |
| 2695 | blocking-ci | [39130704874](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39130704874) | pull_request | queued | — | 33 | {"success":8,"failure":1,"queued":14,"in_progress":6,"skipped":4} |
| 2695 | v8-canary | [39130704775](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39130704775) | pull_request | queued | — | 15 | {"success":1,"cancelled":4,"in_progress":6,"queued":4} |
| 2695 | PR #2695 | [39130702791](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39130702791) | dynamic | queued | — | 5 | {"success":4,"queued":1} |
| 2815 | Hepta architecture convergence | [39114831280](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39114831280) | pull_request | completed | success | 3 | {"success":3} |
| 2815 | v8-canary | [39114831265](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39114831265) | pull_request | completed | success | 3 | {"success":1,"skipped":2} |
| 2815 | blocking-ci | [39114831266](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39114831266) | pull_request | completed | cancelled | 12 | {"success":4,"cancelled":1,"skipped":6,"failure":1} |
| 2815 | PR #2815 | [39114829499](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39114829499) | dynamic | completed | success | 5 | {"success":5} |
| 2789 | blocking-ci | [39130415282](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39130415282) | pull_request | queued | — | 33 | {"success":9,"failure":8,"in_progress":8,"cancelled":1,"skipped":4,"queued":3} |
| 2789 | Hepta ZIP 9 RustSec resolution (diagnostic only) | [39130415230](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39130415230) | pull_request | completed | failure | 2 | {"failure":1,"success":1} |
| 2789 | v8-canary | [39130415275](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39130415275) | pull_request | in_progress | — | 14 | {"success":1,"cancelled":9,"in_progress":3,"skipped":1} |
| 2789 | Hepta architecture convergence | [39130415255](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39130415255) | pull_request | completed | failure | 3 | {"failure":2,"success":1} |
| 2790 | Hepta Keyring Sync Security Migration (Draft) | [39131624051](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39131624051) | pull_request | queued | — | 3 | {"success":1,"queued":2} |
| 2790 | blocking-ci | [39131624144](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39131624144) | pull_request | queued | — | 29 | {"success":3,"queued":22,"in_progress":1,"skipped":3} |
| 2790 | Hepta architecture convergence | [39131624022](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39131624022) | pull_request | in_progress | — | 2 | {"in_progress":1,"failure":1} |
| 2790 | v8-canary | [39131624034](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39131624034) | pull_request | queued | — | 14 | {"success":1,"queued":12,"skipped":1} |
| 2813 | blocking-ci | [39128125730](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39128125730) | pull_request | queued | — | 36 | {"success":16,"failure":5,"cancelled":10,"skipped":4,"queued":1} |
| 2813 | v8-canary | [39128125688](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39128125688) | pull_request | completed | success | 3 | {"success":1,"skipped":2} |
| 2813 | Hepta Windows federated final-use regression | [39128125635](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39128125635) | pull_request | completed | success | 2 | {"success":2} |
| 2813 | Hepta architecture convergence | [39128125660](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39128125660) | pull_request | completed | success | 3 | {"success":3} |
| 2813 | PR #2813 | [39128123642](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39128123642) | dynamic | in_progress | — | 5 | {"success":4,"in_progress":1} |
| 2805 | Hepta architecture convergence | [39134370981](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39134370981) | pull_request | queued | — | 2 | {"queued":2} |
| 2805 | blocking-ci | [39134370594](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39134370594) | pull_request | queued | — | 3 | {"queued":3} |
| 2805 | v8-canary | [39134370653](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39134370653) | pull_request | queued | — | 1 | {"queued":1} |
| 2812 | v8-canary | [39110127510](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39110127510) | pull_request | completed | success | 3 | {"success":1,"skipped":2} |
| 2812 | Hepta P4 Cell matrix receipt contract (qualification only) | [39110127440](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39110127440) | pull_request | completed | success | 1 | {"success":1} |
| 2812 | Hepta architecture convergence | [39110127453](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39110127453) | pull_request | completed | success | 3 | {"success":3} |
| 2812 | blocking-ci | [39110127407](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39110127407) | pull_request | completed | failure | 37 | {"success":11,"failure":10,"cancelled":8,"skipped":8} |
| 2814 | v8-canary | [39110309596](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39110309596) | pull_request | completed | success | 3 | {"success":1,"skipped":2} |
| 2814 | blocking-ci | [39110309530](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39110309530) | pull_request | completed | failure | 12 | {"success":4,"failure":2,"skipped":6} |
| 2814 | Hepta architecture convergence | [39110309505](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39110309505) | pull_request | completed | success | 3 | {"success":3} |

## Interpretation constraints

* PRs 2815, 2813, 2812, 2814 show v8-canary workflow success with only metadata success and two build jobs skipped. This is not V8 build coverage or model evidence.
* PR 2813's dedicated Windows federated final-use regression has two genuinely successful jobs, and Architecture has both source-head/base-merge lanes plus its required aggregator success. Its blocking-ci still has real Windows/macOS Clippy and Windows test failures.
* PR 2815 blocking-ci was cancelled and its required aggregator failed; Architecture success cannot close admission acceptance.
* PR 2814 scoped native job failed but its log returns GitHub BlobNotFound; cause remains unknown rather than attributed to source or infrastructure by guess.
* Exact event base may differ from the current movable target branch during long queue waits. PRs 2789/2790 Architecture base-merge identity checks fail before tests. These fail-closed results must be preserved.

## Scoped queue observations

The 389 unique fetched jobs cover selected runs only. Their status counts are {"failure":63,"cancelled":48,"success":128,"skipped":52,"queued":72,"in_progress":26}. Job labels and runner_name are retained in jobs-RUN.json, but these counts are not organization occupancy. Run queued/pending status can coexist with already-executing child jobs; queue root cause requires runner and workflow concurrency evidence unavailable here.

Raw subject metadata/checks live in SUBJECT.json; jobs in jobs-RUN.json; decoded job logs in job-JOB.log; failures to fetch logs in job-JOB.error.json. SHA/source line references are conclusions of this audit, not new local build validation.



## Raw-log storage update

At 2026-10-18 15:13 UTC, twelve audit-owned large job logs were losslessly gzip-compressed and their original copies removed after full decompression/SHA-256 verification. For a missing `job-ID.log`, read `job-ID.log.gz`; `compressed-logs-manifest.json` maps exact names, lengths and hashes. No remote evidence or unique log bytes were discarded.

## Final published-head observation

At 16:24:26-16:25:06 UTC, the same two repair heads have 17 jobs: 2 success, 14 queued, 1 in_progress, 0 failure and 0 skipped. The f191cd08 Stem/Reader contract job actually ran 27 + 109 Python contract tests successfully. The 19c5cd41 Actions CodeQL analysis completed; the other four languages are queued and the additional CodeQL summary is neutral. Both expected workflow aggregator checks remain absent. Main's required context names were verified; complete protection for the research target was not accessible. No merge qualification or model experiment completion is inferred.

## Later terminal Reader observation (separate from the full matrix snapshot)

At 2026-10-18 16:46 UTC, exact-source run 39140341757 attempt 1 and both jobs were completed/success. Reader job 117713314446 actually executed 64 frozen Laya typed-choice calls from 16:24:39 to 16:27:02 UTC on f191cd081ba16fed8827a18093b5a5b39e9a36cd. Artifact 12143240868 and its three JSON receipts were hash-verified; root independently recomputed row counts/scores/tokens. No full required-check matrix refresh was performed, so earlier 17-job snapshot totals retain their original observation time. See LAYA_TERMINAL_CHECKPOINT.json / ROOT_LAYA_VERIFICATION.json. The 40+72 nine-arm qualification and all production gates remain open.

## Final pre-repair snapshot and subsequent a472 correction

[PRE_REPAIR_CI_SNAPSHOT.md](PRE_REPAIR_CI_SNAPSHOT.md) covers 17:36:53-17:37:42 UTC, 9 runs / 53 checks / 52 jobs on 19c5 and f191. Totals: 15 success, 1 failure, 1 cancelled, 7 skipped, 27 queued, 1 in_progress. Source job 117713683668 failed with two E0599 errors introduced in the fixture patch. Base-merge planning success and metadata-only v8 success do not replace that native failure.

The two-line correction and original strict map refresh are pushed as e69455587d2709c34b6b1832ed1aa4fca9025aeb and a4728553d2f09242640400719d82257bc9c63c73. [POST_REPAIR_CI_CHECKPOINT.json](POST_REPAIR_CI_CHECKPOINT.json) binds the new head: at 18:00 UTC, 6 checks / 6 jobs, all queued, 0 legacy statuses, CI required / Architecture required absent. Run collection was read at 17:56 UTC; the snapshot is explicitly non-atomic. New blocking run 39151714945 and architecture run 39151714876 remain incomplete. Full native tests were not run locally; the locked-version reduced compiler reproducer is separately scoped in PR2599_CONTEXT_REPAIR.json.
