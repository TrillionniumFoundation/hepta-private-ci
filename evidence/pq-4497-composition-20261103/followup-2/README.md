# Second follow-up: Bazel sources, recovery diagnostics and retained CI

Canonical PQ Cell and policy-renewal controls now have successful native execution on all four original Linux lanes for source `2d7506108fd1b7813d5afbe2bbb0aaf5d9460c6d`. Overall acceptance remains **HOLD**: one provider-effect lane still fails, all four Windows diagnostic lanes retain native failures, and broader Bazel jobs contain additional failures. The paired Chain deadline and CPU-budget failures remain unchanged.

This follow-up changes exactly three source files on that published parent. It adds two missing existing Rust inputs to the Bazel graph and makes one assertion print its actual recovery result. The diagnostic change does **not** repair the observed 133/134 failure. Runtime records below belong to the published parent, not to the new three-file candidate.

## Exact source and changes

The parent tree is `80562dbe724b082f388828b32fb305d036e8dff7`. Its prospective merge is `21ceefde202d58ef60e937d637f725727a9fe086`, with base `3a81000aae08c658276958d678874aca4db5eedd`; that merge has the same tree. Earlier `0baf` evidence and the first follow-up's 173-path immutable snapshot are retained byte for byte. [Published-parent readback](published-parent/local-clean-readback.json) records the exact local import and clean state before this follow-up.

| Source path | Change and reason |
|---|---|
| `codex-rs/hepta-infer-worker-host/BUILD.bazel` | Add existing `cognitive_process_learning_auth.rs` and `cognitive_process_learning_auth_tests.rs` to `crate_srcs`. Current cross-crate path modules reach them, but the Linux Bazel action omitted them. |
| `codex-rs/hepta-agentd/BUILD.bazel` | Add those two existing sources to the exports already restricted to the host package. |
| `codex-rs/hepta-automation/tests/support/authorized_provider_receipt_tests.rs` | Preserve `good.is_ok()` and append the existing Debug recovery value to its diagnostic. Original assertion conditions, concurrency operations and retry limits remain. |

The [Bazel review](source-inputs/review.json) and [independent review](source-inputs/independent-review.json) verify the seven-file source closure: five previously declared inputs plus these two existing files. Removing the two added entries from each BUILD file exactly restores its baseline bytes. The [diagnostic proposal](diagnostic-only/proposal.json) records the unchanged baseline test and one-line assertion patch.

The repository-pinned Buildifier v8.5.1 check passed. Original local `just fmt` passed, and all three formatted hashes still equal the reviewed proposals. [Post-format validation](local-validation/hepta-followup2-post-fmt.json) records the exact closed set. This phase did not rerun Rust compilation, native tests or Bazel actions. Execution of the new candidate remains pending.

## Successful native controls on the published parent

The [Cell run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41609576379) completed x64 and ARM64 source-head and prospective-merge lanes. Every lane passed every selected group below. Selections overlap and are not added together as a unique test total.

| Original Cell command group | Passed in each of four lanes |
|---|---:|
| Host material and Cell startup | 23 |
| Cell CLI process | 3 |
| Argument-zero owner | 7 |
| Original owner and FinalUse selection | 42 |
| Canonical contracts library | 195 |
| PQ initial material | 1 |
| PQ initial clock | 1 |
| Shared startup budget | 1 |
| Real Agentd turn start with the bound Codex binary | 1 |

The 195 contracts cases include the three Unix trust-service cases previously blocked locally by AF_UNIX permission errors. They executed and passed in these hosted lanes; old local failures remain in earlier evidence. The 42-owner selection includes ten FinalUse authorizer cases, five using canonical PQ. No selected retry was observed. Filtered-out tests remain unexecuted, and original floors, selectors and budgets remain intact.

Every lane also completed the original Codex Cargo build, native turn-start test, formatter and `just fix` with unchanged-source enforcement. Archive review checks log lengths and digests, source/tested identities, and Cargo build-record and executable-hash binding. The successful workflow checks ELF identity and binary hashes before and after execution on the runner. The observation ZIP does not contain the Codex executable; this independent review did not separately download and hash it. Original `just fix` is distinct from the previously retained local seven-crate, no-`--fix`, strict Clippy result. [Cell evidence](cell-ci/cell-four-lane-summary.json) retains all four original archives and inspection records.

The [policy-renewal run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41609576436) passed all four original lanes. Each ran exactly **14 dispatcher controls and three Agentd/App Server process controls**, once per named case, without a selected failure or ignored case. Original `just fix`, formatting and clean-source checks passed. [The four-lane review](renewal-ci/review-4-lanes.json) retains exact case sets, original receipts and log digests; all four original ZIPs match GitHub digests and sizes.

