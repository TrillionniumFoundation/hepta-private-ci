#!/usr/bin/env python3
"""Wire digest-only context final-use proof through Extension API and Core."""

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


# Extension API module and public exports.
replace(
    "codex-rs/ext/extension-api/src/contributors.rs",
    "mod model_provider_input;\nmod model_provider_policy;",
    "mod model_provider_context;\nmod model_provider_input;\nmod model_provider_policy;",
)
replace(
    "codex-rs/ext/extension-api/src/contributors.rs",
    "pub use model_provider_input::EphemeralModelInputSource;\n"
    "pub use model_provider_policy::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION;",
    "pub use model_provider_input::EphemeralModelInputSource;\n"
    "pub use model_provider_context::MODEL_PROVIDER_CONTEXT_SCHEMA_VERSION;\n"
    "pub use model_provider_context::ModelProviderContextFinalUseContributor;\n"
    "pub use model_provider_context::ModelProviderContextFinalUseInput;\n"
    "pub use model_provider_context::ModelProviderContextFinalUseProposal;\n"
    "pub use model_provider_policy::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION;",
)
replace(
    "codex-rs/ext/extension-api/src/lib.rs",
    "pub use contributors::ModelProviderAttemptLease;\n",
    "pub use contributors::MODEL_PROVIDER_CONTEXT_SCHEMA_VERSION;\n"
    "pub use contributors::ModelProviderAttemptLease;\n"
    "pub use contributors::ModelProviderContextFinalUseContributor;\n"
    "pub use contributors::ModelProviderContextFinalUseInput;\n"
    "pub use contributors::ModelProviderContextFinalUseProposal;\n",
)

# Registry owns one ordered contributor class for pre-finalization context proof.
replace(
    "codex-rs/ext/extension-api/src/registry.rs",
    "use crate::McpServerContributor;\nuse crate::ModelProviderPolicyContributor;",
    "use crate::McpServerContributor;\n"
    "use crate::ModelProviderContextFinalUseContributor;\n"
    "use crate::ModelProviderPolicyContributor;",
)
replace(
    "codex-rs/ext/extension-api/src/registry.rs",
    "                ephemeral_model_input_contributors: Vec::new(),\n"
    "                mcp_server_contributors: Vec::new(),",
    "                ephemeral_model_input_contributors: Vec::new(),\n"
    "                model_provider_context_final_use_contributors: Vec::new(),\n"
    "                mcp_server_contributors: Vec::new(),",
)
replace(
    "codex-rs/ext/extension-api/src/registry.rs",
    "    /// Registers one runtime MCP server contributor.\n"
    "    pub fn mcp_server_contributor",
    "    /// Registers one final-use proof contributor for context already assembled into a request.\n"
    "    pub fn model_provider_context_final_use_contributor(\n"
    "        &mut self,\n"
    "        contributor: Arc<dyn ModelProviderContextFinalUseContributor>,\n"
    "    ) {\n"
    "        self.registry\n"
    "            .model_provider_context_final_use_contributors\n"
    "            .push(contributor);\n"
    "    }\n\n"
    "    /// Registers one runtime MCP server contributor.\n"
    "    pub fn mcp_server_contributor",
)
replace(
    "codex-rs/ext/extension-api/src/registry.rs",
    "    ephemeral_model_input_contributors: Vec<Arc<dyn EphemeralModelInputContributor>>,\n"
    "    mcp_server_contributors:",
    "    ephemeral_model_input_contributors: Vec<Arc<dyn EphemeralModelInputContributor>>,\n"
    "    model_provider_context_final_use_contributors:\n"
    "        Vec<Arc<dyn ModelProviderContextFinalUseContributor>>,\n"
    "    mcp_server_contributors:",
)
replace(
    "codex-rs/ext/extension-api/src/registry.rs",
    "    /// Returns the registered runtime MCP server contributors.\n"
    "    pub fn mcp_server_contributors",
    "    /// Returns provider-context final-use contributors in registration order.\n"
    "    pub fn model_provider_context_final_use_contributors(\n"
    "        &self,\n"
    "    ) -> &[Arc<dyn ModelProviderContextFinalUseContributor>] {\n"
    "        &self.model_provider_context_final_use_contributors\n"
    "    }\n\n"
    "    /// Returns the registered runtime MCP server contributors.\n"
    "    pub fn mcp_server_contributors",
)

