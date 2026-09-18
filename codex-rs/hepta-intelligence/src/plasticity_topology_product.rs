//! Authenticated product composition for topology plasticity proposals.
//!
//! The adapter authenticates generator/observer/evaluator roles, requires an
//! independent evaluation for every structural update candidate, verifies typed
//! writer-handoff plans, durably records the proposal, and commits an external
//! rollback anchor. It deliberately exposes no topology apply operation.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_intelligence_eval::{
    IndependentEvaluationDispositionV1, SignedEvaluationError, decide_with_signed_evidence_v2,
    evaluation_signing_payload_v2,
};
use codex_hepta_learning_ledger::{
    LearningEvidenceRoleV1, LearningEvidenceVerifierV1, SignedEvidenceError,
    SignedLearningEvidenceV1, verify_signed_role_separation,
    verify_verified_role_separation,
};
use codex_hepta_plasticity::{
    AppendDisposition, DurableRegistryAnchorV1, DurableTopologyProposalAppendReceiptV1,
    DurableTopologyProposalRegistryError, DurableTopologyProposalRegistryV2,
    TopologyCandidateKindV2, TopologyChangeV2, TopologyGovernanceErrorV1,
    TopologyMutationPolicyErrorV1, TopologyMutationPolicyV1, TopologyProposalRequestV2,
    TopologyProposalV2, TopologyWriterHandoffV1, propose_topology_v2,
    verify_topology_changes_against_policy_v1, verify_topology_mutation_policy_v1,
    verify_topology_writer_handoffs_v1,
};
use codex_hepta_types::{Digest32, Generation, StableId};

