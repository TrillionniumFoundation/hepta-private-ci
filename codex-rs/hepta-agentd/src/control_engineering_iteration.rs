//! Replay-safe non-test control.engineering coordinator for governed plasticity.
//!
//! The durable journal implementation and stable public record types live in the
//! sibling base module. This coordinator resolves the terminal identity before it
//! invokes the named Agentd producer: exact retries return the original terminal
//! receipt, while any request/freeze/coverage drift fails before proposal I/O.
//! It owns no proposal writer and has no selection or activation operation.

use std::time::Duration;

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::plasticity_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_evaluation_signing_payload_v1;
use codex_hepta_intelligence::topology_generation_signing_payload_v1;
use codex_hepta_intelligence_eval::evaluation_signing_payload_v2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_plasticity::GeneratorCoverageDispositionV1;
use codex_hepta_plasticity::GeneratorCoverageReceiptV1;
use codex_hepta_plasticity::build_generator_coverage_receipt_v1;
use codex_hepta_plasticity::generator_coverage_signing_payload_v1;
use codex_hepta_plasticity::verify_generated_parameter_candidates_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::Instant;
use tokio::time::timeout_at;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdState;

#[allow(dead_code)]
#[path = "control_engineering_iteration_base.rs"]
mod base;

pub use base::ControlEngineeringIterationErrorV1;
pub use base::ControlEngineeringParameterIterationRequestV1;
pub use base::ControlEngineeringTopologyIterationRequestV1;
pub use base::DurableIterationJournalErrorV1;
pub use base::DurableIterationTerminalJournalV1;
pub use base::FrozenPlasticityContextV1;
pub use base::IterationPlasticityKindV1;
pub use base::IterationPlasticityTerminalDispositionV1;
pub use base::IterationPlasticityTerminalReceiptV1;
pub use base::freeze_parameter_context_v1;
pub use base::freeze_topology_context_v1;
pub use base::iteration_envelope_digest_v1;

const MAX_COORDINATOR_QUEUE: usize = 64;

#[derive(Clone)]
pub struct ControlEngineeringIterationHandleV1 {
    sender: mpsc::Sender<ControlEngineeringIterationCommandV1>,
}

pub struct ControlEngineeringIterationBootstrapV1 {
    receiver: mpsc::Receiver<ControlEngineeringIterationCommandV1>,
    journal: DurableIterationTerminalJournalV1,
}

enum ControlEngineeringIterationCommandV1 {
    Parameter {
        request: Box<ControlEngineeringParameterIterationRequestV1>,
        now: u64,
        deadline: Instant,
        response: oneshot::Sender<
            Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1>,
        >,
    },
    Topology {
        request: Box<ControlEngineeringTopologyIterationRequestV1>,
        now: u64,
        deadline: Instant,
        response: oneshot::Sender<
            Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1>,
        >,
    },
}

pub fn control_engineering_iteration_channel_v1(
    capacity: usize,
    journal: DurableIterationTerminalJournalV1,
) -> Result<
    (
        ControlEngineeringIterationHandleV1,
        ControlEngineeringIterationBootstrapV1,
    ),
    AgentdError,
> {
    if !(1..=MAX_COORDINATOR_QUEUE).contains(&capacity) {
        return Err(AgentdError::Invalid(format!(
            "control.engineering iteration queue capacity must be within 1..={MAX_COORDINATOR_QUEUE}"
        )));
    }
    let (sender, receiver) = mpsc::channel(capacity);
    Ok((
        ControlEngineeringIterationHandleV1 { sender },
        ControlEngineeringIterationBootstrapV1 { receiver, journal },
    ))
}

impl ControlEngineeringIterationHandleV1 {
    pub async fn submit_parameter(
        &self,
        request: ControlEngineeringParameterIterationRequestV1,
        now: u64,
    ) -> Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1> {
        let deadline = logical_deadline(now, request.deadline_unix_seconds)?;
        let (response, receive) = oneshot::channel();
        timeout_at(
            deadline,
            self.sender.send(ControlEngineeringIterationCommandV1::Parameter {
                request: Box::new(request),
                now,
                deadline,
                response,
            }),
        )
        .await
        .map_err(|_| ControlEngineeringIterationErrorV1::DeadlineExceeded)?
        .map_err(|_| ControlEngineeringIterationErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| ControlEngineeringIterationErrorV1::Closed)?
    }

