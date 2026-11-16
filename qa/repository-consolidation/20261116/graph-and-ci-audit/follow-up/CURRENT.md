# Current consolidation checkpoint

Captured 2026-11-16 14:56:30 UTC. This report supplements the immutable earlier reports in the parent directory. Their earlier source heads, protection counts, and test results remain historical evidence.

## Scope and protected branches

The source and reviewed history candidate is `ca414120a713eaa0ecb9d5a75c21b9edf5c922fe`, with tree `c2edb469712d59a01005c97be0009db02d7762b7`. The latest complete graph snapshot used here, captured at 2026-11-16T14:54:53Z, contains 7,315 branch names: main, 84 protected HIA branches, and 7,230 original nonprotected candidates. The candidate contains 1,733 of those original candidate tips by ancestry; 5,497 remain outside it. Ancestry is a history-preservation measure, not a claim of semantic or native qualification.

The 84 protected refs include 21 new `codex/cell-experiments-v2-20261116-0c078a-s01` through `s21` refs whose names do not contain HIA. Protection follows the two designated ancestor markers and the explicit protected inventory. All 84 current protected tips, the 63 previously protected tips, and both markers are excluded from the candidate ancestry. Fresh exact-tip checks are required again before any retirement.

Main remains `732e934ba496d90fbe042b8d41d479ef901643e5`. No branch has been deleted. The integration ref was still `285e971b3af3a93a79169b56a42263069e473057` when this report was prepared. Publishing this review checkpoint does not approve a merge into main.

## Changes reviewed since the earlier report

The 164 earlier audit artifacts were committed at `b653e0934b808be2f4159474d3b1229f1eb4831a`. They remain byte-identical. Subsequent source changes are separated into three commits with exact source maps:

- `095fb1d50cc9ac7e53ea5027cf3cfdd2c86b2feb`: four native diagnostic and development-profile files. The SHA-2 0.10.9 dependency has the same development optimization level as the existing SHA-2 profile. Dependencies, lockfiles, feature selection, debug assertions, deadlines, hashes, durable writes, and test expectations are unchanged. Diagnostics emit closed error categories in test builds.
- `a70540b51842034678171fc2278e7b3ecfcf022d`: four CLI/client authentication diagnostic files. Keys are masked completely; diagnostic copies redact known authentication fields while preserving protocol values. Login failures remain failures, numeric RPC codes remain available, and intentional browser/device instructions are preserved.
- `5fed9dcb99feb6c3037e61eec0cc91c0db22dae2`: 162 caller-manifest storage, consumer, test, and workflow files. A small index and bounded compressed part reconstruct the exact original 2,990,722-byte manifest. Its SHA-256 is `e85c1782b94bd6cf1dd0ff3c10490eacc674b6148530ad9741e027e48d56477f`. All 1,645 boundaries and 819 protected rows are unchanged. The loader checks schema, paths, regular files, byte limits, ordering, lengths, and both compressed and decompressed hashes.

The caller change retains all original verifier decisions: 21 other definitions are identical by AST, and inverse transformations establish that existing B4 assertions and control flow are preserved. The 16 added storage tests cover malformed, corrupted, oversized, and symbolic-link inputs. Workflow scope recognizes only the exact part filename grammar; unknown paths still select full validation. The original 512,000-byte blob policy and allowlist are unchanged.

Six ordinary two-parent merges then retain reviewed Rust histories without changing the source tree. Their exact ordered parents are in `root-six-server-map.json` and the branch review package. Each resolution has a source-specific comparison; there is no blanket choice of the current tree. The preserved changes concern CLI recursion, ZIP fixture and name handling, workspace and migration roots, the locked Rama listener API, Git descendant cleanup, issuer-capacity checks, and bounded TUI retries.

## Validation and practical limits

