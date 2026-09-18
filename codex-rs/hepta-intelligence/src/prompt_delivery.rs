//! Source-level consumer for authoritative prompt-registry realizations.
//!
//! This bridge proves that the bytes bound by prompt.registry are the bytes
//! handed to context.compiler. It grants no model or provider authority.

use std::collections::BTreeMap;
use std::fmt;

use codex_hepta_context_compiler::CompiledContextV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCandidateV2;
use codex_hepta_context_compiler::ContextCompilationRequestV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::ContextSerializationReceiptV2;
use codex_hepta_context_compiler::TokenizationReceiptV2;
use codex_hepta_context_compiler::build_attachment;
use codex_hepta_context_compiler::compile_v2;
use codex_hepta_context_compiler::record_serialization;
use codex_hepta_prompt_registry::CompatibleRealizationSetV2;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRegistrySnapshotV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::RealizationDeliveryV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

const COMPILED_DELIVERY_DOMAIN: &[u8] = b"hepta.prompt-registry.compiled-context.v2";
const SERIALIZED_PAYLOAD_DOMAIN: &[u8] = b"hepta.prompt-registry.serialized-context.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistryCompilationRequestV2 {
    pub compilation_id: StableId,
    pub serialization_id: StableId,
    pub attachment_id: StableId,
    pub objective_digest: Digest32,
    pub prompt_portfolio_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub expected_registry_snapshot: PromptRegistrySnapshotV2,
    pub registry_model_tuple: PromptModelTupleV2,
    pub context_model_profile: ContextModelProfileV2,
    pub now_unix_ms: u64,
    pub required_factor_ids: Vec<StableId>,
    pub maximum_realizations: u32,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistryCompiledContextV2 {
    pub compatible: CompatibleRealizationSetV2,
    pub compiled: CompiledContextV2,
    pub selected_deliveries: Vec<RealizationDeliveryV2>,
    pub serialized_payload: Vec<u8>,
    pub serialization: ContextSerializationReceiptV2,
    pub attachment: ContextAttachmentV2,
    pub delivery_set_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptRegistryCompiledContextV2 {
    pub fn validate(&self) -> Result<(), PromptRegistryCompilationErrorV2> {
        self.compatible
            .validate()
            .map_err(DurableRegistryError::Read)
            .map_err(PromptRegistryCompilationErrorV2::Registry)?;
        self.compiled
            .validate()
            .map_err(PromptRegistryCompilationErrorV2::Context)?;
        if self.authority.grants_any() || self.delivery_set_digest.is_zero() {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        let selected = self
            .compiled
            .receipt
            .selected_item_ids
            .iter()
            .cloned()
            .collect::<Vec<_>>();
        let delivered = self
            .selected_deliveries
            .iter()
            .map(|delivery| delivery.binding.realization_id.clone())
            .collect::<Vec<_>>();
        if selected != delivered {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        for delivery in &self.selected_deliveries {
            delivery
                .validate()
                .map_err(DurableRegistryError::Read)
                .map_err(PromptRegistryCompilationErrorV2::Registry)?;
        }
        if self.serialized_payload.is_empty()
            || Digest32::of_bytes(&self.serialized_payload) != self.serialization.payload_digest
        {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        self.serialization
            .validate_for(&self.compiled)
            .map_err(PromptRegistryCompilationErrorV2::Context)?;
        self.attachment
            .validate(&self.compiled, &self.serialization)
            .map_err(PromptRegistryCompilationErrorV2::Context)?;
        if self.delivery_set_digest != self.compute_delivery_set_digest() {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_delivery_set_digest(&self) -> Digest32 {
        let mut bytes = COMPILED_DELIVERY_DOMAIN.to_vec();
        bytes.extend_from_slice(self.compatible.set_digest.as_array());
        bytes.extend_from_slice(self.compiled.receipt.receipt_digest.as_array());
        bytes.extend_from_slice(self.serialization.receipt_digest.as_array());
        bytes.extend_from_slice(self.attachment.attachment_digest.as_array());
        bytes.extend_from_slice(
            &u64::try_from(self.selected_deliveries.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for delivery in &self.selected_deliveries {
            bytes.extend_from_slice(delivery.delivery_digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

pub fn compile_prompt_registry_v2(
    registry: &DurablePromptRegistry,
    request: PromptRegistryCompilationRequestV2,
) -> Result<PromptRegistryCompiledContextV2, PromptRegistryCompilationErrorV2> {
    validate_profiles(&request)?;
    let serialization_id = request.serialization_id.clone();
    let attachment_id = request.attachment_id.clone();
    let compatible = registry
        .read_compatible_v2(
            &request.expected_registry_snapshot,
            request.generation_vector_digest,
            &request.registry_model_tuple,
            request.now_unix_ms,
            request.required_factor_ids,
            request.maximum_realizations,
        )
        .map_err(PromptRegistryCompilationErrorV2::Registry)?;

    let mut deliveries = BTreeMap::new();
    let mut candidates = Vec::with_capacity(compatible.bindings.len());
    for binding in &compatible.bindings {
        let delivery = registry
            .dereference_realization_v2(
                &binding.realization_id,
                &request.expected_registry_snapshot,
                request.generation_vector_digest,
                &request.registry_model_tuple,
                request.now_unix_ms,
            )
            .map_err(PromptRegistryCompilationErrorV2::Registry)?;
        let admission_digest = registry
            .registry()
            .admission_event_digest(&binding.factor_id)
            .ok_or_else(|| {
                PromptRegistryCompilationErrorV2::MissingAdmissionLineage(
                    binding.factor_id.to_string(),
                )
            })?;
        let tokenization = TokenizationReceiptV2::new(
            binding.realization_id.clone(),
            binding.payload_digest,
            binding.tokenizer_digest,
            u64::from(binding.token_cost),
        )
        .map_err(PromptRegistryCompilationErrorV2::Context)?;
        let candidate = ContextCandidateV2 {
            item_id: binding.realization_id.clone(),
            role: context_role(binding.role),
            content_digest: binding.payload_digest,
            source_digest: delivery.delivery_digest,
            generation_vector_digest: request.generation_vector_digest,
            tokenization,
            expected_value: FixedQ32::ONE,
            trusted_admission_digest: Some(admission_digest),
            contains_secret: false,
        };
        deliveries.insert(binding.realization_id.clone(), delivery);
        candidates.push(candidate);
    }

    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: request.compilation_id,
        objective_digest: request.objective_digest,
        prompt_portfolio_digest: request.prompt_portfolio_digest,
        generation_vector_digest: request.generation_vector_digest,
        model_profile: request.context_model_profile,
        token_budget: request.token_budget,
        truncation_policy_digest: request.truncation_policy_digest,
        candidates,
        mandatory_groups: Vec::new(),
    })
    .map_err(PromptRegistryCompilationErrorV2::Context)?;

    let mut selected_deliveries = Vec::with_capacity(compiled.receipt.selected_item_ids.len());
    for realization_id in &compiled.receipt.selected_item_ids {
        let Some(delivery) = deliveries.remove(realization_id) else {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        };
        selected_deliveries.push(delivery);
    }

    let serialized_payload = serialize_selected_deliveries(&selected_deliveries);
    let serialization = record_serialization(
        &compiled,
        serialization_id,
        Digest32::of_bytes(&serialized_payload),
    )
    .map_err(PromptRegistryCompilationErrorV2::Context)?;
    let attachment = build_attachment(&compiled, &serialization, attachment_id)
        .map_err(PromptRegistryCompilationErrorV2::Context)?;

    let mut output = PromptRegistryCompiledContextV2 {
        compatible,
        compiled,
        selected_deliveries,
        serialized_payload,
        serialization,
        attachment,
        delivery_set_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    output.delivery_set_digest = output.compute_delivery_set_digest();
    output.validate()?;
    Ok(output)
}

fn serialize_selected_deliveries(deliveries: &[RealizationDeliveryV2]) -> Vec<u8> {
    let mut bytes = SERIALIZED_PAYLOAD_DOMAIN.to_vec();
    bytes.extend_from_slice(
        &u64::try_from(deliveries.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for delivery in deliveries {
        let realization_id = delivery.binding.realization_id.as_str().as_bytes();
        bytes.extend_from_slice(
            &u64::try_from(realization_id.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(realization_id);
        bytes.push(prompt_role_code(delivery.binding.role));
        bytes.extend_from_slice(delivery.binding.digest().as_array());
        bytes.extend_from_slice(
            &u64::try_from(delivery.payload.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(&delivery.payload);
    }
    bytes
}

const fn prompt_role_code(role: PromptRoleV2) -> u8 {
    match role {
        PromptRoleV2::SystemInstruction => 0,
        PromptRoleV2::DeveloperInstruction => 1,
        PromptRoleV2::UserTemplate => 2,
        PromptRoleV2::ToolSchemaFragment => 3,
    }
}

fn validate_profiles(
    request: &PromptRegistryCompilationRequestV2,
) -> Result<(), PromptRegistryCompilationErrorV2> {
    request
        .registry_model_tuple
        .validate()
        .map_err(DurableRegistryError::Read)
        .map_err(PromptRegistryCompilationErrorV2::Registry)?;
    request
        .context_model_profile
        .validate()
        .map_err(PromptRegistryCompilationErrorV2::Context)?;
    if request.registry_model_tuple.model_digest != request.context_model_profile.model_digest
        || request.registry_model_tuple.tokenizer_digest
            != request.context_model_profile.tokenizer_digest
        || request.registry_model_tuple.template_digest
            != request.context_model_profile.template_digest
        || request.registry_model_tuple.tool_schema_digest
            != request.context_model_profile.tool_schema_digest
    {
        return Err(PromptRegistryCompilationErrorV2::ProfileMismatch);
    }
    Ok(())
}

const fn context_role(role: PromptRoleV2) -> ContextRoleV2 {
    match role {
        PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,
        PromptRoleV2::SystemInstruction
        | PromptRoleV2::DeveloperInstruction
        | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,
    }
}

#[derive(Debug)]
pub enum PromptRegistryCompilationErrorV2 {
    Registry(DurableRegistryError),
    Context(ContextCompilerV2Error),
    MissingAdmissionLineage(String),
    ProfileMismatch,
    Integrity,
}

impl fmt::Display for PromptRegistryCompilationErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PromptRegistryCompilationErrorV2 {}

#[cfg(test)]
#[path = "prompt_delivery_tests.rs"]
mod tests;
