//! Current-owner adapters for the canonical V3 composition graph.
//!
//! The adapter intentionally uses admitted/current owner APIs where they exist:
//! objective admission rather than raw compile, policy-bound NDU evaluation,
//! signed independent evaluation, sparse Neuron receipts and calibrated
//! Intuition V2. It remains authority-free and does not invoke Codex, tools,
//! providers or physical effects.

use std::collections::BTreeSet;

use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::compile as compile_context;
use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_intuition::decide_calibrated_v2;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseSignalReceipt;
use codex_hepta_neuron::SparseTick;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ObjectiveAdmissionContextV1;
use codex_hepta_objective::ObjectiveAdmissionProfileV1;
use codex_hepta_objective::ObjectiveSourceEnvelopeV1;
use codex_hepta_objective::admit_and_compile_objective_v1;
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

const ABSTAIN: &str = "abstain";
const SLOW_PATH: &str = "shadow:slow-path";

#[derive(Clone, Debug)]
pub struct NativeObjectiveInputV3 {
    pub envelope: ObjectiveSourceEnvelopeV1,
    pub profile: ObjectiveAdmissionProfileV1,
    pub context: ObjectiveAdmissionContextV1,
}

#[derive(Clone, Debug)]
pub struct NativeUtilityInputV3 {
    pub set: ContributionSet,
    pub profile: UtilityProfile,
    pub scalarization: Option<ScalarizationProfile>,
    pub policy: EvaluationPolicyV1,
}

#[derive(Clone, Debug)]
pub struct NativeEvaluationInputV3 {
    pub bundle: IndependentEvaluationBundleV1,
    pub roles: Vec<MetricRoleContractV2>,
    pub evidence: SignedEvaluationEvidenceV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub now: u64,
}

#[derive(Clone, Debug)]
pub struct NativeNeuronInputV3 {
    pub config: SparseConfig,
    pub tick: SparseTick,
    pub previous: Option<SparseCheckpoint>,
}

#[derive(Clone, Debug)]
pub struct LearningDecisionTemplateV3 {
    pub episode_id: StableId,
    pub policy_id: StableId,
}

#[derive(Clone, Debug)]
pub struct NativeV3OwnerInputs {
    pub expected_snapshot_digest: Digest32,
    pub expected_objective_digest: Digest32,
    pub expected_body_digest: Digest32,
    pub legal_candidates: LegalActionCandidateSetV1,
    pub objective: NativeObjectiveInputV3,
    pub utility: NativeUtilityInputV3,
    pub evaluation: NativeEvaluationInputV3,
    pub neuron: Option<NativeNeuronInputV3>,
    pub prompt: Option<OptimizationRequest>,
    pub intuition: CalibratedDecisionRequestV1,
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
    last_utility_digest: Option<Digest32>,
    last_intuition: Option<CalibratedIntuitionReceiptV1>,
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
            last_utility_digest: None,
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

    fn validate_common(&self, input: &PortInputV3) -> Result<(), PortFailureV3> {
        if input.snapshot_digest != self.inputs.expected_snapshot_digest
            || self.inputs.legal_candidates.state_digest != self.inputs.expected_snapshot_digest
        {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "snapshot-binding",
            ));
        }
        Ok(())
    }
}

