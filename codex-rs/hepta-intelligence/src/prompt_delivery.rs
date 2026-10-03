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
use codex_hepta_context_compiler::ContextAdmissionRecordV2;
use codex_hepta_context_compiler::ContextAdmissionSnapshotV2;
use codex_hepta_context_compiler::ContextAdmissionVerifierV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextDeliveryPreparationV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextRealizedItemV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::ContextSerializationReceiptV2;
use codex_hepta_context_compiler::MandatoryContextGroupV2;
use codex_hepta_context_compiler::SerializedContextV2;
use codex_hepta_context_compiler::VerifiedAdmissionSnapshotSuccessorV2;
use codex_hepta_context_compiler::VerifiedAdmissionSnapshotV2;
use codex_hepta_context_compiler::canonical_context_bundle_bytes_v2;
use codex_hepta_context_compiler::prepare_delivery_from_successor_v2;
use codex_hepta_context_compiler::verify_admission_snapshot_successor_typed_v2;
use codex_hepta_prompt_registry::CompatibleRealizationSetV2;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::RealizationDeliveryV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::prompt_pipeline::PromptContextCompileRequestV1;
use crate::prompt_pipeline::PromptDeliveryPrepareRequestV1;
use crate::prompt_pipeline::PromptPipelineErrorV1;
use crate::prompt_pipeline::compile_exercised_prompt_context_v1;
use crate::prompt_pipeline::prepare_prompt_delivery_v1;
use crate::prompt_pipeline::prompt_payload_bundle_digest;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;

const COMPILED_DELIVERY_DOMAIN: &[u8] = b"hepta.prompt-registry.compiled-context.v3";
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
    pub registry_model_tuple: PromptModelTupleV2,
    pub admission_snapshot: VerifiedAdmissionSnapshotV2,
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
            || self.registry_model_tuple.digest() != self.compatible.model_tuple_digest
            || self.registry_model_tuple.model_digest != self.model_profile.model_digest
            || self.registry_model_tuple.tokenizer_digest != self.model_profile.tokenizer_digest
            || self.registry_model_tuple.template_digest != self.model_profile.template_digest
            || self.registry_model_tuple.tool_schema_digest != self.model_profile.tool_schema_digest
            || self.admission_snapshot.snapshot_digest()
                != self.attachment.admission_snapshot_digest()
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
    let serialized_payload = serialize_selected_deliveries(&selected_deliveries)?;
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
        admission_snapshot: prepared.admission_snapshot.clone(),
        compiled: prepared.compiled,
        model_profile,
        registry_model_tuple: request.registry_model_tuple.clone(),
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

fn serialize_selected_deliveries(
    deliveries: &[RealizationDeliveryV2],
) -> Result<Vec<u8>, PromptRegistryCompilationErrorV2> {
    let realizations = deliveries
        .iter()
        .map(|delivery| ContextRealizedItemV2 {
            item_id: delivery.binding.realization_id.clone(),
            role: match delivery.binding.role {
                PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,
                PromptRoleV2::SystemInstruction
                | PromptRoleV2::DeveloperInstruction
                | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,
            },
            content: delivery.payload.clone(),
        })
        .collect::<Vec<_>>();
    canonical_context_bundle_bytes_v2(&realizations)
        .map_err(|_| PromptRegistryCompilationErrorV2::Integrity)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistryDeliveryPreparationV2 {
    pub registry_snapshot_digest: Digest32,
    pub final_use_materialization_digest: Digest32,
    pub successor: VerifiedAdmissionSnapshotSuccessorV2,
    pub preparation: ContextDeliveryPreparationV2,
    pub authority: AuthorityPosture,
}

impl PromptRegistryDeliveryPreparationV2 {
    pub fn validate_for(
        &self,
        compiled: &PromptRegistryCompiledContextV2,
    ) -> Result<(), PromptRegistryCompilationErrorV2> {
        if self.registry_snapshot_digest.is_zero()
            || self.final_use_materialization_digest.is_zero()
            || self.final_use_materialization_digest
                != prompt_payload_bundle_digest(&compiled.selected_deliveries)
            || self.successor.predecessor_snapshot_digest()
                != compiled.admission_snapshot.snapshot_digest()
            || self.preparation.admission_snapshot_digest()
                != self.successor.successor_snapshot_digest()
            || self.authority.grants_any()
        {
            return Err(PromptRegistryCompilationErrorV2::Integrity);
        }
        self.preparation
            .validate_for(
                &compiled.attachment,
                &compiled.serialized_context,
                &compiled.model_profile,
            )
            .map_err(PromptRegistryCompilationErrorV2::Context)
    }
}

#[derive(Clone, Debug)]
struct DeliverySnapshotVerifierV2 {
    verifier_digest: Digest32,
    scope_digest: Digest32,
    authority_domain_digest: Digest32,
}

impl ContextAdmissionVerifierV2 for DeliverySnapshotVerifierV2 {
    fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        record.scope_digest == self.scope_digest
            && record.authority_domain_digest == self.authority_domain_digest
            && !record.contains_secret
            && record.validate_shape().is_ok()
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        snapshot.scope_digest == self.scope_digest
            && snapshot.authority_domain_digest == self.authority_domain_digest
            && snapshot.revocation_set_complete
            && snapshot.validate_shape().is_ok()
    }
}

