//! Authenticated, current-lineage admission for generated parameter proposals.
//!
//! This layer closes the trust gap intentionally left by V2. It resolves the
//! evidence bytes named by the proposal, verifies the current artifact lineage,
//! authenticates generator/observer/evaluator roles against host-owned trust,
//! and consumes an independently signed evaluation. The result is still only a
//! proposal requiring later selection/acceptance; it grants no mutation authority.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::SignedEvaluationDecisionV1;
use codex_hepta_intelligence_eval::SignedEvaluationError;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_ledger::CausalV2Error;
use codex_hepta_learning_ledger::DatasetReceiptError;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_learning_ledger::verify_independent_roles;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::Error as ProposalError;
use crate::GeneratedParameterCandidateSetV3;
use crate::LayerNormDenominatorV2;
use crate::ParameterCandidateKindV2;
use crate::ParameterGeneratorErrorV3;
use crate::ParameterGeneratorRequestV3;
use crate::ParameterProposalRequestV2;
use crate::ParameterProposalV2;
use crate::ProposalWindowV2;
use crate::generate_parameter_candidates_v3;
use crate::generator_attestation_payload_v3;
use crate::propose_v2;

const MAX_RESOLVED_EVIDENCE_BYTES: usize = 8 * 1024 * 1024;
const MAX_SINGLE_EVIDENCE_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GovernedParameterProposalRequestV3 {
    pub selected_artifact_id: StableId,
    pub window: ProposalWindowV2,
    pub update_rule_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub eligibility_digest: Digest32,
    /// Digest of the exact canonical artifact-bound norm-profile payload.
    pub norm_profile_evidence_digest: Digest32,
    pub norm_layers: Vec<LayerNormDenominatorV2>,
    pub generator: ParameterGeneratorRequestV3,
    pub dataset: DatasetSnapshotReceiptV3,
    pub evaluation: IndependentEvaluationBundleV1,
    pub metric_roles: Vec<MetricRoleContractV2>,
}

/// Resolver is a host boundary. Production callers implement it over their
/// authoritative evidence stores; missing/unavailable evidence fails closed.
pub trait PlasticityEvidenceResolverV3 {
    fn resolve(
        &mut self,
        digest: Digest32,
    ) -> Result<Option<Vec<u8>>, PlasticityEvidenceResolveErrorV3>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityEvidenceResolveErrorV3 {
    Unavailable,
    Corrupt,
}

impl fmt::Display for PlasticityEvidenceResolveErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for PlasticityEvidenceResolveErrorV3 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedGovernedParameterProposalV3 {
    request: GovernedParameterProposalRequestV3,
    generated: GeneratedParameterCandidateSetV3,
    selected_artifact_digest: Digest32,
    baseline_generation: Generation,
    objective_digest: Digest32,
    artifact_registry_head: Digest32,
    evaluation_request_digest: Digest32,
    required_evidence_digests: Vec<Digest32>,
    generator_payload: Vec<u8>,
    observer_payload: Vec<u8>,
}

impl PreparedGovernedParameterProposalV3 {
    #[must_use]
    pub fn generator_payload(&self) -> &[u8] {
        &self.generator_payload
    }

    #[must_use]
    pub fn observer_payload(&self) -> &[u8] {
        &self.observer_payload
    }

    #[must_use]
    pub fn generated(&self) -> &GeneratedParameterCandidateSetV3 {
        &self.generated
    }

