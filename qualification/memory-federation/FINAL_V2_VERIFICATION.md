# memory.federation V2 final verification

- workflow input head: `3b58ea278d1f99b049b66e43a0130f4a716f79ee`
- branch: `fix/memory-federation-v2-hardening-final`
- runner: `Linux/X64`
- generated UTC: `2026-09-18T22:58:16Z`
- overall: `FAIL`

## Commands

| check | exit |
|---|---:|
| `fmt` | 0 |
| `federation_contract` | 101 |
| `memory_product_adapter` | 0 |
| `memory_legacy_regression` | 0 |
| `extension_federation` | 101 |
| `agentd_runtime` | 101 |
| `composition_check` | 0 |
| `clippy` | 101 |
| `diff_check` | 0 |

## Failure tails

### federation_contract

~~~text
    Updating git repository `https://github.com/openai-oss-forks/crossterm`
    Updating git repository `https://github.com/openai-oss-forks/tokio-tungstenite`
    Updating git repository `https://github.com/openai-oss-forks/tungstenite-rs`
    Updating crates.io index
    Updating git repository `https://github.com/dzbarsky/rules_rust`
    Updating git repository `https://github.com/helix-editor/nucleo.git`
 Downloading crates ...
  Downloaded version_check v0.9.5
  Downloaded block-buffer v0.10.4
  Downloaded generic-array v0.14.7
  Downloaded cfg-if v1.0.4
  Downloaded digest v0.10.7
  Downloaded cpufeatures v0.2.17
  Downloaded crypto-common v0.1.7
  Downloaded sha2 v0.10.9
  Downloaded typenum v1.20.0
   Compiling version_check v0.9.5
   Compiling typenum v1.20.0
   Compiling cfg-if v1.0.4
   Compiling cpufeatures v0.2.17
   Compiling generic-array v0.14.7
   Compiling block-buffer v0.10.4
   Compiling crypto-common v0.1.7
   Compiling digest v0.10.7
   Compiling sha2 v0.10.9
   Compiling codex-hepta-types v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-types)
   Compiling codex-hepta-memory-federation v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-memory-federation)
    Finished `test` profile [unoptimized + debuginfo] target(s) in 12.13s
     Running unittests src/lib.rs (target/debug/deps/codex_hepta_memory_federation-d95851b756406eff)

running 26 tests
test tests::missing_terminal_observation_is_indeterminate ... ok
test tests::revoked_lease_is_rejected ... ok
test tests::snapshot_drift_is_rejected ... ok
test tests::terminal_response_is_bound ... ok
test v2::tests::cancellation_receipt_carries_no_success_assumption ... ok
test v2::tests::cancellation_control_interrupts_pending_transport ... ok
test v2::tests::current_authority_observation_cannot_be_expired ... ok
test v2::tests::deadline_control_interrupts_pending_transport ... ok
test v2::tests::duplicate_remote_identity_is_rejected ... ok
test v2::tests::indeterminate_result_cannot_claim_truncation ... ok
test v2::tests::nonterminal_attempt_is_explicitly_indeterminate_without_retry ... ok
test v2::tests::peer_scope_and_lease_drift_fail_closed ... ok
test v2::tests::one_attempt_returns_bounded_partial_result ... ok
test v2::tests::post_io_generation_drift_suppresses_remote_items ... ok
test v2::tests::post_io_observation_cannot_outlive_lease ... ok
test v2::tests::preflight_rejects_lease_longer_than_live_authority ... ok
test v2::tests::preflight_revocation_blocks_transport_dispatch ... ok
test v2::tests::post_io_revocation_suppresses_remote_items ... ok
test v2::tests::response_cannot_replay_across_query_binding ... ok
test v2::tests::response_digest_detects_field_tampering ... ok
test v2::tests::response_digest_binds_items_and_completeness ... ok
test v2::tests::result_expiry_is_capped_by_query_when_query_is_shorter_than_lease ... FAILED
test v2::tests::result_digest_binds_post_io_authority_observation ... ok
test v2::tests::result_expiry_is_capped_by_lease_and_query ... ok
test v2::tests::result_validator_rejects_semantically_inconsistent_completeness ... ok
test v2::tests::stale_response_generation_never_exposes_remote_items ... ok

failures:

---- v2::tests::result_expiry_is_capped_by_query_when_query_is_shorter_than_lease stdout ----

