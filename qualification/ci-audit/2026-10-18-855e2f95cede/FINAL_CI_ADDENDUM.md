# Final CI addendum — 2026-10-18 16:24–16:25 UTC

This is a new read-only observation after the frozen CI archive. It does not modify or replace the earlier 15:27 / 15:37 snapshots. Both published PR head/base/merge identities are unchanged.

## Current exact-head results

| PR | Source HEAD | Base SHA | Latest jobs | Required context state |
|---|---|---|---|---|
| [#2599](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2599) | 19c5cd41c17dd42da7afac96203a4bc7901e23a6 | f8c9419df6ddeb36ff8b522a50219981fb8d9345 | 10 queued, 1 success | CI required and Architecture required absent |
| [#2714](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2714) | f191cd081ba16fed8827a18093b5a5b39e9a36cd | e08323af4805ed9a8d14afabf2212923195f2156 | 4 queued, 1 running, 1 success | CI required and Architecture required absent |

Total: **17 jobs = 14 queued + 1 in progress + 2 success; 0 failure, 0 skipped.** Check runs total 18: #2599 has 12 and #2714 has 6. Both legacy status collections are empty. Every returned run/check/job source SHA matches its current head. Explicit pages and total_count agree for every collection and latest-attempt job list; all attempts are 1.

Main's two required context names were verified earlier through its branch GET. Research base branch protection remains NOT_ACCESSIBLE; its workflows define the same two aggregator names. Neither target can be called fully qualified from these observations. #2599 is open/non-draft/blocked; #2714 is open/draft/unstable.

## Fresh passing execution and exact scope

[Stem/Reader bridge run 39140341736](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39140341736), [job 117713314591](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39140341736/job/117713314591), executed on GitHub Actions 1000168255 from 16:23:00 to 16:23:09 UTC. The decoded log directly pins checkout to f191cd081ba16fed8827a18093b5a5b39e9a36cd (lines 35, 101, 122). Two suites actually ran:

- `python3 -m unittest discover -v -s qualification/stem-transfer-cell-artifact-p0 -p 'test_*.py'`: 27 tests, OK, log lines 156–158.
- `python3 -m unittest discover -v -s qualification/neuron-shared-encoder/tests -p 'test_*.py'`: 109 tests, OK, lines 274–276, including the new calibration class and strict authority-marker regressions.

These are fresh contract regression executions at the published source head. They establish neither the requested 40 calibration + 72 nine-arm real model runs nor a native Rust / three-platform / required-check pass. No new model calls were performed.

[#2599 Analyze(actions), job 117713672557](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39140464867/job/117713672557), executed from 16:21:49 to 16:22:49 UTC on GitHub Actions 1000168240. Its log confirms source 19c5cd41c17dd42da7afac96203a4bc7901e23a6 (lines 110, 140) and successful analysis result upload (1465, 1469). This is Actions-language CodeQL coverage. Four language jobs remain queued.

The additional GitHub Advanced Security [CodeQL check 117726100554](https://github.com/TrillionniumFoundation/hepta-private-ci/runs/117726100554) is **neutral**, with title "4 configurations not found". Its output states that C/C++, JavaScript/TypeScript, Python and Rust configurations present on main have not yet been found for the PR. This is not full CodeQL success and is consistent with those four queued analyses; it is not yet evidence that a new source fix is needed.

The #2714 laya-reader-intake job 117713314446 was in progress at 16:25:06 UTC, runner GitHub Actions 1000168266, actual start 16:24:39. Its eventual outcome was not polled again. The contract sibling is queued. #2714 blocking-ci run 39140341708 is pending and has no jobs. Architecture source/head and base/merge jobs remain queued for both PRs.

## Evidence and limitations

Raw pages are in `final-head-runs-checks-statuses-jobs.json`; compact machine receipt is `final-ci-checkpoint.json`. Decoded fresh logs are `job-117713314591.log` and `job-117713672557.log`. Every collection was queried once, with complete pagination. The API is not transactional: the Future OOD workflow was queued at its earlier run read while its Reader job had entered in_progress at the later job read. Per-response UTC timestamps are retained.

The development-profile CI versus 26 retained strict qualification map failures distinction remains unchanged. No old failure is attributed to these new runs without actual failing execution. Current source/base/merge SHA equality with earlier observations does not make a queued required lane successful.

The original 2,353,920-byte archive remains frozen, SHA-256 809b6e2427b2daa6543c44daeaba8869bed5a09ed458cd9cef5b4a11eb554fbd. This addendum is separate. All three CI-agent upload requests were explicitly interrupted without a success response or recoverable cell: whole file 1174.6 s, 180,000-byte part 552.2 s, 49,152-byte part 291.3 s. No automatic approval rejection was received. Root has taken over archive publishing; this agent stopped create_blob and makes no background-upload claim.

Research remains **SHADOW_ONLY / DENY_ALL / NO_GO**. Required checks have not closed. No rerun, dispatch, cancellation, ref update, merge or production activation was performed by this CI auditor.
