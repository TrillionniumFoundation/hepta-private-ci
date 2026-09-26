//! Governed bridge from independently evaluated iteration candidates to the
//! existing Agentd plasticity owner.
//!
//! This coordinator owns no artifact, learning, proposal, selection or runtime
//! state. It replays the authority-free iteration ledger, binds the exact
//! evaluated candidate to one parameter/topology proposal, and then calls the
//! already composed Agentd plasticity owner. It cannot select, install, activate,
//! promote, release or merge a candidate.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence::CandidateEvaluationAdmissionV2;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::plasticity_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_evaluation_signing_payload_v1;
use codex_hepta_intelligence::topology_generation_signing_payload_v1;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_learning_artifacts::IterationCandidateStateV1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::IterationLedgerError;
use codex_hepta_learning_artifacts::IterationLedgerSnapshotV1;
use codex_hepta_learning_artifacts::IterationLedgerV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::parameter_generator_signing_payload_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdState;
use crate::PlasticityRuntimeCallErrorV1;

const MAX_SELF_ITERATION_QUEUE: usize = 32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelfIterationProposalKindV1 {
    Parameter,
    Topology,
}

impl SelfIterationProposalKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Parameter => 0,
            Self::Topology => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationCoordinatorReceiptV1 {
    pub envelope_id: StableId,
    pub candidate_id: StableId,
    pub proposal_id: StableId,
    pub kind: SelfIterationProposalKindV1,
    pub submission_digest: Digest32,
    pub product_composition_digest: Digest32,
    pub coordination_digest: Digest32,
}