thread 'v2::tests::result_expiry_is_capped_by_query_when_query_is_shorter_than_lease' (2436) panicked at hepta-memory-federation/src/v2_tests.rs:419:33:
valid query-capped result: LeaseAuthorityHorizonExceeded
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace


failures:
    v2::tests::result_expiry_is_capped_by_query_when_query_is_shorter_than_lease

test result: FAILED. 25 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s

error: test failed, to rerun pass `-p codex-hepta-memory-federation --lib`
~~~

### extension_federation

~~~text
   Compiling prost-build v0.14.3
   Compiling codex-login v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/login)
   Compiling backtrace v0.3.76
   Compiling darling_macro v0.24.0
   Compiling tonic-build v0.14.3
   Compiling rfc6979 v0.4.0
   Compiling sentry-contexts v0.46.1
   Compiling protoc-bin-vendored-linux-s390_64 v3.2.0
   Compiling protoc-bin-vendored-linux-ppcle_64 v3.2.0
   Compiling protoc-bin-vendored-macos-aarch_64 v3.2.0
   Compiling protoc-bin-vendored-win32 v3.2.0
   Compiling protoc-bin-vendored-linux-aarch_64 v3.2.0
   Compiling xmlparser v0.13.6
   Compiling protoc-bin-vendored-macos-x86_64 v3.2.0
   Compiling protoc-bin-vendored-linux-x86_32 v3.2.0
   Compiling protoc-bin-vendored-linux-x86_64 v3.2.0
   Compiling sqlx-core v0.9.0
   Compiling aws-smithy-xml v0.60.13
   Compiling protoc-bin-vendored v3.2.0
   Compiling ecdsa v0.16.9
   Compiling tonic-prost-build v0.14.3
   Compiling darling v0.24.0
   Compiling sentry-backtrace v0.46.1
   Compiling primeorder v0.13.6
   Compiling aws-smithy-query v0.60.9
   Compiling schemars_derive v1.2.1
   Compiling hostname v0.4.2
   Compiling uname v0.1.1
   Compiling rmcp v3.1.3
   Compiling aws-sdk-sts v1.95.0
   Compiling sqlx-sqlite v0.9.0
   Compiling schemars v1.2.1
   Compiling codex-utils-plugins v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/plugins)
   Compiling p256 v0.13.2
   Compiling sentry-panic v0.46.1
   Compiling sentry-debug-images v0.46.1
   Compiling rmcp-macros v3.1.3
   Compiling codex-code-mode-protocol v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/code-mode-protocol)
   Compiling aws-sdk-ssooidc v1.93.0
   Compiling aws-sdk-sso v1.91.0
   Compiling aws-sdk-signin v1.2.0
   Compiling codex-hepta-contracts v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-contracts)
   Compiling oauth2 v5.0.0
   Compiling codex-utils-output-truncation v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/output-truncation)
   Compiling process-wrap v9.0.1
   Compiling reqwest v0.13.4
   Compiling sse-stream v0.2.5
   Compiling base64 v0.23.0
   Compiling pastey v0.2.1
   Compiling sqlx-macros-core v0.9.0
   Compiling aws-config v1.8.12
   Compiling sentry v0.46.1
   Compiling codex-plugin v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/plugin)
   Compiling codex-hepta-types v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-types)
   Compiling semver v1.0.27
   Compiling codex-collaboration-mode-templates v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/collaboration-mode-templates)
   Compiling codex-models-manager v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/models-manager)
   Compiling codex-install-context v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/install-context)
   Compiling codex-connectors v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/connectors)
   Compiling codex-aws-auth v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/aws-auth)
   Compiling codex-feedback v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/feedback)
   Compiling sqlx-macros v0.9.0
   Compiling codex-response-debug-context v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/response-debug-context)
   Compiling sqlx v0.9.0
   Compiling codex-hepta-cognitive-types v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-cognitive-types)
   Compiling codex-model-provider v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/model-provider)
   Compiling codex-exec-server-test-support v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/exec-server/tests/support)
   Compiling codex-history v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/history)
   Compiling codex-rmcp-client v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/rmcp-client)
   Compiling codex-code-mode v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/code-mode)
   Compiling codex-diagnostics v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/diagnostics)
   Compiling jsonptr v0.7.1
   Compiling codex-state v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/state)
   Compiling codex-tools v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/tools)
   Compiling codex-mcp v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/codex-mcp)
   Compiling codex-hepta-cognitive-read v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-cognitive-read)
   Compiling codex-hepta-memory-federation v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-memory-federation)
   Compiling codex-hepta-paths v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-paths)
   Compiling codex-context-fragments v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/context-fragments)
   Compiling codex-hepta-memory v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-memory)
   Compiling codex-extension-api v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/extension-api)
   Compiling codex-hepta-memory-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/hepta-memory)
