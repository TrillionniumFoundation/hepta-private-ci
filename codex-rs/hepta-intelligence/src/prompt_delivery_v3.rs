//! Product prompt compilation using independently authenticated admission,
//! concrete profile revisions, canonical serialization and an exact tokenizer.
//!
//! This is the only prompt-registry compilation entrypoint suitable for a
//! provider-bound product path.  The V2 compatibility entrypoint remains for
//! source consumers but uses caller-local adapters and cannot be promoted into
//! product execution evidence.

use std::collections::BTreeMap;
use std::fmt;

use codex_hepta_context_compiler::CompiledContextV2;
use codex_hepta_context_compiler::ContextAdmissionRecordV2;
use codex_hepta_context_compiler::ContextAdmissionSnapshotV2;
use codex_hepta_context_compiler::ContextAdmissionVerifierV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCandidateV2;
use codex_hepta_context_compiler::ContextCompilationRequestV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextModelProfileRevisionV2;
use codex_hepta_context_compiler::ContextRealizedItemV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::ContextSerializationOutputV2;
use codex_hepta_context_compiler::ContextSerializationSegmentKindV2;
use codex_hepta_context_compiler::ContextSerializationSegmentV2;
use codex_hepta_context_compiler::ContextSerializerV2;
use codex_hepta_context_compiler::ExactTokenizerV2;
use codex_hepta_context_compiler::MandatoryContextGroupV2;
use codex_hepta_context_compiler::SerializedContextV2;
use codex_hepta_context_compiler::TokenizationReceiptV2;
use codex_hepta_context_compiler::VerifiedAdmissionSnapshotLineageV2;
use codex_hepta_context_compiler::build_attachment_with_lineage_v2;
use codex_hepta_context_compiler::compile_v2;
use codex_hepta_context_compiler::record_serialization;
use codex_hepta_context_compiler::verify_admission_v2;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseActionV1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_optimizer::canonical::exercise_v1;
use codex_hepta_prompt_registry::CompatibleRealizationSetV2;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::RealizationDeliveryV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

const COMPILED_DELIVERY_DOMAIN_V3: &[u8] = b"hepta.prompt-registry.compiled-context.v4";
const SERIALIZED_PAYLOAD_DOMAIN_V3: &[u8] = b"hepta.prompt-registry.provider-context.v4";
const CANONICAL_SERIALIZER_REVISION_DOMAIN_V3: &[u8] =
    b"hepta.prompt-registry.canonical-serializer-revision.v3";
const CANONICAL_ROLE_PROFILE_DOMAIN_V3: &[u8] =
    b"hepta.prompt-registry.canonical-role-profile.v3";
const SELECTED_PROMPT_GROUP_ID_V3: &str = "prompt:exercise-selected:v3";

