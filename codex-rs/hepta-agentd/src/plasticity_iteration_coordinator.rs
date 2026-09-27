//! control.engineering-owned self-iteration coordination for governed plasticity.
//!
//! This is the non-test product caller between `IterationEnvelopeV1` and the named
//! `AgentdLearningPlasticityProducerV1`. It freezes and validates the exact
//! envelope/model context, regenerates parameter candidates, accounts for generator
//! coverage, requires independent evidence already carried by the product request,
//! submits through the bounded Agentd owner, and durably records the terminal result
//! in a separate control.engineering journal. It never owns a proposal writer,
//! selects a candidate, activates an artifact, applies topology, promotes or releases.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_intelligence::ParameterPlasticityDispositionV1;
use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::topology_generation_signing_payload_v1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_plasticity::GeneratorCoverageDispositionV1;
use codex_hepta_plasticity::GeneratorCoverageErrorV1;
use codex_hepta_plasticity::GeneratorCoverageReceiptV1;
use codex_hepta_plasticity::ParameterGeneratorErrorV3;
use codex_hepta_plasticity::derive_generator_coverage_receipt_v1;
use codex_hepta_plasticity::expected_learnable_parameter_set_digest_v1;
use codex_hepta_plasticity::generate_parameter_candidates_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio_util::sync::CancellationToken;