error[E0433]: cannot find type `CognitiveScope` in this scope
    --> ext/hepta-memory/src/cognitive/federation.rs:1049:28
     |
1049 |                     scope: CognitiveScope::AgentPrivate,
     |                            ^^^^^^^^^^^^^^ use of undeclared type `CognitiveScope`
     |
help: a struct with a similar name exists
     |
1049 -                     scope: CognitiveScope::AgentPrivate,
1049 +                     scope: CognitiveStore::AgentPrivate,
     |

error[E0433]: cannot find type `CognitiveScope` in this scope
    --> ext/hepta-memory/src/cognitive/federation.rs:1064:32
     |
1064 |                         scope: CognitiveScope::AgentPrivate,
     |                                ^^^^^^^^^^^^^^ use of undeclared type `CognitiveScope`
     |
help: a struct with a similar name exists
     |
1064 -                         scope: CognitiveScope::AgentPrivate,
1064 +                         scope: CognitiveStore::AgentPrivate,
     |

error[E0433]: cannot find type `CognitiveScope` in this scope
    --> ext/hepta-memory/src/cognitive/federation.rs:1085:25
     |
1085 |                         CognitiveScope::AgentPrivate,
     |                         ^^^^^^^^^^^^^^ use of undeclared type `CognitiveScope`
     |
help: a struct with a similar name exists
     |
1085 -                         CognitiveScope::AgentPrivate,
1085 +                         CognitiveStore::AgentPrivate,
     |

For more information about this error, try `rustc --explain E0433`.
error: could not compile `codex-hepta-memory-extension` (lib test) due to 3 previous errors
~~~

### agentd_runtime

