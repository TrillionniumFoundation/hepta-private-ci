# Native failure test integration, v1

## Result and scope

The four requested Rust test files were merged locally without conflicts. The provider file was merged by `git merge-file -p` using the actual shared base; its exit code was 0 and stderr was empty. Independently applying the four original patches in the requested order with `patch --fuzz=0` produced the exact same provider bytes. No h, Rust command, commit, source checkout mutation, or new test queue was used.

This is an integration result, not a Rust compilation or native-test PASS. Formatting and native execution remain **UNRUN**. Ordinary Adopt, ordinary NoUpdate, and full daemon plus Root cold-recovery qualification counts remain unchanged.

The patch modifies exactly:

- `codex-rs/hepta-agentd/src/circuit_original_evaluation_provider_tests.rs`
- `codex-rs/hepta-agentd/src/circuit_original_evaluation_task_support_tests.rs`
- `codex-rs/hepta-agentd/src/circuit_next_use_command_owner_tests.rs`
- `codex-rs/hepta-agentd/src/circuit_selection_command_owner_tests.rs`

No panel, shared stack fixture, deep-readback, production Rust, scanner, gate, or runner configuration file is included. The existing 60-second timeout and 8 MiB stack setting are retained; this patch changes neither setting. Their runtime enforcement was not re-executed in this local integration.

## Exact common base

The integration base is commit `521283379701cca53987cf5c3fe85b85fdda04e6`, tree `778a2c1c1f77fd1ea3d3cd0c203cef6c38db2ec0`. Its only changes relative to tested commit `cc22a69972d029d3ef28d49096f396eb5214c616` are caller-proof metadata. These four captured Rust base files retain their cc22 blob identities.

Each physical base file was independently hashed using the Git blob header and contents, and compared with the recorded exact source identity. The recovery provider postimage was additionally reverse-patched with its original patch, at zero fuzz; the recovered bytes equal the candidate provider base exactly. No fetched or reconstructed source was substituted.

| File | Exact base Git blob |
|---|---|
| Provider tests | `dff2786bc5c00635b8a93cfe029a7a7ae73cf908` |
| Task support | `bcb42c2d31f06a306d0cb3c4032494621b45e69a` |
| NextUse command tests | `191a74d44cfda509b24919a89144a93ec90b4f70` |
| Selector command tests | `9dad4fdd1edabe800a9ef80d876ddeb6a7e6d32b` |

## Applied order and authorship

1. Candidate v2: `candidate-provider-native-failures-521-v2/provider-fixture-and-expiry-v2.patch`.
2. Recovery timeout partition: `native-timeout-split-v1/provider-timeout-only.patch`.
3. Profile expiry tests: `native-command-failures-cc22-v1/expiry-window-tests.patch`.
4. Profile diagnostic: `native-command-failures-cc22-v1/withdrawal-diagnostic-after-expiry.patch`.

Original patches and their source manifests are copied under `inputs/`. The withdrawn candidate v1 patch is not an input.

Each patch first passed a dry run and then applied with zero fuzz, zero offset, and no rejected hunks. The profile expiry intermediate files matched the author's frozen `work/` postimages. After the diagnostic patch, the C command file matched the author's `diagnostic-work/` postimage. Task support also matched its author postimage exactly. The provider file is the only combined postimage.

## Non-overlap proof

The recovery edit occupies the original provider test region at base lines 145–258. The candidate edit occupies the following original test region at base lines 259–365. Their original surrounding bytes are unchanged in the corresponding individual drafts. This includes the complete unsorted-policy test and the nested-module tail.

The recovery helper's complete original body is byte-identical after replacing just the two fixed loop headers with the supplied mutation and mode slices. All mutation bodies, physical owner reads, byte comparisons, and permanent-fence assertions therefore remain intact. The malformed-outcome block and the complete zero-support assertion block are also byte-identical in the combined output.

The two command patches intentionally overlap the same file sequentially: the diagnostic patch's exact base is the expiry patch's C postimage, Git blob `3ab5e01325c422f834fad607fabb877e01b9d6ae`. They address different test functions; the sequential dependency and exact final match are recorded. All six Selector test names and all six C command test names retain their order.