#[derive(Debug)]
pub enum SelfIterationCoordinatorErrorV1 {
    InvalidCapacity,
    Closed,
    Clock,
    Ledger(IterationLedgerError),
    EnvelopeExpired,
    CandidateMissing(String),
    CandidateState,
    CandidateBinding(&'static str),
    Digest(&'static str),
    Plasticity(PlasticityRuntimeCallErrorV1),
}

impl fmt::Display for SelfIterationCoordinatorErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SelfIterationCoordinatorErrorV1 {}
impl From<IterationLedgerError> for SelfIterationCoordinatorErrorV1 {
    fn from(value: IterationLedgerError) -> Self {
        Self::Ledger(value)
    }
}
impl From<PlasticityRuntimeCallErrorV1> for SelfIterationCoordinatorErrorV1 {
    fn from(value: PlasticityRuntimeCallErrorV1) -> Self {
        Self::Plasticity(value)
    }
}

enum SelfIterationCoordinatorCommandV1 {
    Parameter {
        ledger: IterationLedgerSnapshotV1,
        request: Box<ParameterPlasticityProductRequestV1>,
        response: oneshot::Sender<
            Result<
                (
                    SelfIterationCoordinatorReceiptV1,
                    ParameterPlasticityProductReceiptV1,
                ),
                SelfIterationCoordinatorErrorV1,
            >,
        >,
    },
    Topology {
        ledger: IterationLedgerSnapshotV1,
        request: Box<TopologyPlasticityProductRequestV1>,
        response: oneshot::Sender<
            Result<
                (
                    SelfIterationCoordinatorReceiptV1,
                    TopologyPlasticityProductReceiptV1,
                ),
                SelfIterationCoordinatorErrorV1,
            >,
        >,
    },
}

/// Authority-free producer handle. It contains no mutable writer, owner store,
/// trust root or artifact selector.
#[derive(Clone)]
pub struct SelfIterationCoordinatorHandleV1 {
    sender: mpsc::Sender<SelfIterationCoordinatorCommandV1>,
}

impl SelfIterationCoordinatorHandleV1 {
    pub async fn submit_parameter(
        &self,
        ledger: IterationLedgerSnapshotV1,
        request: ParameterPlasticityProductRequestV1,
    ) -> Result<
        (
            SelfIterationCoordinatorReceiptV1,
            ParameterPlasticityProductReceiptV1,
        ),
        SelfIterationCoordinatorErrorV1,
    > {
        let (response, receive) = oneshot::channel();
        self.sender
            .send(SelfIterationCoordinatorCommandV1::Parameter {
                ledger,
                request: Box::new(request),
                response,
            })
            .await
            .map_err(|_| SelfIterationCoordinatorErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| SelfIterationCoordinatorErrorV1::Closed)?
    }

    pub async fn submit_topology(
        &self,
        ledger: IterationLedgerSnapshotV1,
        request: TopologyPlasticityProductRequestV1,
    ) -> Result<
        (
            SelfIterationCoordinatorReceiptV1,
            TopologyPlasticityProductReceiptV1,
        ),
        SelfIterationCoordinatorErrorV1,
    > {
        let (response, receive) = oneshot::channel();
        self.sender
            .send(SelfIterationCoordinatorCommandV1::Topology {
                ledger,
                request: Box::new(request),
                response,
            })
            .await
            .map_err(|_| SelfIterationCoordinatorErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| SelfIterationCoordinatorErrorV1::Closed)?
    }
}

trait SelfIterationClockV1: Send + Sync {
    fn now_unix_seconds(&self) -> Result<u64, SelfIterationCoordinatorErrorV1>;
}

struct SystemSelfIterationClockV1;
impl SelfIterationClockV1 for SystemSelfIterationClockV1 {
    fn now_unix_seconds(&self) -> Result<u64, SelfIterationCoordinatorErrorV1> {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_secs())
            .map_err(|_| SelfIterationCoordinatorErrorV1::Clock)
    }
}

#[cfg(test)]
struct FixedSelfIterationClockV1(u64);
#[cfg(test)]
impl SelfIterationClockV1 for FixedSelfIterationClockV1 {
    fn now_unix_seconds(&self) -> Result<u64, SelfIterationCoordinatorErrorV1> {
        Ok(self.0)
    }
}

/// Single-use runtime bootstrap. The embedding retains the returned producer
/// handle and passes this owner half into `AgentdConfig`.
pub struct SelfIterationCoordinatorBootstrapV1 {
    receiver: mpsc::Receiver<SelfIterationCoordinatorCommandV1>,
    clock: Arc<dyn SelfIterationClockV1>,
}

pub fn self_iteration_coordinator_channel_v1(
    capacity: usize,
) -> Result<
    (
        SelfIterationCoordinatorHandleV1,
        SelfIterationCoordinatorBootstrapV1,
    ),
    SelfIterationCoordinatorErrorV1,
> {
    self_iteration_coordinator_channel_with_clock_v1(capacity, Arc::new(SystemSelfIterationClockV1))
}

#[cfg(test)]
pub(crate) fn self_iteration_coordinator_channel_at_v1(
    capacity: usize,
    now_unix_seconds: u64,
) -> Result<
    (
        SelfIterationCoordinatorHandleV1,
        SelfIterationCoordinatorBootstrapV1,
    ),
    SelfIterationCoordinatorErrorV1,
> {
    self_iteration_coordinator_channel_with_clock_v1(
        capacity,
        Arc::new(FixedSelfIterationClockV1(now_unix_seconds)),
    )
}

fn self_iteration_coordinator_channel_with_clock_v1(
    capacity: usize,
    clock: Arc<dyn SelfIterationClockV1>,
) -> Result<
    (
        SelfIterationCoordinatorHandleV1,
        SelfIterationCoordinatorBootstrapV1,
    ),
    SelfIterationCoordinatorErrorV1,
> {
    if !(1..=MAX_SELF_ITERATION_QUEUE).contains(&capacity) {
        return Err(SelfIterationCoordinatorErrorV1::InvalidCapacity);
    }
    let (sender, receiver) = mpsc::channel(capacity);
    Ok((
        SelfIterationCoordinatorHandleV1 { sender },
        SelfIterationCoordinatorBootstrapV1 { receiver, clock },
    ))
}

pub(crate) struct SelfIterationCoordinatorOwnerV1 {
    receiver: mpsc::Receiver<SelfIterationCoordinatorCommandV1>,
    clock: Arc<dyn SelfIterationClockV1>,
}

pub(crate) fn compose_self_iteration_coordinator_v1(
    bootstrap: Option<SelfIterationCoordinatorBootstrapV1>,
) -> Option<SelfIterationCoordinatorOwnerV1> {
    bootstrap.map(|bootstrap| SelfIterationCoordinatorOwnerV1 {
        receiver: bootstrap.receiver,
        clock: bootstrap.clock,
    })
}

impl SelfIterationCoordinatorOwnerV1 {
    pub(crate) async fn run(
        mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        loop {
            let command = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                command = self.receiver.recv() => command,
            };
            let Some(command) = command else {
                // The external coordinator handle can disappear while durable
                // proposal reconciliation still needs its sole owner alive.
                cancellation.cancelled().await;
                return Ok(());
            };
            let now = match self.clock.now_unix_seconds() {
                Ok(now) => now,
                Err(error) => {
                    match command {
                        SelfIterationCoordinatorCommandV1::Parameter { response, .. } => {
                            let _ = response.send(Err(error));
                        }
                        SelfIterationCoordinatorCommandV1::Topology { response, .. } => {
                            let _ = response.send(Err(error));
                        }
                    }
                    continue;
                }
            };
            match command {
                SelfIterationCoordinatorCommandV1::Parameter {
                    ledger,
                    request,
                    response,
                } => {
                    let result = self.submit_parameter(&state, ledger, *request, now).await;
                    let _ = response.send(result);
                }
                SelfIterationCoordinatorCommandV1::Topology {
                    ledger,
                    request,
                    response,
                } => {
                    let result = self.submit_topology(&state, ledger, *request, now).await;
                    let _ = response.send(result);
                }
            }
        }
    }