~~~text
   Compiling serde_yaml v0.9.34+deprecated
   Compiling zip v2.4.2
   Compiling xz2 v0.1.7
   Compiling bzip2 v0.5.2
   Compiling darling v0.20.11
   Compiling zopfli v0.8.3
   Compiling lzma-rs v0.3.0
   Compiling stop-words v0.9.0
   Compiling filetime v0.2.27
   Compiling pulldown-cmark v0.10.3
   Compiling extended v0.1.0
   Compiling deflate64 v0.1.10
   Compiling symphonia-format-riff v0.6.0
   Compiling tar v0.4.45
   Compiling cached_proc_macro v0.25.0
   Compiling symphonia-format-ogg v0.6.0
   Compiling symphonia-format-isomp4 v0.6.0
   Compiling symphonia-format-mkv v0.6.0
   Compiling symphonia-bundle-mp3 v0.6.0
   Compiling codex-hooks v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hooks)
   Compiling web-time v1.1.0
   Compiling cached_proc_macro_types v0.1.1
   Compiling symphonia v0.6.0
   Compiling cached v0.56.0
   Compiling codex-apply-patch v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/apply-patch)
   Compiling codex-shell-escalation v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/shell-escalation)
   Compiling rust-stemmers v1.2.0
   Compiling deunicode v1.6.2
   Compiling bm25 v2.3.2
   Compiling codex-utils-audio v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/audio)
   Compiling codex-prompts v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/prompts)
   Compiling codex-rollout-trace v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/rollout-trace)
   Compiling codex-agent-graph-store v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/agent-graph-store)
   Compiling codex-memories-read v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/memories/read)
   Compiling codex-utils-stream-parser v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/stream-parser)
   Compiling whoami v1.6.1
   Compiling codex-hepta-paths v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-paths)
   Compiling codex-backend-openapi-models v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/codex-backend-openapi-models)
   Compiling inotify-sys v0.1.5
   Compiling codex-linux-sandbox v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/linux-sandbox)
   Compiling inotify v0.11.0
   Compiling notify-types v2.1.0
   Compiling codex-backend-client v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/backend-client)
   Compiling codex-process-hardening v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/process-hardening)
   Compiling is_ci v1.2.0
   Compiling notify v8.2.0
   Compiling is-terminal v0.4.17
   Compiling owo-colors v4.3.0
   Compiling supports-color v2.1.0
   Compiling codex-hepta-memory v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-memory)
   Compiling codex-arg0 v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/arg0)
   Compiling supports-color v3.0.2
   Compiling codex-hepta-authbus v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-authbus)
   Compiling codex-home v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/codex-home)
   Compiling codex-uds v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/uds)
   Compiling num_cpus v1.17.0
   Compiling deadpool-runtime v0.1.4
   Compiling dtor-proc-macro v0.0.6
   Compiling dtor v0.1.1
   Compiling deadpool v0.12.3
   Compiling codex-hepta-evidence v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-evidence)
   Compiling codex-utils-cli v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/cli)
   Compiling assert-json-diff v2.0.2
   Compiling ctor-proc-macro v0.0.7
   Compiling ctor v0.6.3
   Compiling wiremock v0.6.5
   Compiling codex-hepta-governance v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/hepta-governance)
   Compiling codex-file-watcher v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/file-watcher)
   Compiling codex-analytics v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/analytics)
   Compiling codex-thread-store v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/thread-store)
   Compiling codex-core-plugins v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/core-plugins)
   Compiling codex-skills-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/skills)
   Compiling codex-hepta-memory-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/hepta-memory)
   Compiling codex-core v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/core)
   Compiling codex-connectors-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/connectors)
   Compiling codex-git-attribution v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/git-attribution)
   Compiling codex-hepta-automation v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-automation)
   Compiling codex-hepta-fleet v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-fleet)
   Compiling codex-utils-json-to-toml v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/json-to-toml)
   Compiling codex-hepta-agent-protocol v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-agent-protocol)
   Compiling codex-hepta-ndu v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-ndu)
   Compiling codex-hepta-matrix-protocol v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-matrix-protocol)
   Compiling codex-hepta-control-plane v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-control-plane)
   Compiling codex-hepta-supervisor v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-supervisor)
   Compiling codex-hepta-bellman-operator v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-bellman-operator)
   Compiling codex-hepta-learning-artifacts v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-learning-artifacts)
   Compiling codex-memories-write v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/memories/write)
   Compiling codex-history-notes-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/history-notes)
   Compiling codex-queue-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/queue)
   Compiling codex-web-search-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/web-search)
   Compiling codex-external-agent-migration v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/external-agent-migration)
   Compiling codex-goal-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/goal)
   Compiling codex-mcp-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/mcp)
   Compiling codex-agent-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/agent)
   Compiling codex-guardian-v2 v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/guardian-v2)
   Compiling codex-memories-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/memories)
   Compiling codex-chatgpt v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/chatgpt)
   Compiling codex-cloud-config v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/cloud-config)
   Compiling codex-app-server-transport v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/app-server-transport)
   Compiling codex-image-generation-extension v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/image-generation)
   Compiling core_test_support v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/core/tests/common)
   Compiling codex-app-server v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/app-server)
   Compiling app_test_support v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/app-server/tests/common)
   Compiling codex-app-server-client v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/app-server-client)
   Compiling codex-hepta-agentd v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-agentd)
error[E0422]: cannot find struct, variant or union type `LifecycleSnapshot` in this scope
  --> hepta-agentd/src/state_isolation_tests.rs:75:55
   |