# Core module registration.
replace(
    "codex-rs/core/src/model_provider_policy/mod.rs",
    "mod binding;\n",
    "mod binding;\nmod context_input;\n",
)
replace(
    "codex-rs/core/src/model_provider_policy/mod.rs",
    "pub(crate) use binding::prepare_model_provider_policy;\n"
    "pub(crate) use ephemeral_input::resolve_ephemeral_model_input;",
    "pub(crate) use binding::prepare_model_provider_policy;\n"
    "pub(crate) use context_input::resolve_model_provider_context;\n"
    "pub(crate) use ephemeral_input::resolve_ephemeral_model_input;",
)

# Extend the provider-attempt envelope without changing existing call sites.
replace(
    "codex-rs/core/src/model_provider_policy/binding.rs",
    "use super::ephemeral_input::EphemeralModelInputBinding;\n",
    "use super::context_input::ModelProviderContextBinding;\n"
    "use super::ephemeral_input::EphemeralModelInputBinding;\n",
)
old_header = """    pub(crate) fn finalize<L: Serialize, W: Serialize>(
        self,
        effective_logical_request: &L,
        effective_wire_semantic: &W,
        ephemeral_input: Option<EphemeralModelInputBinding>,
    ) -> Result<PreparedModelProviderPolicy, ModelProviderPolicyError> {
        let logical_request_sha256 = canonical_sha256(effective_logical_request)?;
        let wire_semantic_sha256 = canonical_sha256(effective_wire_semantic)?;
        if ephemeral_input.is_some() != (logical_request_sha256 != self.base_logical_request_sha256)
        {
            return Err(ModelProviderPolicyError::new(
                \"ephemeral_model_input_effective_binding_mismatch\",
                \"effective logical semantics and ephemeral input presence must change together\",
            ));
        }
        let (ephemeral_input_sha256, ephemeral_input_witness_sha256) = match ephemeral_input {
            Some(binding) => {
                let witness = ephemeral_input_witness_sha256(
                    self.attempt_id.as_str(),
                    self.thread_id.as_str(),
                    self.turn_id.as_str(),
                    self.request_binding_id.as_str(),
                    self.transport,
                    &logical_request_sha256,
                    &wire_semantic_sha256,
                    self.previous_response_id_sha256.as_ref(),
                    self.generate,
                    &binding,
                )?;
                (Some(binding.input_sha256().clone()), Some(witness))
            }
            None => (None, None),
        };
"""
new_header = """    pub(crate) fn finalize<L: Serialize, W: Serialize>(
        self,
        effective_logical_request: &L,
        effective_wire_semantic: &W,
        ephemeral_input: Option<EphemeralModelInputBinding>,
    ) -> Result<PreparedModelProviderPolicy, ModelProviderPolicyError> {
        self.finalize_with_context(
            effective_logical_request,
            effective_wire_semantic,
            ephemeral_input,
            /*provider_context*/ None,
        )
    }

    pub(crate) fn finalize_with_context<L: Serialize, W: Serialize>(
        self,
        effective_logical_request: &L,
        effective_wire_semantic: &W,
        ephemeral_input: Option<EphemeralModelInputBinding>,
        provider_context: Option<ModelProviderContextBinding>,
    ) -> Result<PreparedModelProviderPolicy, ModelProviderPolicyError> {
        let logical_request_sha256 = canonical_sha256(effective_logical_request)?;
        let wire_semantic_sha256 = canonical_sha256(effective_wire_semantic)?;
        if ephemeral_input.is_some() && provider_context.is_some() {
            return Err(ModelProviderPolicyError::new(
                \"model_provider_bound_input_conflict\",
                \"ephemeral model input and context final-use proof cannot share one provider evidence slot\",
            ));
        }
        if ephemeral_input.is_some() != (logical_request_sha256 != self.base_logical_request_sha256)
        {
            return Err(ModelProviderPolicyError::new(
                \"ephemeral_model_input_effective_binding_mismatch\",
                \"effective logical semantics and ephemeral input presence must change together\",
            ));
        }
        let (ephemeral_input_sha256, ephemeral_input_witness_sha256) =
            match (ephemeral_input, provider_context) {
                (Some(binding), None) => {
                    let witness = ephemeral_input_witness_sha256(
                        self.attempt_id.as_str(),
                        self.thread_id.as_str(),
                        self.turn_id.as_str(),
                        self.request_binding_id.as_str(),
                        self.transport,
                        &logical_request_sha256,
                        &wire_semantic_sha256,
                        self.previous_response_id_sha256.as_ref(),
                        self.generate,
                        &binding,
                    )?;
                    (Some(binding.input_sha256().clone()), Some(witness))
                }
                (None, Some(binding)) => {
                    if logical_request_sha256 != self.base_logical_request_sha256 {
                        return Err(ModelProviderPolicyError::new(
                            \"model_provider_context_request_mutated\",
                            \"context final-use proof cannot authorize an unbound logical request mutation\",
                        ));
                    }
                    let witness = provider_context_witness_sha256(
                        self.attempt_id.as_str(),
                        self.thread_id.as_str(),
                        self.turn_id.as_str(),
                        self.request_binding_id.as_str(),
                        self.transport,
                        &logical_request_sha256,
                        &wire_semantic_sha256,
                        self.previous_response_id_sha256.as_ref(),
                        self.generate,
                        &binding,
                    )?;
                    (Some(binding.input_sha256().clone()), Some(witness))
                }
                (None, None) => (None, None),
                (Some(_), Some(_)) => unreachable!(\"conflict rejected above\"),
            };
"""
replace("codex-rs/core/src/model_provider_policy/binding.rs", old_header, new_header)

