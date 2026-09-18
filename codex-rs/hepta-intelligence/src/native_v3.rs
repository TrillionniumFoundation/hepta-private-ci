//! Native owner adapters for the converged V3 composition graph.
//!
//! This adapter calls the repository's actual owner libraries. Callers supply
//! already-authorized typed inputs and the learning owner journal; the facade
//! rewrites only run/snapshot/predecessor bindings that belong to orchestration.

use std::collections::BTreeSet;

use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::ContextCompilationReceipt;
use codex_hepta_context_compiler::compile;
use codex_hepta_intelligence_eval::Disposition as EvaluationDisposition;
use codex_hepta_intelligence_eval::EvaluationReceipt;
use codex_hepta_intelligence_eval::EvaluationRequest;
use codex_hepta_intelligence_eval::evaluate;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_intuition::decide_calibrated_v2;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::NduEvaluationReceiptV2;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_neuron::NeuronSignalReceipt;
use codex_hepta_neuron::NeuronState;
use codex_hepta_neuron::StepRequest;
use codex_hepta_neuron::step;
use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ObjectiveCompileReceipt;
use codex_hepta_objective::ObjectiveSourceEnvelope;
use codex_hepta_objective::compile as compile_objective;
use codex_hepta_prompt_optimizer::OptimizationRequest;
use codex_hepta_prompt_optimizer::PromptPortfolioReceipt;
use codex_hepta_prompt_optimizer::optimize;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompositionPortInputV3;
use crate::CompositionPortReceiptV3;
use crate::CompositionPortsV3;
use crate::CompositionStageV3;
use crate::DecisionAppendRequestV3;
use crate::LegalActionCandidateSetV1;
use crate::PortDecisionV1;
use crate::PortFailureClassV1;
use crate::PortFailureV1;
use crate::append_decision_v3;

pub struct NativeNeuronInputV3 {
    pub request: StepRequest,
    pub previous: Option<NeuronState>,
}

pub struct NativeCompositionInputsV3 {
    pub objective: ObjectiveSourceEnvelope,
    pub utility_contributions: ContributionSet,
    pub utility_profile: UtilityProfile,
    pub scalarization: Option<ScalarizationProfile>,
    pub evaluation_policy: EvaluationPolicyV1,
    pub neuron: Option<NativeNeuronInputV3>,
    pub prompt: Option<OptimizationRequest>,
    pub intuition: CalibratedDecisionRequestV1,
    pub context: CompilationRequest,
    pub evaluation: EvaluationRequest,
    pub episode_id: StableId,
    pub policy_id: StableId,
    pub expected_ledger_head: Digest32,
}

pub struct NativeCompositionPortsV3<'a> {
    candidate_set: LegalActionCandidateSetV1,
    inputs: Option<NativeCompositionInputsV3>,
    ledger: &'a mut dyn DurableLearningJournal,
    objective: Option<ObjectiveCompileReceipt>,
    utility: Option<NduEvaluationReceiptV2>,
    neuron: Option<NeuronSignalReceipt>,
    prompt: Option<PromptPortfolioReceipt>,
    intuition: Option<CalibratedIntuitionReceiptV1>,
    context: Option<ContextCompilationReceipt>,
    evaluation: Option<EvaluationReceipt>,
    decision: Option<AppendReceipt>,
}

impl<'a> NativeCompositionPortsV3<'a> {
    pub fn new(
        candidate_set: LegalActionCandidateSetV1,
        inputs: NativeCompositionInputsV3,
        ledger: &'a mut dyn DurableLearningJournal,
    ) -> Self {
        Self {
            candidate_set,
            inputs: Some(inputs),
            ledger,
            objective: None,
            utility: None,
            neuron: None,
            prompt: None,
            intuition: None,
            context: None,
            evaluation: None,
            decision: None,
        }
    }

    #[must_use]
    pub fn objective_receipt(&self) -> Option<&ObjectiveCompileReceipt> {
        self.objective.as_ref()
    }

    #[must_use]
    pub fn utility_receipt(&self) -> Option<&NduEvaluationReceiptV2> {
        self.utility.as_ref()
    }

    #[must_use]
    pub fn neuron_receipt(&self) -> Option<&NeuronSignalReceipt> {
        self.neuron.as_ref()
    }

    #[must_use]
    pub fn prompt_receipt(&self) -> Option<&PromptPortfolioReceipt> {
        self.prompt.as_ref()
    }