/// Re-read the exact durable registry immediately before a provider send. Every
/// selected realization must still dereference to the same binding and payload;
/// expiry, retirement, revocation, replacement, or byte drift fails closed.
pub fn prepare_prompt_registry_delivery_v2(
    registry: &DurablePromptRegistry,
    compiled: &PromptRegistryCompiledContextV2,
    now_unix_ms: u64,
    snapshot_id: StableId,
    preparation_id: StableId,
) -> Result<PromptRegistryDeliveryPreparationV2, PromptRegistryCompilationErrorV2> {
    compiled.validate()?;
    if now_unix_ms == 0 {
        return Err(PromptRegistryCompilationErrorV2::Integrity);
    }
    let generation_vector_digest = compiled.compiled.receipt().generation_vector_digest();
    let registry_snapshot = registry
        .snapshot_v2(generation_vector_digest, &compiled.registry_model_tuple)
        .map_err(PromptRegistryCompilationErrorV2::Registry)?;
    let mut fresh_deliveries = Vec::with_capacity(compiled.selected_deliveries.len());
    for expected in &compiled.selected_deliveries {
        let actual = registry
            .dereference_realization_v2(
                &expected.binding.realization_id,
                &registry_snapshot,
                generation_vector_digest,
                &compiled.registry_model_tuple,
                now_unix_ms,
            )
            .map_err(PromptRegistryCompilationErrorV2::Registry)?;
        if &actual != expected {
            return Err(PromptRegistryCompilationErrorV2::FinalUseDrift);
        }
        fresh_deliveries.push(actual);
    }
    let final_use_materialization_digest = prompt_payload_bundle_digest(&fresh_deliveries);
    if final_use_materialization_digest
        != prompt_payload_bundle_digest(&compiled.selected_deliveries)
    {
        return Err(PromptRegistryCompilationErrorV2::FinalUseDrift);
    }

    let verifier = DeliverySnapshotVerifierV2 {
        verifier_digest: compiled.admission_snapshot.verifier_digest(),
        scope_digest: compiled.admission_snapshot.scope_digest(),
        authority_domain_digest: compiled.admission_snapshot.authority_domain_digest(),
    };
    let observed_unix_ms = now_unix_ms.max(compiled.admission_snapshot.observed_unix_ms());
    let revocation_epoch = compiled
        .admission_snapshot
        .revocation_epoch()
        .checked_add(1)
        .ok_or(PromptRegistryCompilationErrorV2::Integrity)?;
    let raw_successor = ContextAdmissionSnapshotV2::new(
        snapshot_id,
        compiled.admission_snapshot.scope_digest(),
        compiled.admission_snapshot.authority_domain_digest(),
        observed_unix_ms,
        revocation_epoch,
        Vec::new(),
        true,
        Some(compiled.admission_snapshot.snapshot_digest()),
    )
    .map_err(PromptRegistryCompilationErrorV2::Context)?;
    let successor = verify_admission_snapshot_successor_typed_v2(
        raw_successor,
        &compiled.admission_snapshot,
        &verifier,
    )
    .map_err(|error| PromptRegistryCompilationErrorV2::Closure(error.to_string()))?;
    let preparation = prepare_delivery_from_successor_v2(
        &compiled.compiled,
        &compiled.serialized_context,
        &compiled.attachment,
        &compiled.model_profile,
        &successor,
        preparation_id,
    )
    .map_err(|error| PromptRegistryCompilationErrorV2::Closure(error.to_string()))?;
    let output = PromptRegistryDeliveryPreparationV2 {
        registry_snapshot_digest: registry_snapshot.snapshot_digest,
        final_use_materialization_digest,
        successor,
        preparation,
        authority: AuthorityPosture::DENY_ALL,
    };
    output.validate_for(compiled)?;
    Ok(output)
}

#[derive(Debug)]
pub enum PromptRegistryCompilationErrorV2 {
    Registry(DurableRegistryError),
    Pipeline(PromptPipelineErrorV1),
    Context(ContextCompilerV2Error),
    Closure(String),
    ProfileMismatch,
    FinalUseDrift,
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
