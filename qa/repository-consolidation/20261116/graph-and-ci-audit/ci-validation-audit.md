# CI and source audit for the reviewed consolidation checkpoint

This checkpoint passed the complete source boundary checks and several scoped Linux validations. Full platform qualification remains incomplete. The four Windows isolation tests remain blocked, and native v6 was still running when this report was frozen.

## Exact source identity

| Item                     | Value                                                              |
| ------------------------ | ------------------------------------------------------------------ |
| Original hosted head     | `285e971b3af3a93a79169b56a42263069e473057`                         |
| Validated source commit  | `d3746789d49ca8a4bb5600e0c6fbe682ef5f1765`                         |
| Validated source tree    | `751e50a0172e467176be68a1331519c8ea171307`                         |
| Source overlay           | 55 paths                                                           |
| Overlay manifest SHA-256 | `b30ac03e8717c59d8a04598bbb302dd25b2970461d414d232e91f02767dd5b65` |

The [source manifest](ci-evidence/checkpoint-source-manifest-v6.json.gz) records every original and proposed blob. The parent agent controls checkpoint publication. A later merge that changes only ancestry may reuse the content proof only after confirming source equality. This audit performed no HIA ref changes, main merge, or branch deletion.

## Completed source checks

| Check                            | Exact scope                                                                              | Result                                               |
| -------------------------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Original B4 CLI                  | `python3 -B -m unittest discover -s qa/b4-no-bypass`; all 1,315 tests                    | PASS, exit 0; 720.400 seconds within the test runner |
| Complete caller proof            | All 1,645 boundaries, 7,504 Rust files, 819 protected files, and 1,645 inventory entries | PASS, no skipped or duplicate boundaries             |
| Source identity during both runs | Detached source commit above; before and after input hashes; clean worktree              | Unchanged                                            |

The caller run uses the previously verified six-worker schedule with the unchanged verifier functions and assertions. It does not claim a second serial invocation at this head. [B4 receipt](ci-evidence/final55-full-b4-receipt.json.gz), [caller receipt](ci-evidence/final55-parallel-callers-receipt.json.gz), [full proof](ci-evidence/final55-parallel-full-caller-proof.json.gz), and [runner adaptation receipt](ci-evidence/final55-runner-adaptation-receipt.json.gz) preserve commands, hashes, timing, and coverage.

## Completed Linux validation and its limits

| Validation                   | Result                        | Scope                                                                                 |
| ---------------------------- | ----------------------------- | ------------------------------------------------------------------------------------- |
| Agentd feature Clippy        | PASS, exit 0, 857.816 seconds | `just clippy --locked -p codex-hepta-agentd --features qualification-cognitive-write` |
| Lock-sensitive fixture tests | 19 passed; 480 filtered       | Original journal and publication readback filters on ROG Linux                        |
| Bootstrap crash tests        | 2 passed; 441 filtered        | Both original abrupt-exit recovery tests on ROG Linux                                 |
| PTY library tests            | 28 passed; none skipped       | Complete PTY library test set on ROG Linux                                            |

All three ROG test runs occurred after the recorded reboot and used zero retries. The [ROG source bridge](ci-evidence/rog-validation-candidate-source-bindings.json.gz) confirms that their four recorded changed fixture blobs match the final source. They ran the original baseline plus their recorded subsets, so they do not establish equality of the entire execution tree or qualify macOS and Windows.

The Clippy input inventory contains 7,748 paths. Of these, 7,742 match the validated source; the six differences are four separately tested fixture paths and two Windows-only test import changes. All recorded Agentd source inputs match. [The exact comparison](ci-evidence/native-v6-candidate-source-bridge.json.gz) prevents a broader whole-tree claim.

Earlier failures remain preserved. Native v4 ran 108 tests with 102 passes and six failures: three provider binding errors and three model material stack overflows. Native v5 ran 79 tests with 62 passes, 16 failures, and one timeout. Its stack overflow disappeared, while provider binding and deep-readonly failures remained. Later edits do not relabel these historical receipts.

**Native v6: running at report freeze.** Its original 8 MiB stack setting, 60-second nextest timeout, and zero retries remain recorded. A later receipt must supply actual matched test counts and results.

## Original hosted failure inventory

The [original check snapshot](ci-evidence/baseline-285e971-check-runs.json.gz) contains 211 unique checks: 160 successful, 29 failed, 13 skipped, and nine canceled. The original `CI required` check failed. This count does not imply that all 29 failures are required by branch protection.

The [Bazel inventory](ci-evidence/remaining-required-bazel-inventory-285e971.json.gz), [exact log excerpts](ci-evidence/remaining-bazel-excerpts-285e971.json.gz), and [follow-up analysis](ci-evidence/followup-platform-provider-findings-285e971.json.gz) distinguish these concrete groups:

