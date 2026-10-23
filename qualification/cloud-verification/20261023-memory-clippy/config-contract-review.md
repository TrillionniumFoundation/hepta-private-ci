# Bedrock configuration contract review

Reviewed source: `b6cae33e26f09474f96df5598edb59d3d74ddd69` in `/workspace/bedrock-integration`; worktree clean at inspection. Read-only source/document/test review; no Cargo execution, AWS request, fixture credential generation, or production edit.

## Conclusion

No established contract violation or security vulnerability demonstrated. The config batch API explicitly supports successful persisted writes whose effective values remain overridden. Its atomicity promise concerns applying the edit batch to the user file; it does not promise that every edited value becomes effective, nor that a caller's later error rolls the batch back. The Bedrock wrapper translates this successful-but-overridden result into an API error after persistence and after cancelling active login. This is an existing behavior/UX limitation, not an authorization bypass. No production fix is required for the minimal route repair on the evidence reviewed. Do not describe all Bedrock setup errors as mutation-free.

## Concrete contract evidence

- `codex-rs/app-server/README.md:295`: `config/batchWrite` applies multiple edits “atomically to the user's config.toml on disk.” This describes the batch, not a transaction around arbitrary caller operations.
- `codex-rs/app-server-protocol/src/protocol/v2/config.rs:324`: `WriteStatus` explicitly has `Ok` and `OkOverridden`. `OverriddenMetadata` (332) exposes the overriding layer and effective value. `ConfigWriteResponse.file_path` (345) is documented as the canonical path “that was written.” These are successful responses, distinct from `ConfigWriteErrorCode`.
- `ConfigBatchWriteParams` in that file at 1050 supports expected_version and an optional hot reload **after writing**, with no rollback/zero-side-effects promise.
- `config_manager_service.rs:194–218`: value and batch writes share `apply_edits`. At 392–434 it validates candidate user/effective configurations, at 437–443 persists edits, and at 445–464 computes override metadata and returns `OkOverridden` when appropriate. The effective higher-priority configuration remains authoritative.
- `config_manager_service_tests.rs:1167` (`write_value_reports_managed_override`) expects successful `OkOverridden`, overriding layer, and the managed effective value. `multi_agent_v2_boolean_layer_owns_enabled_origin_and_overrides` and `shell_environment_representation_switch_reports_managed_override` also explicitly expect that successful status. These existing tests establish override reporting rather than treating override itself as a failed config write; they do not independently assert every written byte.
- `config_manager_service_tests.rs:303` (`batch_write_rejects_legacy_profile_selector`) asserts that a batch containing one valid edit and one invalid edit leaves the existing file unchanged. `invalid_user_value_rejected_even_if_overridden_by_managed` (805) similarly checks unchanged existing file after actual validation rejection. These support validation atomicity and do not contradict the distinct `OkOverridden` success path.

## Bedrock wrapper scope

- `request_processors/bedrock_auth.rs:43–63` awaits batch_write then converts returned overridden_metadata to invalid_request. It does not undo the successful batch.
- Its preflight at 68–102 rejects an incompatible higher-priority model_provider; it does not reject every higher-priority nested AWS field before writing.
- `request_processors/account_processor/bedrock_setup.rs:123–132` cancels active login before invoking configure_bedrock_provider. Consequently a later persistence error or overridden-result conversion can occur after cancellation.
- `README.md:2309,2437–2480` describes profile/environment validation, config persistence on success, metadata-only discovery, and preserving `.env`. Neither this text nor `protocol/v2/bedrock.rs:46–62` promises rollback or absence of side effects on every failure.
- Existing managed login nested-AWS-override regression (`tests/suite/v2/account.rs:1327`) expects the wrapper error and preservation of stored auth; it does not assert rollback of config or cancellation.

A setup error after a successful overridden batch therefore remains a real observable side effect, but there is no reviewed contractual basis to label it an atomicity violation or require a security fix. If stronger UX semantics are desired, specify them explicitly and add a local static-fixture regression for config bytes and active-login behavior before changing the shared helper. This review did not dynamically reproduce that path; it cannot establish cancellation observability, fault durability, or universal no-partial-write guarantees. The initial lookup for unsplit `protocol/v2.rs` returned file-not-found; the actual split `protocol/v2/config.rs` and `bedrock.rs` were located and inspected.
