//! Non-test control.engineering coordinator for governed plasticity submission.
//!
//! The coordinator freezes one exact `IterationEnvelopeV1` against an artifact,
//! proposal window, mutation grammar and generation transition. It verifies the
//! deterministic generator and Observer-signed coverage proof, submits only through
//! the named Agentd learning producer, and durably records an idempotent terminal
//! receipt. It owns no proposal-registry writer and has no selection, installation,
//! topology-application, activation, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_intelligence::CoveredParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::CoveredParameterPlasticityProductRequestV1;
use codex_hepta_intelligence::ParameterPlasticityDispositionV1;
use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::plasticity_admission_signing_payload_v1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_plasticity::GeneratorCoverageErrorV1;
use codex_hepta_plasticity::GeneratorCoverageTerminalV1;
use codex_hepta_plasticity::ParameterGeneratorErrorV3;
use codex_hepta_plasticity::ParameterMutationSurfaceV1;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::generator_coverage_signing_payload_v1;
use codex_hepta_plasticity::verify_generated_parameter_candidates_v3;
use codex_hepta_plasticity::verify_generator_coverage_receipt_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio_util::sync::CancellationToken;

use crate::IterationPlasticityJournalAppendV1;
use crate::IterationPlasticityJournalErrorV1;
use crate::IterationPlasticityKindV1;
use crate::IterationPlasticityTerminalJournalV1;
use crate::IterationPlasticityTerminalReceiptV1;
use crate::IterationPlasticityTerminalV1;
use crate::PlasticityRuntimeCallErrorV1;
use crate::PlasticityRuntimeHandleV1;
use crate::PlasticityRuntimeRequestBudgetV1;
use crate::PlasticityRuntimeTelemetryV1;
use crate::plasticity_learning_producer::AgentdLearningPlasticityProducerV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenIterationPlasticityContextV1 {
    pub envelope: IterationEnvelopeV1,
    pub envelope_digest: Digest32,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub freeze_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IterationPlasticityCoordinatorDispositionV1 {
    Submitted,
    Replayed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IterationParameterSubmissionReceiptV1 {
    pub disposition: IterationPlasticityCoordinatorDispositionV1,
    pub terminal: IterationPlasticityTerminalReceiptV1,
    pub product: Option<CoveredParameterPlasticityProductReceiptV1>,
    pub runtime_telemetry: Option<PlasticityRuntimeTelemetryV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IterationTopologySubmissionReceiptV1 {
    pub disposition: IterationPlasticityCoordinatorDispositionV1,
    pub terminal: IterationPlasticityTerminalReceiptV1,
    pub product: Option<TopologyPlasticityProductReceiptV1>,
    pub runtime_telemetry: Option<PlasticityRuntimeTelemetryV1>,
}

#[derive(Debug)]
pub enum IterationPlasticityCoordinatorErrorV1 {
    Envelope(String),
    Expired,
    FreezeBinding(&'static str),
    CandidateBudget,
    Coverage(GeneratorCoverageErrorV1),
    Generator(ParameterGeneratorErrorV3),
    Evidence(SignedEvidenceError),
    Runtime(PlasticityRuntimeCallErrorV1),
    Journal(IterationPlasticityJournalErrorV1),
    TerminalJournalAfterCommit {
        product_composition_digest: Digest32,
        journal: IterationPlasticityJournalErrorV1,
    },
}

impl fmt::Display for IterationPlasticityCoordinatorErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for IterationPlasticityCoordinatorErrorV1 {}
impl From<GeneratorCoverageErrorV1> for IterationPlasticityCoordinatorErrorV1 {
    fn from(value: GeneratorCoverageErrorV1) -> Self {
        Self::Coverage(value)
    }
}
impl From<ParameterGeneratorErrorV3> for IterationPlasticityCoordinatorErrorV1 {
    fn from(value: ParameterGeneratorErrorV3) -> Self {
        Self::Generator(value)
    }
}
impl From<SignedEvidenceError> for IterationPlasticityCoordinatorErrorV1 {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}
impl From<PlasticityRuntimeCallErrorV1> for IterationPlasticityCoordinatorErrorV1 {
    fn from(value: PlasticityRuntimeCallErrorV1) -> Self {
        Self::Runtime(value)
    }
}
impl From<IterationPlasticityJournalErrorV1> for IterationPlasticityCoordinatorErrorV1 {
    fn from(value: IterationPlasticityJournalErrorV1) -> Self {
        Self::Journal(value)
    }
}

/// One frozen control.engineering work item. The producer is the same bounded,
/// state-held Agentd façade used by the daemon; mutable writers remain exclusively
/// inside `PlasticityRuntimeOwnerV1`.
pub struct ControlEngineeringPlasticityCoordinatorV1 {
    context: FrozenIterationPlasticityContextV1,
    producer: AgentdLearningPlasticityProducerV1,
    verifier: LearningEvidenceVerifierV1,
    terminal_journal: IterationPlasticityTerminalJournalV1,
}

pub fn freeze_iteration_plasticity_context_v1(
    envelope: IterationEnvelopeV1,
    selected_artifact_digest: Digest32,
    window: ProposalWindowV2,
    baseline_generation: Generation,
    candidate_generation: Generation,
    now: u64,
) -> Result<FrozenIterationPlasticityContextV1, IterationPlasticityCoordinatorErrorV1> {
    envelope
        .validate()
        .map_err(IterationPlasticityCoordinatorErrorV1::Envelope)?;
    if now > envelope.expiry_unix_seconds {
        return Err(IterationPlasticityCoordinatorErrorV1::Expired);
    }
    if selected_artifact_digest.is_zero() || window.window_digest.is_zero() {
        return Err(IterationPlasticityCoordinatorErrorV1::FreezeBinding(
            "artifact/window",
        ));
    }
    if baseline_generation.next() != Ok(candidate_generation) {
        return Err(IterationPlasticityCoordinatorErrorV1::FreezeBinding(
            "generation successor",
        ));
    }
    let envelope_digest = iteration_envelope_digest_v1(&envelope)?;
    let mut bytes = b"hepta.control-engineering.plasticity-freeze.v1\0".to_vec();
    bytes.extend_from_slice(envelope_digest.as_array());
    bytes.extend_from_slice(selected_artifact_digest.as_array());
    push_id(&mut bytes, &window.window_id)?;
    bytes.extend_from_slice(window.window_digest.as_array());
    bytes.extend_from_slice(&baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&candidate_generation.get().to_be_bytes());
    let freeze_digest = Digest32::of_bytes(&bytes);
    Ok(FrozenIterationPlasticityContextV1 {
        envelope,
        envelope_digest,
        selected_artifact_digest,
        window,
        baseline_generation,
        candidate_generation,
        freeze_digest,
    })
}

pub fn iteration_envelope_digest_v1(
    envelope: &IterationEnvelopeV1,
) -> Result<Digest32, IterationPlasticityCoordinatorErrorV1> {
    envelope
        .validate()
        .map_err(IterationPlasticityCoordinatorErrorV1::Envelope)?;
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

impl ControlEngineeringPlasticityCoordinatorV1 {
    pub fn new(
        context: FrozenIterationPlasticityContextV1,
        runtime: PlasticityRuntimeHandleV1,
        verifier: LearningEvidenceVerifierV1,
        journal_file: File,
        maximum_terminal_records: usize,
    ) -> Result<Self, IterationPlasticityCoordinatorErrorV1> {
        if context.envelope_digest != iteration_envelope_digest_v1(&context.envelope)?
            || context.freeze_digest.is_zero()
        {
            return Err(IterationPlasticityCoordinatorErrorV1::FreezeBinding(
                "context digest",
            ));
        }
        let terminal_journal = IterationPlasticityTerminalJournalV1::open(
            journal_file,
            context.freeze_digest,
            maximum_terminal_records,
        )?;
        Ok(Self {
            context,
            producer: AgentdLearningPlasticityProducerV1::new(runtime),
            verifier,
            terminal_journal,
        })
    }

    pub const fn context(&self) -> &FrozenIterationPlasticityContextV1 {
        &self.context
    }

    pub fn terminal_anchor(&self) -> Option<crate::IterationPlasticityJournalAnchorV1> {
        self.terminal_journal.current_anchor()
    }

    pub async fn submit_parameter(
        &mut self,
        request: CoveredParameterPlasticityProductRequestV1,
        now: u64,
        budget: PlasticityRuntimeRequestBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<IterationParameterSubmissionReceiptV1, IterationPlasticityCoordinatorErrorV1> {
        self.validate_live_context(now)?;
        self.validate_parameter_request(&request, now)?;
        let proposal_id = request.product.proposal_id.clone();
        if let Some(receipt) = self.terminal_journal.get(
            self.context.envelope_digest,
            self.context.candidate_generation,
            &proposal_id,
        ) {
            return Ok(IterationParameterSubmissionReceiptV1 {
                disposition: IterationPlasticityCoordinatorDispositionV1::Replayed,
                terminal: receipt.clone(),
                product: None,
                runtime_telemetry: None,
            });
        }

        let outcome = self
            .producer
            .submit_covered_parameter(
                request,
                now,
                self.effective_budget(budget)?,
                cancellation,
            )
            .await?;
        let terminal = parameter_terminal(&outcome.receipt);
        let product_composition_digest = outcome.receipt.composition_digest;
        let journal = self
            .terminal_journal
            .append(
                self.context.envelope.envelope_id.clone(),
                self.context.envelope_digest,
                self.context.candidate_generation,
                proposal_id,
                product_composition_digest,
                IterationPlasticityKindV1::Parameter,
                terminal,
            )
            .map_err(|journal| {
                IterationPlasticityCoordinatorErrorV1::TerminalJournalAfterCommit {
                    product_composition_digest,
                    journal,
                }
            })?;
        Ok(parameter_submission(outcome.receipt, outcome.telemetry, journal))
    }

    pub async fn submit_topology(
        &mut self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
        budget: PlasticityRuntimeRequestBudgetV1,
        cancellation: CancellationToken,
    ) -> Result<IterationTopologySubmissionReceiptV1, IterationPlasticityCoordinatorErrorV1> {
        self.validate_live_context(now)?;
        self.validate_topology_request(&request)?;
        let proposal_id = request.proposal_id.clone();
        if let Some(receipt) = self.terminal_journal.get(
            self.context.envelope_digest,
            self.context.candidate_generation,
            &proposal_id,
        ) {
            return Ok(IterationTopologySubmissionReceiptV1 {
                disposition: IterationPlasticityCoordinatorDispositionV1::Replayed,
                terminal: receipt.clone(),
                product: None,
                runtime_telemetry: None,
            });
        }

        let outcome = self
            .producer
            .submit_topology_bounded(
                request,
                now,
                self.effective_budget(budget)?,
                cancellation,
            )
            .await?;
        let product_composition_digest = outcome.receipt.composition_digest;
        let journal = self
            .terminal_journal
            .append(
                self.context.envelope.envelope_id.clone(),
                self.context.envelope_digest,
                self.context.candidate_generation,
                proposal_id,
                product_composition_digest,
                IterationPlasticityKindV1::Topology,
                IterationPlasticityTerminalV1::TopologyProposal,
            )
            .map_err(|journal| {
                IterationPlasticityCoordinatorErrorV1::TerminalJournalAfterCommit {
                    product_composition_digest,
                    journal,
                }
            })?;
        Ok(topology_submission(outcome.receipt, outcome.telemetry, journal))
    }

    fn validate_live_context(
        &self,
        now: u64,
    ) -> Result<(), IterationPlasticityCoordinatorErrorV1> {
        if now > self.context.envelope.expiry_unix_seconds {
            return Err(IterationPlasticityCoordinatorErrorV1::Expired);
        }
        if self.context.envelope_digest != iteration_envelope_digest_v1(&self.context.envelope)? {
            return Err(IterationPlasticityCoordinatorErrorV1::FreezeBinding(
                "envelope drift",
            ));
        }
        Ok(())
    }

    fn validate_parameter_request(
        &self,
        request: &CoveredParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<(), IterationPlasticityCoordinatorErrorV1> {
        let product = &request.product;
        if product.generated.selected_artifact_digest != self.context.selected_artifact_digest
            || product.generated.window != self.context.window
            || product.admission.selected_artifact_digest != self.context.selected_artifact_digest
            || product.admission.window != self.context.window
            || product.admission.objective_digest != self.context.envelope.objective_digest
            || product.admission.baseline_generation != self.context.baseline_generation
            || product.admission.candidate_generation != self.context.candidate_generation
            || product
                .generator_profile
                .mutation_policy
                .mutation_grammar_digest
                != self.context.envelope.grammar_digest
        {
            return Err(IterationPlasticityCoordinatorErrorV1::FreezeBinding(
                "parameter request",
            ));
        }
        if product.generated.candidates.len()
            > usize::from(self.context.envelope.maximum_candidates)
        {
            return Err(IterationPlasticityCoordinatorErrorV1::CandidateBudget);
        }
        verify_generated_parameter_candidates_v3(
            product.generator_profile.clone(),
            &product.generated,
        )?;
        verify_generator_coverage_receipt_v1(&product.generator_profile, &request.coverage)?;
        let mut expected = product
            .generator_profile
            .mutation_policy
            .rules
            .iter()
            .filter(|rule| rule.surface == ParameterMutationSurfaceV1::LearnableParameter)
            .map(|rule| rule.parameter_id.clone())
            .collect::<Vec<_>>();
        expected.sort();
        if expected != request.coverage.expected_parameter_ids {
            return Err(IterationPlasticityCoordinatorErrorV1::FreezeBinding(
                "learnable parameter coverage",
            ));
        }
        let coverage_observer = self.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &request.coverage_attestation,
            &generator_coverage_signing_payload_v1(&request.coverage),
            now,
        )?;
        let admission_observer = self.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &product.admission_attestation,
            &plasticity_admission_signing_payload_v1(&product.admission),
            now,
        )?;
        if coverage_observer.principal() != admission_observer.principal() {
            return Err(IterationPlasticityCoordinatorErrorV1::FreezeBinding(
                "coverage observer",
            ));
        }
        Ok(())
    }

    fn validate_topology_request(
        &self,
        request: &TopologyPlasticityProductRequestV1,
    ) -> Result<(), IterationPlasticityCoordinatorErrorV1> {
        if request.selected_artifact_digest != self.context.selected_artifact_digest
            || request.window != self.context.window
            || request.admission.objective_digest != self.context.envelope.objective_digest
            || request.baseline_generation != self.context.baseline_generation
            || request.candidate_generation != self.context.candidate_generation
            || request.admission.baseline_generation != self.context.baseline_generation
            || request.admission.candidate_generation != self.context.candidate_generation
            || request.changes.len() > usize::from(self.context.envelope.maximum_candidates)
        {
            return Err(IterationPlasticityCoordinatorErrorV1::FreezeBinding(
                "topology request",
            ));
        }
        Ok(())
    }

    fn effective_budget(
        &self,
        budget: PlasticityRuntimeRequestBudgetV1,
    ) -> Result<PlasticityRuntimeRequestBudgetV1, IterationPlasticityCoordinatorErrorV1> {
        let envelope_bytes = usize::try_from(self.context.envelope.maximum_diff_bytes)
            .map_err(|_| IterationPlasticityCoordinatorErrorV1::CandidateBudget)?;
        Ok(PlasticityRuntimeRequestBudgetV1::bounded(
            budget.maximum_encoded_bytes.min(envelope_bytes),
            budget.maximum_work_units,
            budget
                .deadline_unix_seconds
                .min(self.context.envelope.expiry_unix_seconds),
        ))
    }
}

fn parameter_terminal(
    receipt: &CoveredParameterPlasticityProductReceiptV1,
) -> IterationPlasticityTerminalV1 {
    match receipt.coverage.terminal {
        GeneratorCoverageTerminalV1::ZeroEligibleSignals => {
            IterationPlasticityTerminalV1::ZeroEligibleSignals
        }
        GeneratorCoverageTerminalV1::PolicyDisabledUpdates => {
            IterationPlasticityTerminalV1::PolicyDisabledUpdates
        }
        GeneratorCoverageTerminalV1::Ready => match receipt.product.disposition {
            ParameterPlasticityDispositionV1::UpdateCandidates => {
                IterationPlasticityTerminalV1::UpdateCandidates
            }
            ParameterPlasticityDispositionV1::NoAdmissibleUpdate => {
                IterationPlasticityTerminalV1::NoAdmissibleUpdate
            }
        },
    }
}

fn parameter_submission(
    product: CoveredParameterPlasticityProductReceiptV1,
    runtime_telemetry: PlasticityRuntimeTelemetryV1,
    journal: IterationPlasticityJournalAppendV1,
) -> IterationParameterSubmissionReceiptV1 {
    IterationParameterSubmissionReceiptV1 {
        disposition: match journal.disposition {
            codex_hepta_plasticity::AppendDisposition::Inserted => {
                IterationPlasticityCoordinatorDispositionV1::Submitted
            }
            codex_hepta_plasticity::AppendDisposition::Unchanged => {
                IterationPlasticityCoordinatorDispositionV1::Replayed
            }
        },
        terminal: journal.receipt,
        product: Some(product),
        runtime_telemetry: Some(runtime_telemetry),
    }
}

fn topology_submission(
    product: TopologyPlasticityProductReceiptV1,
    runtime_telemetry: PlasticityRuntimeTelemetryV1,
    journal: IterationPlasticityJournalAppendV1,
) -> IterationTopologySubmissionReceiptV1 {
    IterationTopologySubmissionReceiptV1 {
        disposition: match journal.disposition {
            codex_hepta_plasticity::AppendDisposition::Inserted => {
                IterationPlasticityCoordinatorDispositionV1::Submitted
            }
            codex_hepta_plasticity::AppendDisposition::Unchanged => {
                IterationPlasticityCoordinatorDispositionV1::Replayed
            }
        },
        terminal: journal.receipt,
        product: Some(product),
        runtime_telemetry: Some(runtime_telemetry),
    }
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), IterationPlasticityCoordinatorErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| {
        IterationPlasticityCoordinatorErrorV1::FreezeBinding("identifier length")
    })?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
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
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }
    fn envelope() -> IterationEnvelopeV1 {
        IterationEnvelopeV1 {
            envelope_id: id("envelope:plasticity:1"),
            base_commit: digest(b"commit"),
            base_tree: digest(b"tree"),
            objective_digest: digest(b"objective"),
            grammar_digest: digest(b"grammar"),
            maximum_files: 8,
            maximum_diff_bytes: 32 * 1024,
            maximum_candidates: 8,
            maximum_parallel_sandboxes: 2,
            expiry_unix_seconds: 100,
        }
    }

    #[test]
    fn freeze_binds_exact_source_artifact_window_and_generation() {
        let frozen = freeze_iteration_plasticity_context_v1(
            envelope(),
            digest(b"artifact"),
            ProposalWindowV2 {
                window_id: id("window:plasticity:1"),
                window_digest: digest(b"window"),
            },
            generation(7),
            generation(8),
            50,
        )
        .expect("freeze");
        assert!(!frozen.envelope_digest.is_zero());
        assert!(!frozen.freeze_digest.is_zero());

        let mut changed = envelope();
        changed.base_tree = digest(b"other-tree");
        assert_ne!(
            iteration_envelope_digest_v1(&changed).expect("digest"),
            frozen.envelope_digest
        );
    }

    #[test]
    fn freeze_rejects_expired_or_non_successor_context() {
        assert!(matches!(
            freeze_iteration_plasticity_context_v1(
                envelope(),
                digest(b"artifact"),
                ProposalWindowV2 {
                    window_id: id("window:plasticity:1"),
                    window_digest: digest(b"window"),
                },
                generation(7),
                generation(8),
                101,
            ),
            Err(IterationPlasticityCoordinatorErrorV1::Expired)
        ));
        assert!(matches!(
            freeze_iteration_plasticity_context_v1(
                envelope(),
                digest(b"artifact"),
                ProposalWindowV2 {
                    window_id: id("window:plasticity:1"),
                    window_digest: digest(b"window"),
                },
                generation(7),
                generation(9),
                50,
            ),
            Err(IterationPlasticityCoordinatorErrorV1::FreezeBinding(_))
        ));
    }
}
