//! Authenticated, generator-complete parameter proposal admission.
//!
//! This layer turns the parameter-only V2 record into a governed proposal path:
//! candidates are generated inside this crate, dataset/artifact lineage is
//! checked against owner receipts, generator/source/evaluator identities are
//! authenticated by a host-owned trust snapshot, and only independently
//! eligible candidate sets can be persisted. The result remains authority-free;
//! it does not select, activate, promote, release, or mutate the selected model.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence_eval::{
    IndependentEvaluationBundleV1, IndependentEvaluationDispositionV1, MetricRoleContractV2,
    SignedEvaluationDecisionV1, SignedEvaluationError, SignedEvaluationEvidenceV1,
    decide_with_signed_evidence_v2,
};
use codex_hepta_learning_artifacts::{ArtifactKind, ArtifactRegistry};
use codex_hepta_learning_ledger::{
    CandidateSetCompletenessReceiptV1, CausalV2Error, DatasetReceiptError,
    DatasetSnapshotReceiptV3, LearningEvidenceRoleV1, LearningEvidenceVerifierV1,
    SignedEvidenceError, SignedLearningEvidenceV1, validate_candidate_set_completeness,
    verify_dataset_snapshot_receipt_v3, verify_signed_role_separation,
};
use codex_hepta_types::{Digest32, FixedQ32, Generation, StableId};

use crate::parameter_v2::within_relative_limit;
use crate::types::{
    GLOBAL_MAX_RELATIVE_PPM, MAX_CANDIDATES, MAX_NORM_LAYERS, MAX_PARAMETER_DELTAS,
    PER_LAYER_MAX_RELATIVE_PPM,
};
use crate::{
    Error, LayerNormDenominatorV2, ParameterCandidateKindV2, ParameterCandidateRequestV2,
    ParameterDeltaV2, ParameterProposalRequestV2, ParameterProposalV2, ProposalWindowV2,
    propose_v2,
};