    #[must_use]
    pub fn intuition_receipt(&self) -> Option<&CalibratedIntuitionReceiptV1> {
        self.intuition.as_ref()
    }

    #[must_use]
    pub fn context_receipt(&self) -> Option<&ContextCompilationReceipt> {
        self.context.as_ref()
    }

    #[must_use]
    pub fn evaluation_receipt(&self) -> Option<&EvaluationReceipt> {
        self.evaluation.as_ref()
    }

    #[must_use]
    pub fn decision_append(&self) -> Option<&AppendReceipt> {
        self.decision.as_ref()
    }

    fn ensure_run_binding(
        &self,
        input: &CompositionPortInputV3,
    ) -> Result<(), PortFailureV1> {
        if self.candidate_set.digest() != input.candidate_set_digest
            || self.candidate_set.state_digest != input.snapshot_digest
        {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "native-run-binding",
            ));
        }
        let Some(implementation_digest) = input.capability_implementation_digest else {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "missing-capability-implementation",
            ));
        };
        if implementation_digest.is_zero() || input.capability_generation.is_none() {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "invalid-capability-binding",
            ));
        }
        Ok(())
    }

    fn required_generation(
        &self,
        input: &CompositionPortInputV3,
    ) -> Result<codex_hepta_types::Generation, PortFailureV1> {
        input.capability_generation.ok_or_else(|| {
            native_failure(
                input,
                PortFailureClassV1::Rejected,
                "missing-capability-generation",
            )
        })
    }

    fn inputs_mut(
        &mut self,
        input: &CompositionPortInputV3,
        label: &'static str,
    ) -> Result<&mut NativeCompositionInputsV3, PortFailureV1> {
        self.ensure_run_binding(input)?;
        self.inputs
            .as_mut()
            .ok_or_else(|| native_failure(input, PortFailureClassV1::Rejected, label))
    }

    fn objective_digest(
        &self,
        input: &CompositionPortInputV3,
    ) -> Result<Digest32, PortFailureV1> {
        self.ensure_run_binding(input)?;
        self.objective
            .as_ref()
            .map(|receipt| receipt.objective.semantic_digest)
            .ok_or_else(|| {
                native_failure(
                    input,
                    PortFailureClassV1::Rejected,
                    "objective-not-compiled",
                )
            })
    }
}