    pub async fn submit_topology(
        &self,
        request: ControlEngineeringTopologyIterationRequestV1,
        now: u64,
    ) -> Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1> {
        let deadline = logical_deadline(now, request.deadline_unix_seconds)?;
        let (response, receive) = oneshot::channel();
        timeout_at(
            deadline,
            self.sender.send(ControlEngineeringIterationCommandV1::Topology {
                request: Box::new(request),
                now,
                deadline,
                response,
            }),
        )
        .await
        .map_err(|_| ControlEngineeringIterationErrorV1::DeadlineExceeded)?
        .map_err(|_| ControlEngineeringIterationErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| ControlEngineeringIterationErrorV1::Closed)?
    }
}

impl ControlEngineeringIterationBootstrapV1 {
    pub(crate) async fn run(
        mut self,
        state: std::sync::Arc<AgentdState>,
        verifier: LearningEvidenceVerifierV1,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        loop {
            let command = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                command = self.receiver.recv() => command,
            };
            let Some(command) = command else {
                cancellation.cancelled().await;
                return Ok(());
            };
            match command {
                ControlEngineeringIterationCommandV1::Parameter {
                    request,
                    now,
                    deadline,
                    response,
                } => {
                    if response.is_closed() {
                        continue;
                    }
                    let result = if Instant::now() >= deadline {
                        Err(ControlEngineeringIterationErrorV1::DeadlineExceeded)
                    } else {
                        self.coordinate_parameter(&state, &verifier, *request, now)
                            .await
                    };
                    let _ = response.send(result);
                }
                ControlEngineeringIterationCommandV1::Topology {
                    request,
                    now,
                    deadline,
                    response,
                } => {
                    if response.is_closed() {
                        continue;
                    }
                    let result = if Instant::now() >= deadline {
                        Err(ControlEngineeringIterationErrorV1::DeadlineExceeded)
                    } else {
                        self.coordinate_topology(&state, &verifier, *request, now)
                            .await
                    };
                    let _ = response.send(result);
                }
            }
        }
    }

    async fn coordinate_parameter(
        &mut self,
        state: &AgentdState,
        verifier: &LearningEvidenceVerifierV1,
        request: ControlEngineeringParameterIterationRequestV1,
        now: u64,
    ) -> Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1> {
        validate_envelope(
            &request.envelope,
            now,
            request.deadline_unix_seconds,
        )?;
        verify_generated_parameter_candidates_v3(
            request.product.generator_profile.clone(),
            &request.product.generated,
        )
        .map_err(|_| ControlEngineeringIterationErrorV1::Binding("generated candidate set"))?;
        let frozen = freeze_parameter_context_v1(&request.envelope, &request.product)?;
        if frozen != request.frozen {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "frozen parameter context",
            ));
        }
        if request.product.generated.candidates.len()
            > request.envelope.maximum_candidates as usize
        {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "iteration candidate budget",
            ));
        }
        let expected_coverage = build_generator_coverage_receipt_v1(
            &request.product.generator_profile,
            frozen.owner_frontier_digest,
        )?;
        if expected_coverage != request.coverage {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "generator coverage",
            ));
        }
        verify_parameter_observer_binding(verifier, &request, now)?;

        let request_digest = parameter_iteration_request_digest(&request)?;
        let expected_disposition = parameter_terminal_disposition(request.coverage.disposition);
        let probe = terminal_template(
            &request.envelope,
            &frozen,
            request.product.proposal_id.clone(),
            IterationPlasticityKindV1::Parameter,
            expected_disposition,
            request_digest,
            Digest32::of_bytes(b"hepta.control-engineering.replay-probe.v1"),
            request.coverage.coverage_digest,
            now,
        )?;
        if let Some(existing) = self.lookup_exact_replay(&probe)? {
            return Ok(existing);
        }

        let terminal_payload_digest = match request.coverage.disposition {
            GeneratorCoverageDispositionV1::Complete => {
                let product = state
                    .submit_parameter_plasticity_v1(request.product.clone(), now)
                    .await?;
                parameter_product_digest(&product)
            }
            GeneratorCoverageDispositionV1::ZeroEligibleSignals
            | GeneratorCoverageDispositionV1::PolicyDisabledUpdates
            | GeneratorCoverageDispositionV1::IncompleteSignals => coverage_terminal_digest(
                expected_disposition,
                &request.coverage,
                frozen.freeze_digest,
            ),
        };
        let terminal = terminal_template(
            &request.envelope,
            &frozen,
            request.product.proposal_id,
            IterationPlasticityKindV1::Parameter,
            expected_disposition,
            request_digest,
            terminal_payload_digest,
            request.coverage.coverage_digest,
            now,
        )?;
        self.journal.append(terminal).map_err(Into::into)
    }

    async fn coordinate_topology(
        &mut self,
        state: &AgentdState,
        verifier: &LearningEvidenceVerifierV1,
        request: ControlEngineeringTopologyIterationRequestV1,
        now: u64,
    ) -> Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1> {
        validate_envelope(
            &request.envelope,
            now,
            request.deadline_unix_seconds,
        )?;
        let frozen = freeze_topology_context_v1(&request.envelope, &request.product)?;
        if frozen != request.frozen {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "frozen topology context",
            ));
        }
        if request.product.changes.len().saturating_add(1)
            > request.envelope.maximum_candidates as usize
        {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "iteration topology candidate budget",
            ));
        }
        verify_topology_roles(verifier, &request.product, &request.envelope.objective_digest, now)?;
        let request_digest = topology_iteration_request_digest(&request)?;
        let coverage_digest =
            Digest32::of_bytes(b"hepta.control-engineering.topology-coverage.not-applicable.v1");
        let probe = terminal_template(
            &request.envelope,
            &frozen,
            request.product.proposal_id.clone(),
            IterationPlasticityKindV1::Topology,
            IterationPlasticityTerminalDispositionV1::TopologyCommitted,
            request_digest,
            Digest32::of_bytes(b"hepta.control-engineering.replay-probe.v1"),
            coverage_digest,
            now,
        )?;
        if let Some(existing) = self.lookup_exact_replay(&probe)? {
            return Ok(existing);
        }

        let product = state
            .submit_topology_plasticity_v1(request.product.clone(), now)
            .await?;
        let terminal = terminal_template(
            &request.envelope,
            &frozen,
            request.product.proposal_id,
            IterationPlasticityKindV1::Topology,
            IterationPlasticityTerminalDispositionV1::TopologyCommitted,
            request_digest,
            topology_product_digest(&product),
            coverage_digest,
            now,
        )?;
        self.journal.append(terminal).map_err(Into::into)
    }

    fn lookup_exact_replay(
        &self,
        probe: &IterationPlasticityTerminalReceiptV1,
    ) -> Result<Option<IterationPlasticityTerminalReceiptV1>, ControlEngineeringIterationErrorV1>
    {
        let Some(existing) = self.journal.lookup(probe)? else {
            return Ok(None);
        };
        let exact = existing.envelope_id == probe.envelope_id
            && existing.envelope_digest == probe.envelope_digest
            && existing.freeze_digest == probe.freeze_digest
            && existing.proposal_id == probe.proposal_id
            && existing.candidate_generation == probe.candidate_generation
            && existing.kind == probe.kind
            && existing.disposition == probe.disposition
            && existing.request_digest == probe.request_digest
            && existing.coverage_digest == probe.coverage_digest;
        if !exact {
            return Err(ControlEngineeringIterationErrorV1::Journal(
                DurableIterationJournalErrorV1::Conflict,
            ));
        }
        Ok(Some(existing.clone()))
    }
}