    #[must_use]
    pub fn evaluation_request_digest(&self) -> Digest32 {
        self.evaluation_request_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GovernedParameterProposalAttestationsV3 {
    /// Generator signs `PreparedGovernedParameterProposalV3::generator_payload`.
    pub generator: SignedLearningEvidenceV1,
    /// Independent observer signs `PreparedGovernedParameterProposalV3::observer_payload`.
    pub observer: SignedLearningEvidenceV1,
    /// Existing learning.eval signed independent-evaluation evidence.
    pub evaluation: SignedEvaluationEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GovernedParameterProposalV3 {
    pub proposal: ParameterProposalV2,
    pub selected_artifact_id: StableId,
    pub objective_digest: Digest32,
    pub artifact_registry_head: Digest32,
    pub generator_input_digest: Digest32,
    pub generated_candidate_set_digest: Digest32,
    pub evidence_manifest_digest: Digest32,
    pub evaluation: SignedEvaluationDecisionV1,
    pub governance_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Debug)]
pub enum GovernedParameterProposalErrorV3 {
    ArtifactMissing,
    ArtifactIneligible,
    ArtifactKind,
    ArtifactBinding(&'static str),
    EvidenceMissing(Digest32),
    EvidenceDigestMismatch(Digest32),
    EvidenceLimit,
    EvidenceResolver(PlasticityEvidenceResolveErrorV3),
    Generator(ParameterGeneratorErrorV3),
    Proposal(ProposalError),
    Dataset(DatasetReceiptError),
    Evidence(SignedEvidenceError),
    Evaluation(SignedEvaluationError),
    Roles(CausalV2Error),
    ControllerCollision,
    EvaluationBinding(&'static str),
    EvaluationIneligible(IndependentEvaluationDispositionV1),
    StalePreparedContext,
    Arithmetic,
}

impl fmt::Display for GovernedParameterProposalErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for GovernedParameterProposalErrorV3 {}
impl From<PlasticityEvidenceResolveErrorV3> for GovernedParameterProposalErrorV3 {
    fn from(value: PlasticityEvidenceResolveErrorV3) -> Self {
        Self::EvidenceResolver(value)
    }
}
impl From<ParameterGeneratorErrorV3> for GovernedParameterProposalErrorV3 {
    fn from(value: ParameterGeneratorErrorV3) -> Self {
        Self::Generator(value)
    }
}
impl From<ProposalError> for GovernedParameterProposalErrorV3 {
    fn from(value: ProposalError) -> Self {
        Self::Proposal(value)
    }
}
impl From<DatasetReceiptError> for GovernedParameterProposalErrorV3 {
    fn from(value: DatasetReceiptError) -> Self {
        Self::Dataset(value)
    }
}
impl From<SignedEvidenceError> for GovernedParameterProposalErrorV3 {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}
impl From<SignedEvaluationError> for GovernedParameterProposalErrorV3 {
    fn from(value: SignedEvaluationError) -> Self {
        Self::Evaluation(value)
    }
}
impl From<CausalV2Error> for GovernedParameterProposalErrorV3 {
    fn from(value: CausalV2Error) -> Self {
        Self::Roles(value)
    }
}

/// Canonical payload that must exist in the evidence resolver under
/// `norm_profile_evidence_digest`.
pub fn artifact_norm_profile_payload_v3(
    artifact_id: &StableId,
    artifact_digest: Digest32,
    layers: &[LayerNormDenominatorV2],
) -> Result<Vec<u8>, GovernedParameterProposalErrorV3> {
    let mut canonical = layers.to_vec();
    canonical.sort_by(|left, right| left.layer_id.cmp(&right.layer_id));
    if canonical.is_empty()
        || canonical.windows(2).any(|pair| pair[0].layer_id == pair[1].layer_id)
        || canonical
            .iter()
            .any(|layer| layer.baseline_squared_l2_raw_q64 == 0)
    {
        return Err(GovernedParameterProposalErrorV3::ArtifactBinding(
            "norm profile",
        ));
    }
    let mut bytes = b"hepta.plasticity.artifact-norm-profile.v3".to_vec();
    push_id(&mut bytes, artifact_id)?;
    bytes.extend_from_slice(artifact_digest.as_array());
    push_len(&mut bytes, canonical.len())?;
    for layer in canonical {
        push_id(&mut bytes, &layer.layer_id)?;
        bytes.extend_from_slice(&layer.baseline_squared_l2_raw_q64.to_be_bytes());
    }
    Ok(bytes)
}

/// Resolve all named evidence and freeze the exact current artifact/evaluation
/// context that the generator and observer must sign.
pub fn prepare_governed_parameter_proposal_v3<R: PlasticityEvidenceResolverV3>(
    request: GovernedParameterProposalRequestV3,
    artifacts: &ArtifactRegistry,
    resolver: &mut R,
    now: u64,
) -> Result<PreparedGovernedParameterProposalV3, GovernedParameterProposalErrorV3> {
    verify_dataset_snapshot_receipt_v3(&request.dataset, now)?;
    let manifest = artifacts
        .manifest(&request.selected_artifact_id)
        .ok_or(GovernedParameterProposalErrorV3::ArtifactMissing)?;
    if !artifacts.is_eligible(&request.selected_artifact_id) {
        return Err(GovernedParameterProposalErrorV3::ArtifactIneligible);
    }
    if manifest.kind != ArtifactKind::Parameters {
        return Err(GovernedParameterProposalErrorV3::ArtifactKind);
    }
    if manifest.objective_digest != request.dataset.snapshot.objective_digest {
        return Err(GovernedParameterProposalErrorV3::ArtifactBinding(
            "objective",
        ));
    }
    let artifact_registry_head = artifacts.snapshot().head_digest;
    if artifact_registry_head.is_zero() {
        return Err(GovernedParameterProposalErrorV3::ArtifactBinding(
            "registry head",
        ));
    }

    let generated = generate_parameter_candidates_v3(request.generator.clone())?;
    let target_candidate = generated
        .candidates
        .iter()
        .find(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
        .or_else(|| generated.candidates.first())
        .ok_or(GovernedParameterProposalErrorV3::EvaluationBinding(
            "empty generated set",
        ))?;
    if request.evaluation.baseline_id != request.selected_artifact_id
        || request.evaluation.candidate_id != target_candidate.candidate_id
        || request.evaluation.objective_digest != manifest.objective_digest
        || request.evaluation.dataset_digest != request.dataset.snapshot.dataset_digest
    {
        return Err(GovernedParameterProposalErrorV3::EvaluationBinding(
            "artifact/candidate/dataset/objective",
        ));
    }

    let evaluation_payload = evaluation_signing_payload_v2(&request.evaluation, &request.metric_roles)
        .map_err(|error| GovernedParameterProposalErrorV3::Evaluation(error.into()))?;
    let evaluation_request_digest = Digest32::of_bytes(&evaluation_payload);

    let expected_norm_payload = artifact_norm_profile_payload_v3(
        &request.selected_artifact_id,
        manifest.content_digest,
        &request.norm_layers,
    )?;
    if Digest32::of_bytes(&expected_norm_payload) != request.norm_profile_evidence_digest {
        return Err(GovernedParameterProposalErrorV3::ArtifactBinding(
            "norm profile evidence digest",
        ));
    }

    let mut required = BTreeSet::from([
        request.window.window_digest,
        request.update_rule_digest,
        request.modulator_digest,
        request.modulator_broadcast_digest,
        request.eligibility_digest,
        request.norm_profile_evidence_digest,
    ]);
    for signal in &request.generator.signals {
        required.insert(signal.evidence_digest);
    }
    if required.iter().any(|digest| digest.is_zero()) {
        return Err(GovernedParameterProposalErrorV3::ArtifactBinding(
            "empty evidence digest",
        ));
    }

    let mut total_bytes = 0_usize;
    for digest in &required {
        let material = resolver
            .resolve(*digest)?
            .ok_or(GovernedParameterProposalErrorV3::EvidenceMissing(*digest))?;
        if material.is_empty() || material.len() > MAX_SINGLE_EVIDENCE_BYTES {
            return Err(GovernedParameterProposalErrorV3::EvidenceLimit);
        }
        total_bytes = total_bytes
            .checked_add(material.len())
            .filter(|size| *size <= MAX_RESOLVED_EVIDENCE_BYTES)
            .ok_or(GovernedParameterProposalErrorV3::EvidenceLimit)?;
        if Digest32::of_bytes(&material) != *digest {
            return Err(GovernedParameterProposalErrorV3::EvidenceDigestMismatch(
                *digest,
            ));
        }
        if *digest == request.norm_profile_evidence_digest && material != expected_norm_payload {
            return Err(GovernedParameterProposalErrorV3::ArtifactBinding(
                "norm profile material",
            ));
        }
    }
    let required_evidence_digests = required.into_iter().collect::<Vec<_>>();
    let generator_payload = generator_attestation_payload_v3(&generated);
    let observer_payload = observer_payload(
        &request,
        &generated,
        manifest.content_digest,
        manifest.generation,
        manifest.objective_digest,
        artifact_registry_head,
        evaluation_request_digest,
        &required_evidence_digests,
    )?;

    Ok(PreparedGovernedParameterProposalV3 {
        request,
        generated,
        selected_artifact_digest: manifest.content_digest,
        baseline_generation: manifest.generation,
        objective_digest: manifest.objective_digest,
        artifact_registry_head,
        evaluation_request_digest,
        required_evidence_digests,
        generator_payload,
        observer_payload,
    })
}

/// Re-resolve the prepared context, authenticate all three roles, consume the
/// signed independent evaluation, then produce the legacy-compatible V2 core.
pub fn admit_governed_parameter_proposal_v3<R: PlasticityEvidenceResolverV3>(
    prepared: PreparedGovernedParameterProposalV3,
    attestations: &GovernedParameterProposalAttestationsV3,
    artifacts: &ArtifactRegistry,
    resolver: &mut R,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<GovernedParameterProposalV3, GovernedParameterProposalErrorV3> {
    let refreshed = prepare_governed_parameter_proposal_v3(
        prepared.request.clone(),
        artifacts,
        resolver,
        now,
    )?;
    if refreshed != prepared {
        return Err(GovernedParameterProposalErrorV3::StalePreparedContext);
    }

    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &attestations.generator,
        prepared.generator_payload(),
        now,
    )?;
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &attestations.observer,
        prepared.observer_payload(),
        now,
    )?;
    verify_signed_role_separation(&generator, &observer, now)?;

    let evaluation_payload = evaluation_signing_payload_v2(
        &prepared.request.evaluation,
        &prepared.request.metric_roles,
    )
    .map_err(|error| GovernedParameterProposalErrorV3::Evaluation(error.into()))?;
    let evaluation_generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &attestations.evaluation.generator_plan,
        prepared.request.evaluation.frozen_plan.plan_digest.as_array(),
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &attestations.evaluation.evaluator_bundle,
        &evaluation_payload,
        now,
    )?;
    verify_signed_role_separation(&evaluation_generator, &evaluator, now)?;
    verify_independent_roles(observer.principal(), evaluator.principal(), now)?;
    if observer.controller_id() == evaluator.controller_id() {
        return Err(GovernedParameterProposalErrorV3::ControllerCollision);
    }
    if generator.principal() != evaluation_generator.principal()
        || generator.controller_id() != evaluation_generator.controller_id()
        || generator.principal() != &prepared.request.evaluation.generator
        || evaluator.principal() != &prepared.request.evaluation.evaluator
    {
        return Err(GovernedParameterProposalErrorV3::EvaluationBinding(
            "authenticated roles",
        ));
    }

    let evaluation = decide_with_signed_evidence_v2(
        prepared.request.evaluation.clone(),
        prepared.request.metric_roles.clone(),
        &attestations.evaluation,
        verifier,
        now,
    )?;
    if evaluation.decision.disposition
        != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        return Err(GovernedParameterProposalErrorV3::EvaluationIneligible(
            evaluation.decision.disposition,
        ));
    }

    let candidate_generation = prepared
        .baseline_generation
        .next()
        .map_err(|_| GovernedParameterProposalErrorV3::Arithmetic)?;
    let proposal = propose_v2(ParameterProposalRequestV2 {
        proposal_id: prepared.request.generator.proposal_id.clone(),
        proposer_id: generator.principal().principal_id.clone(),
        evaluator_id: evaluator.principal().principal_id.clone(),
        selected_artifact_digest: prepared.selected_artifact_digest,
        window: prepared.request.window.clone(),
        baseline_generation: prepared.baseline_generation,
        candidate_generation,
        dataset_digest: prepared.request.dataset.snapshot.dataset_digest,
        update_rule_digest: prepared.request.update_rule_digest,
        modulator_digest: prepared.request.modulator_digest,
        modulator_broadcast_digest: prepared.request.modulator_broadcast_digest,
        eligibility_digest: prepared.request.eligibility_digest,
        evaluation_digest: evaluation.decision.evidence_digest,
        rollback_predecessor_digest: prepared.selected_artifact_digest,
        norm_layers: prepared.request.norm_layers.clone(),
        candidates: prepared.generated.candidates.clone(),
    })?;

    let evidence_manifest_digest = Digest32::of_bytes(&prepared.observer_payload);
    let governance_digest = governance_digest(
        &proposal,
        &prepared,
        &evaluation,
        verifier.trust_digest(),
        evidence_manifest_digest,
    );
    Ok(GovernedParameterProposalV3 {
        proposal,
        selected_artifact_id: prepared.request.selected_artifact_id,
        objective_digest: prepared.objective_digest,
        artifact_registry_head: prepared.artifact_registry_head,
        generator_input_digest: prepared.generated.generator_input_digest,
        generated_candidate_set_digest: prepared.generated.candidate_set_digest,
        evidence_manifest_digest,
        evaluation,
        governance_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn observer_payload(
    request: &GovernedParameterProposalRequestV3,
    generated: &GeneratedParameterCandidateSetV3,
    artifact_digest: Digest32,
    generation: Generation,
    objective_digest: Digest32,
    registry_head: Digest32,
    evaluation_request_digest: Digest32,
    required: &[Digest32],
) -> Result<Vec<u8>, GovernedParameterProposalErrorV3> {
    let mut bytes = b"hepta.plasticity.evidence-manifest.v3".to_vec();
    push_id(&mut bytes, &request.selected_artifact_id)?;
    bytes.extend_from_slice(artifact_digest.as_array());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(registry_head.as_array());
    push_id(&mut bytes, &request.window.window_id)?;
    bytes.extend_from_slice(request.window.window_digest.as_array());
    bytes.extend_from_slice(request.dataset.snapshot.dataset_digest.as_array());
    bytes.extend_from_slice(request.update_rule_digest.as_array());
    bytes.extend_from_slice(request.modulator_digest.as_array());
    bytes.extend_from_slice(request.modulator_broadcast_digest.as_array());
    bytes.extend_from_slice(request.eligibility_digest.as_array());
    bytes.extend_from_slice(request.norm_profile_evidence_digest.as_array());
    bytes.extend_from_slice(generated.generator_input_digest.as_array());
    bytes.extend_from_slice(generated.candidate_set_digest.as_array());
    bytes.extend_from_slice(evaluation_request_digest.as_array());
    push_len(&mut bytes, required.len())?;
    for digest in required {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(bytes)
}

fn governance_digest(
    proposal: &ParameterProposalV2,
    prepared: &PreparedGovernedParameterProposalV3,
    evaluation: &SignedEvaluationDecisionV1,
    trust_digest: Digest32,
    evidence_manifest_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.plasticity.governed-proposal.v3".to_vec();
    for digest in [
        proposal.proposal_digest,
        prepared.artifact_registry_head,
        prepared.generated.generator_input_digest,
        prepared.generated.candidate_set_digest,
        evidence_manifest_digest,
        prepared.evaluation_request_digest,
        evaluation.decision.evidence_digest,
        evaluation.authentication_digest,
        trust_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), GovernedParameterProposalErrorV3> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| GovernedParameterProposalErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(
    bytes: &mut Vec<u8>,
    value: usize,
) -> Result<(), GovernedParameterProposalErrorV3> {
    let length = u32::try_from(value).map_err(|_| GovernedParameterProposalErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    Ok(())
}
