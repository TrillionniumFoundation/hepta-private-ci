//! Exercise-bound source consumer for authoritative prompt-registry realizations.
//!
//! The bridge accepts only a validated canonical optimizer exercise decision
//! authenticated against the same durable registry owner view. It dereferences
//! exactly the selected realization IDs, verifies their registry/admission
//! bindings, makes the selected portfolio mandatory in context compilation and
//! serializes the actual stored bytes. It grants no model/provider authority.

use std::collections::BTreeMap;
use std::fmt;

use codex_hepta_context_compiler::CompiledContextV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextSerializationReceiptV2;
use codex_hepta_context_compiler::MandatoryContextGroupV2;
use codex_hepta_context_compiler::SerializedContextV2;
use codex_hepta_prompt_registry::CompatibleRealizationSetV2;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::RealizationDeliveryV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::PromptContextCompileRequestV1;
use crate::PromptDeliveryPrepareRequestV1;
use crate::PromptPipelineErrorV1;
use crate::compile_exercised_prompt_context_v1;
use crate::prepare_prompt_delivery_v1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;

const COMPILED_DELIVERY_DOMAIN: &[u8] = b"hepta.prompt-registry.compiled-context.v3";
const SERIALIZED_PAYLOAD_DOMAIN: &[u8] = b"hepta.prompt-registry.serialized-context.v3";
const SELECTED_PROMPT_GROUP_ID: &str = "prompt:exercise-selected";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistryCompilationRequestV2 {
    pub compilation_id: StableId,
    pub serialization_id: StableId,
    pub attachment_id: StableId,
    pub registry_model_tuple: PromptModelTupleV2,
    pub context_model_profile: ContextModelProfileV2,
    pub now_unix_ms: u64,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistryCompiledContextV2 {
    pub compatible: CompatibleRealizationSetV2,
    pub exercise_receipt_digest: Digest32,
    pub portfolio_receipt_digest: Digest32,
    pub compiled: CompiledContextV2,
    pub model_profile: ContextModelProfileV2,
    pub selected_deliveries: Vec<RealizationDeliveryV2>,
    pub serialized_payload: Vec<u8>,
    pub serialization: ContextSerializationReceiptV2,
    pub serialized_context: SerializedContextV2,
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
        if self.authority.grants_any()
            || self.delivery_set_digest.is_zero()
            || self.exercise_receipt_digest.is_zero()
            || self.portfolio_receipt_digest.is_zero()
            || self.compiled.receipt().prompt_portfolio_digest() != self.portfolio_receipt_digest
        {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        let selected = self.compiled.receipt().selected_item_ids();
        if selected.len() != self.selected_deliveries.len()
            || selected
                .iter()
                .zip(&self.selected_deliveries)
                .any(|(item_id, delivery)| item_id != &delivery.binding.realization_id)
        {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        for delivery in &self.selected_deliveries {
            delivery
                .validate()
                .map_err(DurableRegistryError::Read)
                .map_err(PromptRegistryCompilationErrorV2::Registry)?;
        }
        if self.serialized_payload.is_empty()
            || Digest32::of_bytes(&self.serialized_payload) != self.serialization.payload_digest()
        {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        self.serialized_context
            .validate_for(&self.compiled, &self.model_profile)
            .map_err(PromptRegistryCompilationErrorV2::Context)?;
        if self.serialized_context.receipt() != &self.serialization {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        self.attachment
            .validate_for(
                &self.compiled,
                &self.serialized_context,
                &self.model_profile,
            )
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
        bytes.extend_from_slice(self.exercise_receipt_digest.as_array());
        bytes.extend_from_slice(self.portfolio_receipt_digest.as_array());
        bytes.extend_from_slice(self.compiled.receipt().receipt_digest().as_array());
        bytes.extend_from_slice(self.serialization.receipt_digest().as_array());
        bytes.extend_from_slice(self.attachment.attachment_digest().as_array());
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

/// Compile and serialize the unified optimizer portfolio against the current
/// durable owner, then return the exact source bundle consumed by Agentd.
pub fn compile_prompt_registry_v2(
    registry: &DurablePromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    exercise_request: &PromptExerciseRequestV1,
    request: PromptRegistryCompilationRequestV2,
) -> Result<PromptRegistryCompiledContextV2, PromptRegistryCompilationErrorV2> {
    if request.registry_model_tuple != portfolio.model_tuple
        || request.now_unix_ms != exercise_request.now_unix_ms
    {
        return Err(PromptRegistryCompilationErrorV2::ProfileMismatch);
    }
    let model_profile = request.context_model_profile.clone();
    let prepared = compile_exercised_prompt_context_v1(
        registry,
        portfolio,
        PromptContextCompileRequestV1 {
            exercise: exercise_request.clone(),
            compilation_id: request.compilation_id,
            model_profile: request.context_model_profile,
            token_budget: request.token_budget,
            truncation_policy_digest: request.truncation_policy_digest,
            base_candidates: Vec::new(),
            mandatory_groups: vec![MandatoryContextGroupV2 {
                group_id: StableId::new(SELECTED_PROMPT_GROUP_ID)
                    .map_err(|_| PromptRegistryCompilationErrorV2::Integrity)?,
                item_ids: portfolio
                    .selected
                    .iter()
                    .map(|selected| selected.realization.realization_id.clone())
                    .collect(),
                reason_digest: portfolio.receipt.receipt_digest,
            }],
        },
    )
    .map_err(PromptRegistryCompilationErrorV2::Pipeline)?;
    let by_id = prepared
        .materialization
        .payloads
        .iter()
        .map(|delivery| (delivery.binding.realization_id.clone(), delivery.clone()))
        .collect::<BTreeMap<_, _>>();
    let selected_deliveries = prepared
        .compiled
        .receipt()
        .selected_item_ids()
        .iter()
        .map(|id| {
            by_id
                .get(id)
                .cloned()
                .ok_or(PromptRegistryCompilationErrorV2::Integrity)
        })
        .collect::<Result<Vec<_>, _>>()?;
    let serialized_payload = serialize_selected_deliveries(&selected_deliveries);
    let delivery = prepare_prompt_delivery_v1(
        registry,
        portfolio,
        &prepared,
        PromptDeliveryPrepareRequestV1 {
            exercise: exercise_request.clone(),
            serialization_id: request.serialization_id,
            serialized_payload: serialized_payload.clone(),
            attachment_id: request.attachment_id,
        },
    )
    .map_err(PromptRegistryCompilationErrorV2::Pipeline)?;
    let snapshot = registry
        .snapshot_v2(portfolio.generation_vector_digest, &portfolio.model_tuple)
        .map_err(PromptRegistryCompilationErrorV2::Registry)?;
    let compatible = registry
        .read_compatible_v2(
            &snapshot,
            portfolio.generation_vector_digest,
            &portfolio.model_tuple,
            request.now_unix_ms,
            portfolio.receipt.factor_ids.clone(),
            u32::try_from(portfolio.selected.len())
                .map_err(|_| PromptRegistryCompilationErrorV2::Integrity)?,
        )
        .map_err(PromptRegistryCompilationErrorV2::Registry)?;
    let mut output = PromptRegistryCompiledContextV2 {
        compatible,
        exercise_receipt_digest: delivery.exercise.receipt_digest,
        portfolio_receipt_digest: portfolio.receipt.receipt_digest,
        compiled: prepared.compiled,
        model_profile,
        selected_deliveries,
        serialized_payload,
        serialization: delivery.serialization,
        serialized_context: delivery.serialized_context,
        attachment: delivery.attachment,
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

#[derive(Debug)]
pub enum PromptRegistryCompilationErrorV2 {
    Registry(DurableRegistryError),
    Pipeline(PromptPipelineErrorV1),
    Context(ContextCompilerV2Error),
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
pub(crate) mod tests;