fn verify_parameter_observer_binding(
    verifier: &LearningEvidenceVerifierV1,
    request: &ControlEngineeringParameterIterationRequestV1,
    now: u64,
) -> Result<(), ControlEngineeringIterationErrorV1> {
    let coverage_payload = generator_coverage_signing_payload_v1(&request.coverage)?;
    let coverage_observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &request.coverage_attestation,
        &coverage_payload,
        now,
    )?;
    let admission_payload =
        plasticity_admission_signing_payload_v1(&request.product.admission);
    let admission_observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &request.product.admission_attestation,
        &admission_payload,
        now,
    )?;
    if coverage_observer.principal() != admission_observer.principal()
        || coverage_observer.controller_id() != admission_observer.controller_id()
        || request.coverage_attestation.objective_digest != request.envelope.objective_digest
        || request.product.admission_attestation.objective_digest
            != request.envelope.objective_digest
    {
        return Err(ControlEngineeringIterationErrorV1::Binding(
            "coverage observer",
        ));
    }
    Ok(())
}

fn verify_topology_roles(
    verifier: &LearningEvidenceVerifierV1,
    product: &TopologyPlasticityProductRequestV1,
    objective_digest: &Digest32,
    now: u64,
) -> Result<(), ControlEngineeringIterationErrorV1> {
    let generation_payload = topology_generation_signing_payload_v1(product)
        .map_err(|_| ControlEngineeringIterationErrorV1::Binding("topology generation"))?;
    let admission_payload = topology_admission_signing_payload_v1(&product.admission);
    let evaluation_payload = topology_evaluation_signing_payload_v1(&product.admission);
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &product.generator_attestation,
        &generation_payload,
        now,
    )?;
    let observer = verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &product.observer_attestation,
        &admission_payload,
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &product.evaluator_attestation,
        &evaluation_payload,
        now,
    )?;
    verify_signed_role_separation(&generator, &observer, now)?;
    verify_signed_role_separation(&generator, &evaluator, now)?;
    verify_signed_independent_roles_v1(&observer, &evaluator, now)?;
    if product.admission.objective_digest != *objective_digest {
        return Err(ControlEngineeringIterationErrorV1::Binding(
            "topology objective",
        ));
    }
    Ok(())
}