impl CompositionPortsV3 for NativeCompositionPortsV3<'_> {
    fn validate_objective(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        let source = {
            let inputs = self.inputs_mut(input, "missing-objective-input")?;
            inputs.objective.clone()
        };
        let compiled = compile_objective(source)
            .map_err(|_| native_failure(input, PortFailureClassV1::Rejected, "objective-error"))?
            .map_err(|conflict| PortFailureV1 {
                class: PortFailureClassV1::Rejected,
                evidence_digest: conflict.conflict_digest,
            })?;
        if compiled.disposition != CompileDisposition::Compiled {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "objective-abstain",
            ));
        }
        let legal = compiled
            .objective
            .legal_actions
            .iter()
            .map(|action| action.id.clone())
            .collect::<BTreeSet<_>>();
        if self
            .candidate_set
            .candidates
            .iter()
            .any(|candidate| !legal.contains(&candidate.candidate_id))
        {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "candidate-outside-objective",
            ));
        }
        let digest = compiled.objective.semantic_digest;
        self.objective = Some(compiled);
        native_receipt(
            input,
            "objective.compiler",
            digest,
            digest,
            PortDecisionV1::Continue,
        )
    }

    fn evaluate_utility(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        let objective_digest = self.objective_digest(input)?;
        let (mut contributions, profile, scalarization, policy) = {
            let inputs = self.inputs_mut(input, "missing-utility-input")?;
            (
                inputs.utility_contributions.clone(),
                inputs.utility_profile.clone(),
                inputs.scalarization.clone(),
                inputs.evaluation_policy.clone(),
            )
        };
        let required_generation = self.required_generation(input)?;
        if contributions.generation != required_generation
            || contributions
                .contributions
                .iter()
                .any(|contribution| contribution.generation != required_generation)
        {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "ndu-generation",
            ));
        }
        contributions.objective_digest = objective_digest;
        for contribution in &mut contributions.contributions {
            contribution.objective_digest = objective_digest;
        }
        let abstain = StableId::new("abstain").map_err(|_| {
            native_failure(input, PortFailureClassV1::Rejected, "abstain-id")
        })?;
        let mut expected = self
            .candidate_set
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        expected.insert(abstain);
        let actual = contributions
            .contributions
            .iter()
            .map(|contribution| contribution.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        if actual != expected {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "ndu-candidate-set",
            ));
        }
        let receipt = evaluate_candidates_with_policy(
            contributions,
            profile,
            scalarization,
            policy,
        )
        .map_err(|_| native_failure(input, PortFailureClassV1::Rejected, "ndu-error"))?;
        let output = receipt.evaluation_digest_v2;
        let evidence = receipt.evaluation_policy_digest;
        self.utility = Some(receipt);
        native_receipt(
            input,
            "utility.ndu",
            output,
            evidence,
            PortDecisionV1::Continue,
        )
    }

    fn collect_neural_signal(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        let mut neuron = {
            let inputs = self.inputs_mut(input, "missing-neuron-input")?;
            inputs
                .neuron
                .take()
                .ok_or_else(|| {
                    native_failure(
                        input,
                        PortFailureClassV1::Unavailable,
                        "neuron-not-configured",
                    )
                })?
        };
        let required_generation = self.required_generation(input)?;
        if neuron.request.generation != required_generation {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "neuron-generation",
            ));
        }
        neuron.request.run_id = input.run_id.clone();
        neuron.request.source_digest = input.predecessor_digest;
        let (state, receipt) = step(neuron.request, neuron.previous.as_ref())
            .map_err(|_| native_failure(input, PortFailureClassV1::Rejected, "neuron-error"))?;
        let output = receipt.signal_digest;
        let evidence = state.state_digest;
        self.neuron = Some(receipt);
        native_receipt(
            input,
            "neuron.runtime",
            output,
            evidence,
            PortDecisionV1::Continue,
        )
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        let objective_digest = self.objective_digest(input)?;
        let mut request = {
            let inputs = self.inputs_mut(input, "missing-prompt-input")?;
            inputs
                .prompt
                .take()
                .ok_or_else(|| {
                    native_failure(
                        input,
                        PortFailureClassV1::Unavailable,
                        "prompt-not-configured",
                    )
                })?
        };
        request.decision_id = input.run_id.clone();
        request.objective_digest = objective_digest;
        let receipt = optimize(request)
            .map_err(|_| native_failure(input, PortFailureClassV1::Rejected, "prompt-error"))?;
        let output = receipt.receipt_digest;
        self.prompt = Some(receipt);
        native_receipt(
            input,
            "prompt.optimizer",
            output,
            output,
            PortDecisionV1::Continue,
        )
    }

    fn decide_intuition(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        let objective_digest = self.objective_digest(input)?;
        let mut request = {
            let inputs = self.inputs_mut(input, "missing-intuition-input")?;
            inputs.intuition.clone()
        };
        let required_generation = self.required_generation(input)?;
        if request.policy_generation != required_generation.get() {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "intuition-generation",
            ));
        }
        request.decision_id = input.run_id.clone();
        request.objective_digest = objective_digest;
        request.state_digest = input.snapshot_digest;

        let expected = self
            .candidate_set
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        let actual = request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<BTreeSet<_>>();
        if actual != expected {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "intuition-candidate-set",
            ));
        }
        let utility = self.utility.as_ref().ok_or_else(|| {
            native_failure(
                input,
                PortFailureClassV1::Rejected,
                "utility-not-evaluated",
            )
        })?;
        for candidate in &request.candidates {
            let Some(ndu_candidate) = utility
                .base
                .evaluated_candidates
                .iter()
                .find(|row| row.candidate_id == candidate.candidate_id)
            else {
                return Err(native_failure(
                    input,
                    PortFailureClassV1::Rejected,
                    "intuition-ndu-candidate",
                ));
            };
            if ndu_candidate.scalar_score != Some(candidate.utility) {
                return Err(native_failure(
                    input,
                    PortFailureClassV1::Rejected,
                    "intuition-ndu-utility",
                ));
            }
        }

        let receipt = decide_calibrated_v2(request)
            .map_err(|_| native_failure(input, PortFailureClassV1::Rejected, "intuition-error"))?;
        let decision = match receipt.disposition {
            CalibratedDispositionV1::Selected(_) => PortDecisionV1::Continue,
            CalibratedDispositionV1::Abstained(_) => PortDecisionV1::Abstain,
            CalibratedDispositionV1::SlowPath(_) => PortDecisionV1::SlowPath,
        };
        let output = receipt.receipt_digest;
        self.intuition = Some(receipt);
        native_receipt(
            input,
            "intuition.policy",
            output,
            output,
            decision,
        )
    }

    fn compile_context(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        let objective_digest = self.objective_digest(input)?;
        let mut request = {
            let inputs = self.inputs_mut(input, "missing-context-input")?;
            inputs.context.clone()
        };
        request.run_snapshot_digest = input.snapshot_digest;
        request.objective_digest = objective_digest;
        let receipt = compile(request)
            .map_err(|_| native_failure(input, PortFailureClassV1::Rejected, "context-error"))?;
        let evidence = native_evidence_digest(
            input,
            "context-receipt",
            receipt.context_digest,
        );
        let output = receipt.context_digest;
        self.context = Some(receipt);
        native_receipt(
            input,
            "context.compiler",
            output,
            evidence,
            PortDecisionV1::Continue,
        )
    }

    fn admit_evaluation(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        let objective_digest = self.objective_digest(input)?;
        let (mut request, policy_id) = {
            let inputs = self.inputs_mut(input, "missing-evaluation-input")?;
            (inputs.evaluation.clone(), inputs.policy_id.clone())
        };
        if request.candidate_id != policy_id {
            return Err(native_failure(
                input,
                PortFailureClassV1::Rejected,
                "evaluation-policy-binding",
            ));
        }
        request.objective_digest = objective_digest;
        request.candidate_producer_id = StableId::new("intelligence.control").map_err(|_| {
            native_failure(
                input,
                PortFailureClassV1::Rejected,
                "producer-identity",
            )
        })?;
        let receipt = evaluate(request)
            .map_err(|_| native_failure(input, PortFailureClassV1::Rejected, "evaluation-error"))?;
        if receipt.disposition != EvaluationDisposition::EligibleForFurtherReview {
            return Err(PortFailureV1 {
                class: PortFailureClassV1::Rejected,
                evidence_digest: receipt.evidence_digest,
            });
        }
        let output = receipt.evidence_digest;
        self.evaluation = Some(receipt);
        native_receipt(
            input,
            "learning.eval",
            output,
            output,
            PortDecisionV1::Continue,
        )
    }

    fn record_decision(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        let objective_digest = self.objective_digest(input)?;
        let (selected, propensity, intuition_digest, requires_evaluation) = {
            let intuition = self.intuition.as_ref().ok_or_else(|| {
                native_failure(
                    input,
                    PortFailureClassV1::Rejected,
                    "intuition-not-decided",
                )
            })?;
            let (selected, propensity, requires_evaluation) = match &intuition.disposition {
                CalibratedDispositionV1::Selected(candidate) => {
                    let propensity = intuition
                        .propensities
                        .iter()
                        .find(|row| row.candidate_id == *candidate)
                        .map(|row| row.probability);
                    (candidate.clone(), propensity, true)
                }
                CalibratedDispositionV1::Abstained(_) => (
                    StableId::new("abstain").map_err(|_| {
                        native_failure(input, PortFailureClassV1::Rejected, "abstain-id")
                    })?,
                    Some(intuition.abstain_probability),
                    false,
                ),
                CalibratedDispositionV1::SlowPath(_) => (
                    StableId::new("shadow:slow-path").map_err(|_| {
                        native_failure(input, PortFailureClassV1::Rejected, "slow-path-id")
                    })?,
                    Some(intuition.slow_path_probability),
                    false,
                ),
            };
            let propensity = propensity.filter(|value| value.raw() > 0).ok_or_else(|| {
                native_failure(
                    input,
                    PortFailureClassV1::Rejected,
                    "missing-propensity",
                )
            })?;
            (
                selected,
                propensity,
                intuition.receipt_digest,
                requires_evaluation,
            )
        };
        let evaluation_digest = if requires_evaluation {
            self.evaluation
                .as_ref()
                .ok_or_else(|| {
                    native_failure(
                        input,
                        PortFailureClassV1::Rejected,
                        "evaluation-not-admitted",
                    )
                })?
                .evidence_digest
        } else {
            let mut bytes = b"hepta.intelligence.no-dispatch-evaluation.v3\0".to_vec();
            bytes.extend_from_slice(input.predecessor_digest.as_array());
            bytes.extend_from_slice(intuition_digest.as_array());
            bytes.extend_from_slice(self.candidate_set.digest().as_array());
            Digest32::of_bytes(&bytes)
        };
        let (episode_id, policy_id, expected_head) = {
            let inputs = self.inputs_mut(input, "missing-ledger-input")?;
            (
                inputs.episode_id.clone(),
                inputs.policy_id.clone(),
                inputs.expected_ledger_head,
            )
        };
        let abstain = StableId::new("abstain").map_err(|_| {
            native_failure(input, PortFailureClassV1::Rejected, "abstain-id")
        })?;
        let slow_path = StableId::new("shadow:slow-path").map_err(|_| {
            native_failure(input, PortFailureClassV1::Rejected, "slow-path-id")
        })?;
        let mut candidates = self
            .candidate_set
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        candidates.push(abstain);
        candidates.push(slow_path);
        let mut support = b"hepta.intelligence.native-decision.v3\0".to_vec();
        support.extend_from_slice(input.predecessor_digest.as_array());
        support.extend_from_slice(intuition_digest.as_array());
        support.extend_from_slice(evaluation_digest.as_array());
        support.extend_from_slice(self.candidate_set.digest().as_array());
        let decision = EpisodeDecision {
            record_id: input.run_id.clone(),
            episode_id,
            objective_digest,
            policy_id,
            candidate_ids: candidates,
            selected_candidate_id: selected,
            selected_propensity: propensity,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: Digest32::of_bytes(&support),
        };
        let append = append_decision_v3(
            self.ledger,
            DecisionAppendRequestV3 {
                expected_ledger_head: expected_head,
                decision,
            },
        )
        .map_err(|_| native_failure(input, PortFailureClassV1::Indeterminate, "ledger-error"))?;
        let output = append.chain_digest;
        let evidence = append.event_digest;
        self.decision = Some(append);
        native_receipt(
            input,
            "learning.ledger",
            output,
            evidence,
            PortDecisionV1::Continue,
        )
    }
}

