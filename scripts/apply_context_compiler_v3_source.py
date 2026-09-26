#!/usr/bin/env python3
"""One-shot source migration for the context.compiler V3 product path.

The bootstrap workflow removes this script and itself after all focused Rust
checks pass, leaving only the reviewed source/documentation changes.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected patch anchor missing in {path}: {old[:120]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"patch anchor is not unique in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


# Registry exports its construction-closed authority objects.
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

# Intelligence gets serde for the canonical serializer and contracts for the
# provider receipt consumed by observe_prompt_delivery_v3.
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

# Keep legacy V1/V2 composition available only behind an explicit compatibility
# feature. The V3 compiler is always present.
replace(
    "codex-rs/hepta-intelligence/src/lib.rs",
    "mod prompt_pipeline;\n\npub use prompt_pipeline::PreparedPromptContextV1;",
    "#[cfg(feature = \"legacy-prompt-context-v1\")]\n"
    "mod prompt_pipeline;\n"
    "mod prompt_product_v3;\n\n"
    "#[cfg(feature = \"legacy-prompt-context-v1\")]\n"
    "pub use prompt_pipeline::PreparedPromptContextV1;",
)
legacy_exports = [
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
]
for symbol in legacy_exports:
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
legacy_delivery_exports = [
    "PromptRegistryCompilationErrorV2",
    "PromptRegistryCompilationRequestV2",
    "PromptRegistryCompiledContextV2",
    "compile_prompt_registry_v2",
]
for symbol in legacy_delivery_exports:
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

# Small correctness fixes made after the initial additive source landed.
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

# One-shot bootstrap files disappear only after all checks have succeeded.
(ROOT / ".github/workflows/context-compiler-v3-bootstrap.yml").unlink()
Path(__file__).unlink()
