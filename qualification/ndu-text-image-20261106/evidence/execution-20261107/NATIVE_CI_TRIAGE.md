# PR #5307 — original CI read-only triage

Snapshot: **2026-11-07 11:44:11 UTC**. This is a point-in-time report; later job results may differ.

## Outcome and scope

The native learning-cycle PR remains a draft with **blocking CI failures and pending work**. This report records the original jobs, compares relevant file identities, and proposes focused investigation. It does not rerun jobs, waive gates, modify the source tree, or publish a comment.

**A failure reported in an unchanged file is not a baseline reproduction.** No baseline CI job or isolated baseline replay was obtained for this report. In particular, unchanged file hashes do not prove that all transitive behavior, tools, environments, caches, or merge interactions are identical, and do not establish that the PR cannot contribute to a failure.

At the snapshot, the complete blocking run returned **35 jobs: 11 success, 14 failure, 6 in progress, 4 skipped**. Both architecture-convergence jobs remained in progress at “Converged authority and browser semantics.” The convenience jobs connector returns only its first page, so the snapshot uses the complete GET run/jobs listing with `per_page=100`.

- [Draft PR #5307](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5307)
- [Blocking run 42368719695](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695)
- [Architecture run 42368719690](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719690)
- Architecture source-head job: [128392194248](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719690/job/128392194248)
- Architecture base-merge job: [128392194461](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719690/job/128392194461)

## Revision binding

| Role | Commit or tree |
| --- | --- |
| Original implementation baseline | `cef48673f8a9d8c7192aeff5920d77ccad3d8eb1` |
| PR base at this run | `4edbe0426d05bffd7687861789b69eabe7dd6d9c` |
| Published PR source head | `c892b7eaab5e6f003103b4ac2e651b6d3ad573c8` |
| Blocking job checkout / synthetic merge | `2c38ec493f2cac32def4fc9a6f6d0f8c6dda6957` |
| Independently implemented local head | `d5cfc334266e0f3396f5f4296867ac083b18486a` |
| Published head tree = local head tree | `0ebcb5644f3b4b1f34dc3b8e8b8bbecb43f8257b` |

The published head's Git tree was read from GitHub's Git-commit endpoint and matches `git rev-parse HEAD^{tree}` in the isolated implementation checkout. The checked source tree was clean. The blocking logs identify the synthetic merge above.

The [original-baseline to PR-base comparison](https://github.com/TrillionniumFoundation/hepta-private-ci/compare/cef48673f8a9d8c7192aeff5920d77ccad3d8eb1...4edbe0426d05bffd7687861789b69eabe7dd6d9c) is ahead by three commits, changing exactly these four paths:

- `codex-rs/cli/tests/exec_server.rs`
- `codex-rs/hepta-agentd/src/neuron_generation_update_test_support.rs`
- `codex-rs/hepta-agentd/src/neuron_v13_generation_guarded_tests.rs`
- `codex-rs/hepta-contracts/src/final_use_retained_tests.rs`

The [PR-base to tested-merge comparison](https://github.com/TrillionniumFoundation/hepta-private-ci/compare/4edbe0426d05bffd7687861789b69eabe7dd6d9c...2c38ec493f2cac32def4fc9a6f6d0f8c6dda6957) contains the 16 PR paths. Neither comparison intersects any of the **64 checked diagnostic/input paths** listed below. Local Git object lookups independently show each checked blob identical between the original baseline and local source head. Together these checks bind the listed equal blob IDs across the baseline, PR base, published source, and tested merge. This is a content-identity result, not an execution result.

## Original failed jobs and observed errors

| Job | Original job link | Observed diagnostic | Attribution limit |
| --- | --- | --- | --- |
| Codespell | [128392195015](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392195015) | Three findings: two comment misspellings at joint_generation/codec.rs:170,173 and a plural API noun at hepta-neuron/cell_generation_control.rs:42. Original spellings remain in the linked job log. | Observed in unchanged files; no baseline execution. |
| Python SDK | [128392261132](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261132) | Six process-observation evidence tests fail with `FileNotFoundError: zstd` inside the Python slim container. | Workflow and tests unchanged; runtime provisioning cause observed, baseline reproduction not run. |
| Privileged caller closed set | [128392261258](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261258) | `learning_artifact_verified_current_view` has unexpected caller `codex-rs/hepta-agentd/src/neuron_generation_update_selection.rs`. | Caller, CALLERS.toml, and verifier unchanged. New learning_decision helper is not the reported caller. |
| Rust format | [128392315893](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392315893) | 38 distinct files have `Diff in` output. None intersects the 16-file PR diff. | All 38 blobs are identical at the original baseline, PR base, PR source, and tested merge. |
| Required Rust summary | [128392689650](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392689650) | `GENERAL_RESULT: failure`; terminal output `general failed`. | Aggregation of the failing general/format job; no independent source diagnostic. |
| Linux GNU Bazel clippy | [128392261353](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261353) | Agentd compilation cannot read terminal_cell_owner.rs and cross-crate joint_synthetic.rs. | Relevant BUILD, macro, source, and fixture blobs unchanged; missing declared action inputs inferred from logs and rules. |
| macOS arm64 Bazel clippy | [128392261454](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261454) | Agentd compilation cannot read terminal_cell_owner.rs. | Same unchanged inputs; no baseline execution. |
| Linux GNU release build | [128392261744](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261744) | Agentd unit/qualification targets cannot read terminal_cell_owner.rs; generation integration target cannot read joint_synthetic.rs. | Same unchanged inputs; no baseline execution. |
| macOS arm64 release build | [128392261495](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261495) | Agentd unit/qualification targets cannot read terminal_cell_owner.rs. | Same unchanged inputs; no baseline execution. |
| Windows Bazel clippy | [128392261408](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261408) | E0034: ambiguous as_raw_handle in utils/pty/src/win/native_observation_tests.rs:55,70,93. E0659: ambiguous assert_eq in windows-sandbox-rs/src/unified_exec/delete_permission_tests.rs. | Both test blobs unchanged; no baseline execution. |
| Windows release build | [128392261506](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261506) | The same E0034 and E0659 compiler errors. | Both test blobs unchanged; no baseline execution. |
| Linux GNU Bazel tests | [128392261404](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261404) | Agentd missing compilation inputs; missing real bubblewrap and OpenSSH ssh-keygen; cognitive ToolRegistry/output/readiness failures; core Wine abort_tasks path assertion mismatch. | Reported source/test files checked unchanged where identified below. Overall causal attribution remains open. |
| Linux musl Bazel tests | [128392261409](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261409) | The same classes of Agentd build/runtime, helper provisioning, and Wine failures appear. | Reported source/test files checked unchanged where identified below. Overall causal attribution remains open. |
| cargo-deny | [128392261201](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42368719695/job/128392261201) | Job steps confirm `Run cargo-deny` failed. Dedicated log download repeatedly returned `Transport closed`. | UNLOCALIZED. No claim about a particular advisory, dependency, or baseline cause. |

The Linux Bazel test logs also explicitly report the `hepta-intelligence-unit-tests` target as **PASSED**. The GNU job labels that result **cached**; the musl job summary reports PASSED without that label. These target summaries do not make the whole CI green, and this report does not infer individual test counts from the Bazel summaries. The separately retained local native run has 101 passing tests; its source/format evidence remains in the PR's validation manifest.

For the Linux/Wine failure, the concrete failing test is `suite::abort_tasks::root_turn_suspension_preserves_unfinished_turn_history`, with a path/environment assertion at `codex-rs/core/tests/suite/abort_tasks.rs:211`. Agentd runtime diagnostics include missing advertised cognitive tools, non-JSON tool output, and failed or timed-out readiness. Those runtime diagnostics require owner investigation; the source identity checks alone do not localize their cause.

## Focused repair proposals, not applied

1. **Caller manifest:** Have the owning boundary review the existing `candidate.with_current(...)` use in `neuron_generation_update_selection.rs`, then update the exact caller set and appropriate evidence markers if the use is legitimate. Keep the closed-set verifier and its negative checks. Do not silence the path or weaken the boundary.
2. **Hermetic test inputs:** Include `tests/support/terminal_cell_owner.rs` in the relevant Agentd unit/qualification compilation inputs. Ensure the generation integration target receives the external `hepta-neuron/tests/support/joint_synthetic.rs` input through the integration compile-data mechanism; the common crate macro does not automatically inherit all product `compile_data` into integration targets. Verify the affected action inputs before rerunning only the necessary gates.
3. **Python SDK provisioning:** Provide real `zstd` in the slim-image test environment, preserving the real compression/decompression and tamper-rejection tests. Do not replace evidence verification with a mock.
4. **Native helper provisioning:** Give affected Bazel tests access to actual bubblewrap and OpenSSH `ssh-keygen` through their intended hermetic/toolchain/PATH mechanism. Keep fail-closed behavior when those required binaries are absent.
5. **Windows compiler errors:** Disambiguate the intended native `AsRawHandle` trait call, and use the intended explicitly qualified assertion macro in the existing Windows tests. Preserve their behavioral assertions.
6. **Formatting and spelling:** Apply the repository's pinned formatter to the 38 reported, unchanged files in a separately reviewable maintenance change; correct the three reported spelling findings without broad ignores.
7. **Runtime and Wine assertions:** Investigate the Agentd feature/tool registry/readiness setup and the Wine path round-trip assertion using the original logs. No root cause or fix is certified here.
8. **cargo-deny:** Obtain the original failure diagnostics through the owning CI/log service before deciding a repair. The log transport failure does not justify suppressing advisories, changing policy, or rerunning blindly.

## Exact unchanged-file Git blob identities

Each row has the **same Git blob SHA-1 object ID** at the original baseline and local source head. The two complete remote comparisons and matching source tree described above extend that content identity to the PR base, published head, and tested merge. Every row is outside the PR's 16 changed paths. “Diagnostic/input” includes surrounding gate/build inputs as well as files with direct errors; it does not imply every listed file itself failed.

| Repository-relative path | Equal Git blob ID | Reason checked |
| --- | --- | --- |
| `.github/workflows/cargo-deny.yml` | `db7cad815476abfe22502ee9aa71617606d76a10` | Diagnostic/input |
| `.github/workflows/sdk.yml` | `520d5905b1f3b38c8483490df6d2caf1fdd4e9bb` | Diagnostic/input |
| `CALLERS.toml` | `8e47bde4cc496da69297120b731c4fb87e48e646` | Diagnostic/input |
| `codex-rs/Cargo.lock` | `b7e710988d6a3377a7e0a1dc68aef49c68dda36e` | Diagnostic/input |
| `codex-rs/Cargo.toml` | `7e2ec509988e11cdf92130e385ffdf409bbcc15d` | Diagnostic/input |
| `codex-rs/core/tests/suite/abort_tasks.rs` | `9b26fa2b628c6319f99ccad9452510c38415489c` | Diagnostic/input |
| `codex-rs/deny.toml` | `17c0cd77fd1dd5c6433015e85efeaf9c1551be57` | Diagnostic/input |
| `codex-rs/exec-server/tests/capability_discovery.rs` | `80484ecfa01dac48189cbcc3324caa4374961ea0` | Diagnostic/input |
| `codex-rs/exec-server/tests/file_system_unix.rs` | `5051ec2e5bbc625c090e335cc8872044415a85ad` | Diagnostic/input |
| `codex-rs/hepta-agentd/BUILD.bazel` | `fa232693eb62acb51e1486b1c5e3691079ddf627` | Diagnostic/input |
| `codex-rs/hepta-agentd/src/neuron_generation_update_selection.rs` | `9344d98a3831ae6ee199c85a64cca3e321ce379b` | Diagnostic/input |
| `codex-rs/hepta-agentd/src/terminal_learning_tests.rs` | `118b29fd99037f02b9ecb8ef5bf98ed869608ca3` | Diagnostic/input |
| `codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs` | `b9996dc339646cf95fad5fbbff0b360b5765c085` | Diagnostic/input |
| `codex-rs/hepta-agentd/tests/supervisord_product_e2e.rs` | `953bfe58003423a57fba675cfe7729848f347b0e` | Diagnostic/input |
| `codex-rs/hepta-agentd/tests/support/neuron_generation.rs` | `b5a53cee8ab6bc907b5e70f615384a3750d1bc37` | Diagnostic/input |
| `codex-rs/hepta-agentd/tests/support/terminal_cell_owner.rs` | `f5ae71bfdea755fc5af408816e0a6921e224456b` | Diagnostic/input |
| `codex-rs/hepta-automation/src/circuit_admission_tests.rs` | `54a97993ee1d0c8d0c9fa10585837b420aba098b` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_admission.rs` | `95e6877a9ad3e31fd2e78c800ae94505aa0b95f7` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_budget.rs` | `3dcef7b244fc6c6161a3f7c3c225d7ab58260f01` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_compute.rs` | `e50317f6b9d5d90f898211e66cf758f238dd97c9` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_history.rs` | `faccff9c86a8699700e82568d2cde9dbb760265a` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_join.rs` | `a3d05b99487fb080f26e70f2941be6fbcb2b9410` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_journal.rs` | `b3d6c5eea54471c9203fd6de05795965cefb12ae` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_profile.rs` | `5473561b205e07fe31dc7f93e399fc3027569875` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_progress.rs` | `2d582b2697689b8aa216899fdb68b3a688a61418` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_runtime.rs` | `b44c36c0dd9b7864c8ea09022909e2d9d3beebae` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_state.rs` | `324da89240f32f6bcf8ba043d90eaa16afbf5abb` | Rust fmt |
| `codex-rs/hepta-automation/src/circuit_store.rs` | `2139581e4e01ba74ef3d0177fe53e4eb18e5cdc6` | Rust fmt |
| `codex-rs/hepta-infer-worker-host/src/joint_generation/codec.rs` | `7250397cec46c2d6676815ff1126a3bf14828104` | Diagnostic/input |
| `codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs` | `9ee0fb20246b2591523a24bdcaa432d5847bdff4` | Rust fmt |
| `codex-rs/hepta-infer-worker-host/src/native_message_output_tests.rs` | `543134c8146ddcc5c0950f3cb64206fb04c7eeea` | Rust fmt |
| `codex-rs/hepta-infer-worker-host/src/native_message_output.rs` | `e165039055a56b5b954fb17d29dd442dfb438315` | Rust fmt |
| `codex-rs/hepta-infer-worker-host/src/native_reconciliation_tests.rs` | `e4740ba8094871cbc5b586ee54bb6a9b0752eb01` | Rust fmt |
| `codex-rs/hepta-infer-worker-host/src/native_recovery_tests.rs` | `c995ded3c590249409244fc896ee5c27bdd94d00` | Rust fmt |
| `codex-rs/hepta-infer-worker-host/src/native_recovery.rs` | `a1f48fb8db4fb1edc33be121a2b5f3c5032b7a6d` | Rust fmt |
| `codex-rs/hepta-intelligence-eval/src/product_qualification_use.rs` | `17587b62466ab5073be7c1da6d52daf8c98e059a` | Rust fmt |
| `codex-rs/hepta-intelligence-eval/src/product_runner_tests.rs` | `72babd39b7e0ad3491690d7b599cac03677c0b0b` | Rust fmt |
| `codex-rs/hepta-intelligence-eval/src/self_evolution_ingress_tests.rs` | `7d44929ab27a46025fcee8548f469720367f46af` | Rust fmt |
| `codex-rs/hepta-intelligence-eval/src/self_evolution_qualification_test_support.rs` | `f842cfed87666b560366a261d16747119192fca7` | Rust fmt |
| `codex-rs/hepta-intelligence/BUILD.bazel` | `e1dd35a3698a0dd9d25e08cccf99cd462e04e850` | Diagnostic/input |
| `codex-rs/hepta-intelligence/src/evaluated_shadow_tests.rs` | `9c813e16654cdba9b1ddcffc7a402e489e01b806` | Rust fmt |
| `codex-rs/hepta-intelligence/src/plasticity_qualification_test_support.rs` | `b28ac84dc1035ea14e498d6c404a0bd76dd67e61` | Rust fmt |
| `codex-rs/hepta-learning-artifacts/src/cell_bundle_tests.rs` | `2f538c443279522671df9f1aaf8ce4485fd1d8d6` | Rust fmt |
| `codex-rs/hepta-learning-artifacts/src/cell_bundle.rs` | `4c899d7f4f48e094ec6a15bf59257b38a63a1912` | Rust fmt |
| `codex-rs/hepta-learning-artifacts/src/learning_iteration_digest.rs` | `4680b11898c839df25bd76f6449a475021755a4b` | Rust fmt |
| `codex-rs/hepta-learning-artifacts/src/learning_iteration_tests.rs` | `67a50444d7fc6c75fc097e900c678735b2d25be7` | Rust fmt |
| `codex-rs/hepta-learning-artifacts/src/lib.rs` | `2955e18e02ad3fd88b52af71d01e295155d668aa` | Rust fmt |
| `codex-rs/hepta-neuron/src/cell_batch.rs` | `37b5b5c20d36141b037a845e942794e8dabc2952` | Rust fmt |
| `codex-rs/hepta-neuron/src/cell_binding.rs` | `2e4ad5099bc9e9d56da4019af4d8e369a63155e8` | Rust fmt |
| `codex-rs/hepta-neuron/src/cell_generation_control.rs` | `02e3eaa9fc964d177eef4f73d67d974d95a18b7f` | Diagnostic/input |
| `codex-rs/hepta-neuron/src/cell_inference.rs` | `fdd37af186089082c13742fd4b775badb4102093` | Rust fmt |
| `codex-rs/hepta-neuron/src/cell_owner.rs` | `bce88fc05b87180ca39d9eee8e0668e61ca88c3d` | Rust fmt |
| `codex-rs/hepta-neuron/src/cell_test_support.rs` | `1a47a9cdad18271bad232fd3c2dfb9d8f7e2bd50` | Rust fmt |
| `codex-rs/hepta-neuron/tests/support/joint_synthetic.rs` | `33cb88612c1c859f0bc8ca3b3c5f45e535b48c48` | Diagnostic/input |
| `codex-rs/hepta-operator-acceptance/src/test_support.rs` | `dbe54aaf0af4b0ff3b940671c730174089553018` | Diagnostic/input |
| `codex-rs/hepta-runtime/src/cell_lifecycle_recovery.rs` | `7e9c5b1634d7b4e9d9b6b01c2801f071b3f62fb4` | Rust fmt |
| `codex-rs/hepta-runtime/src/cell_lifecycle_tests.rs` | `77eee2d9c7d88521c430ae5b92c56ae6812363e5` | Rust fmt |
| `codex-rs/hepta-runtime/src/cell_lifecycle.rs` | `68fe5ec26bf5353a5156e2bbe01308ef782425b7` | Rust fmt |
| `codex-rs/state/src/sqlite_pool_tests.rs` | `20fe71be06d34c6b962d07450d21dcaf72cbbb96` | Rust fmt |
| `codex-rs/utils/pty/src/win/native_observation_tests.rs` | `45d6ece35f88b73d87a95ec148e130341e059ec9` | Diagnostic/input |
| `codex-rs/windows-sandbox-rs/src/unified_exec/delete_permission_tests.rs` | `a0cb1647d95f067fcf135bc9ea2a654ca3e5e7a2` | Diagnostic/input |
| `defs.bzl` | `d5d6027f642ab799e3f2c9a2960f4fe634121f3b` | Diagnostic/input |
| `scripts/verify_hepta_callers.py` | `d7a6981ee7775c7254a9c596ac47bb1bb5e43171` | Diagnostic/input |
| `sdk/python/tests/test_process_observation_schema.py` | `fd7acfa85aaf68e5caa213e20869cbcd8461e7b3` | Diagnostic/input |

## Ready-to-publish sanitized status text

> PR #5307 remains draft. Its original blocking run has failures, and architecture convergence was still running at the recorded snapshot. The reviewed diagnostics include spelling/format findings, an existing caller-inventory mismatch, missing test compilation inputs and real helper binaries, Windows test compilation ambiguities, and several runtime/Wine test failures. We verified that the 64 listed diagnostic/input files are byte-identical across the original baseline, PR base, published source, and tested merge, and lie outside this PR's diff. This is an unchanged-file finding; we have not reproduced these failures on an isolated baseline and do not claim complete causal attribution. The CI logs report the hepta-intelligence unit-test target passed, while the overall gates remain red. The cargo-deny failure is not localized because its original log download failed. No gate was weakened, no failed job was rerun, and no model activation or update was performed.

This report excludes credentials, signed download URLs, full runner environment dumps, and application payloads. It preserves the repository-relative source paths, Git identities, and original job links needed for review.