fn parameter_terminal_disposition(
    disposition: GeneratorCoverageDispositionV1,
) -> IterationPlasticityTerminalDispositionV1 {
    match disposition {
        GeneratorCoverageDispositionV1::Complete => {
            IterationPlasticityTerminalDispositionV1::ParameterCommitted
        }
        GeneratorCoverageDispositionV1::ZeroEligibleSignals => {
            IterationPlasticityTerminalDispositionV1::ZeroEligibleSignals
        }
        GeneratorCoverageDispositionV1::PolicyDisabledUpdates => {
            IterationPlasticityTerminalDispositionV1::PolicyDisabledUpdates
        }
        GeneratorCoverageDispositionV1::IncompleteSignals => {
            IterationPlasticityTerminalDispositionV1::IncompleteCoverage
        }
    }
}

fn validate_envelope(
    envelope: &codex_hepta_learning_artifacts::IterationEnvelopeV1,
    now: u64,
    deadline: u64,
) -> Result<(), ControlEngineeringIterationErrorV1> {
    envelope
        .validate()
        .map_err(ControlEngineeringIterationErrorV1::InvalidEnvelope)?;
    if now > envelope.expiry_unix_seconds
        || deadline <= now
        || deadline > envelope.expiry_unix_seconds
    {
        return Err(ControlEngineeringIterationErrorV1::DeadlineExceeded);
    }
    Ok(())
}

fn logical_deadline(
    now: u64,
    deadline: u64,
) -> Result<Instant, ControlEngineeringIterationErrorV1> {
    let seconds = deadline
        .checked_sub(now)
        .filter(|seconds| *seconds > 0)
        .ok_or(ControlEngineeringIterationErrorV1::DeadlineExceeded)?;
    Instant::now()
        .checked_add(Duration::from_secs(seconds))
        .ok_or(ControlEngineeringIterationErrorV1::DeadlineExceeded)
}

