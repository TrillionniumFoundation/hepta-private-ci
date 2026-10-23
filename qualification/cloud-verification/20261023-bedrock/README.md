# Matched-source Bedrock routing integration

Combined source **b6cae33e26f09474f96df5598edb59d3d74ddd69**, parent **74ba1d6c11659c2a3e38b4ef6056778f1d00a2a2** (#3586), tree **79abfc839c992f87794b9fa94fc3b81b0f71e4fc**. Branch: fix/cloud-bedrock-routing-3586-20261023. DRAFT / HOLD_NO_GO; no merge or deployment.

## Result

This is a reproduced app-server integration defect in the existing host architecture. Protocol common.rs declares experimental discover/setup endpoints with account-auth serialization; README.md already documents them; account processors and public JSON-RPC tests exist. The old dispatcher returned MethodNotFound instead of reaching those handlers. Agentd currently embeds/uses app-server, but this repair does not grant native ModelPort invocation authority or prove native inference, Final-use, recovery, or production acceptance.

Exact clean baseline 74ba1d6c: **2 failed**, both `-32601 / Amazon Bedrock setup is not implemented`. Combined clean source b6cae33e: **3 passed, 1013 filtered/skipped**, including successful discovery/environment provider configuration, invalid region/empty or missing profile/missing environment credentials, forced ChatGPT rejection for both endpoints, and experimentalApi=false rejection for both endpoints. Auth rejection checks exact -32600/messages, unchanged config bytes and absent auth.json/.env. See baseline-correct-target.log and exact-tests.log. The repository local nextest profile automatically retried baseline failures; no hosted rerun was requested.

Strict Clippy **FAILED (101)** in unchanged dependency codex-hepta-memory, before complete app-server lint qualification:

- cognitive_intelligence_writer.rs:156 `correct_with_kg_tx`, 8 arguments (limit 7), blob 0e92e867745eca2315d08b34b5ff319e19c76d93.
- local_lease_outbox.rs:2618 `append_outcome_in_transaction`, 8 arguments (limit 7), blob 1c07918ae14e7d7a8c635d1574178424ba3407b4.

Both files are byte-identical to baseline (git diff BASE HEAD -- FILES empty). This attributes the errors to existing source, not a completed separate baseline Clippy run. No suppressions, gate changes or unrelated repairs were added. Normal build also emitted existing hepta-memory-extension dead-code warnings. Format/whitespace checks passed. Initial command incorrectly selected test target suite and exited 101 without running tests; retained baseline-tests.log, then corrected to actual target all.

## Provenance and review

Candidate #3595 exact 00b3f410b13ee8731ec8f6b5341c53be176e6a2a was read in full (two-file PR diff). Its base 0ade699d and our 74ba1d6c have identical preimages: message_processor 1c83eb476c5a613855e352a95e64862698143fd3, bedrock_setup 1f329984bffd499dc14533e8538400c3ddf304e8. Postimages match #3230 donor 8522fc10c71ba5517a3367cf822553ba930f6b77: 955db668d75d9c5d9c7fff196b3332dd8dacbcb4 and 9e7cb31856c2b938c6a8ba73f8affb36bd4b5e3d. No donor CI conclusion is transferred. #3594 was not transplanted.

Only those two production files plus existing bedrock_setup integration test file change. Independent review found no blocker; final three-file diff SHA256 8dd2132b3d3db7063c94a1d3f9bbb3d519cff429b5b89df00de363d0461eb1d9. Final remote test blob b63797da1d7f4546a66392f7d846141562e1135d. GitHub plugin fetch_file verified exact content and blob for all three; git fetch and full tree diff verified combined commit. Reviewer inspected source and baseline failure log, did not run Cargo; final execution is parent-agent evidence.

## Commands and environment

Worktree /workspace/bedrock-integration, isolated from earlier worktrees. Root AGENTS.md read, no applicable nested AGENTS or .agents/skills found. Rust/Cargo 1.95.0, Just 1.59.0, nextest 0.9.149, Linux x86_64; 5 CPUs/about17GiB RAM/no swap. Disk about18GiB free initially, 2.7GiB after building actual app-server dependency closure. No whole-workspace run, model download, credential issuance or supplier request was performed.

```
export RUSTUP_HOME=/workspace/rustup CARGO_HOME=/workspace/cargo
export PATH=/workspace/cargo/bin:$PATH CARGO_TARGET_DIR=/workspace/target-3567 CARGO_BUILD_JOBS=3
git worktree add --detach /workspace/bedrock-integration 74ba1d6c11659c2a3e38b4ef6056778f1d00a2a2
# First attempted --test suite; actual target is all (failure retained).
just test --locked -p codex-app-server --test all -E 'test(v2::bedrock_setup::discover_bedrock_profiles_and_environment_credentials) | test(v2::bedrock_setup::setup_bedrock_rejects_invalid_or_conflicting_credentials)'
git apply /workspace/verification-bedrock/candidate.patch
git apply /workspace/verification-bedrock/auth-tests.patch
just fmt
git diff --check
just test --locked -p codex-app-server --test all -E 'test(v2::bedrock_setup::discover_bedrock_profiles_and_environment_credentials) | test(v2::bedrock_setup::setup_bedrock_rejects_invalid_or_conflicting_credentials) | test(v2::bedrock_setup::bedrock_discovery_and_setup_require_experimental_api)'
CARGO_INCREMENTAL=0 cargo clippy --manifest-path codex-rs/Cargo.toml --locked -p codex-app-server --all-targets -- -D warnings
# After GitHub create_tree/create_commit, verify remote equality before adopting exact SHA:
git fetch origin b6cae33e26f09474f96df5598edb59d3d74ddd69
git diff --exit-code b6cae33e26f09474f96df5598edb59d3d74ddd69
git reset --soft b6cae33e26f09474f96df5598edb59d3d74ddd69
just fmt --check --base 74ba1d6c11659c2a3e38b4ef6056778f1d00a2a2
# Repeat identical three-test command above on clean exact commit: exact-tests.log, exit0.
```

Lockfiles/dependencies unchanged. GitHub tree/commit/branch publication used plugin, not shell push. Full original command output and exit files are retained. Earlier 250 Rust and 54 Python results belong to their earlier exact sources; neither was rerun or claimed for this combined SHA.

## Safety and remaining evidence

Tests use existing static fake values in temporary AWS fixture files and environment overrides, disable EC2 metadata, and never issue real credentials or contact a cloud supplier. The third existing setup_bedrock_profile_and_environment test was deliberately excluded because it writes a simulated managed auth.json; no actual credential store was used. The new authorization tests reject before profile resolution. Actual general profile resolution may invoke credential_process/SSO/STS; passing static fixtures does not prove arbitrary profiles network-free. Environment setup checks presence and persists provider/region configuration, not credential authenticity (source TODO defers ListModels).

Unchanged initialization/experimental gate runs before dispatch. Both handlers first reject host workload identity, active external ChatGPT auth, or forced ChatGPT policy. Workload/external auth checks were inspected but not specifically executed in this restricted test set. No gate was removed.

Existing helper caveat: setup cancels active login and calls configure_bedrock_provider; batch_write may persist user config before reporting higher-precedence nested AWS override metadata as an error. This source-confirmed ordering is not dynamically reproduced or fixed here; no claim that all errors are mutation-free. High-precedence policy remains effective. Independent review found no contract requiring atomic rollback that would block this minimal routing repair.

Still pending: hosted exact-head CI, full app-server tests, strict Clippy dependency failures, workload/external-auth-specific tests, nested override behavior test, Windows/macOS, live supplier authentication/inference, native ModelPort and physical acceptance. Continue by examining exact-head hosted runs and resolving dependency lint failures separately with review; do not merge or deploy on these local results.