- GNU provider binding failures and model material stack overflows; the recorded Core retry recovered.
- Musl selection of a GNU-only Wine target, despite successful native Core targets.
- macOS references to Linux-only fixture return types, noncanonical crash-fixture roots, two PTY timeouts, and a five-agent shutdown failure.
- Windows ambiguous imports, lock-sensitive reads that returned OS error 33, and four separate admission-dependent functional failures.
- Clippy guard-across-await and helper `unwrap`/`expect` findings, source boundary mismatches, and spelling diagnostics in archived binary bytes.

Source repairs do not establish a new hosted PASS. The original failed and canceled jobs remain distinguishable, and the published checkpoint still needs its actual platform matrix.

## macOS experiments

The [PTY experiment](ci-evidence/mac-pty-probe-reproduction-v1.json.gz) showed that a complete readiness literal can appear in terminal echo even without an interpreter. Splitting that literal removes this false readiness signal. The original CI PID timeout was not reproduced, and the experiment does not establish its sole cause. The original 5-second readiness, 2-second PID, and 5-second exit limits remain unchanged.

The [ordered control-socket experiment](ci-evidence/mac-control-close-order-v1.json.gz) observed `ENOTCONN` after a successful write and client close in all five macOS trials; Linux succeeded in all five corresponding trials. A write after client close failed with `EPIPE` on both systems. The narrow source change accepts only `NotConnected` from shutdown after successful `write_all`. All earlier read, frame, JSON, write, reset, and broken-pipe errors retain their failure behavior.

These are standard-library and kernel experiments. They are not full Rust qualification or proof of the original five-agent CI failure.

## Windows functional blocker

The [independent contract review](ci-evidence/windows-four-admission-contract-review.json.gz) preserves four required functional tests:

1. `windows_elevated_does_not_create_missing_workspace_metadata`
2. `windows_elevated_enforces_deny_read_and_protects_setup_marker`
3. `windows_elevated_unified_exec_enforces_managed_deny_reads`
4. `restricted_tokens_select_stable_routes_and_cleanup`

The current admission guard refuses elevated execution because the original native deletion oracle found an ambient parent `FILE_DELETE_CHILD` escape. That refusal contains the known exposure, but does not meet these tests' successful execution and isolation requirements. Existing typed-refusal regressions remain separate. A concrete replacement needs the unchanged native four-cell oracle, positive controls, and original functional tests.

No genuine Windows execution host was available among the configured hosts. Linux fixture passes therefore do not qualify Windows locks or admission behavior.

## CodeQL: all 23 original findings reviewed

[The failed original check](https://github.com/TrillionniumFoundation/hepta-private-ci/runs/133210231982) reported 23 findings: 13 high-severity logging warnings and ten critical cryptographic-value warnings. The [original 23-item queue](ci-evidence/codeql-285e971-triage-queue-v1.json.gz), [raw annotations](ci-evidence/codeql-285e971-annotations.json.gz), and [original SARIF](ci-evidence/codeql-285e971-analysis2176372976.sarif.json.gz) retain rule IDs, paths, functions, line numbers, alert links, and detected head. All 23 reported source blobs are unchanged between the original and validated source.

The [ten fixture reviews](ci-evidence/codeql-285e971-fixture-triage-v1.json.gz) trace exact synthetic values and test-only module reachability. The [four root source reviews](ci-evidence/codeql-root-four-source-review.json.gz) distinguish a bounded frame counter, completely overwritten hex buffer, and `read_exact` random buffer from fixed production entropy. They also identify partial API-key output in the CLI as a remaining remediation item.

The [nine executable-client reviews](ci-evidence/codeql-login-nine-review-v1.json.gz) trace five typed paths without authentication-secret flow and two required browser/device instructions. Duplicate login material and unbounded upstream error text need separate remediation. A proposed logging change is outside this 55-path source checkpoint and requires its own validation.

These are 23 original warnings, not 23 confirmed vulnerabilities. No alert was dismissed, no gate was overridden, and source-level triage does not turn the original failed check into a pass.

## Evidence integrity and outstanding work

[The artifact manifest](ci-artifact-manifest.json) binds every file to its Git blob SHA, SHA-256, and byte count. Original receipts and logs use deterministic gzip: empty filename, zero timestamp, compression level nine, byte-exact decompression, and no blob larger than 500,000 bytes. The report uses the existing spelling configuration without new exclusions.

Outstanding evidence includes the hosted GNU, musl, macOS, and Windows matrices; native v6 results; Windows isolation qualification; and separate remediation of CLI partial-key output, duplicate login material, and unbounded upstream error text. The source proofs above are complete for the pinned source and do not replace those results.