/// Trusted host adapters for one concrete product profile.
///
/// No default or caller-local implementation is supplied.  The admission
/// verifier must authenticate records and snapshots issued by an independent
/// authority.  `count_tokens` must invoke the exact tokenizer identified by
/// `product_profile_digest`; lookup tables and heuristic counts are not valid
/// implementations.
pub trait PromptCompilerProductAdaptersV3:
    ContextAdmissionVerifierV2 + ExactTokenizerV2 + Send + Sync
{
    fn product_profile_digest(&self) -> Digest32;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistryCompilationRequestV3 {
    pub compilation_id: StableId,
    pub serialization_id: StableId,
    pub attachment_id: StableId,
    pub registry_model_tuple: PromptModelTupleV2,
    pub product_profile: ContextModelProfileRevisionV2,
    pub now_unix_ms: u64,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
    pub admission_snapshot: ContextAdmissionSnapshotV2,
    pub predecessor_lineage: Option<VerifiedAdmissionSnapshotLineageV2>,
    pub admission_records: Vec<ContextAdmissionRecordV2>,
}

#[derive(Clone, Eq, PartialEq)]
pub struct PromptRegistryCompiledContextV3 {
    pub compatible: CompatibleRealizationSetV2,
    pub exercise_receipt_digest: Digest32,
    pub portfolio_receipt_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub product_profile: ContextModelProfileRevisionV2,
    pub compiled: CompiledContextV2,
    pub selected_deliveries: Vec<RealizationDeliveryV2>,
    pub serialized_context: SerializedContextV2,
    pub attachment: ContextAttachmentV2,
    pub admission_lineage: VerifiedAdmissionSnapshotLineageV2,
    pub delivery_set_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl fmt::Debug for PromptRegistryCompiledContextV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptRegistryCompiledContextV3")
            .field("compatible", &self.compatible)
            .field("exercise_receipt_digest", &self.exercise_receipt_digest)
            .field("portfolio_receipt_digest", &self.portfolio_receipt_digest)
            .field("model_tuple", &self.model_tuple)
            .field("product_profile_digest", &self.product_profile.digest())
            .field("compiled", &self.compiled)
            .field("selected_delivery_count", &self.selected_deliveries.len())
            .field(
                "selected_delivery_digests",
                &self
                    .selected_deliveries
                    .iter()
                    .map(|delivery| delivery.delivery_digest)
                    .collect::<Vec<_>>(),
            )
            .field("serialized_context", &self.serialized_context)
            .field("attachment", &self.attachment)
            .field("admission_lineage", &self.admission_lineage)
            .field("delivery_set_digest", &self.delivery_set_digest)
            .field("authority", &self.authority)
            .finish()
    }
}

