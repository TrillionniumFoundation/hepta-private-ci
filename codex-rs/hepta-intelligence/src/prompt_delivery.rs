//! Exercise-bound source consumer for authoritative prompt-registry realizations.
//!
//! The bridge accepts only a validated canonical optimizer exercise decision
//! authenticated against the same durable registry owner view. It dereferences
//! exactly the selected realization IDs, verifies their registry/admission
//! bindings, makes the selected portfolio mandatory in context compilation and
//! serializes the actual stored bytes. It grants no model/provider authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fmt;

use codex_hepta_context_compiler::CompiledContextV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCandidateV2;
use codex_hepta_context_compiler::ContextCompilationRequestV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::ContextSerializationReceiptV2;
use codex_hepta_context_compiler::MandatoryContextGroupV2;
use codex_hepta_context_compiler::TokenizationReceiptV2;
use codex_hepta_context_compiler::build_attachment;
use codex_hepta_context_compiler::compile_v2;
use codex_hepta_context_compiler::record_serialization;
use codex_hepta_prompt_optimizer::PromptCandidateRoleV1;
use codex_hepta_prompt_optimizer::PromptCandidateSetReceiptV1;
use codex_hepta_prompt_optimizer::PromptCandidateSourceAuthenticatorV1;
use codex_hepta_prompt_optimizer::PromptExerciseDecisionV1;
use codex_hepta_prompt_optimizer::PromptExerciseDispositionV1;
use codex_hepta_prompt_optimizer::PromptExerciseErrorV1;
use codex_hepta_prompt_optimizer::PromptExerciseInvalidationV1;
use codex_hepta_prompt_optimizer::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::PromptPortfolioReceiptV1;
use codex_hepta_prompt_optimizer::PromptPricingReceiptV1;
use codex_hepta_prompt_optimizer::PromptRelationSourceV1;
use codex_hepta_prompt_registry::CompatibleRealizationSetV2;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::RealizationDeliveryV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::PromptRegistryCandidateAdapterV1;

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
        if self.authority.grants_any()
            || self.delivery_set_digest.is_zero()
            || self.exercise_receipt_digest.is_zero()
            || self.portfolio_receipt_digest.is_zero()
            || self.compiled.receipt.prompt_portfolio_digest != self.portfolio_receipt_digest
        {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        let selected = &self.compiled.receipt.selected_item_ids;
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
        bytes.extend_from_slice(self.exercise_receipt_digest.as_array());
        bytes.extend_from_slice(self.portfolio_receipt_digest.as_array());
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

#[allow(clippy::too_many_arguments)]
pub fn compile_prompt_registry_v2(
    registry: &DurablePromptRegistry,
    adapter: &PromptRegistryCandidateAdapterV1,
    candidate_set: &PromptCandidateSetReceiptV1,
    pricing: &PromptPricingReceiptV1,
    relations: &PromptRelationSourceV1,
    portfolio: &PromptPortfolioReceiptV1,
    exercise: &PromptExerciseDecisionV1,
    exercise_request: &PromptExerciseRequestV1,
    request: PromptRegistryCompilationRequestV2,
) -> Result<PromptRegistryCompiledContextV2, PromptRegistryCompilationErrorV2> {
    exercise
        .validate_for(
            candidate_set,
            pricing,
            relations,
            portfolio,
            exercise_request,
        )
        .map_err(PromptRegistryCompilationErrorV2::Optimizer)?;
    adapter
        .authenticate_candidate_source(
            &exercise_request.current_source,
            portfolio.objective_digest,
            exercise_request.now_unix_ms,
        )
        .map_err(|_| PromptRegistryCompilationErrorV2::SourceAuthenticationRejected)?;
    match exercise.disposition {
        PromptExerciseDispositionV1::ExercisePortfolio => {}
        PromptExerciseDispositionV1::NoIntervention => {
            return Err(PromptRegistryCompilationErrorV2::NoIntervention);
        }
        PromptExerciseDispositionV1::Invalidated(reason) => {
            return Err(PromptRegistryCompilationErrorV2::Invalidated(reason));
        }
    }
    if &exercise_request.current_source != adapter.source()
        || exercise.current_registry_snapshot_digest != adapter.snapshot().snapshot_digest
        || exercise.current_registry_revision != adapter.snapshot().revision.get()
        || exercise.current_revocation_frontier != adapter.snapshot().revocation_frontier
        || exercise.current_generation_vector_digest != adapter.snapshot().generation_vector_digest
        || request.now_unix_ms != exercise_request.now_unix_ms
    {
        return Err(PromptRegistryCompilationErrorV2::Integrity);
    }
    validate_profiles(&request, adapter)?;

    let current_bindings = adapter
        .source()
        .bindings
        .iter()
        .map(|binding| (binding.candidate_id.clone(), binding))
        .collect::<BTreeMap<_, _>>();
    let prices = pricing
        .prices
        .iter()
        .map(|price| (price.candidate_id.clone(), price))
        .collect::<BTreeMap<_, _>>();

    let mut deliveries = BTreeMap::new();
    let mut candidates = Vec::with_capacity(portfolio.selected_candidate_ids.len());
    for candidate_id in &portfolio.selected_candidate_ids {
        let candidate = current_bindings.get(candidate_id).ok_or_else(|| {
            PromptRegistryCompilationErrorV2::MissingSelectedBinding(candidate_id.to_string())
        })?;
        let price = prices.get(candidate_id).ok_or_else(|| {
            PromptRegistryCompilationErrorV2::MissingSelectedPrice(candidate_id.to_string())
        })?;
        let delivery = registry
            .dereference_realization_v2(
                &candidate.realization_id,
                adapter.snapshot(),
                adapter.source().generation_vector_digest,
                &request.registry_model_tuple,
                request.now_unix_ms,
            )
            .map_err(PromptRegistryCompilationErrorV2::Registry)?;
        let admission_digest = registry
            .registry()
            .admission_event_digest(&candidate.factor_id)
            .ok_or_else(|| {
                PromptRegistryCompilationErrorV2::MissingAdmissionLineage(
                    candidate.factor_id.to_string(),
                )
            })?;
        if candidate.candidate_id != candidate.realization_id
            || candidate.realization_id != delivery.binding.realization_id
            || candidate.factor_id != delivery.binding.factor_id
            || candidate.registry_binding_digest != delivery.binding.digest()
            || candidate.admission_digest != admission_digest
            || candidate.payload_digest != delivery.binding.payload_digest
            || candidate.token_cost != u64::from(delivery.binding.token_cost)
            || candidate.expires_unix_ms != delivery.binding.expires_unix_ms
            || candidate.role != optimizer_role(delivery.binding.role)
        {
            return Err(PromptRegistryCompilationErrorV2::SelectionBindingMismatch(
                candidate_id.to_string(),
            ));
        }

        let tokenization = TokenizationReceiptV2::new(
            candidate_id.clone(),
            candidate.payload_digest,
            delivery.binding.tokenizer_digest,
            candidate.token_cost,
        )
        .map_err(PromptRegistryCompilationErrorV2::Context)?;
        candidates.push(ContextCandidateV2 {
            item_id: candidate_id.clone(),
            role: context_role(delivery.binding.role),
            content_digest: candidate.payload_digest,
            source_digest: delivery.delivery_digest,
            generation_vector_digest: exercise.current_generation_vector_digest,
            tokenization,
            expected_value: price.confidence,
            trusted_admission_digest: Some(admission_digest),
            contains_secret: false,
        });
        deliveries.insert(candidate_id.clone(), delivery);
    }

    let selected_set = portfolio
        .selected_candidate_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: request.compilation_id,
        objective_digest: portfolio.objective_digest,
        prompt_portfolio_digest: portfolio.receipt_digest,
        generation_vector_digest: exercise.current_generation_vector_digest,
        model_profile: request.context_model_profile,
        token_budget: request.token_budget,
        truncation_policy_digest: request.truncation_policy_digest,
        candidates,
        mandatory_groups: vec![MandatoryContextGroupV2 {
            group_id: StableId::new(SELECTED_PROMPT_GROUP_ID)
                .map_err(|_| PromptRegistryCompilationErrorV2::Integrity)?,
            item_ids: portfolio.selected_candidate_ids.clone(),
            reason_digest: exercise.receipt_digest,
        }],
    })
    .map_err(PromptRegistryCompilationErrorV2::Context)?;
    if compiled
        .receipt
        .selected_item_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        != selected_set
        || !compiled.receipt.omitted_item_ids.is_empty()
    {
        return Err(PromptRegistryCompilationErrorV2::Integrity);
    }

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
        request.serialization_id,
        Digest32::of_bytes(&serialized_payload),
    )
    .map_err(PromptRegistryCompilationErrorV2::Context)?;
    let attachment = build_attachment(&compiled, &serialization, request.attachment_id)
        .map_err(PromptRegistryCompilationErrorV2::Context)?;

    let mut output = PromptRegistryCompiledContextV2 {
        compatible: adapter.compatible().clone(),
        exercise_receipt_digest: exercise.receipt_digest,
        portfolio_receipt_digest: portfolio.receipt_digest,
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

fn validate_profiles(
    request: &PromptRegistryCompilationRequestV2,
    adapter: &PromptRegistryCandidateAdapterV1,
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
    let source = &adapter.source().model_profile;
    if request.registry_model_tuple.model_id != source.model_id
        || request.registry_model_tuple.model_version != source.model_version
        || request.registry_model_tuple.model_digest != source.model_digest
        || request.registry_model_tuple.tokenizer_digest != source.tokenizer_digest
        || request.registry_model_tuple.template_digest != source.template_digest
        || request.registry_model_tuple.tool_schema_digest != source.tool_schema_digest
        || request.registry_model_tuple.context_profile_digest != source.context_profile_digest
        || request.registry_model_tuple.locale_id != source.locale_id
        || request.context_model_profile.model_digest != source.model_digest
        || request.context_model_profile.tokenizer_digest != source.tokenizer_digest
        || request.context_model_profile.template_digest != source.template_digest
        || request.context_model_profile.tool_schema_digest != source.tool_schema_digest
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

const fn optimizer_role(role: PromptRoleV2) -> PromptCandidateRoleV1 {
    match role {
        PromptRoleV2::SystemInstruction => PromptCandidateRoleV1::SystemInstruction,
        PromptRoleV2::DeveloperInstruction => PromptCandidateRoleV1::DeveloperInstruction,
        PromptRoleV2::UserTemplate => PromptCandidateRoleV1::UserTemplate,
        PromptRoleV2::ToolSchemaFragment => PromptCandidateRoleV1::ToolSchemaFragment,
    }
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
    Optimizer(PromptExerciseErrorV1),
    Context(ContextCompilerV2Error),
    NoIntervention,
    Invalidated(PromptExerciseInvalidationV1),
    SourceAuthenticationRejected,
    MissingSelectedBinding(String),
    MissingSelectedPrice(String),
    MissingAdmissionLineage(String),
    SelectionBindingMismatch(String),
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
