//! Product-facing composition for the canonical prompt optimizer.
//!
//! This layer does not invoke a provider. It converts an exercised, revalidated
//! prompt portfolio into the existing context compiler's trusted candidates,
//! preserves the serialization/attachment digest chain, and requires a second
//! optimizer revalidation immediately before a delivery attachment is prepared.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_context_compiler::CompiledContextV2;
use codex_hepta_context_compiler::ContextAdmissionBindingV2;
use codex_hepta_context_compiler::ContextAdmissionRecordV2;
use codex_hepta_context_compiler::ContextAdmissionSnapshotV2;
use codex_hepta_context_compiler::ContextAdmissionVerifierV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCandidateV2;
use codex_hepta_context_compiler::ContextCompilationRequestV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextDeliveryDispositionV2;
use codex_hepta_context_compiler::ContextDeliveryObservationV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ContextRealizedItemV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::ContextSerializationReceiptV2;
use codex_hepta_context_compiler::ContextSerializerV2;
use codex_hepta_context_compiler::ExactTokenizerV2;
use codex_hepta_context_compiler::MandatoryContextGroupV2;
use codex_hepta_context_compiler::SerializedContextV2;
use codex_hepta_context_compiler::TokenizationReceiptV2;
use codex_hepta_context_compiler::VerifiedAdmissionSnapshotV2;
use codex_hepta_context_compiler::build_attachment;
use codex_hepta_context_compiler::compile_v2;
use codex_hepta_context_compiler::record_serialization;
use codex_hepta_context_compiler::verify_admission_snapshot_v2;
use codex_hepta_context_compiler::verify_admission_v2;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseActionV1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseDecisionV1;
use codex_hepta_prompt_optimizer::canonical::PromptExerciseRequestV1;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_optimizer::canonical::exercise_v1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_prompt_registry::RealizationDeliveryV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptContextCompileRequestV1 {
    pub exercise: PromptExerciseRequestV1,
    pub compilation_id: StableId,
    pub model_profile: ContextModelProfileV2,
    pub token_budget: u64,
    pub truncation_policy_digest: Digest32,
    pub base_candidates: Vec<ContextCandidateV2>,
    pub mandatory_groups: Vec<MandatoryContextGroupV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPayloadMaterializationV1 {
    pub payloads: Vec<RealizationDeliveryV2>,
    pub bundle_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptPayloadMaterializationV1 {
    pub fn validate(&self) -> Result<(), PromptPipelineErrorV1> {
        for payload in &self.payloads {
            payload
                .validate()
                .map_err(|error| PromptPipelineErrorV1::Registry(format!("{error:?}")))?;
        }
        if self.authority.grants_any()
            || self.bundle_digest != prompt_payload_bundle_digest(&self.payloads)
        {
            return Err(PromptPipelineErrorV1::PayloadMaterializationDrift);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedPromptContextV1 {
    pub exercise: PromptExerciseDecisionV1,
    pub compiled: CompiledContextV2,
    pub materialization: PromptPayloadMaterializationV1,
    pub model_profile: ContextModelProfileV2,
    pub admission_snapshot: VerifiedAdmissionSnapshotV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryPrepareRequestV1 {
    pub exercise: PromptExerciseRequestV1,
    pub serialization_id: StableId,
    pub serialized_payload: Vec<u8>,
    pub attachment_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptSerializationOccurrenceV1 {
    pub realization_id: StableId,
    pub payload_digest: Digest32,
    pub start_offset: u64,
    pub end_offset: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptSerializationProofV1 {
    pub compilation_receipt_digest: Digest32,
    pub materialization_bundle_digest: Digest32,
    pub serialized_payload_digest: Digest32,
    pub occurrences: Vec<PromptSerializationOccurrenceV1>,
    pub proof_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptSerializationProofV1 {
    pub fn validate(&self) -> Result<(), PromptPipelineErrorV1> {
        if self.compilation_receipt_digest.is_zero()
            || self.materialization_bundle_digest.is_zero()
            || self.serialized_payload_digest.is_zero()
            || self.proof_digest.is_zero()
            || self.authority.grants_any()
        {
            return Err(PromptPipelineErrorV1::SerializationProofDrift);
        }
        let mut previous_end = 0_u64;
        for occurrence in &self.occurrences {
            if occurrence.payload_digest.is_zero()
                || occurrence.start_offset >= occurrence.end_offset
                || occurrence.start_offset < previous_end
            {
                return Err(PromptPipelineErrorV1::SerializationProofDrift);
            }
            previous_end = occurrence.end_offset;
        }
        if self.proof_digest != prompt_serialization_proof_digest(self) {
            return Err(PromptPipelineErrorV1::SerializationProofDrift);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedPromptDeliveryV1 {
    pub exercise: PromptExerciseDecisionV1,
    pub serialization: ContextSerializationReceiptV2,
    pub serialized_context: SerializedContextV2,
    pub attachment: ContextAttachmentV2,
    pub materialization: PromptPayloadMaterializationV1,
    pub serialization_proof: PromptSerializationProofV1,
    pub serialized_payload: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptPipelineErrorV1 {
    ModelTupleMismatch,
    ExerciseRejected(PromptExerciseActionV1),
    Optimizer(String),
    ContextCompiler(String),
    DuplicateContextItem(String),
    PortfolioContextBindingMismatch,
    SelectedRealizationMissing(String),
    Registry(String),
    PayloadMaterializationDrift,
    SerializedPayloadMissing(String),
    SerializationProofDrift,
    ProviderEvidenceRequired,
    Arithmetic,
}

impl fmt::Display for PromptPipelineErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptPipelineErrorV1 {}

#[derive(Clone, Debug)]
struct RegistryAdmissionVerifier {
    digest: Digest32,
    scope_digest: Digest32,
    authority_domain_digest: Digest32,
}

impl ContextAdmissionVerifierV2 for RegistryAdmissionVerifier {
    fn verifier_digest(&self) -> Digest32 {
        self.digest
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

#[derive(Clone, Debug)]
struct RegistryBoundTokenizer {
    tokenizer_digest: Digest32,
    exact_counts: BTreeMap<Digest32, u64>,
}

impl ExactTokenizerV2 for RegistryBoundTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        self.tokenizer_digest
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        self.exact_counts
            .get(&Digest32::of_bytes(bytes))
            .copied()
            .ok_or(ContextCompilerV2Error::InvalidSerializedTokenCount)
    }
}

#[derive(Clone, Debug)]
struct ExactPreparedSerializer {
    serializer_digest: Digest32,
    template_digest: Digest32,
    tool_schema_digest: Digest32,
    payload: Vec<u8>,
}

impl ContextSerializerV2 for ExactPreparedSerializer {
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
        _items: &[ContextRealizedItemV2],
    ) -> Result<Vec<u8>, ContextCompilerV2Error> {
        Ok(self.payload.clone())
    }
}

fn admission_domains(
    portfolio: &SelectedPromptPortfolioV1,
    materialization: &PromptPayloadMaterializationV1,
) -> (Digest32, Digest32, Digest32) {
    let mut scope = b"hepta.prompt-pipeline.context-scope.v2\0".to_vec();
    scope.extend_from_slice(portfolio.receipt.receipt_digest.as_array());
    scope.extend_from_slice(portfolio.generation_vector_digest.as_array());
    let scope_digest = Digest32::of_bytes(&scope);
    let mut authority = b"hepta.prompt-pipeline.registry-authority.v2\0".to_vec();
    authority.extend_from_slice(materialization.bundle_digest.as_array());
    let authority_domain_digest = Digest32::of_bytes(&authority);
    let mut verifier = b"hepta.prompt-pipeline.registry-admission-verifier.v2\0".to_vec();
    verifier.extend_from_slice(scope_digest.as_array());
    verifier.extend_from_slice(authority_domain_digest.as_array());
    (
        scope_digest,
        authority_domain_digest,
        Digest32::of_bytes(&verifier),
    )
}

pub fn compile_exercised_prompt_context_v1(
    registry: &DurablePromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    request: PromptContextCompileRequestV1,
) -> Result<PreparedPromptContextV1, PromptPipelineErrorV1> {
    ensure_model_tuple_matches(portfolio, &request.model_profile)?;
    if !request.base_candidates.is_empty() {
        return Err(PromptPipelineErrorV1::PortfolioContextBindingMismatch);
    }
    let now_unix_ms = request.exercise.now_unix_ms;
    let current_registry = registry
        .registry()
        .map_err(|error| PromptPipelineErrorV1::Registry(format!("{error:?}")))?;
    let exercise = exercise_v1(current_registry, portfolio, request.exercise)
        .map_err(|error| PromptPipelineErrorV1::Optimizer(format!("{error:?}")))?;
    ensure_exercisable(exercise.decision)?;
    let materialization = materialize_prompt_payloads(registry, portfolio, now_unix_ms)?;
    let (scope_digest, authority_domain_digest, verifier_digest) =
        admission_domains(portfolio, &materialization);
    let verifier = RegistryAdmissionVerifier {
        digest: verifier_digest,
        scope_digest,
        authority_domain_digest,
    };
    let snapshot_raw = ContextAdmissionSnapshotV2::new(
        request.compilation_id.clone(),
        scope_digest,
        authority_domain_digest,
        now_unix_ms.max(1),
        1,
        Vec::new(),
        true,
        None,
    )
    .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
    let admission_snapshot = verify_admission_snapshot_v2(snapshot_raw, &verifier)
        .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;

    let mut candidates = Vec::with_capacity(portfolio.selected.len());
    let mut seen = BTreeSet::new();
    let mut counts = BTreeMap::new();
    for (selected, payload) in portfolio.selected.iter().zip(&materialization.payloads) {
        let realization = &payload.binding;
        if !seen.insert(realization.realization_id.clone()) {
            return Err(PromptPipelineErrorV1::DuplicateContextItem(
                realization.realization_id.to_string(),
            ));
        }
        let role = match realization.role {
            PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,
            PromptRoleV2::SystemInstruction
            | PromptRoleV2::DeveloperInstruction
            | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,
        };
        counts.insert(
            realization.payload_digest,
            u64::from(realization.token_cost),
        );
        let tokenizer = RegistryBoundTokenizer {
            tokenizer_digest: realization.tokenizer_digest,
            exact_counts: counts.clone(),
        };
        let tokenization = TokenizationReceiptV2::from_exact_bytes(
            realization.realization_id.clone(),
            &payload.payload,
            &tokenizer,
        )
        .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
        let expires_unix_ms = realization
            .expires_unix_ms
            .unwrap_or(portfolio.receipt.valid_until_unix_ms)
            .min(portfolio.receipt.valid_until_unix_ms);
        let record = ContextAdmissionRecordV2::new(
            realization.realization_id.clone(),
            ContextAdmissionBindingV2 {
                item_id: realization.realization_id.clone(),
                role,
                content_digest: realization.payload_digest,
                source_digest: selected.binding_digest,
                generation_vector_digest: portfolio.generation_vector_digest,
                scope_digest,
                authority_domain_digest,
                contains_secret: false,
            },
            now_unix_ms.saturating_sub(1).max(1),
            expires_unix_ms,
        )
        .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
        let admission = verify_admission_v2(record, &admission_snapshot, &verifier)
            .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
        candidates.push(ContextCandidateV2 {
            item_id: realization.realization_id.clone(),
            role,
            content_digest: realization.payload_digest,
            source_digest: selected.binding_digest,
            generation_vector_digest: portfolio.generation_vector_digest,
            tokenization,
            expected_value: FixedQ32::ONE,
            admission,
        });
    }

    let compiled = compile_v2(ContextCompilationRequestV2 {
        compilation_id: request.compilation_id,
        objective_digest: portfolio.objective_digest,
        prompt_portfolio_digest: portfolio.receipt.receipt_digest,
        generation_vector_digest: portfolio.generation_vector_digest,
        scope_digest,
        authority_domain_digest,
        admission_verifier_digest: verifier_digest,
        model_profile: request.model_profile.clone(),
        token_budget: request.token_budget,
        truncation_policy_digest: request.truncation_policy_digest,
        candidates,
        mandatory_groups: request.mandatory_groups,
    })
    .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;

    for selected in &portfolio.selected {
        if !compiled
            .receipt()
            .selected_item_ids()
            .contains(&selected.realization.realization_id)
        {
            return Err(PromptPipelineErrorV1::SelectedRealizationMissing(
                selected.realization.realization_id.to_string(),
            ));
        }
    }
    Ok(PreparedPromptContextV1 {
        exercise,
        compiled,
        materialization,
        model_profile: request.model_profile,
        admission_snapshot,
    })
}

pub fn prepare_prompt_delivery_v1(
    registry: &DurablePromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    prepared: &PreparedPromptContextV1,
    request: PromptDeliveryPrepareRequestV1,
) -> Result<PreparedPromptDeliveryV1, PromptPipelineErrorV1> {
    let receipt = prepared.compiled.receipt();
    if receipt.objective_digest() != portfolio.objective_digest
        || receipt.prompt_portfolio_digest() != portfolio.receipt.receipt_digest
        || receipt.generation_vector_digest() != portfolio.generation_vector_digest
    {
        return Err(PromptPipelineErrorV1::PortfolioContextBindingMismatch);
    }
    let PromptDeliveryPrepareRequestV1 {
        exercise: exercise_request,
        serialization_id,
        serialized_payload,
        attachment_id,
    } = request;
    let now_unix_ms = exercise_request.now_unix_ms;
    let current_registry = registry
        .registry()
        .map_err(|error| PromptPipelineErrorV1::Registry(format!("{error:?}")))?;
    let exercise = exercise_v1(current_registry, portfolio, exercise_request)
        .map_err(|error| PromptPipelineErrorV1::Optimizer(format!("{error:?}")))?;
    ensure_exercisable(exercise.decision)?;
    let materialization = materialize_prompt_payloads(registry, portfolio, now_unix_ms)?;
    if materialization != prepared.materialization {
        return Err(PromptPipelineErrorV1::PayloadMaterializationDrift);
    }
    let serialization_proof =
        prove_prompt_serialization(&prepared.compiled, &materialization, &serialized_payload)?;

    let by_id = materialization
        .payloads
        .iter()
        .map(|payload| (payload.binding.realization_id.clone(), payload))
        .collect::<BTreeMap<_, _>>();
    let mut realizations = Vec::new();
    let mut counts = BTreeMap::new();
    let mut serialized_count = 0_u64;
    for item_id in prepared.compiled.receipt().selected_item_ids() {
        let payload = by_id.get(item_id).ok_or_else(|| {
            PromptPipelineErrorV1::SelectedRealizationMissing(item_id.to_string())
        })?;
        let role = match payload.binding.role {
            PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,
            PromptRoleV2::SystemInstruction
            | PromptRoleV2::DeveloperInstruction
            | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,
        };
        counts.insert(
            payload.binding.payload_digest,
            u64::from(payload.binding.token_cost),
        );
        serialized_count = serialized_count
            .checked_add(u64::from(payload.binding.token_cost))
            .ok_or(PromptPipelineErrorV1::Arithmetic)?;
        realizations.push(ContextRealizedItemV2 {
            item_id: item_id.clone(),
            role,
            content: payload.payload.clone(),
        });
    }
    counts.insert(
        Digest32::of_bytes(&serialized_payload),
        serialized_count.max(1),
    );
    let tokenizer = RegistryBoundTokenizer {
        tokenizer_digest: prepared.model_profile.tokenizer_digest,
        exact_counts: counts,
    };
    let serializer = ExactPreparedSerializer {
        serializer_digest: prepared.model_profile.serializer_digest,
        template_digest: prepared.model_profile.template_digest,
        tool_schema_digest: prepared.model_profile.tool_schema_digest,
        payload: serialized_payload.clone(),
    };
    let serialized_context = record_serialization(
        &prepared.compiled,
        &prepared.model_profile,
        serialization_id,
        realizations,
        &serializer,
        &tokenizer,
    )
    .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
    let serialization = serialized_context.receipt().clone();
    let attachment = build_attachment(
        &prepared.compiled,
        &serialized_context,
        &prepared.model_profile,
        &prepared.admission_snapshot,
        attachment_id,
    )
    .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
    Ok(PreparedPromptDeliveryV1 {
        exercise,
        serialization,
        serialized_context,
        attachment,
        materialization,
        serialization_proof,
        serialized_payload,
    })
}

pub fn observe_prompt_delivery_v1(
    _prepared: &PreparedPromptDeliveryV1,
    _observation_id: StableId,
    _observed_payload_digest: Option<Digest32>,
    _terminal_observed: bool,
    _disposition: ContextDeliveryDispositionV2,
    _observed_unix_ms: u64,
) -> Result<ContextDeliveryObservationV2, PromptPipelineErrorV1> {
    Err(PromptPipelineErrorV1::ProviderEvidenceRequired)
}

fn materialize_prompt_payloads(
    registry: &DurablePromptRegistry,
    portfolio: &SelectedPromptPortfolioV1,
    now_unix_ms: u64,
) -> Result<PromptPayloadMaterializationV1, PromptPipelineErrorV1> {
    let snapshot = registry
        .snapshot_v2(portfolio.generation_vector_digest, &portfolio.model_tuple)
        .map_err(|error| PromptPipelineErrorV1::Registry(format!("{error:?}")))?;
    let mut payloads = Vec::with_capacity(portfolio.selected.len());
    for selected in &portfolio.selected {
        let payload = registry
            .dereference_realization_v2(
                &selected.realization.realization_id,
                &snapshot,
                portfolio.generation_vector_digest,
                &portfolio.model_tuple,
                now_unix_ms,
            )
            .map_err(|error| PromptPipelineErrorV1::Registry(format!("{error:?}")))?;
        if payload.binding != selected.realization
            || payload.binding.digest() != selected.binding_digest
            || payload.binding.payload_digest != selected.realization.payload_digest
        {
            return Err(PromptPipelineErrorV1::PayloadMaterializationDrift);
        }
        payloads.push(payload);
    }
    let materialization = PromptPayloadMaterializationV1 {
        bundle_digest: prompt_payload_bundle_digest(&payloads),
        payloads,
        authority: AuthorityPosture::DENY_ALL,
    };
    materialization.validate()?;
    Ok(materialization)
}

fn prove_prompt_serialization(
    compiled: &CompiledContextV2,
    materialization: &PromptPayloadMaterializationV1,
    serialized_payload: &[u8],
) -> Result<PromptSerializationProofV1, PromptPipelineErrorV1> {
    compiled
        .validate()
        .map_err(|error| PromptPipelineErrorV1::ContextCompiler(format!("{error:?}")))?;
    materialization.validate()?;

    let mut cursor = 0_usize;
    let mut occurrences = Vec::with_capacity(materialization.payloads.len());
    for item_id in compiled.receipt().selected_item_ids() {
        let Some(payload) = materialization
            .payloads
            .iter()
            .find(|payload| payload.binding.realization_id == *item_id)
        else {
            continue;
        };
        if payload.payload.is_empty() {
            return Err(PromptPipelineErrorV1::SerializedPayloadMissing(
                item_id.to_string(),
            ));
        }
        let Some(relative_start) = find_subslice(&serialized_payload[cursor..], &payload.payload)
        else {
            return Err(PromptPipelineErrorV1::SerializedPayloadMissing(
                item_id.to_string(),
            ));
        };
        let start = cursor
            .checked_add(relative_start)
            .ok_or(PromptPipelineErrorV1::Arithmetic)?;
        let end = start
            .checked_add(payload.payload.len())
            .ok_or(PromptPipelineErrorV1::Arithmetic)?;
        occurrences.push(PromptSerializationOccurrenceV1 {
            realization_id: item_id.clone(),
            payload_digest: payload.binding.payload_digest,
            start_offset: u64::try_from(start).map_err(|_| PromptPipelineErrorV1::Arithmetic)?,
            end_offset: u64::try_from(end).map_err(|_| PromptPipelineErrorV1::Arithmetic)?,
        });
        cursor = end;
    }
    if occurrences.len() != materialization.payloads.len() {
        return Err(PromptPipelineErrorV1::SerializationProofDrift);
    }

    let mut proof = PromptSerializationProofV1 {
        compilation_receipt_digest: compiled.receipt().receipt_digest(),
        materialization_bundle_digest: materialization.bundle_digest,
        serialized_payload_digest: Digest32::of_bytes(serialized_payload),
        occurrences,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = prompt_serialization_proof_digest(&proof);
    proof.validate()?;
    Ok(proof)
}

fn prompt_serialization_proof_digest(proof: &PromptSerializationProofV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-pipeline.serialization-proof.v1".to_vec();
    bytes.extend_from_slice(proof.compilation_receipt_digest.as_array());
    bytes.extend_from_slice(proof.materialization_bundle_digest.as_array());
    bytes.extend_from_slice(proof.serialized_payload_digest.as_array());
    push_len(&mut bytes, proof.occurrences.len());
    for occurrence in &proof.occurrences {
        push_id(&mut bytes, &occurrence.realization_id);
        bytes.extend_from_slice(occurrence.payload_digest.as_array());
        bytes.extend_from_slice(&occurrence.start_offset.to_be_bytes());
        bytes.extend_from_slice(&occurrence.end_offset.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() {
        return None;
    }
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

fn prompt_payload_bundle_digest(payloads: &[RealizationDeliveryV2]) -> Digest32 {
    let mut bytes = b"hepta.prompt-pipeline.payload-materialization.v1".to_vec();
    push_len(&mut bytes, payloads.len());
    for payload in payloads {
        push_id(&mut bytes, &payload.binding.factor_id);
        push_id(&mut bytes, &payload.binding.realization_id);
        bytes.extend_from_slice(payload.binding.digest().as_array());
        bytes.extend_from_slice(payload.binding.payload_digest.as_array());
        push_len(&mut bytes, payload.payload.len());
        bytes.extend_from_slice(&payload.payload);
    }
    Digest32::of_bytes(&bytes)
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn ensure_model_tuple_matches(
    portfolio: &SelectedPromptPortfolioV1,
    profile: &ContextModelProfileV2,
) -> Result<(), PromptPipelineErrorV1> {
    if profile.model_digest != portfolio.model_tuple.model_digest
        || profile.tokenizer_digest != portfolio.model_tuple.tokenizer_digest
        || profile.template_digest != portfolio.model_tuple.template_digest
        || profile.tool_schema_digest != portfolio.model_tuple.tool_schema_digest
    {
        return Err(PromptPipelineErrorV1::ModelTupleMismatch);
    }
    Ok(())
}

fn ensure_exercisable(decision: PromptExerciseActionV1) -> Result<(), PromptPipelineErrorV1> {
    match decision {
        PromptExerciseActionV1::Exercise | PromptExerciseActionV1::NoIntervention => Ok(()),
        PromptExerciseActionV1::Wait | PromptExerciseActionV1::RejectStale => {
            Err(PromptPipelineErrorV1::ExerciseRejected(decision))
        }
    }
}

#[cfg(test)]
#[path = "prompt_pipeline_tests.rs"]
mod tests;