| Check                                        | Exact source or input scope                                                        | Result                                                                                              |
| -------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Full B4 suite                                | Caller-format tree `c2edb469`; 14,349 pinned inputs                                | PASS: 1,331 tests, including all 1,315 existing tests and 16 new storage tests; zero changed inputs |
| Original whole-checkpoint blob policy        | Base `285e971b` to tree `c2edb469`; 1,376 changed paths                            | PASS with the original 512,000-byte default and original allowlist                                  |
| Formatter after caller storage change        | Exact changed scope on tree `c2edb469`                                             | PASS                                                                                                |
| Original caller-verification CLI             | Exact caller-format candidate; 14,349 pinned inputs                                | PASS: 1,645 boundaries, PASS_HEPTA_CALLER_CLOSED_SET; 1,830.188 seconds; zero changed inputs        |
| Whole-tree spelling and custody              | Separate complete materialization of tree `c2edb469`                               | Pending; earlier changed-scope results do not establish a full-tree pass                            |
| CLI/client formatter and scoped Clippy fixes | `a70540b5`, tree `7ae5fd3b`                                                        | PASS; zero source changes                                                                           |
| CLI login tests                              | Same exact security candidate                                                      | PASS: 6 selected tests; 10 excluded by the focus filter                                             |
| Client authentication diagnostics            | Same exact security candidate                                                      | PASS: 5 selected tests; 5 excluded by the focus filter                                              |
| Both complete library suites                 | Same exact security candidate                                                      | PASS: 26 tests                                                                                      |
| Both complete packages                       | Same exact security candidate; original command with four threads and zero retries | PASS: 666 tests, zero skipped, zero changed inputs                                                  |
| Native Agentd v7 selection                   | `095fb1d5`, tree `85918c80`; 7,749 pinned native inputs                            | FAIL: 26 executed, 10 passed, 16 timed out; 1,584 filtered; exit 100                                |
| Native Agentd v7 formatter                   | Same exact native candidate, original formatter                                    | PASS; source unchanged                                                                              |
| Hosted required checks and CodeQL            | Must run on the published combined head                                            | Pending                                                                                             |

The native v7 run retained the original 60-second test timeout, four test threads, zero retries, and 8 MiB stack. The deep read-only test that failed on v6 now passes, but all 16 remaining timeouts are unresolved. The run took 275.688 seconds for tests and 1,786.85 seconds including compilation. Its log SHA-256 is `dc707f3f7bbf934ab6e2c75290693bf16674ffa7b2a10c3c37aff1cab2aa46be`. All 7,749 source inputs and the control files were unchanged. No test expectation or runtime limit was weakened.

A separate owned-child debugger diagnostic of one provider test exited normally with code zero in 20.805 seconds of the execution interval, including about 1.202 seconds of debugger pauses. Its source and binary hashes were unchanged and the child was absent after cleanup. This single-test diagnostic does not qualify the original concurrent suite or establish the cause of its timeouts.

The earlier whole-checkpoint blob check failed because the modified monolithic caller manifest exceeded the existing limit. That failure is retained. The new storage representation fixes the actual changed blob instead of adding an exception or increasing the threshold.

The security native evidence archive preserves all 40 original files with verified round-trip bytes: SHA-256 `602ea149bd7597141a6b61682060289e23714636c5b6afffdcdda0d629d4c381`. The complete-package result is tied to its own exact candidate, not to untested later source changes.

## Remaining merge blockers and work

Windows elevated admission remains unqualified for the four positive isolation contracts. The protective refusal guard remains in place. Linux checks, source comparisons, finite-root experiments, and unchanged-tree merges do not establish native Windows isolation. The historical 16/17 claim in an earlier PR description has not been independently relocated in this follow-up; it is not used as a new qualification result.

The baseline CodeQL analysis has 195 results. All 23 exposed annotations were source-reviewed, including 13 high logging findings and 10 critical hardcoded-value findings, but this is not a complete disposition of all 195 results. No alert was dismissed or suppressed. Intentional interactive authentication instructions may still be flagged; fresh analysis remains necessary.

Continue reviewing and resolving the remaining 5,497 original candidate histories, repair the native provider and Windows failures, run the original source-bound checks on the combined head, and satisfy both `CI required` and `Architecture required` before merging to main. Retirement requires a fresh protected-ref inventory, equality with the intended exact branch tip, and containment in the actual main commit.
