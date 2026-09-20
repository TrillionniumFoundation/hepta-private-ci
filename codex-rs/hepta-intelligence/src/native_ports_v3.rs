//! Native owner adapters for the canonical V3 composition graph.
//!
//! This profile calls the actual owner crates rather than manufacturing stage
//! receipts. It is still authority-free: owner results are proposals/evidence,
//! runtime.agentd owns the host handoff, and learning.ledger owns durable facts.
//! Authentication of external observations and hard I/O cancellation remain host
//! responsibilities.

use std::collections::BTreeSet;

use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::compile as compile_context;
use codex_hepta_intelligence_eval::Disposition as EvaluationDisposition;
use codex_hepta_intelligence_eval::EvaluationRequest;
use codex_hepta_intelligence_eval::evaluate as evaluate_independently;
use codex_hepta_intuition::Decision;
use codex_hepta_intuition::DecisionRequest;
use codex_hepta_intuition::IntuitionDecisionReceipt;
use codex_hepta_intuition::decide as decide_intuition;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates;
use codex_hepta_neuron::NeuronState;
use codex_hepta_neuron::StepRequest;
use codex_hepta_neuron::step as run_neuron;
use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ObjectiveSourceEnvelope;
use codex_hepta_objective::compile as compile_objective;
use codex_hepta_prompt_optimizer::OptimizationRequest;
use codex_hepta_prompt_optimizer::optimize as optimize_prompt;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::IntelligenceHostEnvelopeV1;
use crate::LaneFStageV3;
use crate::LaneFV3Ports;
use crate::LegalActionCandidateSetV1;
use crate::PortDecisionV3;
use crate::PortFailureClassV3;
use crate::PortFailureV3;
use crate::PortInputV3;
use crate::PortReceiptV3;

#[derive(Clone, Debug)]
pub struct LearningDecisionTemplateV3 {
    pub episode_id: StableId,
    pub policy_id: StableId,
}

#[derive(Clone, Debug)]
pub struct NativeV3OwnerInputs {
    pub expected_objective_digest: Digest32,
    pub legal_candidates: LegalActionCandidateSetV1,
    pub objective: ObjectiveSourceEnvelope,
    pub utility_set: ContributionSet,
    pub utility_profile: UtilityProfile,
    pub utility_scalarization: Option<ScalarizationProfile>,
    pub evaluation: EvaluationRequest,
    pub neuron: Option<StepRequest>,
    pub neuron_previous: Option<NeuronState>,
    pub prompt: Option<OptimizationRequest>,
    pub intuition: DecisionRequest,
    pub context: CompilationRequest,
    pub learning: LearningDecisionTemplateV3,
}

pub trait HostEnvelopePortV3 {
    fn accept_host_envelope_v3(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3>;
}

pub struct NativeV3OwnerPorts<'a, H> {
    inputs: NativeV3OwnerInputs,
    ledger: &'a mut dyn DurableLearningJournal,
    expected_ledger_head: Digest32,
    host: H,
    last_intuition: Option<IntuitionDecisionReceipt>,
    learning_append: Option<AppendReceipt>,
}

impl<'a, H> NativeV3OwnerPorts<'a, H> {
    pub fn new(
        inputs: NativeV3OwnerInputs,
        ledger: &'a mut dyn DurableLearningJournal,
        expected_ledger_head: Digest32,
        host: H,
    ) -> Self {
        Self {
            inputs,
            ledger,
            expected_ledger_head,
            host,
            last_intuition: None,
            learning_append: None,
        }
    }

    #[must_use]
    pub fn learning_append(&self) -> Option<&AppendReceipt> {
        self.learning_append.as_ref()
    }

    #[must_use]
    pub fn host(&self) -> &H {
        &self.host
    }

    pub fn host_mut(&mut self) -> &mut H {
        &mut self.host
    }
}