75 |         serde_json::to_value(AgentdPayload::Lifecycle(LifecycleSnapshot {
   |                                                       ^^^^^^^^^^^^^^^^^ not found in this scope

error[E0433]: cannot find type `AgentdPayload` in this scope
  --> hepta-agentd/src/state_isolation_tests.rs:75:30
   |
75 |         serde_json::to_value(AgentdPayload::Lifecycle(LifecycleSnapshot {
   |                              ^^^^^^^^^^^^^ use of undeclared type `AgentdPayload`

Some errors have detailed explanations: E0422, E0433.
For more information about an error, try `rustc --explain E0422`.
error: could not compile `codex-hepta-agentd` (lib test) due to 2 previous errors
~~~

### clippy

~~~text
 Downloading crates ...
  Downloaded test-case v3.3.1
  Downloaded test-case-core v3.3.1
  Downloaded sdd v3.0.10
  Downloaded serial_test_derive v3.3.1
  Downloaded test-case-macros v3.3.1
  Downloaded serial_test v3.3.1
  Downloaded scc v2.4.0
    Checking hyper v1.8.1
    Checking codex-utils-absolute-path v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/absolute-path)
    Checking codex-utils-rustls-provider v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/rustls-provider)
    Checking codex-utils-cache v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/cache)
    Checking codex-utils-redacted-string v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/redacted-string)
    Checking codex-utils-string v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/string)
    Checking codex-utils-image v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/image)
    Checking codex-utils-home-dir v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/home-dir)
    Checking codex-network-proxy v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/network-proxy)
    Checking codex-execpolicy v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/execpolicy)
    Checking codex-utils-path-uri v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/path-uri)
    Checking hyper-util v0.1.20
    Checking codex-extension-items v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/ext/items)
    Checking codex-async-utils v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/async-utils)
    Checking codex-utils-pty v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/pty)
    Checking codex-utils-path v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/path-utils)
   Compiling codex-windows-sandbox v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/windows-sandbox-rs)
    Checking codex-keyring-store v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/keyring-store)
    Checking codex-hepta-contracts v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-contracts)
    Checking hyper-rustls v0.27.7
    Checking hyper-tls v0.6.0
    Checking hyper-timeout v0.5.2
    Checking reqwest v0.12.28
    Checking tonic v0.14.3
    Checking codex-http-client v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/http-client)
    Checking tonic-prost v0.14.3
    Checking opentelemetry-proto v0.31.0
    Checking codex-websocket-client v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/websocket-client)
    Checking codex-client v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/codex-client)
    Checking opentelemetry-http v0.31.0
    Checking axum v0.8.8
    Checking opentelemetry-otlp v0.31.0
    Checking codex-protocol v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/protocol)
    Checking aws-smithy-http-client v1.1.12
    Checking aws-smithy-runtime v1.9.5
    Checking codex-utils-template v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/template)
    Checking codex-workload-identity v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/workload-identity)
    Checking aws-runtime v1.5.17
    Checking codex-terminal-detection v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/terminal-detection)
   Compiling rmcp v3.1.3
    Checking oauth2 v5.0.0
    Checking reqwest v0.13.4
    Checking codex-install-context v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/install-context)
    Checking aws-sdk-sts v1.95.0
    Checking aws-sdk-ssooidc v1.93.0
    Checking aws-sdk-signin v1.2.0
    Checking aws-sdk-sso v1.91.0
   Compiling codex-code-mode-protocol v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/code-mode-protocol)
    Checking sentry v0.46.1
    Checking aws-config v1.8.12
    Checking codex-collaboration-mode-templates v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/collaboration-mode-templates)
    Checking codex-diagnostics v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/diagnostics)
    Checking codex-file-search v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/file-search)
    Checking codex-utils-cargo-bin v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/cargo-bin)
   Compiling codex-experimental-api-macros v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/codex-experimental-api-macros)
   Compiling codex-app-server-protocol-noop-macros v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/app-server-protocol-noop-macros)
   Compiling codex-skills v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/skills)
    Checking codex-utils-stream-parser v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/utils/stream-parser)
    Checking codex-hepta-types v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-types)
    Checking codex-hepta-paths v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-paths)
    Checking codex-aws-auth v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/aws-auth)
    Checking codex-hepta-cognitive-types v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-cognitive-types)
    Checking codex-hepta-memory-federation v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-memory-federation)
    Checking codex-hepta-cognitive-read v0.0.0 (/home/runner/work/hepta-private-ci/hepta-private-ci/codex-rs/hepta-cognitive-read)
error: large size difference between variants
   --> hepta-memory-federation/src/v2.rs:300:1
    |
300 | / pub enum FederationTransportResultV2 {
301 | |     Terminal(RemoteFederatedResponseV2),
    | |     ----------------------------------- the largest variant contains at least 232 bytes
302 | |     NonTerminal(FederationTransportOutcomeV2),
    | |     ----------------------------------------- the second-largest variant contains at least 1 bytes
303 | | }
    | |_^ the entire enum is at least 232 bytes
    |
    = help: for further information visit https://rust-lang.github.io/rust-clippy/rust-1.95.0/index.html#large_enum_variant
    = note: `-D clippy::large-enum-variant` implied by `-D warnings`
    = help: to override `-D warnings` add `#[allow(clippy::large_enum_variant)]`
help: consider boxing the large fields or introducing indirection in some other way to reduce the total size of the enum
    |
301 -     Terminal(RemoteFederatedResponseV2),
301 +     Terminal(Box<RemoteFederatedResponseV2>),
    |

error: could not compile `codex-hepta-memory-federation` (lib) due to 1 previous error
warning: build failed, waiting for other jobs to finish...
~~~