#[allow(clippy::too_many_arguments)]
fn terminal_template(
    envelope: &codex_hepta_learning_artifacts::IterationEnvelopeV1,
    frozen: &FrozenPlasticityContextV1,
    proposal_id: StableId,
    kind: IterationPlasticityKindV1,
    disposition: IterationPlasticityTerminalDispositionV1,
    request_digest: Digest32,
    terminal_payload_digest: Digest32,
    coverage_digest: Digest32,
    observed_unix_seconds: u64,
) -> Result<IterationPlasticityTerminalReceiptV1, ControlEngineeringIterationErrorV1> {
    if request_digest.is_zero()
        || terminal_payload_digest.is_zero()
        || coverage_digest.is_zero()
        || observed_unix_seconds == 0
    {
        return Err(ControlEngineeringIterationErrorV1::Binding(
            "terminal receipt",
        ));
    }
    Ok(IterationPlasticityTerminalReceiptV1 {
        sequence: 0,
        envelope_id: envelope.envelope_id.clone(),
        envelope_digest: frozen.envelope_digest,
        freeze_digest: frozen.freeze_digest,
        proposal_id,
        candidate_generation: frozen.candidate_generation.get(),
        kind,
        disposition,
        request_digest,
        terminal_payload_digest,
        coverage_digest,
        observed_unix_seconds,
        predecessor_frame_digest: Digest32::ZERO,
        frame_digest: Digest32::ZERO,
    })
}

