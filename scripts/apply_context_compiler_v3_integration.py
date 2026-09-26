#!/usr/bin/env python3
"""Wire the registry-authoritative V3 prompt product as an independent strict path."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARGO = ROOT / "codex-rs/hepta-intelligence/Cargo.toml"
LIB = ROOT / "codex-rs/hepta-intelligence/src/lib.rs"
PRODUCT = ROOT / "codex-rs/hepta-intelligence/src/prompt_product_v3.rs"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path.relative_to(ROOT)}: expected one replacement, found {count}: {old[:120]!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def patch_cargo() -> None:
    replace_once(
        CARGO,
        '''[lib]
name = "codex_hepta_intelligence"
path = "src/lib.rs"
doctest = false

[lints]
''',
        '''[lib]
name = "codex_hepta_intelligence"
path = "src/lib.rs"
doctest = false

[features]
default = ["legacy-prompt-context-v1"]
legacy-prompt-context-v1 = []

[lints]
''',
    )
    replace_once(
        CARGO,
        'codex-hepta-context-compiler = { path = "../hepta-context-compiler" }\n',
        'codex-hepta-context-compiler = { path = "../hepta-context-compiler" }\n'
        'codex-hepta-contracts = { path = "../hepta-contracts" }\n',
    )
    replace_once(
        CARGO,
        '''codex-hepta-types = { path = "../hepta-types" }

[dev-dependencies]
codex-hepta-contracts = { path = "../hepta-contracts" }
''',
        '''codex-hepta-types = { path = "../hepta-types" }
serde = { workspace = true, features = ["derive"] }
serde_json = { workspace = true }

[dev-dependencies]
''',
    )


def cfg_export(symbol: str) -> None:
    replace_once(
        LIB,
        f"pub use prompt_pipeline::{symbol};",
        f'#[cfg(feature = "legacy-prompt-context-v1")]\npub use prompt_pipeline::{symbol};',
    )


def patch_lib() -> None:
    replace_once(
        LIB,
        "mod prompt_pipeline;\n\npub use prompt_pipeline::PreparedPromptContextV1;",
        '#[cfg(feature = "legacy-prompt-context-v1")]\n'
        "mod prompt_pipeline;\n"
        "mod prompt_product_v3;\n\n"
        '#[cfg(feature = "legacy-prompt-context-v1")]\n'
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
        cfg_export(symbol)

    replace_once(
        LIB,
        '''mod pipeline_v2;
mod prompt_delivery;
mod provider_bound_prompt;
''',
        '''mod pipeline_v2;
#[cfg(feature = "legacy-prompt-context-v1")]
mod prompt_delivery;
#[cfg(feature = "legacy-prompt-context-v1")]
mod provider_bound_prompt;
''',
    )
    for symbol in [
        "PromptRegistryCompilationErrorV2",
        "PromptRegistryCompilationRequestV2",
        "PromptRegistryCompiledContextV2",
        "compile_prompt_registry_v2",
    ]:
        replace_once(
            LIB,
            f"pub use prompt_delivery::{symbol};",
            f'#[cfg(feature = "legacy-prompt-context-v1")]\npub use prompt_delivery::{symbol};',
        )
    for symbol in [
        "PreparedProviderBoundPromptV2",
        "ProviderBoundPromptErrorV2",
        "ProviderBoundPromptPrepareRequestV2",
        "ProviderRequestBuilderV2",
        "ProviderRequestMaterializationV2",
        "prepare_provider_bound_prompt_v2",
    ]:
        replace_once(
            LIB,
            f"pub use provider_bound_prompt::{symbol};",
            f'#[cfg(feature = "legacy-prompt-context-v1")]\npub use provider_bound_prompt::{symbol};',
        )

    anchor = '''#[cfg(feature = "legacy-prompt-context-v1")]
pub use provider_bound_prompt::prepare_provider_bound_prompt_v2;

mod pipeline;
'''
    exports = '''#[cfg(feature = "legacy-prompt-context-v1")]
pub use provider_bound_prompt::prepare_provider_bound_prompt_v2;
pub use prompt_product_v3::PreparedPromptDeliveryV3;
pub use prompt_product_v3::PromptExactTokenizerV3;
pub use prompt_product_v3::PromptExecutionProfileV3;
pub use prompt_product_v3::PromptProductV3Error;
pub use prompt_product_v3::PromptRegistryCompilationRequestV3;
pub use prompt_product_v3::PromptRegistryCompiledContextV3;
pub use prompt_product_v3::PromptTokenizerIdentityV3;
pub use prompt_product_v3::compile_prompt_registry_v3;
pub use prompt_product_v3::observe_prompt_delivery_v3;
pub use prompt_product_v3::prepare_prompt_delivery_v3;

mod pipeline;
'''
    replace_once(LIB, anchor, exports)


def patch_product() -> None:
    replace_once(
        PRODUCT,
        "use std::collections::BTreeMap;\nuse std::fmt;",
        "use std::fmt;",
    )
    replace_once(
        PRODUCT,
        '''    pub const fn execution_profile_digest(&self) -> Digest32 {
        self.source_binding_digest
    }
''',
        '''    pub fn execution_profile_digest(&self) -> Digest32 {
        self.execution_profile.digest()
    }
''',
    )
    replace_once(
        PRODUCT,
        '''        self.authority.admissions().iter().any(|admission| {
            record.admission_id == *admission.admission_id()
                && record.item_id == *admission.realization_id()
                && record.role == context_role(admission.role()).ok().unwrap_or(ContextRoleV2::Schema)
''',
        '''        self.authority.admissions().iter().any(|admission| {
            let Ok(role) = context_role(admission.role()) else {
                return false;
            };
            record.admission_id == *admission.admission_id()
                && record.item_id == *admission.realization_id()
                && record.role == role
''',
    )
    replace_once(
        PRODUCT,
        '''    if prepared.authority.grants_any()
        || prepared.preparation_binding_digest.is_zero()
        || prepared.verified_snapshot.snapshot_digest()
            != prepared.authority_successor.current().snapshot_digest()
    {
''',
        '''    if prepared.authority.grants_any()
        || prepared.preparation_binding_digest.is_zero()
        || prepared.preparation.payload_digest()
            != compiled.serialized_context.receipt().payload_digest()
    {
''',
    )
    replace_once(
        PRODUCT,
        '''            .field(
                "preparation_binding_digest",
                &self.preparation_binding_digest,
            )
''',
        '''            .field(
                "verified_snapshot_digest",
                &self.verified_snapshot.snapshot_digest(),
            )
            .field(
                "preparation_binding_digest",
                &self.preparation_binding_digest,
            )
''',
    )
    replace_once(
        PRODUCT,
        "    bytes.extend_from_slice(output.portfolio_receipt_digest.as_array());\n",
        "    bytes.extend_from_slice(output.portfolio_receipt_digest.as_array());\n"
        "    bytes.extend_from_slice(output.generation_vector_digest.as_array());\n",
    )


def main() -> int:
    patch_cargo()
    patch_lib()
    patch_product()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