impl<H: HostEnvelopePortV3> LaneFV3Ports for NativeV3OwnerPorts<'_, H> {
    fn validate_objective(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        let compiled = compile_objective(self.inputs.objective.clone())
            .map_err(|_| failure(input, PortFailureClassV3::Rejected, "objective-error"))?
            .map_err(|conflict| PortFailureV3 {
                class: PortFailureClassV3::Rejected,
                evidence_digest: conflict.conflict_digest,
            })?;
        if compiled.disposition != CompileDisposition::Compiled
            || compiled.objective.semantic_digest != self.inputs.expected_objective_digest
        {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "objective-binding",
            ));
        }
        let objective_candidates = compiled
            .objective
            .legal_actions
            .iter()
            .map(|action| action.id.clone())
            .collect::<BTreeSet<_>>();
        let declared_candidates = self
            .inputs
            .legal_candidates
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        if objective_candidates != declared_candidates {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "legal-candidate-objective-binding",
            ));
        }
        success(
            input,
            "objective.compiler",
            compiled.objective.semantic_digest,
        )
    }

    fn evaluate_utility(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        if self.inputs.utility_set.objective_digest != self.inputs.expected_objective_digest {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "utility-objective",
            ));
        }
        let utility_candidates = self
            .inputs
            .utility_set
            .contributions
            .iter()
            .map(|contribution| contribution.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        let legal_candidates = self
            .inputs
            .legal_candidates
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        if utility_candidates != legal_candidates {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "utility-candidate-binding",
            ));
        }
        let receipt = evaluate_candidates(
            self.inputs.utility_set.clone(),
            self.inputs.utility_profile.clone(),
            self.inputs.utility_scalarization.clone(),
        )
        .map_err(|_| failure(input, PortFailureClassV3::Rejected, "utility-error"))?;
        success(input, "utility.ndu", receipt.evaluation_digest)
    }

    fn admit_evaluation(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        if self.inputs.evaluation.objective_digest != self.inputs.expected_objective_digest {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "evaluation-objective",
            ));
        }
        let receipt = evaluate_independently(self.inputs.evaluation.clone())
            .map_err(|_| failure(input, PortFailureClassV3::Rejected, "evaluation-error"))?;
        if receipt.disposition != EvaluationDisposition::EligibleForFurtherReview {
            return Err(PortFailureV3 {
                class: PortFailureClassV3::Rejected,
                evidence_digest: receipt.evidence_digest,
            });
        }
        success(input, "learning.eval", receipt.evidence_digest)
    }

    fn collect_neural_signal(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let Some(mut request) = self.inputs.neuron.clone() else {
            return Err(failure(
                input,
                PortFailureClassV3::Unavailable,
                "neuron-absent",
            ));
        };
        if request.run_id != input.run_id {
            return Err(failure(input, PortFailureClassV3::Rejected, "neuron-run"));
        }
        request.source_digest = input.predecessor_digest;
        let (_, receipt) = run_neuron(request, self.inputs.neuron_previous.as_ref())
            .map_err(|_| failure(input, PortFailureClassV3::Rejected, "neuron-error"))?;
        if receipt.authority.grants_any() {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "neuron-authority",
            ));
        }
        success(input, "neuron.runtime", receipt.signal_digest)
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        let Some(mut request) = self.inputs.prompt.clone() else {
            return Err(failure(
                input,
                PortFailureClassV3::Unavailable,
                "prompt-absent",
            ));
        };
        if request.objective_digest != self.inputs.expected_objective_digest {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "prompt-objective",
            ));
        }
        request.decision_id = input.run_id.clone();
        let receipt = optimize_prompt(request)
            .map_err(|_| failure(input, PortFailureClassV3::Rejected, "prompt-error"))?;
        if receipt.authority.grants_any() {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "prompt-authority",
            ));
        }
        success(input, "prompt.optimizer", receipt.receipt_digest)
    }

    fn decide_intuition(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        let mut request = self.inputs.intuition.clone();
        if request.objective_digest != self.inputs.expected_objective_digest
            || request.candidate_set_digest != self.inputs.legal_candidates.candidate_set_digest
        {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "intuition-binding",
            ));
        }
        let intuition_candidates = request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        let legal_candidates = self
            .inputs
            .legal_candidates
            .candidates
            .iter()
            .filter(|candidate| candidate.candidate_id.as_str() != "abstain")
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        if intuition_candidates != legal_candidates {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "intuition-candidate-binding",
            ));
        }
        request.decision_id = input.run_id.clone();
        let receipt = decide_intuition(request)
            .map_err(|_| failure(input, PortFailureClassV3::Rejected, "intuition-error"))?;
        if receipt.authority.grants_any() {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "intuition-authority",
            ));
        }
        let decision = match receipt.decision {
            Decision::Selected(_) => PortDecisionV3::Continue,
            Decision::Abstained(_) => PortDecisionV3::Abstain,
        };
        let result =
            success_with_decision(input, "intuition.policy", receipt.receipt_digest, decision);
        self.last_intuition = Some(receipt);
        result
    }

    fn compile_context(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        let mut request = self.inputs.context.clone();
        if request.objective_digest != self.inputs.expected_objective_digest {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "context-objective",
            ));
        }
        request.run_snapshot_digest = input.snapshot_digest;
        let receipt = compile_context(request)
            .map_err(|_| failure(input, PortFailureClassV3::Rejected, "context-error"))?;
        if receipt.authority.grants_any() {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "context-authority",
            ));
        }
        success(input, "context.compiler", receipt.context_digest)
    }

    fn accept_host_envelope(
        &mut self,
        input: &PortInputV3,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.host.accept_host_envelope_v3(input, envelope)
    }

    fn record_learning(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        let intuition = self.last_intuition.as_ref().ok_or_else(|| {
            failure(
                input,
                PortFailureClassV3::Rejected,
                "missing-intuition-receipt",
            )
        })?;
        let abstain = stable_id("abstain", input)?;
        let (selected, propensity) = match &intuition.decision {
            Decision::Selected(candidate) => {
                let propensity = intuition
                    .propensities
                    .iter()
                    .find(|row| &row.candidate_id == candidate)
                    .map(|row| row.probability)
                    .ok_or_else(|| {
                        failure(input, PortFailureClassV3::Rejected, "missing-propensity")
                    })?;
                (candidate.clone(), propensity)
            }
            Decision::Abstained(_) => (abstain.clone(), intuition.abstain_probability),
        };
        if propensity.raw() == 0 {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "zero-propensity",
            ));
        }
        let mut candidate_ids = self
            .inputs
            .legal_candidates
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        if !candidate_ids.contains(&abstain) {
            candidate_ids.push(abstain);
        }
        let event = LedgerEvent::Decision(EpisodeDecision {
            record_id: input.run_id.clone(),
            episode_id: self.inputs.learning.episode_id.clone(),
            objective_digest: self.inputs.expected_objective_digest,
            policy_id: self.inputs.learning.policy_id.clone(),
            candidate_ids,
            selected_candidate_id: selected,
            selected_propensity: propensity,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: input.predecessor_digest,
        });
        let receipt = self
            .ledger
            .append(self.expected_ledger_head, event)
            .map_err(|_| failure(input, PortFailureClassV3::Indeterminate, "ledger-append"))?;
        let output = receipt.chain_digest;
        self.learning_append = Some(receipt);
        success(input, "learning.ledger", output)
    }
}