    async fn submit_parameter(
        &self,
        state: &AgentdState,
        snapshot: IterationLedgerSnapshotV1,
        request: ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<
        (
            SelfIterationCoordinatorReceiptV1,
            ParameterPlasticityProductReceiptV1,
        ),
        SelfIterationCoordinatorErrorV1,
    > {
        let test_plan_digest = self_iteration_parameter_evaluation_digest_v1(&request)?;
        let evaluator_identity = parameter_evaluator_identity(&request)?;
        let (envelope, candidate) = evaluated_candidate(
            snapshot,
            EvaluatedCandidateBindingV1 {
                proposal_id: &request.proposal_id,
                baseline_id: &request.admission.baseline_id,
                objective_digest: request.admission.objective_digest,
                rollback_digest: request.admission.selected_artifact_digest,
                generator_identity: &request.generator_attestation.principal_id,
                evaluator_identity: &evaluator_identity,
                evaluation_digest: test_plan_digest,
                now,
            },
        )?;
        if envelope.grammar_digest
            != request
                .generator_profile
                .mutation_policy
                .mutation_grammar_digest
        {
            return Err(SelfIterationCoordinatorErrorV1::CandidateBinding(
                "parameter mutation grammar",
            ));
        }
        let submission_digest = self_iteration_parameter_submission_digest_v1(&envelope, &request)?;
        if candidate.test_plan_digest != test_plan_digest
            || candidate.semantic_diff_digest != submission_digest
        {
            return Err(SelfIterationCoordinatorErrorV1::CandidateBinding(
                "parameter candidate evidence",
            ));
        }
        let product = state.submit_parameter_plasticity_v1(request, now).await?;
        let receipt = coordination_receipt(
            envelope.envelope_id,
            candidate.candidate_id,
            product.proposal.proposal_id.clone(),
            SelfIterationProposalKindV1::Parameter,
            submission_digest,
            product.composition_digest,
        );
        Ok((receipt, product))
    }

    async fn submit_topology(
        &self,
        state: &AgentdState,
        snapshot: IterationLedgerSnapshotV1,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<
        (
            SelfIterationCoordinatorReceiptV1,
            TopologyPlasticityProductReceiptV1,
        ),
        SelfIterationCoordinatorErrorV1,
    > {
        let test_plan_digest = self_iteration_topology_evaluation_digest_v1(&request);
        let (envelope, candidate) = evaluated_candidate(
            snapshot,
            EvaluatedCandidateBindingV1 {
                proposal_id: &request.proposal_id,
                baseline_id: &request.admission.baseline_id,
                objective_digest: request.admission.objective_digest,
                rollback_digest: request.selected_artifact_digest,
                generator_identity: &request.proposer_generation_id,
                evaluator_identity: &request.evaluator_attestation.principal_id,
                evaluation_digest: test_plan_digest,
                now,
            },
        )?;
        let submission_digest = self_iteration_topology_submission_digest_v1(&envelope, &request)?;
        if candidate.test_plan_digest != test_plan_digest
            || candidate.semantic_diff_digest != submission_digest
        {
            return Err(SelfIterationCoordinatorErrorV1::CandidateBinding(
                "topology candidate evidence",
            ));
        }
        let product = state.submit_topology_plasticity_v1(request, now).await?;
        let receipt = coordination_receipt(
            envelope.envelope_id,
            candidate.candidate_id,
            product.governed.proposal.proposal_id.clone(),
            SelfIterationProposalKindV1::Topology,
            submission_digest,
            product.composition_digest,
        );
        Ok((receipt, product))
    }
}

struct EvaluatedCandidateBindingV1<'a> {
    proposal_id: &'a StableId,
    baseline_id: &'a StableId,
    objective_digest: Digest32,
    rollback_digest: Digest32,
    generator_identity: &'a StableId,
    evaluator_identity: &'a StableId,
    evaluation_digest: Digest32,
    now: u64,
}

fn evaluated_candidate(
    snapshot: IterationLedgerSnapshotV1,
    binding: EvaluatedCandidateBindingV1<'_>,
) -> Result<
    (
        IterationEnvelopeV1,
        codex_hepta_learning_artifacts::IterationCandidateV1,
    ),
    SelfIterationCoordinatorErrorV1,
> {
    let ledger = IterationLedgerV1::from_snapshot(snapshot)?;
    let envelope = ledger.envelope().clone();
    if binding.now > envelope.expiry_unix_seconds {
        return Err(SelfIterationCoordinatorErrorV1::EnvelopeExpired);
    }
    if envelope.objective_digest != binding.objective_digest {
        return Err(SelfIterationCoordinatorErrorV1::CandidateBinding(
            "iteration objective",
        ));
    }
    let candidate = ledger
        .candidate(binding.proposal_id)
        .cloned()
        .ok_or_else(|| {
            SelfIterationCoordinatorErrorV1::CandidateMissing(binding.proposal_id.to_string())
        })?;
    if candidate.state != IterationCandidateStateV1::IndependentlyEvaluated {
        return Err(SelfIterationCoordinatorErrorV1::CandidateState);
    }
    if &candidate.generator_identity != binding.generator_identity
        || candidate.predecessor.as_ref() != Some(binding.baseline_id)
        || candidate.rollback_digest != binding.rollback_digest
    {
        return Err(SelfIterationCoordinatorErrorV1::CandidateBinding(
            "candidate lineage",
        ));
    }
    let evaluation = ledger
        .events()
        .iter()
        .find(|event| {
            event.candidate_id == *binding.proposal_id
                && event.to == IterationCandidateStateV1::IndependentlyEvaluated
        })
        .ok_or(SelfIterationCoordinatorErrorV1::CandidateState)?;
    if &evaluation.evidence.actor_id != binding.evaluator_identity
        || evaluation.evidence.evidence_digest != binding.evaluation_digest
        || evaluation.evidence.observed_unix_seconds > binding.now
    {
        return Err(SelfIterationCoordinatorErrorV1::CandidateBinding(
            "independent evaluation evidence",
        ));
    }
    Ok((envelope, candidate))
}

fn parameter_evaluator_identity(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<StableId, SelfIterationCoordinatorErrorV1> {
    let no_change = request
        .no_change_attestation
        .as_ref()
        .map(|attestation| attestation.principal_id.clone());
    let mut evaluations = request.evaluations.iter();
    let first = evaluations
        .next()
        .map(|evaluation| evaluation.bundle.evaluator.principal_id.clone());
    match (no_change, first) {
        (Some(identity), None) => Ok(identity),
        (None, Some(identity))
            if evaluations
                .all(|evaluation| evaluation.bundle.evaluator.principal_id == identity) =>
        {
            Ok(identity)
        }
        _ => Err(SelfIterationCoordinatorErrorV1::CandidateBinding(
            "parameter evaluator identity",
        )),
    }
}

pub fn self_iteration_parameter_evaluation_digest_v1(
    request: &ParameterPlasticityProductRequestV1,
) -> Result<Digest32, SelfIterationCoordinatorErrorV1> {
    let mut bytes = b"hepta.agentd.self-iteration.parameter-evaluation.v1\0".to_vec();
    let mut evaluations = request.evaluations.iter().collect::<Vec<_>>();
    evaluations.sort_by(|left, right| left.bundle.candidate_id.cmp(&right.bundle.candidate_id));
    push_len(&mut bytes, evaluations.len());
    for evaluation in evaluations {
        push_candidate_evaluation(&mut bytes, evaluation)?;
    }
    push_optional_attestation(&mut bytes, request.no_change_attestation.as_ref());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_candidate_evaluation(
    bytes: &mut Vec<u8>,
    evaluation: &CandidateEvaluationAdmissionV2,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    push_id(bytes, &evaluation.bundle.evaluation_id);
    push_id(bytes, &evaluation.bundle.candidate_id);
    push_id(bytes, &evaluation.bundle.baseline_id);
    let payload = evaluation_signing_payload_v2(&evaluation.bundle, &evaluation.metric_roles)
        .map_err(|_| SelfIterationCoordinatorErrorV1::Digest("evaluation payload"))?;
    bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
    for digest in [
        evaluation.qualification.temporal_execution_digest,
        evaluation.qualification.publication_digest,
        evaluation.qualification.evidence_digest,
        evaluation.qualification.decision.decision.evidence_digest,
        evaluation.qualification.decision.authentication_digest,
        evaluation.qualification.decision.trust_digest,
        attestation_digest(&evaluation.evidence.generator_plan),
        attestation_digest(&evaluation.evidence.evaluator_bundle),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(())
}

pub fn self_iteration_parameter_submission_digest_v1(
    envelope: &IterationEnvelopeV1,
    request: &ParameterPlasticityProductRequestV1,
) -> Result<Digest32, SelfIterationCoordinatorErrorV1> {
    let mut bytes = b"hepta.agentd.self-iteration.parameter-submission.v1\0".to_vec();
    push_envelope(&mut bytes, envelope);
    push_id(&mut bytes, &request.proposal_id);
    push_id(&mut bytes, &request.admission.baseline_id);
    bytes.extend_from_slice(
        Digest32::of_bytes(&parameter_generator_signing_payload_v3(&request.generated)).as_array(),
    );
    bytes.extend_from_slice(
        Digest32::of_bytes(&plasticity_admission_signing_payload_v1(&request.admission)).as_array(),
    );
    for digest in [
        request.generated.generator_digest,
        request
            .generator_profile
            .mutation_policy
            .mutation_grammar_digest,
        request.generator_profile.mutation_policy.policy_digest,
        request.admission.selected_artifact_digest,
        request.admission.artifact_registry_binding,
        request.admission.artifact_registry_head_digest,
        request.admission.qualification_evidence_head_digest,
        request.admission.owner_evidence_set_digest,
        request.admission.dataset_digest,
        request.admission.update_rule_digest,
        request.admission.modulator_digest,
        request.admission.modulator_broadcast_digest,
        request.admission.eligibility_digest,
        request.expected_registry_predecessor,
        attestation_digest(&request.generator_attestation),
        attestation_digest(&request.admission_attestation),
        self_iteration_parameter_evaluation_digest_v1(request)?,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, request.generated.candidates.len());
    for candidate in &request.generated.candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        bytes.push(match candidate.kind {
            ParameterCandidateKindV2::NoChange => 0,
            ParameterCandidateKindV2::Update => 1,
        });
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn self_iteration_topology_evaluation_digest_v1(
    request: &TopologyPlasticityProductRequestV1,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.self-iteration.topology-evaluation.v1\0".to_vec();
    bytes.extend_from_slice(
        Digest32::of_bytes(&topology_evaluation_signing_payload_v1(&request.admission)).as_array(),
    );
    bytes.extend_from_slice(request.admission.evaluation_receipt_digest.as_array());
    bytes.extend_from_slice(attestation_digest(&request.evaluator_attestation).as_array());
    Digest32::of_bytes(&bytes)
}

pub fn self_iteration_topology_submission_digest_v1(
    envelope: &IterationEnvelopeV1,
    request: &TopologyPlasticityProductRequestV1,
) -> Result<Digest32, SelfIterationCoordinatorErrorV1> {
    let mut bytes = b"hepta.agentd.self-iteration.topology-submission.v1\0".to_vec();
    push_envelope(&mut bytes, envelope);
    push_id(&mut bytes, &request.proposal_id);
    push_id(&mut bytes, &request.proposer_generation_id);
    push_id(&mut bytes, &request.admission.baseline_id);
    let generation = topology_generation_signing_payload_v1(request)
        .map_err(|_| SelfIterationCoordinatorErrorV1::Digest("topology generation"))?;
    bytes.extend_from_slice(Digest32::of_bytes(&generation).as_array());
    bytes.extend_from_slice(
        Digest32::of_bytes(&topology_admission_signing_payload_v1(&request.admission)).as_array(),
    );
    for digest in [
        envelope.grammar_digest,
        request.selected_artifact_digest,
        request.rollback_predecessor_digest,
        request.admission.generation_digest,
        request.admission.artifact_registry_head_digest,
        request.admission.qualification_evidence_head_digest,
        request.expected_registry_predecessor,
        attestation_digest(&request.generator_attestation),
        attestation_digest(&request.observer_attestation),
        attestation_digest(&request.evaluator_attestation),
        self_iteration_topology_evaluation_digest_v1(request),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn coordination_receipt(
    envelope_id: StableId,
    candidate_id: StableId,
    proposal_id: StableId,
    kind: SelfIterationProposalKindV1,
    submission_digest: Digest32,
    product_composition_digest: Digest32,
) -> SelfIterationCoordinatorReceiptV1 {
    let mut bytes = b"hepta.agentd.self-iteration.coordination.v1\0".to_vec();
    push_id(&mut bytes, &envelope_id);
    push_id(&mut bytes, &candidate_id);
    push_id(&mut bytes, &proposal_id);
    bytes.push(kind.tag());
    bytes.extend_from_slice(submission_digest.as_array());
    bytes.extend_from_slice(product_composition_digest.as_array());
    SelfIterationCoordinatorReceiptV1 {
        envelope_id,
        candidate_id,
        proposal_id,
        kind,
        submission_digest,
        product_composition_digest,
        coordination_digest: Digest32::of_bytes(&bytes),
    }
}

fn attestation_digest(evidence: &SignedLearningEvidenceV1) -> Digest32 {
    let mut bytes = evidence.signing_bytes();
    bytes.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&bytes)
}

fn push_optional_attestation(bytes: &mut Vec<u8>, evidence: Option<&SignedLearningEvidenceV1>) {
    match evidence {
        Some(evidence) => {
            bytes.push(1);
            bytes.extend_from_slice(attestation_digest(evidence).as_array());
        }
        None => bytes.push(0),
    }
}

fn push_envelope(bytes: &mut Vec<u8>, envelope: &IterationEnvelopeV1) {
    push_id(bytes, &envelope.envelope_id);
    for digest in [
        envelope.base_commit,
        envelope.base_tree,
        envelope.objective_digest,
        envelope.grammar_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&envelope.maximum_files.to_be_bytes());
    bytes.extend_from_slice(&envelope.maximum_diff_bytes.to_be_bytes());
    bytes.extend_from_slice(&envelope.maximum_candidates.to_be_bytes());
    bytes.push(envelope.maximum_parallel_sandboxes);
    bytes.extend_from_slice(&envelope.expiry_unix_seconds.to_be_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&(value as u64).to_be_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn coordinator_capacity_is_bounded() {
        assert!(self_iteration_coordinator_channel_at_v1(1, 50).is_ok());
        assert!(self_iteration_coordinator_channel_at_v1(MAX_SELF_ITERATION_QUEUE, 50).is_ok());
        assert!(matches!(
            self_iteration_coordinator_channel_at_v1(0, 50),
            Err(SelfIterationCoordinatorErrorV1::InvalidCapacity)
        ));
        assert!(matches!(
            self_iteration_coordinator_channel_at_v1(MAX_SELF_ITERATION_QUEUE + 1, 50),
            Err(SelfIterationCoordinatorErrorV1::InvalidCapacity)
        ));
    }
}
