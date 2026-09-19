//! Reusable in-process owner adapters for the V3 composition facade.
//!
//! These adapters invoke the registered native owner algorithms and translate
//! their typed receipts into the generic composition port envelope. They do not
//! authenticate external observations or grant effect authority. A production
//! host must still supply current trust/revocation inputs and cancellable I/O
//! boundaries around any adapter that can block.

use std::fmt::Debug;

use codex_hepta_context_compiler::CompilationRequest;
use codex_hepta_context_compiler::compile as compile_context;
use codex_hepta_intelligence_eval::Disposition as EvaluationDisposition;
use codex_hepta_intelligence_eval::EvaluationRequest;
use codex_hepta_intelligence_eval::evaluate as evaluate_independently;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::decide_calibrated;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseTick;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_objective::CompileDisposition;
use codex_hepta_objective::ObjectiveSourceEnvelope;
use codex_hepta_objective::compile as compile_objective;
use codex_hepta_prompt_optimizer::local_shadow::LocalShadowInput;
use codex_hepta_prompt_optimizer::local_shadow::calculate_local_shadow;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompositionFailureClassV3;
use crate::CompositionPortDecisionV3;
use crate::CompositionPortFailureV3;
use crate::CompositionPortInputV3;
use crate::CompositionPortReceiptV3;
use crate::CompositionPortsV3;
use crate::CompositionStageV3;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeUtilityStageV3 {
    pub contributions: ContributionSet,
    pub profile: UtilityProfile,
    pub scalarization: Option<ScalarizationProfile>,
    pub policy: EvaluationPolicyV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeNeuronStageV3 {
    pub config: SparseConfig,
    pub tick: SparseTick,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeCompositionInputsV3 {
    pub objective: ObjectiveSourceEnvelope,
    pub utility: NativeUtilityStageV3,
    pub evaluation: EvaluationRequest,
    pub neuron: Option<NativeNeuronStageV3>,
    pub prompt: Option<LocalShadowInput>,
    pub intuition: CalibratedDecisionRequestV1,
    pub context: CompilationRequest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeCompositionPortsV3 {
    inputs: NativeCompositionInputsV3,
}

impl NativeCompositionPortsV3 {
    #[must_use]
    pub fn new(inputs: NativeCompositionInputsV3) -> Self {
        Self { inputs }
    }

    #[must_use]
    pub fn inputs(&self) -> &NativeCompositionInputsV3 {
        &self.inputs
    }
}

impl CompositionPortsV3 for NativeCompositionPortsV3 {
    fn validate_objective(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        let receipt = match compile_objective(self.inputs.objective.clone()) {
            Ok(Ok(receipt)) if receipt.disposition == CompileDisposition::Compiled => receipt,
            Ok(Ok(receipt)) => {
                return Err(failure_from_debug(
                    input.stage,
                    CompositionFailureClassV3::Rejected,
                    "objective disposition",
                    &receipt.disposition,
                ));
            }
            Ok(Err(conflict)) => {
                return Err(CompositionPortFailureV3 {
                    class: CompositionFailureClassV3::Rejected,
                    evidence_digest: conflict.conflict_digest,
                });
            }
            Err(error) => {
                return Err(failure_from_debug(
                    input.stage,
                    CompositionFailureClassV3::Rejected,
                    "objective",
                    &error,
                ));
            }
        };
        receipt_from_owner(
            input,
            "objective.compiler",
            receipt.objective.semantic_digest,
            receipt.objective.hard_constraint_digest,
            CompositionPortDecisionV3::Continue,
        )
    }

    fn evaluate_utility(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        let utility = &self.inputs.utility;
        let receipt = evaluate_candidates_with_policy(
            utility.contributions.clone(),
            utility.profile.clone(),
            utility.scalarization.clone(),
            utility.policy.clone(),
        )
        .map_err(|error| {
            failure_from_debug(
                input.stage,
                CompositionFailureClassV3::Rejected,
                "utility.ndu",
                &error,
            )
        })?;
        receipt_from_owner(
            input,
            "utility.ndu",
            receipt.evaluation_digest_v2,
            receipt.evaluation_policy_digest,
            CompositionPortDecisionV3::Continue,
        )
    }

    fn admit_evaluation(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        let receipt = evaluate_independently(self.inputs.evaluation.clone()).map_err(|error| {
            failure_from_debug(
                input.stage,
                CompositionFailureClassV3::Rejected,
                "learning.eval",
                &error,
            )
        })?;
        if receipt.disposition != EvaluationDisposition::EligibleForFurtherReview {
            return Err(CompositionPortFailureV3 {
                class: CompositionFailureClassV3::Rejected,
                evidence_digest: receipt.evidence_digest,
            });
        }
        receipt_from_owner(
            input,
            "learning.eval",
            receipt.evidence_digest,
            receipt.evidence_digest,
            CompositionPortDecisionV3::Continue,
        )
    }

    fn collect_neural_signal(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        let stage = self.inputs.neuron.as_ref().ok_or_else(|| {
            failure_from_debug(
                input.stage,
                CompositionFailureClassV3::Unavailable,
                "neuron.runtime",
                &"native neuron input absent",
            )
        })?;
        let (_, receipt) = sparse_tick(&stage.config, &stage.tick, None).map_err(|error| {
            failure_from_debug(
                input.stage,
                CompositionFailureClassV3::Rejected,
                "neuron.runtime",
                &error,
            )
        })?;
        if receipt.authority.grants_any() {
            return Err(authority_failure(input.stage, "neuron.runtime"));
        }
        receipt_from_owner(
            input,
            "neuron.runtime",
            receipt.checkpoint_after,
            receipt.signal_digest,
            CompositionPortDecisionV3::Continue,
        )
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        let stage = self.inputs.prompt.as_ref().ok_or_else(|| {
            failure_from_debug(
                input.stage,
                CompositionFailureClassV3::Unavailable,
                "prompt.optimizer",
                &"native prompt input absent",
            )
        })?;
        let receipt = calculate_local_shadow(stage.clone()).map_err(|error| {
            failure_from_debug(
                input.stage,
                CompositionFailureClassV3::Rejected,
                "prompt.optimizer",
                &error,
            )
        })?;
        if receipt.authority().grants_any() {
            return Err(authority_failure(input.stage, "prompt.optimizer"));
        }
        receipt_from_owner(
            input,
            "prompt.optimizer",
            receipt.proposal_digest,
            receipt.proposal_digest,
            CompositionPortDecisionV3::Continue,
        )
    }

    fn decide_intuition(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        let receipt = decide_calibrated(self.inputs.intuition.clone()).map_err(|error| {
            failure_from_debug(
                input.stage,
                CompositionFailureClassV3::Rejected,
                "intuition.policy",
                &error,
            )
        })?;
        if receipt.authority.grants_any() {
            return Err(authority_failure(input.stage, "intuition.policy"));
        }
        let decision = match receipt.disposition {
            CalibratedDispositionV1::Selected(_) => CompositionPortDecisionV3::Continue,
            CalibratedDispositionV1::Abstained(_) => CompositionPortDecisionV3::Abstain,
            CalibratedDispositionV1::SlowPath(_) => CompositionPortDecisionV3::SlowPath,
        };
        receipt_from_owner(
            input,
            "intuition.policy",
            receipt.receipt_digest,
            receipt.receipt_digest,
            decision,
        )
    }

    fn compile_context(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        let receipt = compile_context(self.inputs.context.clone()).map_err(|error| {
            failure_from_debug(
                input.stage,
                CompositionFailureClassV3::Rejected,
                "context.compiler",
                &error,
            )
        })?;
        if receipt.authority.grants_any() {
            return Err(authority_failure(input.stage, "context.compiler"));
        }
        receipt_from_owner(
            input,
            "context.compiler",
            receipt.context_digest,
            receipt.context_digest,
            CompositionPortDecisionV3::Continue,
        )
    }
}

fn receipt_from_owner(
    input: &CompositionPortInputV3,
    producer: &str,
    output_digest: Digest32,
    evidence_digest: Digest32,
    decision: CompositionPortDecisionV3,
) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
    let producer = StableId::new(producer).map_err(|error| {
        failure_from_debug(
            input.stage,
            CompositionFailureClassV3::Rejected,
            "producer identity",
            &error,
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

fn authority_failure(stage: CompositionStageV3, producer: &str) -> CompositionPortFailureV3 {
    failure_from_debug(
        stage,
        CompositionFailureClassV3::Rejected,
        "authority widening",
        &producer,
    )
}

fn failure_from_debug(
    stage: CompositionStageV3,
    class: CompositionFailureClassV3,
    owner: &str,
    error: &impl Debug,
) -> CompositionPortFailureV3 {
    let mut bytes = b"hepta.intelligence.native-owner-failure.v3\0".to_vec();
    bytes.push(stage_code(stage));
    bytes.push(failure_code(class));
    bytes.extend_from_slice(owner.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(format!("{error:?}").as_bytes());
    CompositionPortFailureV3 {
        class,
        evidence_digest: Digest32::of_bytes(&bytes),
    }
}

const fn stage_code(value: CompositionStageV3) -> u8 {
    match value {
        CompositionStageV3::ObjectiveValidated => 0,
        CompositionStageV3::LegalCandidatesBuilt => 1,
        CompositionStageV3::UtilityEvaluated => 2,
        CompositionStageV3::EvaluationAdmitted => 3,
        CompositionStageV3::NeuralSignalCollected => 4,
        CompositionStageV3::PromptPortfolioBuilt => 5,
        CompositionStageV3::IntuitionDecided => 6,
        CompositionStageV3::ContextCompiled => 7,
    }
}

const fn failure_code(value: CompositionFailureClassV3) -> u8 {
    match value {
        CompositionFailureClassV3::Rejected => 0,
        CompositionFailureClassV3::Unavailable => 1,
        CompositionFailureClassV3::TimedOut => 2,
        CompositionFailureClassV3::Quarantined => 3,
        CompositionFailureClassV3::Indeterminate => 4,
    }
}