fn parameter_iteration_request_digest(
    request: &ControlEngineeringParameterIterationRequestV1,
) -> Result<Digest32, ControlEngineeringIterationErrorV1> {
    let mut bytes = b"hepta.control-engineering.parameter-iteration-request.v1\0".to_vec();
    bytes.extend_from_slice(request.frozen.freeze_digest.as_array());
    push_id(&mut bytes, &request.product.proposal_id)?;
    bytes.extend_from_slice(request.product.generated.generator_digest.as_array());
    bytes.extend_from_slice(request.coverage.coverage_digest.as_array());
    bytes.extend_from_slice(request.product.expected_registry_predecessor.as_array());
    push_signed_evidence(&mut bytes, &request.product.generator_attestation);
    push_signed_evidence(&mut bytes, &request.product.admission_attestation);
    push_signed_evidence(&mut bytes, &request.coverage_attestation);
    match &request.product.no_change_attestation {
        Some(evidence) => {
            bytes.push(1);
            push_signed_evidence(&mut bytes, evidence);
        }
        None => bytes.push(0),
    }
    let mut evaluations = request.product.evaluations.iter().collect::<Vec<_>>();
    evaluations.sort_by(|left, right| left.bundle.candidate_id.cmp(&right.bundle.candidate_id));
    push_len(&mut bytes, evaluations.len())?;
    for evaluation in evaluations {
        push_id(&mut bytes, &evaluation.bundle.candidate_id)?;
        let payload = evaluation_signing_payload_v2(&evaluation.bundle, &evaluation.metric_roles)
            .map_err(|_| ControlEngineeringIterationErrorV1::Binding("evaluation payload"))?;
        bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        push_signed_evidence(&mut bytes, &evaluation.evidence.generator_plan);
        push_signed_evidence(&mut bytes, &evaluation.evidence.evaluator_bundle);
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn topology_iteration_request_digest(
    request: &ControlEngineeringTopologyIterationRequestV1,
) -> Result<Digest32, ControlEngineeringIterationErrorV1> {
    let mut bytes = b"hepta.control-engineering.topology-iteration-request.v1\0".to_vec();
    bytes.extend_from_slice(request.frozen.freeze_digest.as_array());
    push_id(&mut bytes, &request.product.proposal_id)?;
    for payload in [
        topology_generation_signing_payload_v1(&request.product)
            .map_err(|_| ControlEngineeringIterationErrorV1::Binding("topology generation"))?,
        topology_admission_signing_payload_v1(&request.product.admission),
        topology_evaluation_signing_payload_v1(&request.product.admission),
    ] {
        bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
    }
    for evidence in [
        &request.product.generator_attestation,
        &request.product.observer_attestation,
        &request.product.evaluator_attestation,
    ] {
        push_signed_evidence(&mut bytes, evidence);
    }
    bytes.extend_from_slice(request.product.expected_registry_predecessor.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn parameter_product_digest(receipt: &ParameterPlasticityProductReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.parameter-product-terminal.v1\0".to_vec();
    for digest in [
        receipt.proposal.proposal_digest,
        receipt.registry.frame_digest,
        receipt.committed_registry_anchor.frame_digest,
        receipt.composition_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn topology_product_digest(receipt: &TopologyPlasticityProductReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.topology-product-terminal.v1\0".to_vec();
    for digest in [
        receipt.governed.proposal.proposal_digest,
        receipt.governed.admission_digest,
        receipt.durable.frame_digest,
        receipt.next_registry_anchor.frame_digest,
        receipt.composition_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn coverage_terminal_digest(
    disposition: IterationPlasticityTerminalDispositionV1,
    coverage: &GeneratorCoverageReceiptV1,
    freeze_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.coverage-terminal.v1\0".to_vec();
    bytes.push(match disposition {
        IterationPlasticityTerminalDispositionV1::ParameterCommitted => 0,
        IterationPlasticityTerminalDispositionV1::TopologyCommitted => 1,
        IterationPlasticityTerminalDispositionV1::ZeroEligibleSignals => 2,
        IterationPlasticityTerminalDispositionV1::PolicyDisabledUpdates => 3,
        IterationPlasticityTerminalDispositionV1::IncompleteCoverage => 4,
    });
    bytes.extend_from_slice(coverage.coverage_digest.as_array());
    bytes.extend_from_slice(freeze_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_signed_evidence(bytes: &mut Vec<u8>, evidence: &SignedLearningEvidenceV1) {
    bytes.extend_from_slice(Digest32::of_bytes(&evidence.signing_bytes()).as_array());
    bytes.extend_from_slice(&evidence.signature);
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), ControlEngineeringIterationErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| ControlEngineeringIterationErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(
    bytes: &mut Vec<u8>,
    value: usize,
) -> Result<(), ControlEngineeringIterationErrorV1> {
    let value = u32::try_from(value).map_err(|_| ControlEngineeringIterationErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::OpenOptions;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn probe(request_digest: Digest32) -> IterationPlasticityTerminalReceiptV1 {
        IterationPlasticityTerminalReceiptV1 {
            sequence: 0,
            envelope_id: id("envelope:replay"),
            envelope_digest: digest(b"envelope"),
            freeze_digest: digest(b"freeze"),
            proposal_id: id("proposal:replay"),
            candidate_generation: 2,
            kind: IterationPlasticityKindV1::Parameter,
            disposition: IterationPlasticityTerminalDispositionV1::ParameterCommitted,
            request_digest,
            terminal_payload_digest: digest(b"terminal"),
            coverage_digest: digest(b"coverage"),
            observed_unix_seconds: 10,
            predecessor_frame_digest: Digest32::ZERO,
            frame_digest: Digest32::ZERO,
        }
    }

    #[test]
    fn exact_replay_returns_original_before_product_and_drift_conflicts() {
        let fixture = tempfile::NamedTempFile::new().expect("file");
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(fixture.path())
            .expect("open");
        let mut journal = DurableIterationTerminalJournalV1::bootstrap_new(
            file,
            digest(b"scope"),
            1,
            8,
        )
        .expect("journal");
        let original = journal.append(probe(digest(b"request-a"))).expect("append");
        let (_sender, mut bootstrap) = control_engineering_iteration_channel_v1(1, journal)
            .expect("channel");
        assert_eq!(
            bootstrap
                .lookup_exact_replay(&probe(digest(b"request-a")))
                .expect("lookup"),
            Some(original)
        );
        assert!(matches!(
            bootstrap.lookup_exact_replay(&probe(digest(b"request-b"))),
            Err(ControlEngineeringIterationErrorV1::Journal(
                DurableIterationJournalErrorV1::Conflict
            ))
        ));
    }
}
