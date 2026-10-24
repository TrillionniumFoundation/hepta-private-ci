# Explicit Serde callback contract

Parent: #3683, b04e4a07f5a757b3dfb7318de355ffb953b0ad00, tree bb7b0886a17663f56ddb8d81372e0a03d7f2a786.

The only production change is one function-level expectation for clippy::trivially_copy_pass_by_ref on taskflow_serde::generation::serialize, with a Serde callback reason. Its &Generation signature, serialize_u64 call and constructor-validated decoder are unchanged. No module/global lint relaxation, public API, shared type serialization contract, authorization or durable schema change.

Serde explicitly requires serialize_with to be callable as fn(&T, S); with uses that callback. Official reference: https://serde.rs/field-attrs.html. The parent revision already contains the equivalent nested-if cleanup. The repository's existing is_true(&bool) callback in protocol/src/openai_models.rs:382/417 uses local allow; this patch instead uses expect, so a future obsolete expectation is diagnosable. No unfulfilled_lint_expectations suppression is added. This expectation documents a required callback signature, not a product behavior exception.

Existing codec fixtures are reused, not duplicated. The generation test retains zero/negative/noninteger/string/null rejection, adds missing and raw JSON u64 overflow rejection, and verifies 1/u64::MAX as numeric JSON plus complete Frame and canonical-byte roundtrips. This tests primitive codec boundaries, not authority, lease validity or cross-generation reauthorization.

The earlier actual strict failure remains committed under qualification/dot-verification/20261024-native-owner-lint/strict.log in the parent. It is not deleted or relabelled. No remote CI queries, socket operations or real provider calls are part of this validation.

## Local results

Rust 1.96.0, locked/offline, jobs=1. Five selected integration targets: 42/42 passed, zero skipped/retried. Strict scoped no-deps Clippy passed (exit 0), including the five test targets. This is not whole-workspace or all-features Clippy: upstream PTY dependency deprecation warning remains visible. just fmt and git diff --check passed; both modified files are byte-identical before/after formatting, and tests were not rerun after formatting per repository instructions.