impl<H: HostEnvelopePortV3> LaneFV3Ports for NativeV3OwnerPorts<'_, H> {
    fn validate_objective(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.validate_common(input)?;
        let outcome = admit_and_compile_objective_v1(
            &self.inputs.objective.envelope,
            &self.inputs.objective.profile,
            &self.inputs.objective.context,
        )
        .map_err(|_| failure(input, PortFailureClassV3::Rejected, "objective-admission"))?;
        if outcome.receipt.authority.grants_any() {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "objective-authority",
            ));
        }
        let compiled = outcome.compile_result.map_err(|conflict| PortFailureV3 {
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
        let declared_candidates = legal_candidate_ids(&self.inputs.legal_candidates);
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
        self.validate_common(input)?;
        if self.inputs.utility.set.objective_digest != self.inputs.expected_objective_digest {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "utility-objective",
            ));
        }
        let mut expected = legal_candidate_ids(&self.inputs.legal_candidates);
        expected.insert(stable_id(ABSTAIN, input)?);
        let actual = self
            .inputs
            .utility
            .set
            .contributions
            .iter()
            .map(|contribution| contribution.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        if actual != expected {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "utility-candidate-binding",
            ));
        }
        let receipt = evaluate_candidates_with_policy(
            self.inputs.utility.set.clone(),
            self.inputs.utility.profile.clone(),
            self.inputs.utility.scalarization.clone(),
            self.inputs.utility.policy.clone(),
        )
        .map_err(|_| failure(input, PortFailureClassV3::Rejected, "utility-error"))?;
        self.last_utility_digest = Some(receipt.evaluation_digest_v2);
        success(input, "utility.ndu", receipt.evaluation_digest_v2)
    }

    fn admit_evaluation(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.validate_common(input)?;
        if self.inputs.evaluation.bundle.objective_digest != self.inputs.expected_objective_digest {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "evaluation-objective",
            ));
        }
        let receipt = decide_with_signed_evidence_v2(
            self.inputs.evaluation.bundle.clone(),
            self.inputs.evaluation.roles.clone(),
            &self.inputs.evaluation.evidence,
            &self.inputs.evaluation.verifier,
            self.inputs.evaluation.now,
        )
        .map_err(|_| failure(input, PortFailureClassV3::Rejected, "evaluation-authentication"))?;
        if receipt.decision.disposition
            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(PortFailureV3 {
                class: PortFailureClassV3::Rejected,
                evidence_digest: receipt.decision.evidence_digest,
            });
        }
        success(
            input,
            "learning.eval",
            signed_evaluation_stage_digest(
                receipt.decision.evidence_digest,
                receipt.trust_digest,
                receipt.authentication_digest,
            ),
        )
    }

    fn collect_neural_signal(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.validate_common(input)?;
        let Some(neuron) = self.inputs.neuron.as_ref() else {
            return Err(failure(
                input,
                PortFailureClassV3::Unavailable,
                "neuron-absent",
            ));
        };
        let Some(utility_digest) = self.last_utility_digest else {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "neuron-before-utility",
            ));
        };
        if neuron.tick.objective_digest != self.inputs.expected_objective_digest
            || neuron.tick.body_digest != self.inputs.expected_body_digest
            || neuron.tick.ndu_digest != utility_digest
        {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "neuron-binding",
            ));
        }
        let (_, receipt) = sparse_tick(&neuron.config, &neuron.tick, neuron.previous.as_ref())
            .map_err(|_| failure(input, PortFailureClassV3::Rejected, "neuron-error"))?;
        if receipt.authority.grants_any() {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "neuron-authority",
            ));
        }
        success(input, "neuron.runtime", sparse_signal_receipt_digest(&receipt))
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV3,
    ) -> Result<PortReceiptV3, PortFailureV3> {
        self.validate_common(input)?;
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
        self.validate_common(input)?;
        let mut request = self.inputs.intuition.clone();
        if request.objective_digest != self.inputs.expected_objective_digest
            || request.state_digest != self.inputs.expected_snapshot_digest
            || request.completeness.omitted_count_bound != 0
        {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "intuition-binding",
            ));
        }
        let actual = request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        if actual != legal_candidate_ids(&self.inputs.legal_candidates) {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "intuition-candidate-binding",
            ));
        }
        request.decision_id = input.run_id.clone();
        let receipt = decide_calibrated_v2(request)
            .map_err(|_| failure(input, PortFailureClassV3::Rejected, "intuition-error"))?;
        if receipt.authority.grants_any() {
            return Err(failure(
                input,
                PortFailureClassV3::Rejected,
                "intuition-authority",
            ));
        }
        let decision = match receipt.disposition {
            CalibratedDispositionV1::Selected(_) => PortDecisionV3::Continue,
            CalibratedDispositionV1::Abstained(_) => PortDecisionV3::Abstain,
            CalibratedDispositionV1::SlowPath(_) => PortDecisionV3::SlowPath,
        };
        let output = receipt.receipt_digest;
        self.last_intuition = Some(receipt);
        success_with_decision(input, "intuition.policy", output, decision)
    }

    fn compile_context(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.validate_common(input)?;
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
        self.validate_common(input)?;
        self.host.accept_host_envelope_v3(input, envelope)
    }

    fn record_learning(&mut self, input: &PortInputV3) -> Result<PortReceiptV3, PortFailureV3> {
        self.validate_common(input)?;
        let intuition = self.last_intuition.as_ref().ok_or_else(|| {
            failure(
                input,
                PortFailureClassV3::Rejected,
                "missing-intuition-receipt",
            )
        })?;
        let abstain = stable_id(ABSTAIN, input)?;
        let slow_path = stable_id(SLOW_PATH, input)?;
        let (selected, propensity) = match &intuition.disposition {
            CalibratedDispositionV1::Selected(candidate) => {
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
            CalibratedDispositionV1::Abstained(_) => {
                (abstain.clone(), intuition.abstain_probability)
            }
            CalibratedDispositionV1::SlowPath(_) => {
                (slow_path.clone(), intuition.slow_path_probability)
            }
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
        candidate_ids.push(abstain);
        candidate_ids.push(slow_path);
        candidate_ids.sort();
        candidate_ids.dedup();
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

fn legal_candidate_ids(value: &LegalActionCandidateSetV1) -> BTreeSet<StableId> {
    value
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect()
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
    if output_digest.is_zero() {
        return Err(failure(
            input,
            PortFailureClassV3::Rejected,
            "empty-owner-output",
        ));
    }
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

fn signed_evaluation_stage_digest(
    evidence_digest: Digest32,
    trust_digest: Digest32,
    authentication_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.signed-evaluation-stage.v1\0".to_vec();
    bytes.extend_from_slice(evidence_digest.as_array());
    bytes.extend_from_slice(trust_digest.as_array());
    bytes.extend_from_slice(authentication_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn sparse_signal_receipt_digest(receipt: &SparseSignalReceipt) -> Digest32 {
    let mut bytes = b"hepta.intelligence.sparse-signal-stage.v1\0".to_vec();
    for digest in [
        receipt.config_digest,
        receipt.input_digest,
        receipt.checkpoint_before,
        receipt.checkpoint_after,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.active_fraction_ppm.to_be_bytes());
    bytes.extend_from_slice(&receipt.prediction_error_q24.to_be_bytes());
    bytes.extend_from_slice(&receipt.projection_count.to_be_bytes());
    bytes.push(u8::from(receipt.requires_calibration));
    bytes.extend_from_slice(&(receipt.activation_q24.len() as u64).to_be_bytes());
    for value in &receipt.activation_q24 {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
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
