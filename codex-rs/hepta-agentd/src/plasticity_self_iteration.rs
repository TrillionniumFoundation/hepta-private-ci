//! Control-engineering-owned self-iteration bindings for Agentd plasticity.
//!
//! The coordinator consumes an already frozen `IterationEnvelopeV1`, exact
//! parameter/topology product requests and independent evidence. It owns no
//! proposal writer and grants no selection, activation, topology-apply,
//! promotion or release authority. Idempotency is derived from the envelope,
//! generation and proposal semantics rather than mutable coordinator state.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence::ParameterPlasticityDispositionV1;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::plasticity_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_generation_signing_payload_v1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_plasticity::GeneratorCoverageDispositionV1;
use codex_hepta_plasticity::GeneratorCoverageErrorV1;
use codex_hepta_plasticity::GeneratorCoverageReceiptV1;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::generator_coverage_signing_payload_v1;
use codex_hepta_plasticity::verify_generator_coverage_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationParameterSubmissionV1 {
    pub envelope: IterationEnvelopeV1,
    pub coverage: GeneratorCoverageReceiptV1,
    pub coverage_attestation: SignedLearningEvidenceV1,
    pub request: ParameterPlasticityProductRequestV1,
    /// Absolute Unix-seconds deadline. It may be stricter than the envelope but
    /// can never extend the envelope's expiry.
    pub deadline_unix_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationTopologySubmissionV1 {
    pub envelope: IterationEnvelopeV1,
    pub request: TopologyPlasticityProductRequestV1,
    pub deadline_unix_seconds: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SelfIterationPlasticityTerminalV1 {
    ParameterCandidatesAppended,
    NoAdmissibleParameterUpdate,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
    TopologyCandidatesAppended,
}

impl SelfIterationPlasticityTerminalV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::ParameterCandidatesAppended => 0,
            Self::NoAdmissibleParameterUpdate => 1,
            Self::ZeroEligibleSignals => 2,
            Self::PolicyDisabledUpdates => 3,
            Self::TopologyCandidatesAppended => 4,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationParameterReceiptV1 {
    pub envelope_digest: Digest32,
    pub coverage_receipt_digest: Digest32,
    pub proposal_id: StableId,
    pub proposal_digest: Digest32,
    pub registry_sequence: u64,
    pub registry_frame_digest: Digest32,
    pub committed_anchor_frame_digest: Digest32,
    pub product_composition_digest: Digest32,
    pub terminal: SelfIterationPlasticityTerminalV1,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelfIterationTopologyReceiptV1 {
    pub envelope_digest: Digest32,
    pub proposal_id: StableId,
    pub proposal_digest: Digest32,
    pub registry_sequence: u64,
    pub registry_frame_digest: Digest32,
    pub committed_anchor_frame_digest: Digest32,
    pub product_composition_digest: Digest32,
    pub terminal: SelfIterationPlasticityTerminalV1,
    pub receipt_digest: Digest32,
}

#[derive(Debug)]
pub enum SelfIterationPlasticityErrorV1 {
    InvalidEnvelope(String),
    Expired,
    InvalidDeadline,
    Binding(&'static str),
    ProposalIdentity,
    IncompleteCoverage,
    Coverage(GeneratorCoverageErrorV1),
    CoverageEvidence(SignedEvidenceError),
    AdmissionEvidence(SignedEvidenceError),
    TopologyGeneration,
    Arithmetic,
}

impl fmt::Display for SelfIterationPlasticityErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SelfIterationPlasticityErrorV1 {}
impl From<GeneratorCoverageErrorV1> for SelfIterationPlasticityErrorV1 {
    fn from(value: GeneratorCoverageErrorV1) -> Self {
        Self::Coverage(value)
    }
}

pub fn iteration_envelope_digest_v1(
    envelope: &IterationEnvelopeV1,
) -> Result<Digest32, SelfIterationPlasticityErrorV1> {
    envelope
        .validate()
        .map_err(SelfIterationPlasticityErrorV1::InvalidEnvelope)?;
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

pub fn parameter_iteration_proposal_id_v1(
    envelope: &IterationEnvelopeV1,
    coverage: &GeneratorCoverageReceiptV1,
    request: &ParameterPlasticityProductRequestV1,
) -> Result<StableId, SelfIterationPlasticityErrorV1> {
    let mut bytes = b"hepta.control-engineering.parameter-iteration.v1\0".to_vec();
    bytes.extend_from_slice(iteration_envelope_digest_v1(envelope)?.as_array());
    bytes.extend_from_slice(coverage.receipt_digest.as_array());
    bytes.extend_from_slice(request.generated.generator_digest.as_array());
    bytes.extend_from_slice(request.generated.selected_artifact_digest.as_array());
    push_id(&mut bytes, &request.generated.window.window_id)?;
    bytes.extend_from_slice(request.generated.window.window_digest.as_array());
    bytes.extend_from_slice(&request.admission.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&request.admission.candidate_generation.get().to_be_bytes());
    StableId::new(format!(
        "plasticity:iteration:{}",
        Digest32::of_bytes(&bytes)
    ))
    .map_err(|_| SelfIterationPlasticityErrorV1::ProposalIdentity)
}

pub fn topology_iteration_proposal_id_v1(
    envelope: &IterationEnvelopeV1,
    request: &TopologyPlasticityProductRequestV1,
) -> Result<StableId, SelfIterationPlasticityErrorV1> {
    let generation = topology_generation_signing_payload_v1(request)
        .map_err(|_| SelfIterationPlasticityErrorV1::TopologyGeneration)?;
    let mut bytes = b"hepta.control-engineering.topology-iteration.v1\0".to_vec();
    bytes.extend_from_slice(iteration_envelope_digest_v1(envelope)?.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&generation).as_array());
    StableId::new(format!(
        "topology:iteration:{}",
        Digest32::of_bytes(&bytes)
    ))
    .map_err(|_| SelfIterationPlasticityErrorV1::ProposalIdentity)
}

pub fn validate_self_iteration_parameter_bindings_v1(
    submission: &SelfIterationParameterSubmissionV1,
    now: u64,
) -> Result<Digest32, SelfIterationPlasticityErrorV1> {
    validate_deadline(
        &submission.envelope,
        submission.deadline_unix_seconds,
        now,
    )?;
    verify_generator_coverage_receipt_v1(
        &submission.request.generator_profile,
        &submission.coverage,
    )?;
    let request = &submission.request;
    let coverage = &submission.coverage;
    if submission.envelope.objective_digest != request.admission.objective_digest
        || submission.envelope.grammar_digest != coverage.mutation_grammar_digest
        || submission.envelope.grammar_digest
            != request
                .generator_profile
                .mutation_policy
                .mutation_grammar_digest
        || coverage.selected_artifact_digest != request.generated.selected_artifact_digest
        || coverage.window != request.generated.window
        || coverage.owner_frontier_digest != request.admission.owner_evidence_set_digest
        || request.admission.selected_artifact_digest != request.generated.selected_artifact_digest
        || request.admission.window != request.generated.window
        || request.admission.generator_digest != request.generated.generator_digest
        || request.admission.baseline_generation.next()
            != Ok(request.admission.candidate_generation)
    {
        return Err(SelfIterationPlasticityErrorV1::Binding(
            "frozen parameter iteration",
        ));
    }
    if coverage.disposition == GeneratorCoverageDispositionV1::Incomplete {
        return Err(SelfIterationPlasticityErrorV1::IncompleteCoverage);
    }
    let has_update = request
        .generated
        .candidates
        .iter()
        .any(|candidate| candidate.kind == ParameterCandidateKindV2::Update);
    if matches!(
        coverage.disposition,
        GeneratorCoverageDispositionV1::ZeroEligibleSignals
            | GeneratorCoverageDispositionV1::PolicyDisabledUpdates
    ) && (has_update || request.no_change_attestation.is_none())
    {
        return Err(SelfIterationPlasticityErrorV1::Binding(
            "dedicated no-update terminal",
        ));
    }
    if request.proposal_id
        != parameter_iteration_proposal_id_v1(&submission.envelope, coverage, request)?
    {
        return Err(SelfIterationPlasticityErrorV1::ProposalIdentity);
    }
    iteration_envelope_digest_v1(&submission.envelope)
}

pub fn authenticate_self_iteration_parameter_v1(
    submission: &SelfIterationParameterSubmissionV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<Digest32, SelfIterationPlasticityErrorV1> {
    let envelope_digest = validate_self_iteration_parameter_bindings_v1(submission, now)?;
    let coverage_payload = generator_coverage_signing_payload_v1(&submission.coverage)?;
    let coverage_observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &submission.coverage_attestation,
            &coverage_payload,
            now,
        )
        .map_err(SelfIterationPlasticityErrorV1::CoverageEvidence)?;
    let admission_payload = plasticity_admission_signing_payload_v1(&submission.request.admission);
    let admission_observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &submission.request.admission_attestation,
            &admission_payload,
            now,
        )
        .map_err(SelfIterationPlasticityErrorV1::AdmissionEvidence)?;
    if coverage_observer.principal() != admission_observer.principal()
        || submission.coverage_attestation.objective_digest
            != submission.envelope.objective_digest
        || submission.request.admission_attestation.objective_digest
            != submission.envelope.objective_digest
    {
        return Err(SelfIterationPlasticityErrorV1::Binding(
            "coverage/admission observer",
        ));
    }
    Ok(envelope_digest)
}

pub fn validate_self_iteration_topology_bindings_v1(
    submission: &SelfIterationTopologySubmissionV1,
    now: u64,
) -> Result<Digest32, SelfIterationPlasticityErrorV1> {
    validate_deadline(
        &submission.envelope,
        submission.deadline_unix_seconds,
        now,
    )?;
    let request = &submission.request;
    if submission.envelope.objective_digest != request.admission.objective_digest
        || request.admission.selected_artifact_digest != request.selected_artifact_digest
        || request.admission.window != request.window
        || request.admission.baseline_generation != request.baseline_generation
        || request.admission.candidate_generation != request.candidate_generation
        || request.baseline_generation.next() != Ok(request.candidate_generation)
    {
        return Err(SelfIterationPlasticityErrorV1::Binding(
            "frozen topology iteration",
        ));
    }
    if request.proposal_id
        != topology_iteration_proposal_id_v1(&submission.envelope, request)?
    {
        return Err(SelfIterationPlasticityErrorV1::ProposalIdentity);
    }
    iteration_envelope_digest_v1(&submission.envelope)
}

pub fn finalize_self_iteration_parameter_receipt_v1(
    submission: &SelfIterationParameterSubmissionV1,
    product: &ParameterPlasticityProductReceiptV1,
) -> Result<SelfIterationParameterReceiptV1, SelfIterationPlasticityErrorV1> {
    if product.proposal.proposal_id != submission.request.proposal_id {
        return Err(SelfIterationPlasticityErrorV1::Binding(
            "parameter product receipt",
        ));
    }
    let terminal = match submission.coverage.disposition {
        GeneratorCoverageDispositionV1::ZeroEligibleSignals => {
            SelfIterationPlasticityTerminalV1::ZeroEligibleSignals
        }
        GeneratorCoverageDispositionV1::PolicyDisabledUpdates => {
            SelfIterationPlasticityTerminalV1::PolicyDisabledUpdates
        }
        GeneratorCoverageDispositionV1::Complete => match product.disposition {
            ParameterPlasticityDispositionV1::UpdateCandidates => {
                SelfIterationPlasticityTerminalV1::ParameterCandidatesAppended
            }
            ParameterPlasticityDispositionV1::NoAdmissibleUpdate => {
                SelfIterationPlasticityTerminalV1::NoAdmissibleParameterUpdate
            }
        },
        GeneratorCoverageDispositionV1::Incomplete => {
            return Err(SelfIterationPlasticityErrorV1::IncompleteCoverage);
        }
    };
    let envelope_digest = iteration_envelope_digest_v1(&submission.envelope)?;
    let mut receipt = SelfIterationParameterReceiptV1 {
        envelope_digest,
        coverage_receipt_digest: submission.coverage.receipt_digest,
        proposal_id: product.proposal.proposal_id.clone(),
        proposal_digest: product.proposal.proposal_digest,
        registry_sequence: product.registry.sequence,
        registry_frame_digest: product.registry.frame_digest,
        committed_anchor_frame_digest: product.committed_registry_anchor.frame_digest,
        product_composition_digest: product.composition_digest,
        terminal,
        receipt_digest: Digest32::ZERO,
    };
    receipt.receipt_digest = digest_parameter_receipt(&receipt);
    Ok(receipt)
}

pub fn finalize_self_iteration_topology_receipt_v1(
    submission: &SelfIterationTopologySubmissionV1,
    product: &TopologyPlasticityProductReceiptV1,
) -> Result<SelfIterationTopologyReceiptV1, SelfIterationPlasticityErrorV1> {
    if product.governed.proposal.proposal_id != submission.request.proposal_id {
        return Err(SelfIterationPlasticityErrorV1::Binding(
            "topology product receipt",
        ));
    }
    let envelope_digest = iteration_envelope_digest_v1(&submission.envelope)?;
    let mut receipt = SelfIterationTopologyReceiptV1 {
        envelope_digest,
        proposal_id: product.governed.proposal.proposal_id.clone(),
        proposal_digest: product.governed.proposal.proposal_digest,
        registry_sequence: product.durable.sequence,
        registry_frame_digest: product.durable.frame_digest,
        committed_anchor_frame_digest: product.next_registry_anchor.frame_digest,
        product_composition_digest: product.composition_digest,
        terminal: SelfIterationPlasticityTerminalV1::TopologyCandidatesAppended,
        receipt_digest: Digest32::ZERO,
    };
    receipt.receipt_digest = digest_topology_receipt(&receipt);
    Ok(receipt)
}

fn validate_deadline(
    envelope: &IterationEnvelopeV1,
    deadline_unix_seconds: u64,
    now: u64,
) -> Result<(), SelfIterationPlasticityErrorV1> {
    envelope
        .validate()
        .map_err(SelfIterationPlasticityErrorV1::InvalidEnvelope)?;
    if deadline_unix_seconds == 0 || deadline_unix_seconds > envelope.expiry_unix_seconds {
        return Err(SelfIterationPlasticityErrorV1::InvalidDeadline);
    }
    if now == 0 || now > deadline_unix_seconds || now > envelope.expiry_unix_seconds {
        return Err(SelfIterationPlasticityErrorV1::Expired);
    }
    Ok(())
}

fn digest_parameter_receipt(receipt: &SelfIterationParameterReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.parameter-iteration-receipt.v1\0".to_vec();
    for digest in [
        receipt.envelope_digest,
        receipt.coverage_receipt_digest,
        receipt.proposal_digest,
        receipt.registry_frame_digest,
        receipt.committed_anchor_frame_digest,
        receipt.product_composition_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(receipt.proposal_id.as_str().as_bytes());
    bytes.extend_from_slice(&receipt.registry_sequence.to_be_bytes());
    bytes.push(receipt.terminal.tag());
    Digest32::of_bytes(&bytes)
}

fn digest_topology_receipt(receipt: &SelfIterationTopologyReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.topology-iteration-receipt.v1\0".to_vec();
    for digest in [
        receipt.envelope_digest,
        receipt.proposal_digest,
        receipt.registry_frame_digest,
        receipt.committed_anchor_frame_digest,
        receipt.product_composition_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(receipt.proposal_id.as_str().as_bytes());
    bytes.extend_from_slice(&receipt.registry_sequence.to_be_bytes());
    bytes.push(receipt.terminal.tag());
    Digest32::of_bytes(&bytes)
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), SelfIterationPlasticityErrorV1> {
    let raw = value.as_str().as_bytes();
    let length =
        u32::try_from(raw.len()).map_err(|_| SelfIterationPlasticityErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }
    fn digest(value: u8) -> Digest32 {
        Digest32::from_array([value; 32])
    }

    fn envelope() -> IterationEnvelopeV1 {
        IterationEnvelopeV1 {
            envelope_id: id("iteration:envelope:1"),
            base_commit: digest(1),
            base_tree: digest(2),
            objective_digest: digest(3),
            grammar_digest: digest(4),
            maximum_files: 10,
            maximum_diff_bytes: 1_024,
            maximum_candidates: 4,
            maximum_parallel_sandboxes: 2,
            expiry_unix_seconds: 100,
        }
    }

    #[test]
    fn envelope_digest_binds_every_budget_and_expiry() {
        let mut value = envelope();
        let base = iteration_envelope_digest_v1(&value).expect("digest");
        value.maximum_diff_bytes += 1;
        assert_ne!(
            base,
            iteration_envelope_digest_v1(&value).expect("changed digest")
        );
        value.maximum_diff_bytes -= 1;
        value.expiry_unix_seconds += 1;
        assert_ne!(
            base,
            iteration_envelope_digest_v1(&value).expect("expiry digest")
        );
    }

    #[test]
    fn deadline_cannot_extend_or_outlive_envelope() {
        let value = envelope();
        assert!(validate_deadline(&value, 100, 10).is_ok());
        assert!(matches!(
            validate_deadline(&value, 101, 10),
            Err(SelfIterationPlasticityErrorV1::InvalidDeadline)
        ));
        assert!(matches!(
            validate_deadline(&value, 100, 101),
            Err(SelfIterationPlasticityErrorV1::Expired)
        ));
    }
}