fn native_receipt(
    input: &CompositionPortInputV3,
    producer: &str,
    output_digest: Digest32,
    evidence_digest: Digest32,
    decision: PortDecisionV1,
) -> Result<CompositionPortReceiptV3, PortFailureV1> {
    let producer = StableId::new(producer).map_err(|_| {
        native_failure(
            input,
            PortFailureClassV1::Rejected,
            "producer-identity",
        )
    })?;
    Ok(CompositionPortReceiptV3 {
        stage: input.stage,
        producer,
        snapshot_digest: input.snapshot_digest,
        predecessor_digest: input.predecessor_digest,
        output_digest,
        evidence_digest,
        decision,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn native_failure(
    input: &CompositionPortInputV3,
    class: PortFailureClassV1,
    label: &str,
) -> PortFailureV1 {
    let mut bytes = b"hepta.intelligence.native-port-failure.v3\0".to_vec();
    bytes.push(stage_code(input.stage));
    bytes.extend_from_slice(input.snapshot_digest.as_array());
    bytes.extend_from_slice(input.predecessor_digest.as_array());
    bytes.extend_from_slice(label.as_bytes());
    PortFailureV1 {
        class,
        evidence_digest: Digest32::of_bytes(&bytes),
    }
}

fn native_evidence_digest(
    input: &CompositionPortInputV3,
    label: &str,
    owner_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.native-port-evidence.v3\0".to_vec();
    bytes.push(stage_code(input.stage));
    bytes.extend_from_slice(input.predecessor_digest.as_array());
    bytes.extend_from_slice(owner_digest.as_array());
    bytes.extend_from_slice(label.as_bytes());
    Digest32::of_bytes(&bytes)
}

const fn stage_code(stage: CompositionStageV3) -> u8 {
    match stage {
        CompositionStageV3::ObjectiveValidated => 0,
        CompositionStageV3::LegalSetBuilt => 1,
        CompositionStageV3::UtilityEvaluated => 2,
        CompositionStageV3::NeuralSignalCollected => 3,
        CompositionStageV3::PromptPortfolioBuilt => 4,
        CompositionStageV3::IntuitionDecided => 5,
        CompositionStageV3::ContextCompiled => 6,
        CompositionStageV3::EvaluationAdmitted => 7,
        CompositionStageV3::DecisionRecorded => 8,
    }
}

#[cfg(test)]
#[path = "native_v3_tests.rs"]
mod tests;