impl PromptRegistryCompiledContextV3 {
    pub fn validate(&self) -> Result<(), PromptRegistryCompilationErrorV3> {
        self.compatible
            .validate()
            .map_err(DurableRegistryError::Read)
            .map_err(PromptRegistryCompilationErrorV3::Registry)?;
        self.model_tuple
            .validate()
            .map_err(|_| PromptRegistryCompilationErrorV3::Integrity)?;
        self.product_profile
            .validate()
            .map_err(PromptRegistryCompilationErrorV3::Context)?;
        self.compiled
            .validate()
            .map_err(PromptRegistryCompilationErrorV3::Context)?;
        if self.authority.grants_any()
            || self.delivery_set_digest.is_zero()
            || self.exercise_receipt_digest.is_zero()
            || self.portfolio_receipt_digest.is_zero()
            || self.product_profile.digest() != self.model_tuple.context_profile_digest
            || self.compiled.receipt().prompt_portfolio_digest()
                != self.portfolio_receipt_digest
        {
            return Err(PromptRegistryCompilationErrorV3::Integrity);
        }
        let selected = self.compiled.receipt().selected_item_ids();
        if selected.len() != self.selected_deliveries.len()
            || selected
                .iter()
                .zip(&self.selected_deliveries)
                .any(|(item_id, delivery)| item_id != &delivery.binding.realization_id)
        {
            return Err(PromptRegistryCompilationErrorV3::Integrity);
        }
        for delivery in &self.selected_deliveries {
            delivery
                .validate()
                .map_err(DurableRegistryError::Read)
                .map_err(PromptRegistryCompilationErrorV3::Registry)?;
        }
        self.serialized_context
            .validate_for(&self.compiled, &self.product_profile.base_profile)
            .map_err(PromptRegistryCompilationErrorV3::Context)?;
        self.attachment
            .validate_for(
                &self.compiled,
                &self.serialized_context,
                &self.product_profile.base_profile,
            )
            .map_err(PromptRegistryCompilationErrorV3::Context)?;
        if self.attachment.admission_snapshot_digest()
            != self.admission_lineage.current().snapshot_digest()
            || self.delivery_set_digest != self.compute_delivery_set_digest()
        {
            return Err(PromptRegistryCompilationErrorV3::Integrity);
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_delivery_set_digest(&self) -> Digest32 {
        let mut bytes = COMPILED_DELIVERY_DOMAIN_V3.to_vec();
        for digest in [
            self.compatible.set_digest,
            self.exercise_receipt_digest,
            self.portfolio_receipt_digest,
            self.model_tuple.digest(),
            self.product_profile.digest(),
            self.compiled.receipt().receipt_digest(),
            self.serialized_context.receipt().receipt_digest(),
            self.attachment.attachment_digest(),
            self.admission_lineage.lineage_digest(),
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
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

/// Compile one exact optimizer portfolio through the independently authenticated
/// V2 context proof chain.
///
/// The canonical serializer constructs bytes solely from typed realizations and
/// returns a complete segment map.  The supplied product adapter then tokenizes
/// those exact final bytes.  No registry `token_cost`, substring proof or
/// caller-supplied payload is promoted into an exact-token claim.
pub fn compile_prompt_registry_v3(
    registry: &DurablePromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    exercise_request: &PromptExerciseRequestV1,
    request: PromptRegistryCompilationRequestV3,
    adapters: &dyn PromptCompilerProductAdaptersV3,
) -> Result<PromptRegistryCompiledContextV3, PromptRegistryCompilationErrorV3> {
    validate_profile(portfolio, exercise_request, &request, adapters)?;
    if portfolio.selected.is_empty() {
        return Err(PromptRegistryCompilationErrorV3::EmptySelection);
    }

    let current_registry = registry
        .registry()
        .map_err(PromptRegistryCompilationErrorV3::Registry)?;
    let exercise = exercise_v1(current_registry, portfolio, exercise_request.clone())
        .map_err(|error| PromptRegistryCompilationErrorV3::Optimizer(error.to_string()))?;
    match exercise.decision {
        PromptExerciseActionV1::Exercise => {}
        PromptExerciseActionV1::NoIntervention => {
            return Err(PromptRegistryCompilationErrorV3::EmptySelection);
        }
        PromptExerciseActionV1::Wait | PromptExerciseActionV1::RejectStale => {
            return Err(PromptRegistryCompilationErrorV3::ExerciseRejected(
                exercise.decision,
            ));
        }
    }

    let registry_snapshot = registry
        .snapshot_v2(portfolio.generation_vector_digest, &portfolio.model_tuple)
        .map_err(PromptRegistryCompilationErrorV3::Registry)?;
    let compatible = registry
        .read_compatible_v2(
            &registry_snapshot,
            portfolio.generation_vector_digest,
            &portfolio.model_tuple,
            request.now_unix_ms,
            portfolio.receipt.factor_ids.clone(),
            u32::try_from(portfolio.selected.len())
                .map_err(|_| PromptRegistryCompilationErrorV3::Arithmetic)?,
        )
        .map_err(PromptRegistryCompilationErrorV3::Registry)?;

    let selected_deliveries = portfolio
        .selected
        .iter()
        .map(|selected| {
            let delivery = registry
                .dereference_realization_v2(
                    &selected.realization.realization_id,
                    &registry_snapshot,
                    portfolio.generation_vector_digest,
                    &portfolio.model_tuple,
                    request.now_unix_ms,
                )
                .map_err(PromptRegistryCompilationErrorV3::Registry)?;
            if delivery.binding != selected.realization
                || delivery.binding.digest() != selected.binding_digest
            {
                return Err(PromptRegistryCompilationErrorV3::RegistryDrift);
            }
            Ok(delivery)
        })
        .collect::<Result<Vec<_>, _>>()?;

    let admission_lineage = match &request.predecessor_lineage {
        Some(predecessor) => VerifiedAdmissionSnapshotLineageV2::verify_successor(
            request.admission_snapshot.clone(),
            predecessor,
            adapters,
        ),
        None => VerifiedAdmissionSnapshotLineageV2::verify_root(
            request.admission_snapshot.clone(),
            adapters,
        ),
    }
    .map_err(PromptRegistryCompilationErrorV3::Context)?;

    let mut records = request
        .admission_records
        .into_iter()
        .map(|record| (record.item_id.clone(), record))
        .collect::<BTreeMap<_, _>>();
    if records.len() != selected_deliveries.len() {
        return Err(PromptRegistryCompilationErrorV3::AdmissionSetMismatch);
    }

    let mut candidates = Vec::with_capacity(selected_deliveries.len());
    let mut realizations_by_id = BTreeMap::new();
    let mut prompt_roles = BTreeMap::new();
    for (selected, delivery) in portfolio.selected.iter().zip(&selected_deliveries) {
        let item_id = delivery.binding.realization_id.clone();
        let role = context_role(delivery.binding.role);
        let record = records
            .remove(&item_id)
            .ok_or(PromptRegistryCompilationErrorV3::AdmissionSetMismatch)?;
        if record.item_id != item_id
            || record.role != role
            || record.content_digest != delivery.binding.payload_digest
            || record.source_digest != selected.binding_digest
            || record.generation_vector_digest != portfolio.generation_vector_digest
            || record.scope_digest != admission_lineage.current().scope_digest()
            || record.authority_domain_digest
                != admission_lineage.current().authority_domain_digest()
            || record.contains_secret
        {
            return Err(PromptRegistryCompilationErrorV3::AdmissionBindingMismatch(
                item_id.to_string(),
            ));
        }
        let admission = verify_admission_v2(record, admission_lineage.current(), adapters)
            .map_err(PromptRegistryCompilationErrorV3::Context)?;
        let tokenization = TokenizationReceiptV2::from_exact_bytes(
            item_id.clone(),
            &delivery.payload,
            adapters,
        )
        .map_err(PromptRegistryCompilationErrorV3::Context)?;
        candidates.push(ContextCandidateV2 {
            item_id: item_id.clone(),
            role,
            content_digest: delivery.binding.payload_digest,
            source_digest: selected.binding_digest,
            generation_vector_digest: portfolio.generation_vector_digest,
            tokenization,
            expected_value: FixedQ32::ONE,
            admission,
        });
        if realizations_by_id
            .insert(
                item_id.clone(),
                ContextRealizedItemV2 {
                    item_id: item_id.clone(),
                    role,
                    content: delivery.payload.clone(),
                },
            )
            .is_some()
            || prompt_roles.insert(item_id, delivery.binding.role).is_some()
        {
            return Err(PromptRegistryCompilationErrorV3::Integrity);
        }
    }
    if !records.is_empty() {
        return Err(PromptRegistryCompilationErrorV3::AdmissionSetMismatch);
    }

    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: request.compilation_id,
        objective_digest: portfolio.objective_digest,
        prompt_portfolio_digest: portfolio.receipt.receipt_digest,
        generation_vector_digest: portfolio.generation_vector_digest,
        scope_digest: admission_lineage.current().scope_digest(),
        authority_domain_digest: admission_lineage.current().authority_domain_digest(),
        admission_verifier_digest: adapters.verifier_digest(),
        model_profile: request.product_profile.base_profile.clone(),
        token_budget: request.token_budget,
        truncation_policy_digest: request.truncation_policy_digest,
        candidates,
        mandatory_groups: vec![MandatoryContextGroupV2 {
            group_id: StableId::new(SELECTED_PROMPT_GROUP_ID_V3)
                .map_err(|_| PromptRegistryCompilationErrorV3::Integrity)?,
            item_ids: portfolio
                .selected
                .iter()
                .map(|selected| selected.realization.realization_id.clone())
                .collect(),
            reason_digest: portfolio.receipt.receipt_digest,
        }],
    })
    .map_err(PromptRegistryCompilationErrorV3::Context)?;

    let realizations = compiled
        .receipt()
        .selected_item_ids()
        .iter()
        .map(|item_id| {
            realizations_by_id
                .remove(item_id)
                .ok_or(PromptRegistryCompilationErrorV3::Integrity)
        })
        .collect::<Result<Vec<_>, _>>()?;
    if !realizations_by_id.is_empty() {
        return Err(PromptRegistryCompilationErrorV3::Integrity);
    }

    let serializer = CanonicalPromptSerializerV3 {
        product_profile_digest: request.product_profile.digest(),
        serializer_digest: request.product_profile.base_profile.serializer_digest,
        template_digest: request.product_profile.base_profile.template_digest,
        tool_schema_digest: request.product_profile.base_profile.tool_schema_digest,
        prompt_roles,
    };
    let serialized_context = record_serialization(
        &compiled,
        &request.product_profile.base_profile,
        request.serialization_id,
        realizations,
        &serializer,
        adapters,
    )
    .map_err(PromptRegistryCompilationErrorV3::Context)?;
    let attachment = build_attachment_with_lineage_v2(
        &compiled,
        &serialized_context,
        &request.product_profile.base_profile,
        &admission_lineage,
        request.attachment_id,
    )
    .map_err(PromptRegistryCompilationErrorV3::Context)?;

    let mut output = PromptRegistryCompiledContextV3 {
        compatible,
        exercise_receipt_digest: exercise.receipt_digest,
        portfolio_receipt_digest: portfolio.receipt.receipt_digest,
        model_tuple: request.registry_model_tuple,
        product_profile: request.product_profile,
        compiled,
        selected_deliveries,
        serialized_context,
        attachment,
        admission_lineage,
        delivery_set_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    output.delivery_set_digest = output.compute_delivery_set_digest();
    output.validate()?;
    Ok(output)
}

#[must_use]
pub fn canonical_prompt_serializer_revision_digest_v3() -> Digest32 {
    Digest32::of_bytes(CANONICAL_SERIALIZER_REVISION_DOMAIN_V3)
}

#[must_use]
pub fn canonical_prompt_role_profile_digest_v3() -> Digest32 {
    Digest32::of_bytes(CANONICAL_ROLE_PROFILE_DOMAIN_V3)
}

fn validate_profile(
    portfolio: &SelectedPromptPortfolioV1,
    exercise_request: &PromptExerciseRequestV1,
    request: &PromptRegistryCompilationRequestV3,
    adapters: &dyn PromptCompilerProductAdaptersV3,
) -> Result<(), PromptRegistryCompilationErrorV3> {
    request
        .registry_model_tuple
        .validate()
        .map_err(DurableRegistryError::Read)
        .map_err(PromptRegistryCompilationErrorV3::Registry)?;
    request
        .product_profile
        .validate()
        .map_err(PromptRegistryCompilationErrorV3::Context)?;
    let profile = &request.product_profile.base_profile;
    if request.registry_model_tuple != portfolio.model_tuple
        || request.now_unix_ms != exercise_request.now_unix_ms
        || request.now_unix_ms == 0
        || profile.model_digest != portfolio.model_tuple.model_digest
        || profile.provider_model_digest != portfolio.model_tuple.model_digest
        || profile.tokenizer_digest != portfolio.model_tuple.tokenizer_digest
        || profile.template_digest != portfolio.model_tuple.template_digest
        || profile.tool_schema_digest != portfolio.model_tuple.tool_schema_digest
        || request.product_profile.digest() != portfolio.model_tuple.context_profile_digest
        || adapters.product_profile_digest() != request.product_profile.digest()
        || adapters.tokenizer_digest() != profile.tokenizer_digest
        || request.product_profile.serializer_revision_digest
            != canonical_prompt_serializer_revision_digest_v3()
        || request.product_profile.role_profile_digest
            != canonical_prompt_role_profile_digest_v3()
    {
        return Err(PromptRegistryCompilationErrorV3::ProfileMismatch);
    }
    Ok(())
}

struct CanonicalPromptSerializerV3 {
    product_profile_digest: Digest32,
    serializer_digest: Digest32,
    template_digest: Digest32,
    tool_schema_digest: Digest32,
    prompt_roles: BTreeMap<StableId, PromptRoleV2>,
}

impl ContextSerializerV2 for CanonicalPromptSerializerV3 {
    fn serializer_digest(&self) -> Digest32 {
        self.serializer_digest
    }

    fn template_digest(&self) -> Digest32 {
        self.template_digest
    }

    fn tool_schema_digest(&self) -> Digest32 {
        self.tool_schema_digest
    }

    fn serialize(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> Result<ContextSerializationOutputV2, ContextCompilerV2Error> {
        let mut payload = SERIALIZED_PAYLOAD_DOMAIN_V3.to_vec();
        payload.extend_from_slice(self.product_profile_digest.as_array());
        payload.extend_from_slice(
            &u64::try_from(items.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        let mut segments = vec![framing_segment(0, payload.len(), &payload)];
        for item in items {
            let prompt_role = self
                .prompt_roles
                .get(&item.item_id)
                .ok_or(ContextCompilerV2Error::InvalidSerializationSegmentMap)?;
            let framing_start = payload.len();
            push_id(&mut payload, &item.item_id);
            payload.push(prompt_role_code(*prompt_role));
            payload.push(context_role_code(item.role));
            payload.extend_from_slice(
                &u64::try_from(item.content.len())
                    .unwrap_or(u64::MAX)
                    .to_be_bytes(),
            );
            payload.extend_from_slice(Digest32::of_bytes(&item.content).as_array());
            segments.push(framing_segment(
                framing_start,
                payload.len(),
                &payload[framing_start..],
            ));
            let item_start = payload.len();
            payload.extend_from_slice(&item.content);
            segments.push(ContextSerializationSegmentV2 {
                kind: ContextSerializationSegmentKindV2::Item,
                item_id: Some(item.item_id.clone()),
                role: Some(item.role),
                start_offset: u64::try_from(item_start).unwrap_or(u64::MAX),
                end_offset: u64::try_from(payload.len()).unwrap_or(u64::MAX),
                bytes_digest: Digest32::of_bytes(&item.content),
            });
        }
        ContextSerializationOutputV2::new(payload, segments)
    }
}

fn framing_segment(
    start: usize,
    end: usize,
    bytes: &[u8],
) -> ContextSerializationSegmentV2 {
    ContextSerializationSegmentV2 {
        kind: ContextSerializationSegmentKindV2::Framing,
        item_id: None,
        role: None,
        start_offset: u64::try_from(start).unwrap_or(u64::MAX),
        end_offset: u64::try_from(end).unwrap_or(u64::MAX),
        bytes_digest: Digest32::of_bytes(bytes),
    }
}

const fn context_role(role: PromptRoleV2) -> ContextRoleV2 {
    match role {
        PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,
        PromptRoleV2::SystemInstruction
        | PromptRoleV2::DeveloperInstruction
        | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,
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

const fn context_role_code(role: ContextRoleV2) -> u8 {
    match role {
        ContextRoleV2::TrustedInstruction => 0,
        ContextRoleV2::Schema => 1,
        ContextRoleV2::UntrustedEvidence => 2,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Debug)]
pub enum PromptRegistryCompilationErrorV3 {
    Registry(DurableRegistryError),
    Optimizer(String),
    Context(ContextCompilerV2Error),
    ProfileMismatch,
    EmptySelection,
    ExerciseRejected(PromptExerciseActionV1),
    RegistryDrift,
    AdmissionSetMismatch,
    AdmissionBindingMismatch(String),
    Integrity,
    Arithmetic,
}

impl PromptRegistryCompilationErrorV3 {
    #[must_use]
    pub const fn stable_code(&self) -> &'static str {
        match self {
            Self::Registry(_) => "prompt_compile_v3_registry",
            Self::Optimizer(_) => "prompt_compile_v3_optimizer",
            Self::Context(_) => "prompt_compile_v3_context",
            Self::ProfileMismatch => "prompt_compile_v3_profile_mismatch",
            Self::EmptySelection => "prompt_compile_v3_empty_selection",
            Self::ExerciseRejected(_) => "prompt_compile_v3_exercise_rejected",
            Self::RegistryDrift => "prompt_compile_v3_registry_drift",
            Self::AdmissionSetMismatch => "prompt_compile_v3_admission_set_mismatch",
            Self::AdmissionBindingMismatch(_) => "prompt_compile_v3_admission_binding_mismatch",
            Self::Integrity => "prompt_compile_v3_integrity",
            Self::Arithmetic => "prompt_compile_v3_arithmetic",
        }
    }
}

impl fmt::Display for PromptRegistryCompilationErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.stable_code())
    }
}

impl std::error::Error for PromptRegistryCompilationErrorV3 {}

#[cfg(test)]
#[path = "prompt_delivery_v3_tests.rs"]
mod tests;