fn success(
    input: &PortInputV3,
    producer: &str,
    output_digest: Digest32,
) -> Result<PortReceiptV3, PortFailureV3> {
    success_with_decision(input, producer, output_digest, PortDecisionV3::Continue)
}

fn success_with_decision(
    input: &PortInputV3,
    producer: &str,
    output_digest: Digest32,
    decision: PortDecisionV3,
) -> Result<PortReceiptV3, PortFailureV3> {
    let producer = StableId::new(producer)
        .map_err(|_| failure(input, PortFailureClassV3::Rejected, "producer-id"))?;
    Ok(PortReceiptV3 {
        stage: input.stage,
        producer,
        snapshot_digest: input.snapshot_digest,
        predecessor_digest: input.predecessor_digest,
        output_digest,
        decision,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn stable_id(value: &str, input: &PortInputV3) -> Result<StableId, PortFailureV3> {
    StableId::new(value).map_err(|_| failure(input, PortFailureClassV3::Rejected, "stable-id"))
}

fn failure(input: &PortInputV3, class: PortFailureClassV3, label: &str) -> PortFailureV3 {
    let mut bytes = b"hepta.intelligence.native-v3-owner-failure\0".to_vec();
    bytes.push(stage_code(input.stage));
    bytes.extend_from_slice(input.snapshot_digest.as_array());
    bytes.extend_from_slice(input.predecessor_digest.as_array());
    bytes.extend_from_slice(label.as_bytes());
    PortFailureV3 {
        class,
        evidence_digest: Digest32::of_bytes(&bytes),
    }
}

const fn stage_code(stage: LaneFStageV3) -> u8 {
    match stage {
        LaneFStageV3::ObjectiveValidated => 0,
        LaneFStageV3::LegalSetBuilt => 1,
        LaneFStageV3::UtilityEvaluated => 2,
        LaneFStageV3::EvaluationAdmitted => 3,
        LaneFStageV3::NeuralSignalCollected => 4,
        LaneFStageV3::PromptPortfolioBuilt => 5,
        LaneFStageV3::IntuitionDecided => 6,
        LaneFStageV3::ContextCompiled => 7,
        LaneFStageV3::HostEnvelopeBuilt => 8,
        LaneFStageV3::HostHandoffAccepted => 9,
        LaneFStageV3::LearningRecorded => 10,
    }
}

#[cfg(test)]
#[path = "native_ports_v3_tests.rs"]
mod tests;