The added cancellation control pauses the active owner after the protected read and before database mutation. It proves admission release and subsequent progress at that point for the two profiles inside the test. It does not establish all unknown-commit recovery outcomes. Earlier `0baf` renewal records still show zero observed executions of their 13 dispatcher and three process controls; later passes do not relabel them.

## Failures still retained

**Provider-effect recovery:** three lanes passed 134/134 and all six subsequent exact HTTP controls. The x64 prospective-merge lane passed 133 and failed one; its original concurrent receipt test failed on both configured attempts. The command returned 100 without a command timeout. The subsequent six controls did not execute. The assertion did not print the actual recovery error, so a cause is not established. [All four effect archives](effect-ci/four-lane-summary.json) are retained. Printing that error in a future run is the sole purpose of the diagnostic change.

**Windows diagnostics:** all four lanes now pass FinalUse 8/8 and execute beyond the former missing `windows_private_owner` module failure. Each has 19 passing and three failing command groups: `broad-identity-delete`, `legacy-delete-boundary` and `command-runner-terminal`. Their actual assertions and process observations remain failures, not an environment-only classification. [The four-lane review](windows-ci/four-lane-review.json) verifies all 22 command receipts per lane, original result hash links and unchanged source identities. Full Windows ownership and production sandbox qualification remain false.

**General blocking CI:** the [snapshot at 2026-11-03T09:52:33.373Z](blocking-ci/followup2-blocking-jobs-snapshot.json) contains 21 successful, six failed, four running and four skipped jobs. The workflow is not reported as successful. Codespell passed. The complete repository job passed 22 QA tests, caller self-test, the 52-boundary scan over 5,604 Rust files, formatting and clean-source checks. The scanner still reports `authorityGranted=false`; these repository checks ran the recorded prospective merge.

Two Linux Bazel actions failed because a nested learning-authorization source was missing from their declared inputs. The two BUILD changes address that observed declaration gap, but their new Bazel execution remains pending. [Complete original logs and archive hashes](blocking-ci/linux-bazel-inclusion-failures.json) retain both failures.

The Mac Intel job contains real native failures alongside build-service availability errors. Its original Bazel summary is: 206 of 612 targets executed; 291 passed, 79 failed to build, 13 failed locally and 229 were skipped. Passing counts include cached results. The 13 local failures include two target timeouts. Remote build service DNS or availability errors are observed, but are not assigned as the cause of every failure. [The complete compressed log and review](blocking-ci/mac-intel-native-failure.json) retain this mixed result. Mac ARM release and Clippy passed; its broader test job was still running at the snapshot.

Three Windows Bazel shards completed with actual native failures; the fourth was still running. Their original summaries were respectively 99 pass/3 local fail/49 skipped, 101/7/45 and 102/3/54, including cached results. Failures include PQ owner, host/Agentd ownership and existing sandbox controls. Windows release and Clippy passed. [Complete compressed logs and target summaries](blocking-ci/windows-bazel-completed-failures.json) preserve these separate observations. Remaining unrelated Bazel jobs are not waited on indefinitely, and pending jobs are not counted as passes.

## Pairing and acceptance

Chain remains pinned to `1c7e8ab7cd6a321cad4e6c7f7e8a197d7b3be14c`, tree `535660af742d62b6578b5e4334e0f2d2c17527e0`. The V5 selected-source manifest digest remains `57ebcfa34d3e578679c3040fab3e4065683bd032592a183574767d5d3eaa9404`. Earlier 43-control and later full Node results remain separate: full Node still has deadline or CPU-budget failures in three lanes, with 22 ignored cases per lane, despite four passing Clippy lanes. This follow-up changes neither the pins nor these results.

The component passes establish execution of selected authorization, clock, startup and renewal controls on the recorded parent. They do not grant full Hepta native acceptance, installed business-loop qualification, independent WAN/deployment acceptance or whole-chain post-quantum security. Proof PQ-128 parameters, quantum mining economics and complete authority/recovery coverage remain outside this acceptance. Later source revisions inherit no qualification automatically.

## Preservation

Original workflow ZIPs are unmodified. Large decoded job logs use lossless XZ compression with original lengths, digests and verified round trips. Every retained blob stays within the existing 512,000-byte limit; no allowlist exception or threshold change was added. Temporary signed download URLs are omitted. [The machine-readable summary](summary.json) separates static candidate checks from actual parent runtime results and overall HOLD status. Final spelling outputs and the final summary observation are generated after the text scan and are not counted as its scanned inputs.