use crate::{
    CandidateEvaluationAdmissionV1, PlasticityAnchorCommitterV1, PlasticityWriterStateV1,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyPlasticityAdmissionEvidenceV1 {
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub artifact_registry_binding: Digest32,
    pub artifact_registry_head_digest: Digest32,
    pub qualification_evidence_head_digest: Digest32,
    pub topology_policy_digest: Digest32,
    pub window: codex_hepta_plasticity::ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub dataset_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyPlasticityProductRequestV1 {
    pub proposal_id: StableId,
    pub topology_policy: TopologyMutationPolicyV1,
    pub changes: Vec<TopologyChangeV2>,
    pub handoffs: Vec<TopologyWriterHandoffV1>,
    pub generator_attestation: SignedLearningEvidenceV1,
    pub admission: TopologyPlasticityAdmissionEvidenceV1,
    pub admission_attestation: SignedLearningEvidenceV1,
    pub evaluations: Vec<CandidateEvaluationAdmissionV1>,
    pub expected_registry_predecessor: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyPlasticityProductReceiptV1 {
    pub proposal: TopologyProposalV2,
    pub handoff_set_digest: Digest32,
    pub registry: DurableTopologyProposalAppendReceiptV1,
    pub committed_registry_anchor: DurableRegistryAnchorV1,
    pub generator_authentication_digest: Digest32,
    pub admission_authentication_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub composition_digest: Digest32,
}

#[derive(Debug)]
pub enum TopologyPlasticityProductErrorV1 {
    Binding(&'static str),
    GeneratorEvidence(SignedEvidenceError),
    AdmissionEvidence(SignedEvidenceError),
    Evaluation(SignedEvaluationError),
    Ineligible(IndependentEvaluationDispositionV1),
    MissingEvaluation(String),
    DuplicateEvaluation(String),
    UnexpectedEvaluation(String),
    EvaluatorMismatch,
    NoUpdateCandidate,
    Policy(TopologyMutationPolicyErrorV1),
    Proposal(codex_hepta_plasticity::TopologyProposalErrorV2),
    Governance(TopologyGovernanceErrorV1),
    Registry(DurableTopologyProposalRegistryError),
    AnchorPersistenceFailed,
}
impl fmt::Display for TopologyPlasticityProductErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for TopologyPlasticityProductErrorV1 {}
impl From<TopologyMutationPolicyErrorV1> for TopologyPlasticityProductErrorV1 {
    fn from(value: TopologyMutationPolicyErrorV1) -> Self {
        Self::Policy(value)
    }
}
impl From<codex_hepta_plasticity::TopologyProposalErrorV2> for TopologyPlasticityProductErrorV1 {
    fn from(value: codex_hepta_plasticity::TopologyProposalErrorV2) -> Self {
        Self::Proposal(value)
    }
}
impl From<TopologyGovernanceErrorV1> for TopologyPlasticityProductErrorV1 {
    fn from(value: TopologyGovernanceErrorV1) -> Self {
        Self::Governance(value)
    }
}
impl From<DurableTopologyProposalRegistryError> for TopologyPlasticityProductErrorV1 {
    fn from(value: DurableTopologyProposalRegistryError) -> Self {
        Self::Registry(value)
    }
}

pub struct AnchoredTopologyPlasticityWriterV1 {
    registry: DurableTopologyProposalRegistryV2,
    registry_scope_digest: Digest32,
    writer_fence: u64,
    state: PlasticityWriterStateV1,
}
impl AnchoredTopologyPlasticityWriterV1 {
    pub fn bootstrap_new(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableTopologyProposalRegistryError> {
        Ok(Self {
            registry: DurableTopologyProposalRegistryV2::open_bootstrap_empty(
                file,
                registry_scope_digest,
                writer_fence,
                maximum_records,
            )?,
            registry_scope_digest,
            writer_fence,
            state: PlasticityWriterStateV1::Healthy,
        })
    }

    pub fn reopen_anchored(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: DurableRegistryAnchorV1,
    ) -> Result<Self, DurableTopologyProposalRegistryError> {
        let registry = DurableTopologyProposalRegistryV2::open_anchored(
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
            anchor,
        )?;
        if registry.current_anchor()? != Some(anchor) {
            // Preserve a valid later tail for explicit reconciliation, but never
            // let the product writer treat unacknowledged structural proposals as
            // a healthy externally acknowledged head.
            return Err(DurableTopologyProposalRegistryError::Conflict);
        }
        Ok(Self {
            registry,
            registry_scope_digest,
            writer_fence,
            state: PlasticityWriterStateV1::Healthy,
        })
    }

    #[must_use]
    pub const fn state(&self) -> PlasticityWriterStateV1 {
        self.state
    }

    pub fn record_count(&self) -> Result<usize, DurableTopologyProposalRegistryError> {
        if self.state != PlasticityWriterStateV1::Healthy {
            return Err(DurableTopologyProposalRegistryError::Poisoned);
        }
        self.registry.record_count()
    }
}

pub fn topology_generation_signing_payload_v1(
    admission: &TopologyPlasticityAdmissionEvidenceV1,
    changes: &[TopologyChangeV2],
    handoffs: &[TopologyWriterHandoffV1],
) -> Result<Vec<u8>, TopologyPlasticityProductErrorV1> {
    validate_admission(admission)?;
    let mut changes = changes.to_vec();
    changes.sort();
    let mut handoffs = handoffs.to_vec();
    handoffs.sort_by(|left, right| {
        left.module_id
            .cmp(&right.module_id)
            .then_with(|| left.operation.cmp(&right.operation))
            .then_with(|| left.handoff_digest.cmp(&right.handoff_digest))
    });
    let mut bytes = b"hepta.intelligence.topology-plasticity-generation.v1\0".to_vec();
    push_admission(&mut bytes, admission);
    push_len(&mut bytes, changes.len())?;
    for change in &changes {
        push_id(&mut bytes, &change.module_id);
        bytes.push(match change.operation {
            codex_hepta_plasticity::TopologyOperationV2::Add => 0,
            codex_hepta_plasticity::TopologyOperationV2::Remove => 1,
            codex_hepta_plasticity::TopologyOperationV2::Replace => 2,
            codex_hepta_plasticity::TopologyOperationV2::Split => 3,
            codex_hepta_plasticity::TopologyOperationV2::Merge => 4,
            codex_hepta_plasticity::TopologyOperationV2::Rewire => 5,
            codex_hepta_plasticity::TopologyOperationV2::Retire => 6,
        });
        push_optional_digest(&mut bytes, change.predecessor_digest);
        push_optional_digest(&mut bytes, change.candidate_digest);
        for digest in [
            change.migration_digest,
            change.rollback_digest,
            change.writer_handoff_digest,
            change.evidence_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
    }
    push_len(&mut bytes, handoffs.len())?;
    for handoff in &handoffs {
        push_id(&mut bytes, &handoff.module_id);
        bytes.extend_from_slice(handoff.handoff_digest.as_array());
    }
    Ok(bytes)
}

pub fn topology_admission_signing_payload_v1(
    admission: &TopologyPlasticityAdmissionEvidenceV1,
) -> Result<Vec<u8>, TopologyPlasticityProductErrorV1> {
    validate_admission(admission)?;
    let mut bytes = b"hepta.intelligence.topology-plasticity-admission.v1\0".to_vec();
    push_admission(&mut bytes, admission);
    Ok(bytes)
}

pub fn propose_authenticated_topology_plasticity_v1(
    request: TopologyPlasticityProductRequestV1,
    verifier: &LearningEvidenceVerifierV1,
    writer: &mut AnchoredTopologyPlasticityWriterV1,
    anchor_committer: &mut impl PlasticityAnchorCommitterV1,
    now: u64,
) -> Result<TopologyPlasticityProductReceiptV1, TopologyPlasticityProductErrorV1> {
    use TopologyPlasticityProductErrorV1 as E;
    if writer.state != PlasticityWriterStateV1::Healthy {
        return Err(E::Registry(DurableTopologyProposalRegistryError::Poisoned));
    }
    validate_admission(&request.admission)?;
    verify_topology_mutation_policy_v1(&request.topology_policy)?;
    if request.topology_policy.policy_digest != request.admission.topology_policy_digest {
        return Err(E::Binding("topology policy digest"));
    }
    verify_topology_changes_against_policy_v1(
        request.admission.selected_artifact_digest,
        &request.changes,
        &request.topology_policy,
    )?;
    let generator_payload = topology_generation_signing_payload_v1(
        &request.admission,
        &request.changes,
        &request.handoffs,
    )?;
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &request.generator_attestation,
            &generator_payload,
            now,
        )
        .map_err(E::GeneratorEvidence)?;
    let admission_payload = topology_admission_signing_payload_v1(&request.admission)?;
    let observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &request.admission_attestation,
            &admission_payload,
            now,
        )
        .map_err(E::AdmissionEvidence)?;
    verify_signed_role_separation(&generator, &observer, now).map_err(E::AdmissionEvidence)?;
    let generator_authentication_digest = attestation_digest(&request.generator_attestation);
    let admission_authentication_digest = attestation_digest(&request.admission_attestation);
    if request.generator_attestation.objective_digest != request.admission.objective_digest
        || request.admission_attestation.objective_digest != request.admission.objective_digest
    {
        return Err(E::Binding("objective trust context"));
    }

    let provisional_evaluator = request
        .evaluations
        .first()
        .map(|value| value.bundle.evaluator.principal_id.clone())
        .ok_or(E::NoUpdateCandidate)?;
    let provisional = propose_topology_v2(TopologyProposalRequestV2 {
        proposal_id: request.proposal_id.clone(),
        proposer_id: generator.principal().principal_id.clone(),
        evaluator_id: provisional_evaluator,
        selected_artifact_digest: request.admission.selected_artifact_digest,
        window: request.admission.window.clone(),
        baseline_generation: request.admission.baseline_generation,
        candidate_generation: request.admission.candidate_generation,
        evaluation_digest: Digest32::of_bytes(&generator_payload),
        rollback_predecessor_digest: request.admission.selected_artifact_digest,
        changes: request.changes.clone(),
    })?;
    let updates = provisional
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
        .collect::<Vec<_>>();
    if updates.is_empty() {
        return Err(E::NoUpdateCandidate);
    }

    let mut evaluations = BTreeMap::new();
    for evaluation in request.evaluations {
        let candidate_id = evaluation.bundle.candidate_id.clone();
        if evaluations.insert(candidate_id.clone(), evaluation).is_some() {
            return Err(E::DuplicateEvaluation(candidate_id.to_string()));
        }
    }
    let mut evaluator_id = None;
    let mut evaluation_binding =
        b"hepta.intelligence.topology-plasticity-evaluations-and-admission.v1\0".to_vec();
    evaluation_binding.extend_from_slice(generator_authentication_digest.as_array());
    evaluation_binding.extend_from_slice(admission_authentication_digest.as_array());
    evaluation_binding.extend_from_slice(request.topology_policy.policy_digest.as_array());
    for candidate in updates {
        let candidate_id = candidate.candidate_id.clone();
        let evaluation = evaluations
            .remove(&candidate_id)
            .ok_or_else(|| E::MissingEvaluation(candidate_id.to_string()))?;
        if evaluation.bundle.baseline_id != request.admission.baseline_id
            || evaluation.bundle.objective_digest != request.admission.objective_digest
            || evaluation.bundle.dataset_digest != request.admission.dataset_digest
            || &evaluation.bundle.generator != generator.principal()
        {
            return Err(E::Binding("candidate evaluation lineage"));
        }
        let this_evaluator = evaluation.bundle.evaluator.principal_id.clone();
        if evaluator_id
            .as_ref()
            .is_some_and(|existing: &StableId| existing != &this_evaluator)
        {
            return Err(E::EvaluatorMismatch);
        }
        evaluator_id.get_or_insert(this_evaluator);
        let evaluator_payload =
            evaluation_signing_payload_v2(&evaluation.bundle, &evaluation.metric_roles)
                .map_err(|error| E::Evaluation(error.into()))?;
        let verified_evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evaluation.evidence.evaluator_bundle,
                &evaluator_payload,
                now,
            )
            .map_err(|error| E::Evaluation(SignedEvaluationError::Evidence(error)))?;
        verify_verified_role_separation(&observer, &verified_evaluator, now)
            .map_err(|error| E::Evaluation(SignedEvaluationError::Evidence(error)))?;
        let decision = decide_with_signed_evidence_v2(
            evaluation.bundle,
            evaluation.metric_roles,
            &evaluation.evidence,
            verifier,
            now,
        )
        .map_err(E::Evaluation)?;
        if decision.decision.disposition
            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(E::Ineligible(decision.decision.disposition));
        }
        push_id(&mut evaluation_binding, &candidate_id);
        evaluation_binding.extend_from_slice(decision.decision.evidence_digest.as_array());
        evaluation_binding.extend_from_slice(decision.authentication_digest.as_array());
        evaluation_binding.extend_from_slice(decision.trust_digest.as_array());
    }
    if let Some(unexpected) = evaluations.keys().next() {
        return Err(E::UnexpectedEvaluation(unexpected.to_string()));
    }
    let evaluation_digest = Digest32::of_bytes(&evaluation_binding);
    let proposal = propose_topology_v2(TopologyProposalRequestV2 {
        proposal_id: request.proposal_id,
        proposer_id: generator.principal().principal_id.clone(),
        evaluator_id: evaluator_id.ok_or(E::NoUpdateCandidate)?,
        selected_artifact_digest: request.admission.selected_artifact_digest,
        window: request.admission.window.clone(),
        baseline_generation: request.admission.baseline_generation,
        candidate_generation: request.admission.candidate_generation,
        evaluation_digest,
        rollback_predecessor_digest: request.admission.selected_artifact_digest,
        changes: request.changes,
    })?;
    let handoff_set_digest = verify_topology_writer_handoffs_v1(&proposal, &request.handoffs)?;

    let registry = match writer
        .registry
        .append_v2(request.expected_registry_predecessor, proposal.clone())
    {
        Ok(receipt) => {
            writer.state = PlasticityWriterStateV1::AppendPendingAnchor;
            receipt
        }
        Err(error) => {
            if matches!(
                error,
                DurableTopologyProposalRegistryError::Indeterminate
                    | DurableTopologyProposalRegistryError::Poisoned
            ) {
                writer.state = PlasticityWriterStateV1::Poisoned;
            }
            return Err(E::Registry(error));
        }
    };
    let committed_registry_anchor = match writer.registry.current_anchor() {
        Ok(Some(anchor)) => anchor,
        Ok(None) => {
            writer.state = PlasticityWriterStateV1::Poisoned;
            return Err(E::Registry(DurableTopologyProposalRegistryError::Corrupt));
        }
        Err(error) => {
            writer.state = PlasticityWriterStateV1::Poisoned;
            return Err(E::Registry(error));
        }
    };
    if !anchor_committer.persist_anchor(
        writer.registry_scope_digest,
        writer.writer_fence,
        committed_registry_anchor,
    ) {
        writer.state = PlasticityWriterStateV1::Poisoned;
        return Err(E::AnchorPersistenceFailed);
    }
    writer.state = PlasticityWriterStateV1::Healthy;

    let mut composition = b"hepta.intelligence.topology-plasticity-composition.v1\0".to_vec();
    for digest in [
        proposal.proposal_digest,
        handoff_set_digest,
        registry.frame_digest,
        committed_registry_anchor.frame_digest,
        generator_authentication_digest,
        admission_authentication_digest,
        evaluation_digest,
    ] {
        composition.extend_from_slice(digest.as_array());
    }
    Ok(TopologyPlasticityProductReceiptV1 {
        proposal,
        handoff_set_digest,
        registry,
        committed_registry_anchor,
        generator_authentication_digest,
        admission_authentication_digest,
        evaluation_digest,
        composition_digest: Digest32::of_bytes(&composition),
    })
}

fn validate_admission(
    admission: &TopologyPlasticityAdmissionEvidenceV1,
) -> Result<(), TopologyPlasticityProductErrorV1> {
    for (name, digest) in [
        ("objective", admission.objective_digest),
        ("selected artifact", admission.selected_artifact_digest),
        ("artifact registry binding", admission.artifact_registry_binding),
        ("artifact registry head", admission.artifact_registry_head_digest),
        (
            "qualification evidence head",
            admission.qualification_evidence_head_digest,
        ),
        ("topology policy", admission.topology_policy_digest),
        ("window", admission.window.window_digest),
        ("dataset", admission.dataset_digest),
    ] {
        if digest.is_zero() {
            return Err(TopologyPlasticityProductErrorV1::Binding(name));
        }
    }
    if admission.baseline_generation.next() != Ok(admission.candidate_generation) {
        return Err(TopologyPlasticityProductErrorV1::Binding(
            "generation successor",
        ));
    }
    Ok(())
}

fn push_admission(bytes: &mut Vec<u8>, admission: &TopologyPlasticityAdmissionEvidenceV1) {
    push_id(bytes, &admission.baseline_id);
    for digest in [
        admission.objective_digest,
        admission.selected_artifact_digest,
        admission.artifact_registry_binding,
        admission.artifact_registry_head_digest,
        admission.qualification_evidence_head_digest,
        admission.topology_policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(bytes, &admission.window.window_id);
    bytes.extend_from_slice(admission.window.window_digest.as_array());
    bytes.extend_from_slice(&admission.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&admission.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(admission.dataset_digest.as_array());
}

fn push_optional_digest(bytes: &mut Vec<u8>, digest: Option<Digest32>) {
    match digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
}
fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}
fn push_len(
    bytes: &mut Vec<u8>,
    value: usize,
) -> Result<(), TopologyPlasticityProductErrorV1> {
    let value = u32::try_from(value)
        .map_err(|_| TopologyPlasticityProductErrorV1::Binding("length overflow"))?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}
fn attestation_digest(evidence: &SignedLearningEvidenceV1) -> Digest32 {
    let mut bytes = evidence.signing_bytes();
    bytes.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&bytes)
}

#[allow(dead_code)]
fn _disposition_is_non_authoritative(disposition: AppendDisposition) -> bool {
    matches!(disposition, AppendDisposition::Inserted | AppendDisposition::Unchanged)
}