# Add the context-specific exact-attempt witness next to the existing memory witness.
anchor = """pub(crate) fn canonical_sha256<T: Serialize>(
"""
context_witness = """#[allow(clippy::too_many_arguments)]
fn provider_context_witness_sha256(
    attempt_id: &str,
    thread_id: &str,
    turn_id: &str,
    request_binding_id: &str,
    transport: ModelProviderTransport,
    logical_request_sha256: &ModelProviderSha256Digest,
    wire_semantic_sha256: &ModelProviderSha256Digest,
    previous_response_id_sha256: Option<&ModelProviderSha256Digest>,
    generate: bool,
    binding: &ModelProviderContextBinding,
) -> Result<ModelProviderSha256Digest, ModelProviderPolicyError> {
    let (previous_presence, previous_sha256) = match previous_response_id_sha256 {
        Some(digest) => (\"present\", digest.as_str()),
        None => (\"absent\", \"\"),
    };
    digest_parts_sha256([
        \"codex:provider-context-final-use-witness:v1\",
        attempt_id,
        thread_id,
        turn_id,
        request_binding_id,
        transport_name(transport),
        logical_request_sha256.as_str(),
        wire_semantic_sha256.as_str(),
        previous_presence,
        previous_sha256,
        if generate { \"generate\" } else { \"no_generate\" },
        binding.authority_sha256().as_str(),
        binding.input_sha256().as_str(),
    ])
}

pub(crate) fn canonical_sha256<T: Serialize>(
"""
replace("codex-rs/core/src/model_provider_policy/binding.rs", anchor, context_witness)

# Resolve context final-use immediately after optional memory input and before
# final logical/wire digests are frozen.
replace(
    "codex-rs/core/src/client.rs",
    "use crate::model_provider_policy::resolve_ephemeral_model_input;",
    "use crate::model_provider_policy::resolve_ephemeral_model_input;\n"
    "use crate::model_provider_policy::resolve_model_provider_context;",
)
replace(
    "codex-rs/core/src/client.rs",
    "                let request_for_policy = effective_request.as_ref().unwrap_or(&request);",
    "                let provider_context_binding = resolve_model_provider_context(context, &attempt)\n"
    "                    .await\n"
    "                    .map_err(model_provider_policy_error)?;\n"
    "                if ephemeral_binding.is_some() && provider_context_binding.is_some() {\n"
    "                    return Err(model_provider_policy_error(ModelProviderPolicyError::new(\n"
    "                        \"model_provider_bound_input_conflict\",\n"
    "                        \"memory ephemeral input and prompt context final-use proof cannot occupy one provider evidence slot\",\n"
    "                    )));\n"
    "                }\n"
    "                has_ephemeral_input =\n"
    "                    ephemeral_binding.is_some() || provider_context_binding.is_some();\n"
    "                let request_for_policy = effective_request.as_ref().unwrap_or(&request);",
)
replace(
    "codex-rs/core/src/client.rs",
    "                    .finalize(\n"
    "                        &effective_logical_request,\n"
    "                        &wire_semantic,\n"
    "                        ephemeral_binding,\n"
    "                    )",
    "                    .finalize_with_context(\n"
    "                        &effective_logical_request,\n"
    "                        &wire_semantic,\n"
    "                        ephemeral_binding,\n"
    "                        provider_context_binding,\n"
    "                    )",
)
replace(
    "codex-rs/core/src/client.rs",
    "                            \"ephemeral_model_input_policy_missing\",\n"
    "                            \"ephemeral model input requires an active provider policy lease\",",
    "                            \"model_provider_bound_input_policy_missing\",\n"
    "                            \"bound provider input requires an active provider policy lease\",",
)
