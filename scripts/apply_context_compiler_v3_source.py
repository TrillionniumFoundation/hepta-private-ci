#!/usr/bin/env python3
"""Apply the canonical context.compiler V3 source wiring once."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one patch anchor, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


# Registry exports construction-closed authority snapshots and typed successors.
replace(
    "codex-rs/hepta-prompt-registry/src/lib.rs",
    "mod admission;\nmod delivery;",
    "mod admission;\nmod context_authority;\nmod delivery;",
)
replace(
    "codex-rs/hepta-prompt-registry/src/lib.rs",
    "pub use admission::final_use_revoke_binding;\npub use delivery::MAX_REALIZATION_PAYLOAD_BYTES;",
    "pub use admission::final_use_revoke_binding;\n"
    "pub use context_authority::PromptContextAuthorityAdmissionV3;\n"
    "pub use context_authority::PromptContextAuthorityErrorV3;\n"
    "pub use context_authority::PromptContextAuthoritySnapshotV3;\n"
    "pub use context_authority::PromptContextAuthoritySuccessorV3;\n"
    "pub use context_authority::prompt_context_authority_verifier_digest_v3;\n"
    "pub use delivery::MAX_REALIZATION_PAYLOAD_BYTES;",
)

# Intelligence owns the canonical serializer and exact-tokenizer adapter seam.
replace(
    "codex-rs/hepta-intelligence/Cargo.toml",
    "[lib]\nname = \"codex_hepta_intelligence\"\npath = \"src/lib.rs\"\ndoctest = false\n\n[lints]",
    "[lib]\nname = \"codex_hepta_intelligence\"\npath = \"src/lib.rs\"\ndoctest = false\n\n"
    "[features]\n"
    "default = [\"legacy-prompt-context-v1\"]\n"
    "legacy-prompt-context-v1 = []\n\n"
    "[lints]",
)
replace(
    "codex-rs/hepta-intelligence/Cargo.toml",
    "codex-hepta-context-compiler = { path = \"../hepta-context-compiler\" }\n",
    "codex-hepta-context-compiler = { path = \"../hepta-context-compiler\" }\n"
    "codex-hepta-contracts = { path = \"../hepta-contracts\" }\n",
)
replace(
    "codex-rs/hepta-intelligence/Cargo.toml",
    "codex-hepta-types = { path = \"../hepta-types\" }\n\n[dev-dependencies]\n"
    "codex-hepta-contracts = { path = \"../hepta-contracts\" }\n",
    "codex-hepta-types = { path = \"../hepta-types\" }\n"
    "serde = { workspace = true, features = [\"derive\"] }\n"
    "serde_json = { workspace = true }\n\n[dev-dependencies]\n",
)

replace(
    "codex-rs/hepta-intelligence/src/lib.rs",
    "mod prompt_pipeline;\n\npub use prompt_pipeline::PreparedPromptContextV1;",
    "#[cfg(feature = \"legacy-prompt-context-v1\")]\n"
    "mod prompt_pipeline;\n"
    "mod prompt_product_v3;\n\n"
    "#[cfg(feature = \"legacy-prompt-context-v1\")]\n"
    "pub use prompt_pipeline::PreparedPromptContextV1;",
)
for symbol in [
    "PreparedPromptDeliveryV1",
    "PromptContextCompileRequestV1",
    "PromptDeliveryPrepareRequestV1",
    "PromptPayloadMaterializationV1",
    "PromptPipelineErrorV1",
    "PromptSerializationOccurrenceV1",
    "PromptSerializationProofV1",
    "compile_exercised_prompt_context_v1",
    "observe_prompt_delivery_v1",
    "prepare_prompt_delivery_v1",
]:
    replace(
        "codex-rs/hepta-intelligence/src/lib.rs",
        f"pub use prompt_pipeline::{symbol};",
        f"#[cfg(feature = \"legacy-prompt-context-v1\")]\n"
        f"pub use prompt_pipeline::{symbol};",
    )
replace(
    "codex-rs/hepta-intelligence/src/lib.rs",
    "mod pipeline_v2;\nmod prompt_delivery;",
    "mod pipeline_v2;\n"
    "#[cfg(feature = \"legacy-prompt-context-v1\")]\n"
    "mod prompt_delivery;",
)
for symbol in [
    "PromptRegistryCompilationErrorV2",
    "PromptRegistryCompilationRequestV2",
    "PromptRegistryCompiledContextV2",
]:
    replace(
        "codex-rs/hepta-intelligence/src/lib.rs",
        f"pub use prompt_delivery::{symbol};",
        f"#[cfg(feature = \"legacy-prompt-context-v1\")]\n"
        f"pub use prompt_delivery::{symbol};",
    )
replace(
    "codex-rs/hepta-intelligence/src/lib.rs",
    "pub use prompt_delivery::compile_prompt_registry_v2;\n\nmod pipeline;",
    "#[cfg(feature = \"legacy-prompt-context-v1\")]\n"
    "pub use prompt_delivery::compile_prompt_registry_v2;\n\n"
    "pub use prompt_product_v3::PreparedPromptDeliveryV3;\n"
    "pub use prompt_product_v3::PromptExactTokenizerV3;\n"
    "pub use prompt_product_v3::PromptExecutionProfileV3;\n"
    "pub use prompt_product_v3::PromptProductV3Error;\n"
    "pub use prompt_product_v3::PromptRegistryCompilationRequestV3;\n"
    "pub use prompt_product_v3::PromptRegistryCompiledContextV3;\n"
    "pub use prompt_product_v3::PromptTokenizerIdentityV3;\n"
    "pub use prompt_product_v3::compile_prompt_registry_v3;\n"
    "pub use prompt_product_v3::observe_prompt_delivery_v3;\n"
    "pub use prompt_product_v3::prepare_prompt_delivery_v3;\n\n"
    "mod pipeline;",
)

# Correct additive source details before compilation.
replace(
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "use std::collections::BTreeMap;\nuse std::fmt;",
    "use std::fmt;",
)
replace(
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "    pub const fn execution_profile_digest(&self) -> Digest32 {\n"
    "        self.source_binding_digest\n"
    "    }",
    "    pub fn execution_profile_digest(&self) -> Digest32 {\n"
    "        self.execution_profile.digest()\n"
    "    }",
)
replace(
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "        self.authority.admissions().iter().any(|admission| {\n"
    "            record.admission_id == *admission.admission_id()\n"
    "                && record.item_id == *admission.realization_id()\n"
    "                && record.role == context_role(admission.role()).ok().unwrap_or(ContextRoleV2::Schema)",
    "        self.authority.admissions().iter().any(|admission| {\n"
    "            let Ok(role) = context_role(admission.role()) else {\n"
    "                return false;\n"
    "            };\n"
    "            record.admission_id == *admission.admission_id()\n"
    "                && record.item_id == *admission.realization_id()\n"
    "                && record.role == role",
)
replace(
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "    if prepared.authority.grants_any()\n"
    "        || prepared.preparation_binding_digest.is_zero()\n"
    "        || prepared.verified_snapshot.snapshot_digest()\n"
    "            != prepared.authority_successor.current().snapshot_digest()\n"
    "    {",
    "    if prepared.authority.grants_any()\n"
    "        || prepared.preparation_binding_digest.is_zero()\n"
    "        || prepared.preparation.payload_digest()\n"
    "            != compiled.serialized_context.receipt().payload_digest()\n"
    "    {",
)
replace(
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "            .field(\n"
    "                \"preparation_binding_digest\",\n"
    "                &self.preparation_binding_digest,\n"
    "            )",
    "            .field(\n"
    "                \"verified_snapshot_digest\",\n"
    "                &self.verified_snapshot.snapshot_digest(),\n"
    "            )\n"
    "            .field(\n"
    "                \"preparation_binding_digest\",\n"
    "                &self.preparation_binding_digest,\n"
    "            )",
)
replace(
    "codex-rs/hepta-intelligence/src/prompt_product_v3.rs",
    "    bytes.extend_from_slice(output.portfolio_receipt_digest.as_array());\n",
    "    bytes.extend_from_slice(output.portfolio_receipt_digest.as_array());\n"
    "    bytes.extend_from_slice(output.generation_vector_digest.as_array());\n",
)