use crate::AgentdLearningPlasticityProducerV1;
use crate::ControlEngineeringPlasticityJournalV1;
use crate::PersistedPlasticityIterationReceiptV1;
use crate::PlasticityIterationJournalErrorV1;
use crate::PlasticityIterationKindV1;
use crate::PlasticityIterationTerminalReceiptV1;
use crate::PlasticityIterationTerminalV1;
use crate::PlasticityRuntimeCallErrorV1;
use crate::PlasticityRuntimeHandleV1;
use crate::build_terminal_receipt_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterPlasticityIterationV1 {
    pub envelope: IterationEnvelopeV1,
    /// Independent control.engineering expectation for the complete learnable set.
    pub expected_learnable_parameter_set_digest: Digest32,
    pub request: ParameterPlasticityProductRequestV1,
    pub deadline_unix_seconds: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyPlasticityIterationV1 {
    pub envelope: IterationEnvelopeV1,
    /// Exact structural grammar selected by control.engineering. It must equal the
    /// envelope grammar and is additionally bound into the terminal receipt.
    pub structural_grammar_digest: Digest32,
    pub request: TopologyPlasticityProductRequestV1,
    pub deadline_unix_seconds: u64,
}

#[derive(Debug)]
pub enum ControlEngineeringPlasticityErrorV1 {
    InvalidEnvelope(String),
    Expired,
    InvalidDeadline,
    Binding(&'static str),
    Identity,
    Arithmetic,
    IncompleteCoverage,
    Coverage(GeneratorCoverageErrorV1),
    Generator(ParameterGeneratorErrorV3),
    Runtime(PlasticityRuntimeCallErrorV1),
    Journal(PlasticityIterationJournalErrorV1),
    JournalWorkerFailed,
    TerminalMismatch,
}

impl fmt::Display for ControlEngineeringPlasticityErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ControlEngineeringPlasticityErrorV1 {}
impl From<GeneratorCoverageErrorV1> for ControlEngineeringPlasticityErrorV1 {
    fn from(value: GeneratorCoverageErrorV1) -> Self {
        Self::Coverage(value)
    }
}
impl From<ParameterGeneratorErrorV3> for ControlEngineeringPlasticityErrorV1 {
    fn from(value: ParameterGeneratorErrorV3) -> Self {
        Self::Generator(value)
    }
}
impl From<PlasticityRuntimeCallErrorV1> for ControlEngineeringPlasticityErrorV1 {
    fn from(value: PlasticityRuntimeCallErrorV1) -> Self {
        Self::Runtime(value)
    }
}
impl From<PlasticityIterationJournalErrorV1> for ControlEngineeringPlasticityErrorV1 {
    fn from(value: PlasticityIterationJournalErrorV1) -> Self {
        Self::Journal(value)
    }
}

/// Public control.engineering façade over the named Agentd producer and a separate
/// terminal journal. The façade contains no proposal writer or trust root.
#[derive(Clone)]
pub struct ControlEngineeringPlasticityCoordinatorV1 {
    producer: AgentdLearningPlasticityProducerV1,
    journal: Arc<Mutex<ControlEngineeringPlasticityJournalV1>>,
}

impl ControlEngineeringPlasticityCoordinatorV1 {
    pub fn new(
        handle: PlasticityRuntimeHandleV1,
        journal: ControlEngineeringPlasticityJournalV1,
    ) -> Self {
        Self {
            producer: AgentdLearningPlasticityProducerV1::new(handle),
            journal: Arc::new(Mutex::new(journal)),
        }
    }

    pub fn from_shared_journal(
        handle: PlasticityRuntimeHandleV1,
        journal: Arc<Mutex<ControlEngineeringPlasticityJournalV1>>,
    ) -> Self {
        Self {
            producer: AgentdLearningPlasticityProducerV1::new(handle),
            journal,
        }
    }

    #[must_use]
    pub fn journal(&self) -> Arc<Mutex<ControlEngineeringPlasticityJournalV1>> {
        Arc::clone(&self.journal)
    }

    pub async fn submit_parameter(
        &self,
        iteration: ParameterPlasticityIterationV1,
        now: u64,
    ) -> Result<PersistedPlasticityIterationReceiptV1, ControlEngineeringPlasticityErrorV1> {
        self.submit_parameter_with_control(iteration, now, CancellationToken::new())
            .await
    }

    pub async fn submit_parameter_with_control(
        &self,
        mut iteration: ParameterPlasticityIterationV1,
        now: u64,
        cancellation: CancellationToken,
    ) -> Result<PersistedPlasticityIterationReceiptV1, ControlEngineeringPlasticityErrorV1> {
        let envelope_digest = validate_envelope_and_deadline(
            &iteration.envelope,
            iteration.deadline_unix_seconds,
            now,
        )?;
        let request = &mut iteration.request;
        if request.admission.objective_digest != iteration.envelope.objective_digest
            || request.generator_profile.mutation_policy.mutation_grammar_digest
                != iteration.envelope.grammar_digest
        {
            return Err(ControlEngineeringPlasticityErrorV1::Binding(
                "iteration objective or mutation grammar",
            ));
        }

        // The coordinator, not an arbitrary caller, executes the deterministic
        // generator and requires the signed request to carry exactly that output.
        let regenerated = generate_parameter_candidates_v3(request.generator_profile.clone())?;
        if regenerated != request.generated
            || regenerated.candidates.len() > usize::from(iteration.envelope.maximum_candidates)
        {
            return Err(ControlEngineeringPlasticityErrorV1::Binding(
                "regenerated candidate set or envelope candidate budget",
            ));
        }

        let expected =
            expected_learnable_parameter_set_digest_v1(&request.generator_profile.mutation_policy)?;
        if expected != iteration.expected_learnable_parameter_set_digest {
            return Err(ControlEngineeringPlasticityErrorV1::Binding(
                "expected learnable parameter set",
            ));
        }
        let coverage = derive_generator_coverage_receipt_v1(
            &request.generator_profile,
            request.admission.owner_evidence_set_digest,
        )?;
        if coverage.expected_learnable_parameter_set_digest
            != iteration.expected_learnable_parameter_set_digest
        {
            return Err(ControlEngineeringPlasticityErrorV1::Binding(
                "coverage learnable parameter set",
            ));
        }
        if coverage.disposition == GeneratorCoverageDispositionV1::IncompleteSignalCoverage {
            return Err(ControlEngineeringPlasticityErrorV1::IncompleteCoverage);
        }

        let expected_proposal_id = parameter_iteration_proposal_id_v1(
            envelope_digest,
            request.admission.candidate_generation,
            request.generated.generator_digest,
            coverage.coverage_digest,
        )?;
        if request.proposal_id != expected_proposal_id {
            return Err(ControlEngineeringPlasticityErrorV1::Binding(
                "deterministic parameter proposal identity",
            ));
        }

        let product = self
            .producer
            .submit_parameter_with_control(
                iteration.request,
                now,
                iteration.deadline_unix_seconds,
                cancellation,
            )
            .await?;
        let terminal = parameter_terminal_receipt(envelope_digest, coverage, product)?;
        self.persist_terminal(terminal).await
    }

    pub async fn submit_topology(
        &self,
        iteration: TopologyPlasticityIterationV1,
        now: u64,
    ) -> Result<PersistedPlasticityIterationReceiptV1, ControlEngineeringPlasticityErrorV1> {
        self.submit_topology_with_control(iteration, now, CancellationToken::new())
            .await
    }

    pub async fn submit_topology_with_control(
        &self,
        iteration: TopologyPlasticityIterationV1,
        now: u64,
        cancellation: CancellationToken,
    ) -> Result<PersistedPlasticityIterationReceiptV1, ControlEngineeringPlasticityErrorV1> {
        let envelope_digest = validate_envelope_and_deadline(
            &iteration.envelope,
            iteration.deadline_unix_seconds,
            now,
        )?;
        if iteration.structural_grammar_digest != iteration.envelope.grammar_digest
            || iteration.request.admission.objective_digest != iteration.envelope.objective_digest
            || iteration.request.changes.len()
                > usize::from(iteration.envelope.maximum_candidates.saturating_sub(1))
        {
            return Err(ControlEngineeringPlasticityErrorV1::Binding(
                "topology envelope context or candidate budget",
            ));
        }
        let generation_payload = topology_generation_signing_payload_v1(&iteration.request)
            .map_err(|_| {
                ControlEngineeringPlasticityErrorV1::Binding("topology generation payload")
            })?;
        let generation_digest = Digest32::of_bytes(&generation_payload);
        let expected_proposal_id = topology_iteration_proposal_id_v1(
            envelope_digest,
            iteration.request.candidate_generation,
            generation_digest,
            iteration.structural_grammar_digest,
        )?;
        if iteration.request.proposal_id != expected_proposal_id {
            return Err(ControlEngineeringPlasticityErrorV1::Binding(
                "deterministic topology proposal identity",
            ));
        }

        let product = self
            .producer
            .submit_topology_with_control(
                iteration.request,
                now,
                iteration.deadline_unix_seconds,
                cancellation,
            )
            .await?;
        let terminal = topology_terminal_receipt(envelope_digest, product)?;
        self.persist_terminal(terminal).await
    }

    async fn persist_terminal(
        &self,
        terminal: PlasticityIterationTerminalReceiptV1,
    ) -> Result<PersistedPlasticityIterationReceiptV1, ControlEngineeringPlasticityErrorV1> {
        let journal = Arc::clone(&self.journal);
        let persisted_terminal = terminal.clone();
        let append = tokio::task::spawn_blocking(move || {
            let mut journal = journal
                .lock()
                .map_err(|_| PlasticityIterationJournalErrorV1::Poisoned)?;
            journal.append(persisted_terminal)
        })
        .await
        .map_err(|_| ControlEngineeringPlasticityErrorV1::JournalWorkerFailed)??;
        Ok(PersistedPlasticityIterationReceiptV1 {
            terminal,
            journal: append,
        })
    }
}

pub fn iteration_envelope_digest_v1(
    envelope: &IterationEnvelopeV1,
) -> Result<Digest32, ControlEngineeringPlasticityErrorV1> {
    envelope
        .validate()
        .map_err(ControlEngineeringPlasticityErrorV1::InvalidEnvelope)?;
    let mut bytes = b"hepta.control-engineering.plasticity-iteration-envelope.v1\0".to_vec();
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
    envelope_digest: Digest32,
    candidate_generation: Generation,
    generator_digest: Digest32,
    coverage_digest: Digest32,
) -> Result<StableId, ControlEngineeringPlasticityErrorV1> {
    if envelope_digest.is_zero() || generator_digest.is_zero() || coverage_digest.is_zero() {
        return Err(ControlEngineeringPlasticityErrorV1::Binding(
            "parameter proposal identity digest",
        ));
    }
    let mut bytes = b"hepta.control-engineering.parameter-iteration-proposal.v1\0".to_vec();
    bytes.extend_from_slice(envelope_digest.as_array());
    bytes.extend_from_slice(&candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(generator_digest.as_array());
    bytes.extend_from_slice(coverage_digest.as_array());
    StableId::new(format!(
        "iteration:parameter:{}",
        Digest32::of_bytes(&bytes)
    ))
    .map_err(|_| ControlEngineeringPlasticityErrorV1::Identity)
}

pub fn topology_iteration_proposal_id_v1(
    envelope_digest: Digest32,
    candidate_generation: Generation,
    generation_digest: Digest32,
    structural_grammar_digest: Digest32,
) -> Result<StableId, ControlEngineeringPlasticityErrorV1> {
    if envelope_digest.is_zero()
        || generation_digest.is_zero()
        || structural_grammar_digest.is_zero()
    {
        return Err(ControlEngineeringPlasticityErrorV1::Binding(
            "topology proposal identity digest",
        ));
    }
    let mut bytes = b"hepta.control-engineering.topology-iteration-proposal.v1\0".to_vec();
    bytes.extend_from_slice(envelope_digest.as_array());
    bytes.extend_from_slice(&candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(generation_digest.as_array());
    bytes.extend_from_slice(structural_grammar_digest.as_array());
    StableId::new(format!(
        "iteration:topology:{}",
        Digest32::of_bytes(&bytes)
    ))
    .map_err(|_| ControlEngineeringPlasticityErrorV1::Identity)
}

fn validate_envelope_and_deadline(
    envelope: &IterationEnvelopeV1,
    deadline: u64,
    now: u64,
) -> Result<Digest32, ControlEngineeringPlasticityErrorV1> {
    let digest = iteration_envelope_digest_v1(envelope)?;
    if now >= envelope.expiry_unix_seconds {
        return Err(ControlEngineeringPlasticityErrorV1::Expired);
    }
    if deadline <= now || deadline > envelope.expiry_unix_seconds {
        return Err(ControlEngineeringPlasticityErrorV1::InvalidDeadline);
    }
    Ok(digest)
}

fn parameter_terminal_receipt(
    envelope_digest: Digest32,
    coverage: GeneratorCoverageReceiptV1,
    product: ParameterPlasticityProductReceiptV1,
) -> Result<PlasticityIterationTerminalReceiptV1, ControlEngineeringPlasticityErrorV1> {
    if product.proposal.authority.grants_any()
        || product.registry.authority.grants_any()
        || product.proposal.proposal_id != product.registry.proposal_id
    {
        return Err(ControlEngineeringPlasticityErrorV1::TerminalMismatch);
    }
    let terminal = match (product.disposition, coverage.disposition) {
        (
            ParameterPlasticityDispositionV1::UpdateCandidates,
            GeneratorCoverageDispositionV1::CompleteSearch,
        ) => PlasticityIterationTerminalV1::UpdateCandidates,
        (
            ParameterPlasticityDispositionV1::NoAdmissibleUpdate,
            GeneratorCoverageDispositionV1::CompleteSearch,
        ) => PlasticityIterationTerminalV1::NoAdmissibleUpdate,
        (
            ParameterPlasticityDispositionV1::NoAdmissibleUpdate,
            GeneratorCoverageDispositionV1::ZeroEligibleSignals,
        ) => PlasticityIterationTerminalV1::ZeroEligibleSignals,
        (
            ParameterPlasticityDispositionV1::NoAdmissibleUpdate,
            GeneratorCoverageDispositionV1::PolicyDisabledUpdates,
        ) => PlasticityIterationTerminalV1::PolicyDisabledUpdates,
        _ => return Err(ControlEngineeringPlasticityErrorV1::TerminalMismatch),
    };
    Ok(build_terminal_receipt_v1(
        envelope_digest,
        product.proposal.proposal_id,
        product.proposal.candidate_generation,
        PlasticityIterationKindV1::Parameter,
        terminal,
        Some(coverage.coverage_digest),
        product.registry.sequence,
        product.registry.frame_digest,
        product.composition_digest,
        false,
    )?)
}

fn topology_terminal_receipt(
    envelope_digest: Digest32,
    product: TopologyPlasticityProductReceiptV1,
) -> Result<PlasticityIterationTerminalReceiptV1, ControlEngineeringPlasticityErrorV1> {
    if product.governed.proposal.authority.grants_any()
        || product.durable.authority.grants_any()
        || product.governed.proposal.proposal_id != product.durable.proposal_id
    {
        return Err(ControlEngineeringPlasticityErrorV1::TerminalMismatch);
    }
    let terminal = if product
        .governed
        .proposal
        .candidates
        .iter()
        .any(|candidate| !candidate.changes.is_empty())
    {
        PlasticityIterationTerminalV1::TopologyCandidates
    } else {
        PlasticityIterationTerminalV1::NoTopologyChange
    };
    Ok(build_terminal_receipt_v1(
        envelope_digest,
        product.governed.proposal.proposal_id,
        product.governed.proposal.candidate_generation,
        PlasticityIterationKindV1::Topology,
        terminal,
        None,
        product.durable.sequence,
        product.durable.frame_digest,
        product.composition_digest,
        false,
    )?)
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), ControlEngineeringPlasticityErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| ControlEngineeringPlasticityErrorV1::Arithmetic)?;
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
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }
    fn envelope() -> IterationEnvelopeV1 {
        IterationEnvelopeV1 {
            envelope_id: id("iteration:plasticity:1"),
            base_commit: digest(b"commit"),
            base_tree: digest(b"tree"),
            objective_digest: digest(b"objective"),
            grammar_digest: digest(b"grammar"),
            maximum_files: 10,
            maximum_diff_bytes: 1024,
            maximum_candidates: 4,
            maximum_parallel_sandboxes: 2,
            expiry_unix_seconds: 100,
        }
    }

    #[test]
    fn envelope_and_proposal_identity_bind_every_frozen_context() {
        let first = iteration_envelope_digest_v1(&envelope()).expect("envelope");
        let mut changed = envelope();
        changed.base_tree = digest(b"other-tree");
        let second = iteration_envelope_digest_v1(&changed).expect("changed");
        assert_ne!(first, second);

        let parameter = parameter_iteration_proposal_id_v1(
            first,
            generation(2),
            digest(b"generator"),
            digest(b"coverage"),
        )
        .expect("parameter id");
        let changed_generation = parameter_iteration_proposal_id_v1(
            first,
            generation(3),
            digest(b"generator"),
            digest(b"coverage"),
        )
        .expect("changed generation");
        assert_ne!(parameter, changed_generation);
    }

    #[test]
    fn deadline_must_be_live_and_inside_the_envelope() {
        assert!(validate_envelope_and_deadline(&envelope(), 99, 1).is_ok());
        assert!(matches!(
            validate_envelope_and_deadline(&envelope(), 101, 1),
            Err(ControlEngineeringPlasticityErrorV1::InvalidDeadline)
        ));
        assert!(matches!(
            validate_envelope_and_deadline(&envelope(), 100, 100),
            Err(ControlEngineeringPlasticityErrorV1::Expired)
        ));
    }

    #[test]
    fn topology_identity_binds_the_control_engineering_grammar() {
        let envelope_digest = iteration_envelope_digest_v1(&envelope()).expect("envelope");
        let first = topology_iteration_proposal_id_v1(
            envelope_digest,
            generation(2),
            digest(b"generation"),
            envelope().grammar_digest,
        )
        .expect("first");
        let second = topology_iteration_proposal_id_v1(
            envelope_digest,
            generation(2),
            digest(b"generation"),
            digest(b"other-grammar"),
        )
        .expect("second");
        assert_ne!(first, second);
    }
}