const MAX_GENERATED_SCALES: usize = 8;
const PPM_DENOMINATOR: i128 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterOpportunityV3 {
    pub layer_id: StableId,
    pub parameter_id: StableId,
    /// Bounded eligibility value for this parameter.
    pub eligibility: FixedQ32,
    /// The manifest-bound group-projected modulator q(t,g), not a credential or authority value.
    pub projected_modulator: FixedQ32,
    pub lower_bound: FixedQ32,
    pub upper_bound: FixedQ32,
    /// Owner evidence for the eligibility/modulator/parameter binding.
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterGenerationPolicyV3 {
    pub generator_id: StableId,
    pub generator_code_digest: Digest32,
    pub grammar_digest: Digest32,
    pub hard_filter_digest: Digest32,
    pub truncation_digest: Digest32,
    pub learning_rate: FixedQ32,
    /// Deterministic candidate scales. 1_000_000 ppm is the full local update.
    pub candidate_scales_ppm: Vec<u32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterEvidenceBindingV3 {
    pub selected_artifact_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub objective_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub dataset_digest: Digest32,
    pub update_rule_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub eligibility_digest: Digest32,
    pub norm_layers: Vec<LayerNormDenominatorV2>,
    pub opportunities: Vec<ParameterOpportunityV3>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratedParameterCandidateSetV3 {
    pub candidates: Vec<ParameterCandidateRequestV2>,
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub candidate_set_digest: Digest32,
    pub canonical_order_digest: Digest32,
}

pub struct GovernedParameterProposalRequestV3<'a> {
    pub proposal_id: StableId,
    pub set_id: StableId,
    pub binding: ParameterEvidenceBindingV3,
    pub generation_policy: ParameterGenerationPolicyV3,
    /// Generator signature over `candidate_completeness_signing_payload_v3`.
    pub generator_evidence: &'a SignedLearningEvidenceV1,
    /// Independent source/observer signature over `evidence_binding_signing_payload_v3`.
    pub source_evidence: &'a SignedLearningEvidenceV1,
    pub dataset: &'a DatasetSnapshotReceiptV3,
    pub evaluation: IndependentEvaluationBundleV1,
    pub metric_roles: Vec<MetricRoleContractV2>,
    pub evaluation_evidence: &'a SignedEvaluationEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GovernedParameterProposalV3 {
    pub proposal: ParameterProposalV2,
    pub completeness: CandidateSetCompletenessReceiptV1,
    pub completeness_digest: Digest32,
    pub artifact_registry_head_digest: Digest32,
    pub source_authentication_digest: Digest32,
    pub generator_authentication_digest: Digest32,
    pub evaluation: SignedEvaluationDecisionV1,
    pub admission_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GovernedProposalError {
    Binding(&'static str),
    Generator(&'static str),
    Artifact(&'static str),
    Arithmetic,
    Proposal(Error),
    Dataset(DatasetReceiptError),
    Completeness(CausalV2Error),
    Evidence(SignedEvidenceError),
    Evaluation(SignedEvaluationError),
    EvaluationIneligible(IndependentEvaluationDispositionV1),
}

impl fmt::Display for GovernedProposalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for GovernedProposalError {}
impl From<Error> for GovernedProposalError {
    fn from(value: Error) -> Self {
        Self::Proposal(value)
    }
}
impl From<DatasetReceiptError> for GovernedProposalError {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}
impl From<CausalV2Error> for GovernedProposalError {
    fn from(value: CausalV2Error) -> Self {
        Self::Completeness(value)
    }
}
impl From<SignedEvidenceError> for GovernedProposalError {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}
impl From<SignedEvaluationError> for GovernedProposalError {
    fn from(value: SignedEvaluationError) -> Self {
        Self::Evaluation(value)
    }
}

/// Generate the complete bounded candidate set for this generator profile.
///
/// The local rule is `eta * q(t,g) * eligibility`, followed by the configured
/// candidate scale, per-parameter bounds, and a conservative deterministic
/// projection into the V2 per-layer/global trust region. Exactly one no-change
/// candidate is always present. This function never reads caller-supplied delta
/// candidates.
pub fn generate_parameter_candidates_v3(
    set_id: StableId,
    binding: &ParameterEvidenceBindingV3,
    policy: &ParameterGenerationPolicyV3,
    state_digest: Digest32,
) -> Result<GeneratedParameterCandidateSetV3, GovernedProposalError> {
    validate_generation_inputs(binding, policy, state_digest)?;

    let mut scales = policy.candidate_scales_ppm.clone();
    scales.sort_unstable();
    if scales.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(GovernedProposalError::Generator("duplicate candidate scale"));
    }

    let mut candidates = vec![ParameterCandidateRequestV2 {
        candidate_id: stable_id("plasticity:no-change")?,
        kind: ParameterCandidateKindV2::NoChange,
        parameter_deltas: Vec::new(),
    }];

    for scale in scales {
        let mut deltas = Vec::with_capacity(binding.opportunities.len());
        for opportunity in &binding.opportunities {
            if opportunity.lower_bound > opportunity.upper_bound {
                return Err(GovernedProposalError::Generator("inverted opportunity bounds"));
            }
            if opportunity.evidence_digest.is_zero() {
                return Err(GovernedProposalError::Generator("empty opportunity evidence"));
            }
            let local = opportunity
                .eligibility
                .checked_mul(opportunity.projected_modulator)
                .and_then(|value| value.checked_mul(policy.learning_rate))
                .map_err(|_| GovernedProposalError::Arithmetic)?;
            let scaled = scale_fixed(local, scale)?
                .clamp(opportunity.lower_bound, opportunity.upper_bound)
                .map_err(|_| GovernedProposalError::Arithmetic)?;
            if scaled != FixedQ32::ZERO {
                deltas.push(ParameterDeltaV2 {
                    layer_id: opportunity.layer_id.clone(),
                    parameter_id: opportunity.parameter_id.clone(),
                    delta: scaled,
                    lower_bound: opportunity.lower_bound,
                    upper_bound: opportunity.upper_bound,
                    evidence_digest: opportunity.evidence_digest,
                });
            }
        }
        deltas.sort_by(|left, right| {
            left.layer_id
                .cmp(&right.layer_id)
                .then_with(|| left.parameter_id.cmp(&right.parameter_id))
        });
        deltas = project_into_trust_region(deltas, &binding.norm_layers)?;
        if deltas.is_empty() {
            continue;
        }
        candidates.push(ParameterCandidateRequestV2 {
            candidate_id: stable_id(&format!("plasticity:update:{scale}"))?,
            kind: ParameterCandidateKindV2::Update,
            parameter_deltas: deltas,
        });
    }

    if candidates.len() > MAX_CANDIDATES {
        return Err(GovernedProposalError::Generator("generated candidate limit"));
    }
    let total_deltas = candidates
        .iter()
        .try_fold(0usize, |count, candidate| {
            count.checked_add(candidate.parameter_deltas.len())
        })
        .ok_or(GovernedProposalError::Arithmetic)?;
    if total_deltas > MAX_PARAMETER_DELTAS {
        return Err(GovernedProposalError::Generator("generated delta limit"));
    }

    let candidate_set_digest = digest_candidate_set(&candidates)?;
    let canonical_order_digest = digest_candidate_order(&candidates)?;
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id,
        state_digest,
        generator_id: policy.generator_id.clone(),
        generator_code_digest: policy.generator_code_digest,
        grammar_digest: policy.grammar_digest,
        hard_filter_digest: policy.hard_filter_digest,
        truncation_digest: policy.truncation_digest,
        candidates_digest: candidate_set_digest,
        candidate_count: u32::try_from(candidates.len())
            .map_err(|_| GovernedProposalError::Arithmetic)?,
        omitted_count_bound: 0,
        canonical_order_digest,
        complete_for_generator: true,
    };
    let validated = validate_candidate_set_completeness(&completeness)?;
    if validated.is_zero() {
        return Err(GovernedProposalError::Generator("empty completeness digest"));
    }
    Ok(GeneratedParameterCandidateSetV3 {
        candidates,
        completeness,
        candidate_set_digest,
        canonical_order_digest,
    })
}

/// Canonical payload an independent source/observer signs after verifying the
/// current artifact/window and every supplied lineage/evidence fact.
pub fn evidence_binding_signing_payload_v3(
    binding: &ParameterEvidenceBindingV3,
    artifact_registry_head_digest: Digest32,
    dataset_snapshot_id: &StableId,
) -> Result<Vec<u8>, GovernedProposalError> {
    if artifact_registry_head_digest.is_zero() {
        return Err(GovernedProposalError::Binding("empty artifact registry head"));
    }
    let mut bytes = b"hepta.plasticity.evidence-binding.v3\0".to_vec();
    push_id(&mut bytes, &binding.selected_artifact_id)?;
    bytes.extend_from_slice(binding.selected_artifact_digest.as_array());
    bytes.extend_from_slice(binding.objective_digest.as_array());
    push_id(&mut bytes, &binding.window.window_id)?;
    bytes.extend_from_slice(binding.window.window_digest.as_array());
    bytes.extend_from_slice(&binding.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&binding.candidate_generation.get().to_be_bytes());
    push_id(&mut bytes, dataset_snapshot_id)?;
    for digest in [
        artifact_registry_head_digest,
        binding.dataset_digest,
        binding.update_rule_digest,
        binding.modulator_digest,
        binding.modulator_broadcast_digest,
        binding.eligibility_digest,
    ] {
        if digest.is_zero() {
            return Err(GovernedProposalError::Binding("empty evidence binding digest"));
        }
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, binding.norm_layers.len())?;
    for layer in &binding.norm_layers {
        push_id(&mut bytes, &layer.layer_id)?;
        bytes.extend_from_slice(&layer.baseline_squared_l2_raw_q64.to_be_bytes());
    }
    push_len(&mut bytes, binding.opportunities.len())?;
    for opportunity in &binding.opportunities {
        push_id(&mut bytes, &opportunity.layer_id)?;
        push_id(&mut bytes, &opportunity.parameter_id)?;
        bytes.extend_from_slice(&opportunity.eligibility.raw().to_be_bytes());
        bytes.extend_from_slice(&opportunity.projected_modulator.raw().to_be_bytes());
        bytes.extend_from_slice(&opportunity.lower_bound.raw().to_be_bytes());
        bytes.extend_from_slice(&opportunity.upper_bound.raw().to_be_bytes());
        bytes.extend_from_slice(opportunity.evidence_digest.as_array());
    }
    Ok(bytes)
}

/// Canonical payload signed by the authenticated generator after the candidate
/// set has been deterministically produced.
pub fn candidate_completeness_signing_payload_v3(
    receipt: &CandidateSetCompletenessReceiptV1,
) -> Result<Vec<u8>, GovernedProposalError> {
    let digest = validate_candidate_set_completeness(receipt)?;
    let mut bytes = b"hepta.plasticity.candidate-completeness.v3\0".to_vec();
    bytes.extend_from_slice(digest.as_array());
    Ok(bytes)
}

/// Produce one governed, authority-free parameter proposal.
///
/// All authentication happens before construction of the V2 record. The
/// independently evaluated object is the complete generated candidate set,
/// identified by `set_id`; evaluation eligibility is not selection or runtime
/// activation.
pub fn propose_governed_v3(
    request: GovernedParameterProposalRequestV3<'_>,
    verifier: &LearningEvidenceVerifierV1,
    artifacts: &ArtifactRegistry,
    now: u64,
) -> Result<GovernedParameterProposalV3, GovernedProposalError> {
    let binding = &request.binding;
    let manifest = artifacts
        .manifest(&binding.selected_artifact_id)
        .ok_or(GovernedProposalError::Artifact("selected artifact missing"))?;
    if !artifacts.is_eligible(&binding.selected_artifact_id) {
        return Err(GovernedProposalError::Artifact("selected artifact lineage unavailable"));
    }
    if !matches!(manifest.kind, ArtifactKind::Parameters | ArtifactKind::Model) {
        return Err(GovernedProposalError::Artifact("selected artifact kind"));
    }
    if manifest.content_digest != binding.selected_artifact_digest
        || manifest.objective_digest != binding.objective_digest
        || manifest.generation != binding.baseline_generation
    {
        return Err(GovernedProposalError::Artifact("selected artifact binding"));
    }
    if binding.baseline_generation.next() != Ok(binding.candidate_generation) {
        return Err(GovernedProposalError::Binding("candidate generation is not exact successor"));
    }

    verify_dataset_snapshot_receipt_v3(request.dataset, now)?;
    if request.dataset.snapshot.dataset_digest != binding.dataset_digest
        || request.dataset.snapshot.objective_digest != binding.objective_digest
    {
        return Err(GovernedProposalError::Binding("dataset binding"));
    }

    let artifact_registry_head_digest = artifacts
        .records()
        .last()
        .map_or(Digest32::ZERO, |record| record.chain_digest);
    let source_payload = evidence_binding_signing_payload_v3(
        binding,
        artifact_registry_head_digest,
        &request.dataset.snapshot.snapshot_id,
    )?;
    let source = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        request.source_evidence,
        &source_payload,
        now,
    )?;
    let source_authentication_digest = attestation_digest(request.source_evidence);

    let generated = generate_parameter_candidates_v3(
        request.set_id.clone(),
        binding,
        &request.generation_policy,
        Digest32::of_bytes(&source_payload),
    )?;
    if generated.completeness.omitted_count_bound != 0
        || generated.completeness.candidate_count
            != u32::try_from(generated.candidates.len())
                .map_err(|_| GovernedProposalError::Arithmetic)?
    {
        return Err(GovernedProposalError::Generator("candidate completeness mismatch"));
    }
    let completeness_digest = validate_candidate_set_completeness(&generated.completeness)?;
    let generator_payload = candidate_completeness_signing_payload_v3(&generated.completeness)?;
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        request.generator_evidence,
        &generator_payload,
        now,
    )?;
    if generator.principal().principal_id != request.generation_policy.generator_id {
        return Err(GovernedProposalError::Binding("generator identity"));
    }
    verify_signed_role_separation(&generator, &source, now)?;
    let generator_authentication_digest = attestation_digest(request.generator_evidence);

    let evaluation_bundle = &request.evaluation;
    let evaluator_id = evaluation_bundle.evaluator.principal_id.clone();
    if evaluation_bundle.candidate_id != request.set_id
        || evaluation_bundle.baseline_id != binding.selected_artifact_id
        || evaluation_bundle.objective_digest != binding.objective_digest
        || evaluation_bundle.dataset_digest != binding.dataset_digest
        || &evaluation_bundle.generator != generator.principal()
    {
        return Err(GovernedProposalError::Binding("independent evaluation binding"));
    }
    let evaluation = decide_with_signed_evidence_v2(
        request.evaluation,
        request.metric_roles,
        request.evaluation_evidence,
        verifier,
        now,
    )?;
    if evaluation.decision.disposition
        != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        return Err(GovernedProposalError::EvaluationIneligible(
            evaluation.decision.disposition,
        ));
    }

    let admission_digest = digest_admission(
        artifact_registry_head_digest,
        completeness_digest,
        source_authentication_digest,
        generator_authentication_digest,
        &evaluation,
        verifier.trust_digest(),
    );
    let proposal = propose_v2(ParameterProposalRequestV2 {
        proposal_id: request.proposal_id,
        proposer_id: generator.principal().principal_id.clone(),
        evaluator_id,
        selected_artifact_digest: binding.selected_artifact_digest,
        window: binding.window.clone(),
        baseline_generation: binding.baseline_generation,
        candidate_generation: binding.candidate_generation,
        dataset_digest: binding.dataset_digest,
        update_rule_digest: binding.update_rule_digest,
        modulator_digest: binding.modulator_digest,
        modulator_broadcast_digest: binding.modulator_broadcast_digest,
        eligibility_digest: binding.eligibility_digest,
        evaluation_digest: admission_digest,
        rollback_predecessor_digest: binding.selected_artifact_digest,
        norm_layers: binding.norm_layers.clone(),
        candidates: generated.candidates,
    })?;

    Ok(GovernedParameterProposalV3 {
        proposal,
        completeness: generated.completeness,
        completeness_digest,
        artifact_registry_head_digest,
        source_authentication_digest,
        generator_authentication_digest,
        evaluation,
        admission_digest,
    })
}

fn validate_generation_inputs(
    binding: &ParameterEvidenceBindingV3,
    policy: &ParameterGenerationPolicyV3,
    state_digest: Digest32,
) -> Result<(), GovernedProposalError> {
    if state_digest.is_zero()
        || binding.selected_artifact_digest.is_zero()
        || binding.objective_digest.is_zero()
        || binding.window.window_digest.is_zero()
        || binding.dataset_digest.is_zero()
        || binding.update_rule_digest.is_zero()
        || binding.modulator_digest.is_zero()
        || binding.modulator_broadcast_digest.is_zero()
        || binding.eligibility_digest.is_zero()
    {
        return Err(GovernedProposalError::Binding("empty generator input digest"));
    }
    if binding.opportunities.len() > MAX_PARAMETER_DELTAS {
        return Err(GovernedProposalError::Generator("opportunity limit"));
    }
    if !(1..=MAX_NORM_LAYERS).contains(&binding.norm_layers.len()) {
        return Err(GovernedProposalError::Generator("norm layer limit"));
    }
    if policy.learning_rate == FixedQ32::ZERO
        || policy.generator_code_digest.is_zero()
        || policy.grammar_digest.is_zero()
        || policy.hard_filter_digest.is_zero()
        || policy.truncation_digest.is_zero()
    {
        return Err(GovernedProposalError::Generator("invalid generator policy"));
    }
    if policy.candidate_scales_ppm.is_empty()
        || policy.candidate_scales_ppm.len() > MAX_GENERATED_SCALES
        || policy
            .candidate_scales_ppm
            .iter()
            .any(|scale| *scale == 0 || *scale > 1_000_000)
    {
        return Err(GovernedProposalError::Generator("candidate scale profile"));
    }
    Ok(())
}

fn scale_fixed(value: FixedQ32, ppm: u32) -> Result<FixedQ32, GovernedProposalError> {
    let raw = i128::from(value.raw())
        .checked_mul(i128::from(ppm))
        .ok_or(GovernedProposalError::Arithmetic)?
        / PPM_DENOMINATOR;
    Ok(FixedQ32::from_raw(
        i64::try_from(raw).map_err(|_| GovernedProposalError::Arithmetic)?,
    ))
}

fn project_into_trust_region(
    mut deltas: Vec<ParameterDeltaV2>,
    norm_layers: &[LayerNormDenominatorV2],
) -> Result<Vec<ParameterDeltaV2>, GovernedProposalError> {
    for _ in 0..64 {
        if candidate_within_trust_region(&deltas, norm_layers)? {
            return Ok(deltas);
        }
        for delta in &mut deltas {
            delta.delta = FixedQ32::from_raw(delta.delta.raw() / 2);
        }
        deltas.retain(|delta| delta.delta != FixedQ32::ZERO);
        if deltas.is_empty() {
            return Ok(deltas);
        }
    }
    Err(GovernedProposalError::Arithmetic)
}

fn candidate_within_trust_region(
    deltas: &[ParameterDeltaV2],
    norm_layers: &[LayerNormDenominatorV2],
) -> Result<bool, GovernedProposalError> {
    let mut denominators = BTreeMap::new();
    let mut global_baseline = 0u128;
    for layer in norm_layers {
        if layer.baseline_squared_l2_raw_q64 == 0
            || denominators
                .insert(layer.layer_id.clone(), layer.baseline_squared_l2_raw_q64)
                .is_some()
        {
            return Err(GovernedProposalError::Generator("invalid norm profile"));
        }
        global_baseline = global_baseline
            .checked_add(layer.baseline_squared_l2_raw_q64)
            .ok_or(GovernedProposalError::Arithmetic)?;
    }
    let mut squared_by_layer: BTreeMap<StableId, u128> = denominators
        .keys()
        .cloned()
        .map(|layer_id| (layer_id, 0))
        .collect();
    let mut parameters = BTreeSet::new();
    for delta in deltas {
        if !parameters.insert(delta.parameter_id.clone()) {
            return Err(GovernedProposalError::Generator("duplicate parameter opportunity"));
        }
        let Some(total) = squared_by_layer.get_mut(&delta.layer_id) else {
            return Err(GovernedProposalError::Generator("missing norm layer"));
        };
        let raw = i128::from(delta.delta.raw());
        let squared = u128::try_from(raw * raw).map_err(|_| GovernedProposalError::Arithmetic)?;
        *total = total
            .checked_add(squared)
            .ok_or(GovernedProposalError::Arithmetic)?;
    }
    let mut global_delta = 0u128;
    for (layer_id, baseline) in &denominators {
        let delta = squared_by_layer.get(layer_id).copied().unwrap_or(0);
        if !within_relative_limit(delta, *baseline, PER_LAYER_MAX_RELATIVE_PPM)? {
            return Ok(false);
        }
        global_delta = global_delta
            .checked_add(delta)
            .ok_or(GovernedProposalError::Arithmetic)?;
    }
    within_relative_limit(global_delta, global_baseline, GLOBAL_MAX_RELATIVE_PPM)
        .map_err(GovernedProposalError::Proposal)
}

fn digest_candidate_set(
    candidates: &[ParameterCandidateRequestV2],
) -> Result<Digest32, GovernedProposalError> {
    let mut bytes = b"hepta.plasticity.generated-candidate-set.v3\0".to_vec();
    push_len(&mut bytes, candidates.len())?;
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.push(match candidate.kind {
            ParameterCandidateKindV2::NoChange => 0,
            ParameterCandidateKindV2::Update => 1,
        });
        push_len(&mut bytes, candidate.parameter_deltas.len())?;
        for delta in &candidate.parameter_deltas {
            push_id(&mut bytes, &delta.layer_id)?;
            push_id(&mut bytes, &delta.parameter_id)?;
            bytes.extend_from_slice(&delta.delta.raw().to_be_bytes());
            bytes.extend_from_slice(&delta.lower_bound.raw().to_be_bytes());
            bytes.extend_from_slice(&delta.upper_bound.raw().to_be_bytes());
            bytes.extend_from_slice(delta.evidence_digest.as_array());
        }
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_candidate_order(
    candidates: &[ParameterCandidateRequestV2],
) -> Result<Digest32, GovernedProposalError> {
    let mut bytes = b"hepta.plasticity.generated-candidate-order.v3\0".to_vec();
    push_len(&mut bytes, candidates.len())?;
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn attestation_digest(evidence: &SignedLearningEvidenceV1) -> Digest32 {
    let mut bytes = b"hepta.plasticity.signed-attestation.v3\0".to_vec();
    bytes.extend_from_slice(Digest32::of_bytes(&evidence.signing_bytes()).as_array());
    bytes.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&bytes)
}

fn digest_admission(
    artifact_registry_head_digest: Digest32,
    completeness_digest: Digest32,
    source_authentication_digest: Digest32,
    generator_authentication_digest: Digest32,
    evaluation: &SignedEvaluationDecisionV1,
    trust_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.plasticity.governed-admission.v3\0".to_vec();
    for digest in [
        artifact_registry_head_digest,
        completeness_digest,
        source_authentication_digest,
        generator_authentication_digest,
        evaluation.decision.evidence_digest,
        evaluation.authentication_digest,
        evaluation.trust_digest,
        trust_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn stable_id(value: &str) -> Result<StableId, GovernedProposalError> {
    StableId::new(value.to_owned()).map_err(|_| GovernedProposalError::Generator("candidate id"))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), GovernedProposalError> {
    let raw = value.as_str().as_bytes();
    let len = u32::try_from(raw.len()).map_err(|_| GovernedProposalError::Arithmetic)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), GovernedProposalError> {
    let value = u32::try_from(value).map_err(|_| GovernedProposalError::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}