`BASE_IDENTITIES.json`, `INTEGRATION_CHECKS.json`, and `checks/patch-application.json` contain the physical hashes and structural checks. `checks/provider-three-way.json` contains the real local merge invocation and result. These checks are not represented as native test results.

## Provider scenario mapping

| Original scenario | Combined test |
|---|---|
| Actual B and retention release after consumption | Existing `original_evaluation_provider_releases_actual_b_and_retention_only_after_consumption`, unchanged |
| `withdraw`, `source-bytes` | Existing `original_evaluation_provider_current_withdrawal_and_corruption_never_release_cached_rows` |
| `ledger-bytes`, `rollback` | `original_evaluation_provider_ledger_corruption_and_clock_rollback_never_release_cached_rows` |
| `unreleased`, `cold-readonly` | `original_evaluation_provider_unreleased_and_cold_readonly_never_release_cached_rows` |
| `MissingLast`, `WrongUnitLast` | `original_evaluation_provider_refuses_missing_and_wrong_unit_outcomes` |
| `freeze-renewal`, `training-renewal` | `original_evaluation_provider_refuses_renewed_original_signatures` |
| `expired-window` for the original Training signature | `original_evaluation_provider_expired_training_signature_permanently_fences_readback` |
| Zero support / unsupported candidate action | `original_evaluation_provider_zero_support_consumes_holdout_once` |
| `NonCanonicalOrder` | Existing `original_evaluation_accepts_unsorted_source_policy_without_reordering_its_bytes`, unchanged |

The original two monolithic provider tests become three and four bounded tests respectively. Together with the unchanged release and unsorted tests, provider tests increase from 4 to 9. The other two test files keep their 12 original tests, giving 16 to 21 test functions across these files. This is a source inventory count, not an execution count.

The expiry test first validates the original signature at its inclusive final second, advances to `expires_at + 1` while the work envelope remains live, requires `Evidence(ValidityWindow)`, then requires permanent `Indeterminate`. It preserves the complete original signature and ledger bytes. The prior rejected v1 diagnosis is not used.

The task-support correction orders the complete original Cell definition by the actual input candidate IDs before initial construction. It preserves each candidate's activation mapping and the selected ID, rejects duplicate, unknown, or omitted IDs, and checks the actual original policy order and selection after publication. It neither changes signed material after publication nor relaxes the product's `IncompleteCandidates` rejection.

## Command scenarios and remaining runtime question

The Selector and C expiry tests now wait strictly past the inclusive original expiry second and require the precise `Evidence(ValidityWindow)` result. Their subsequent Unavailable, byte, custody, and frame assertions are retained.

The C publication-withdrawal test retains its actual withdrawal and refusal path. Its first original evidence read now records elapsed time and the existing peer's join result if that read fails. It does not retry, create another channel, extend a deadline, replace the error, or classify the existing native failure as fixed. The diagnostic result still requires a real native rerun.

## Handoff

`postimages/` contains the complete four merged files. `native-failures-integration-v1.patch` is the combined base-to-postimage patch. `MANIFEST.json` records all source patches, base and final file identities, local verification status, and the unchanged qualification boundary.

Root owns actual Rust 1.96 formatting, integration with the separate panel/stack/deep changes, and the next native run. Any formatter output is a new postimage and must be hashed before publication.

## Source guard and CI name audit

The exact 521 `qa/b4-no-bypass/test_original_evaluation_provider_source_closure.py` was fetched and independently verified as blob `6b7e5887b39117398119e58a7aa1f6867c741574`. Its ten tests protect product source boundaries; none requires the removed combined native-test name or any of the replacement test names. The original complete cc22 source log confirms that this suite ran.

The exact 521 daemon-learning-native, consolidated-source, and converged-learning workflows were also inspected. None requires these provider test names. The daemon's ordinary invocation selects the complete library packages with `test("ordinary", [*packages, "--lib", "--test-threads", "2"])`; the replacement provider cases therefore remain selected. The separate ignored Root-parent list is unchanged.

The available `root-final-source-integration` QA, CI, and script files also contain no matching native-test name. That local checkout is sparse; this audit does not claim to have downloaded every repository QA or CI file. The targeted exact source guard and three relevant workflows are retained with hashes under `checks/source-name-audit/`. No actual stale name requirement was found, so no QA/CI patch was added and no extra suite was run. The existing S/C/intake names are untouched.
