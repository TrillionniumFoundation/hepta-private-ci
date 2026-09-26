//! `control.engineering`-owned self-iteration coordination semantics hosted by Agentd.
//!
//! The coordinator validates one exact `IterationEnvelopeV1`, regenerates and checks
//! parameter candidate completeness, binds the expected learnable set and current
//! owner frontier, and derives a stable idempotency key before the named Agentd
//! plasticity producer is invoked. It owns no proposal writer and grants no
//! selection, activation, topology-application, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence::CandidateEvaluationAdmissionV1;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::plasticity_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_evaluation_signing_payload_v1;
use codex_hepta_intelligence::topology_generation_signing_payload_v1;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_plasticity::GeneratorCoverageErrorV1;
use codex_hepta_plasticity::GeneratorCoverageReceiptV1;
use codex_hepta_plasticity::verify_generated_parameter_candidates_v3;
use codex_hepta_plasticity::verify_generator_coverage_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

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
pub struct ParameterSelfIterationRequestV1 {
    pub envelope: IterationEnvelopeV1,
    pub coverage: GeneratorCoverageReceiptV1,
    pub product: ParameterPlasticityProductRequestV1,
    pub deadline_unix_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologySelfIterationRequestV1 {
    pub envelope: IterationEnvelopeV1,
    pub topology_grammar_digest: Digest32,
    pub product: TopologyPlasticityProductRequestV1,
    pub deadline_unix_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedSelfIterationContextV1 {
    pub kind: SelfIterationProposalKindV1,
    pub envelope_digest: Digest32,
    pub request_digest: Digest32,
    pub idempotency_digest: Digest32,
    pub proposal_id: StableId,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub deadline_unix_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedParameterSelfIterationV1 {
    pub context: PreparedSelfIterationContextV1,
    pub request: ParameterPlasticityProductRequestV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedTopologySelfIterationV1 {
    pub context: PreparedSelfIterationContextV1,
    pub request: TopologyPlasticityProductRequestV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelfIterationTerminalDispositionV1 {
    ParameterCommitted,
    TopologyCommitted,
    Rejected,
    ReconciliationRequired,
}

impl SelfIterationTerminalDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::ParameterCommitted => 0,
            Self::TopologyCommitted => 1,
            Self::Rejected => 2,
            Self::ReconciliationRequired => 3,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationTerminalReceiptV1 {
    pub kind: SelfIterationProposalKindV1,
    pub envelope_digest: Digest32,
    pub request_digest: Digest32,
    pub idempotency_digest: Digest32,
    pub proposal_id: StableId,
    pub candidate_generation: Generation,
    pub disposition: SelfIterationTerminalDispositionV1,
    pub proposal_digest: Digest32,
    pub registry_frame_digest: Digest32,
    pub failure_digest: Digest32,
    pub receipt_digest: Digest32,
}

#[derive(Debug)]
pub enum SelfIterationCoordinatorErrorV1 {
    Envelope(String),
    Expired,
    Deadline,
    Binding(&'static str),
    Coverage(GeneratorCoverageErrorV1),
    Generator(codex_hepta_plasticity::ParameterGeneratorErrorV3),
    Evaluation(codex_hepta_intelligence_eval::EvaluationClosureError),
    Topology(codex_hepta_intelligence::TopologyPlasticityProductErrorV1),
    EmptyFailureDigest,
    Arithmetic,
}

impl fmt::Display for SelfIterationCoordinatorErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SelfIterationCoordinatorErrorV1 {}
impl From<GeneratorCoverageErrorV1> for SelfIterationCoordinatorErrorV1 {
    fn from(value: GeneratorCoverageErrorV1) -> Self {
        Self::Coverage(value)
    }
}
impl From<codex_hepta_plasticity::ParameterGeneratorErrorV3>
    for SelfIterationCoordinatorErrorV1
{
    fn from(value: codex_hepta_plasticity::ParameterGeneratorErrorV3) -> Self {
        Self::Generator(value)
    }
}
impl From<codex_hepta_intelligence_eval::EvaluationClosureError>
    for SelfIterationCoordinatorErrorV1
{
    fn from(value: codex_hepta_intelligence_eval::EvaluationClosureError) -> Self {
        Self::Evaluation(value)
    }
}
impl From<codex_hepta_intelligence::TopologyPlasticityProductErrorV1>
    for SelfIterationCoordinatorErrorV1
{
    fn from(value: codex_hepta_intelligence::TopologyPlasticityProductErrorV1) -> Self {
        Self::Topology(value)
    }
}

pub fn prepare_parameter_self_iteration_v1(
    request: ParameterSelfIterationRequestV1,
    now: u64,
) -> Result<PreparedParameterSelfIterationV1, SelfIterationCoordinatorErrorV1> {
    validate_envelope(&request.envelope, request.deadline_unix_seconds, now)?;
    verify_generated_parameter_candidates_v3(
        request.product.generator_profile.clone(),
        &request.product.generated,
    )?;
    verify_generator_coverage_receipt_v1(
        &request.product.generator_profile,
        &request.coverage,
    )?;
    if request.product.admission.objective_digest != request.envelope.objective_digest
        || request.product.generator_profile.mutation_policy.mutation_grammar_digest
            != request.envelope.grammar_digest
        || request.coverage.grammar_manifest_digest != request.envelope.grammar_digest
        || request.coverage.owner_frontier_digest
            != request.product.admission.owner_evidence_set_digest
        || request.product.admission.baseline_generation.next()
            != Ok(request.product.admission.candidate_generation)
        || request.product.generated.candidates.len()
            > usize::from(request.envelope.maximum_candidates)
    {
        return Err(SelfIterationCoordinatorErrorV1::Binding(
            "parameter iteration envelope",
        ));
    }
    let envelope_digest = iteration_envelope_digest_v1(&request.envelope)?;
    let request_digest = parameter_request_digest_v1(
        envelope_digest,
        &request.coverage,
        &request.product,
    )?;
    let context = context(
        SelfIterationProposalKindV1::Parameter,
        envelope_digest,
        request_digest,
        request.product.proposal_id.clone(),
        request.product.admission.baseline_generation,
        request.product.admission.candidate_generation,
        request.deadline_unix_seconds,
    )?;
    Ok(PreparedParameterSelfIterationV1 {
        context,
        request: request.product,
    })
}

pub fn prepare_topology_self_iteration_v1(
    request: TopologySelfIterationRequestV1,
    now: u64,
) -> Result<PreparedTopologySelfIterationV1, SelfIterationCoordinatorErrorV1> {
    validate_envelope(&request.envelope, request.deadline_unix_seconds, now)?;
    if request.topology_grammar_digest.is_zero()
        || request.topology_grammar_digest != request.envelope.grammar_digest
        || request.product.admission.objective_digest != request.envelope.objective_digest
        || request.product.baseline_generation.next() != Ok(request.product.candidate_generation)
        || request.product.changes.len().saturating_add(1)
            > usize::from(request.envelope.maximum_candidates)
    {
        return Err(SelfIterationCoordinatorErrorV1::Binding(
            "topology iteration envelope",
        ));
    }
    let envelope_digest = iteration_envelope_digest_v1(&request.envelope)?;
    let request_digest = topology_request_digest_v1(envelope_digest, &request.product)?;
    let context = context(
        SelfIterationProposalKindV1::Topology,
        envelope_digest,
        request_digest,
        request.product.proposal_id.clone(),
        request.product.baseline_generation,
        request.product.candidate_generation,
        request.deadline_unix_seconds,
    )?;
    Ok(PreparedTopologySelfIterationV1 {
        context,
        request: request.product,
    })
}

pub fn complete_parameter_self_iteration_v1(
    context: &PreparedSelfIterationContextV1,
    receipt: &ParameterPlasticityProductReceiptV1,
) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
    terminal_receipt(
        context,
        SelfIterationTerminalDispositionV1::ParameterCommitted,
        receipt.proposal.proposal_digest,
        receipt.registry.frame_digest,
        Digest32::ZERO,
    )
}

pub fn complete_topology_self_iteration_v1(
    context: &PreparedSelfIterationContextV1,
    receipt: &TopologyPlasticityProductReceiptV1,
) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
    terminal_receipt(
        context,
        SelfIterationTerminalDispositionV1::TopologyCommitted,
        receipt.governed.proposal.proposal_digest,
        receipt.durable.frame_digest,
        Digest32::ZERO,
    )
}

pub fn reject_self_iteration_v1(
    context: &PreparedSelfIterationContextV1,
    failure_digest: Digest32,
    reconciliation_required: bool,
) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
    if failure_digest.is_zero() {
        return Err(SelfIterationCoordinatorErrorV1::EmptyFailureDigest);
    }
    terminal_receipt(
        context,
        if reconciliation_required {
            SelfIterationTerminalDispositionV1::ReconciliationRequired
        } else {
            SelfIterationTerminalDispositionV1::Rejected
        },
        Digest32::ZERO,
        Digest32::ZERO,
        failure_digest,
    )
}

pub fn iteration_envelope_digest_v1(
    envelope: &IterationEnvelopeV1,
) -> Result<Digest32, SelfIterationCoordinatorErrorV1> {
    envelope
        .validate()
        .map_err(SelfIterationCoordinatorErrorV1::Envelope)?;
    let mut bytes = b"hepta.control-engineering.iteration-envelope.v1\0".to_vec();
    push_id(&mut bytes, &envelope.envelope_id)?;
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
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_envelope(
    envelope: &IterationEnvelopeV1,
    deadline: u64,
    now: u64,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    envelope
        .validate()
        .map_err(SelfIterationCoordinatorErrorV1::Envelope)?;
    if now == 0 || now > envelope.expiry_unix_seconds {
        return Err(SelfIterationCoordinatorErrorV1::Expired);
    }
    if deadline == 0 || deadline < now || deadline > envelope.expiry_unix_seconds {
        return Err(SelfIterationCoordinatorErrorV1::Deadline);
    }
    Ok(())
}

fn context(
    kind: SelfIterationProposalKindV1,
    envelope_digest: Digest32,
    request_digest: Digest32,
    proposal_id: StableId,
    baseline_generation: Generation,
    candidate_generation: Generation,
    deadline_unix_seconds: u64,
) -> Result<PreparedSelfIterationContextV1, SelfIterationCoordinatorErrorV1> {
    if baseline_generation.next() != Ok(candidate_generation) {
        return Err(SelfIterationCoordinatorErrorV1::Binding(
            "generation successor",
        ));
    }
    let mut bytes = b"hepta.control-engineering.self-iteration-idempotency.v1\0".to_vec();
    bytes.push(kind.tag());
    bytes.extend_from_slice(envelope_digest.as_array());
    bytes.extend_from_slice(request_digest.as_array());
    push_id(&mut bytes, &proposal_id)?;
    bytes.extend_from_slice(&candidate_generation.get().to_be_bytes());
    Ok(PreparedSelfIterationContextV1 {
        kind,
        envelope_digest,
        request_digest,
        idempotency_digest: Digest32::of_bytes(&bytes),
        proposal_id,
        baseline_generation,
        candidate_generation,
        deadline_unix_seconds,
    })
}

fn parameter_request_digest_v1(
    envelope_digest: Digest32,
    coverage: &GeneratorCoverageReceiptV1,
    request: &ParameterPlasticityProductRequestV1,
) -> Result<Digest32, SelfIterationCoordinatorErrorV1> {
    let mut bytes = b"hepta.control-engineering.parameter-self-iteration.v1\0".to_vec();
    bytes.extend_from_slice(envelope_digest.as_array());
    bytes.extend_from_slice(coverage.receipt_digest.as_array());
    push_id(&mut bytes, &request.proposal_id)?;
    bytes.extend_from_slice(request.generated.generator_digest.as_array());
    bytes.extend_from_slice(
        Digest32::of_bytes(&plasticity_admission_signing_payload_v1(&request.admission))
            .as_array(),
    );
    push_attestation(&mut bytes, &request.generator_attestation)?;
    push_attestation(&mut bytes, &request.admission_attestation)?;
    match &request.no_change_attestation {
        Some(value) => {
            bytes.push(1);
            push_attestation(&mut bytes, value)?;
        }
        None => bytes.push(0),
    }
    let mut evaluations = request.evaluations.iter().collect::<Vec<_>>();
    evaluations.sort_by(|left, right| left.bundle.candidate_id.cmp(&right.bundle.candidate_id));
    push_len(&mut bytes, evaluations.len())?;
    for evaluation in evaluations {
        push_evaluation(&mut bytes, evaluation)?;
    }
    bytes.extend_from_slice(request.expected_registry_predecessor.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn topology_request_digest_v1(
    envelope_digest: Digest32,
    request: &TopologyPlasticityProductRequestV1,
) -> Result<Digest32, SelfIterationCoordinatorErrorV1> {
    let mut bytes = b"hepta.control-engineering.topology-self-iteration.v1\0".to_vec();
    bytes.extend_from_slice(envelope_digest.as_array());
    push_id(&mut bytes, &request.proposal_id)?;
    bytes.extend_from_slice(
        Digest32::of_bytes(&topology_generation_signing_payload_v1(request)?).as_array(),
    );
    bytes.extend_from_slice(
        Digest32::of_bytes(&topology_admission_signing_payload_v1(&request.admission)).as_array(),
    );
    bytes.extend_from_slice(
        Digest32::of_bytes(&topology_evaluation_signing_payload_v1(&request.admission)).as_array(),
    );
    push_attestation(&mut bytes, &request.generator_attestation)?;
    push_attestation(&mut bytes, &request.observer_attestation)?;
    push_attestation(&mut bytes, &request.evaluator_attestation)?;
    bytes.extend_from_slice(request.expected_registry_predecessor.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_evaluation(
    bytes: &mut Vec<u8>,
    evaluation: &CandidateEvaluationAdmissionV1,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    push_id(bytes, &evaluation.bundle.candidate_id)?;
    bytes.extend_from_slice(
        Digest32::of_bytes(&evaluation_signing_payload_v2(
            &evaluation.bundle,
            &evaluation.metric_roles,
        )?)
        .as_array(),
    );
    push_attestation(bytes, &evaluation.evidence.generator_plan)?;
    push_attestation(bytes, &evaluation.evidence.evaluator_bundle)?;
    Ok(())
}

fn push_attestation(
    bytes: &mut Vec<u8>,
    evidence: &SignedLearningEvidenceV1,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    let signing = evidence.signing_bytes();
    push_len(bytes, signing.len())?;
    bytes.extend_from_slice(&signing);
    push_len(bytes, evidence.signature.len())?;
    bytes.extend_from_slice(&evidence.signature);
    Ok(())
}

fn terminal_receipt(
    context: &PreparedSelfIterationContextV1,
    disposition: SelfIterationTerminalDispositionV1,
    proposal_digest: Digest32,
    registry_frame_digest: Digest32,
    failure_digest: Digest32,
) -> Result<SelfIterationTerminalReceiptV1, SelfIterationCoordinatorErrorV1> {
    let mut bytes = b"hepta.control-engineering.self-iteration-terminal.v1\0".to_vec();
    bytes.push(context.kind.tag());
    bytes.extend_from_slice(context.envelope_digest.as_array());
    bytes.extend_from_slice(context.request_digest.as_array());
    bytes.extend_from_slice(context.idempotency_digest.as_array());
    push_id(&mut bytes, &context.proposal_id)?;
    bytes.extend_from_slice(&context.candidate_generation.get().to_be_bytes());
    bytes.push(disposition.tag());
    bytes.extend_from_slice(proposal_digest.as_array());
    bytes.extend_from_slice(registry_frame_digest.as_array());
    bytes.extend_from_slice(failure_digest.as_array());
    Ok(SelfIterationTerminalReceiptV1 {
        kind: context.kind,
        envelope_digest: context.envelope_digest,
        request_digest: context.request_digest,
        idempotency_digest: context.idempotency_digest,
        proposal_id: context.proposal_id.clone(),
        candidate_generation: context.candidate_generation,
        disposition,
        proposal_digest,
        registry_frame_digest,
        failure_digest,
        receipt_digest: Digest32::of_bytes(&bytes),
    })
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| SelfIterationCoordinatorErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(
    bytes: &mut Vec<u8>,
    value: usize,
) -> Result<(), SelfIterationCoordinatorErrorV1> {
    let value = u32::try_from(value).map_err(|_| SelfIterationCoordinatorErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn envelope() -> IterationEnvelopeV1 {
        IterationEnvelopeV1 {
            envelope_id: id("iteration:1"),
            base_commit: digest(b"commit"),
            base_tree: digest(b"tree"),
            objective_digest: digest(b"objective"),
            grammar_digest: digest(b"grammar"),
            maximum_files: 10,
            maximum_diff_bytes: 1024,
            maximum_candidates: 4,
            maximum_parallel_sandboxes: 1,
            expiry_unix_seconds: 100,
        }
    }

    #[test]
    fn envelope_digest_binds_every_budget_and_source_field() {
        let first = iteration_envelope_digest_v1(&envelope()).expect("digest");
        let mut changed = envelope();
        changed.maximum_candidates += 1;
        assert_ne!(
            first,
            iteration_envelope_digest_v1(&changed).expect("changed")
        );
        let mut changed = envelope();
        changed.base_tree = digest(b"other-tree");
        assert_ne!(
            first,
            iteration_envelope_digest_v1(&changed).expect("changed")
        );
    }

    #[test]
    fn envelope_deadline_cannot_outlive_authorized_window() {
        assert!(validate_envelope(&envelope(), 90, 50).is_ok());
        assert!(matches!(
            validate_envelope(&envelope(), 101, 50),
            Err(SelfIterationCoordinatorErrorV1::Deadline)
        ));
    }
}
