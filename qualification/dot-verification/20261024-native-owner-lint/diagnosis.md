# Narrow native-owner lint repair

Parent: #3682, 8db04ef9d30d2ad633e8ed2092e46a47a4385671 (tree c002c9ef7c11a2a7df445e18df33f11af1971eeb).

Only the nested conditional in AutomationStatusEffectOwner::pending changes. The let-chain preserves the Option guard and the entire grouped disjunction of eight identity checks. No schema, public API, authorization, receipt, cancel, or durable storage changes.

The other strict diagnostic remains deliberately unresolved: taskflow_serde::generation::serialize takes &Generation, an eight-byte Copy type. Serde's with/serialize_with contract requires a callable fn(&T, S); changing to Generation by value is incompatible with the existing derive call. No generic/lifetime/macro workaround or allow/expect is added. The repository has an analogous local allowance for is_true(&bool), used by skip_serializing_if in protocol/src/openai_models.rs:382/417, and generated prost code has a file-level allowance. Neither is adopted here.

Official contract: https://serde.rs/field-attrs.html (see serialize_with and with sections on that page).
Official lint reference: https://rust-lang.github.io/rust-clippy/rust-1.96.0/index.html#trivially_copy_pass_by_ref

Existing pre-change strict failure is preserved in the parent evidence. This is a partial lint cleanup, not a strict pass, durable adapter completion, provider execution, network attestation, or production qualification. Remote CI is not queried per user instruction.

## Local validation

Rust 1.96.0, jobs=1, offline/locked; 37/37 existing selected integration tests passed, zero skips/retries (exit 0). Scoped no-deps strict Clippy exits 101 with only the unchanged Serde reference lint. just fmt and git diff --check exit 0; the changed source is byte-identical before/after formatting. No tests rerun after fmt, per repository instructions. Raw test and strict logs retained here; this is not a complete workspace test.
