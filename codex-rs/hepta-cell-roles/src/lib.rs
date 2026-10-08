//! Thin, typed adapters for the semantic cell roles.
//!
//! This crate deliberately owns no runtime, store, route, authority, artifact,
//! or promotion lifecycle.  It converts receipts from existing owners into the
//! shared [`CellStepReceiptV1`] contract so a circuit can compose
//! Representation, MemoryRead, Predictor, Value, and Evaluator roles without
//! making each role a new process or persistence owner.
#![forbid(unsafe_code)]

mod action_proposal;

mod communication;
mod control_owner;
mod decision;
mod decision_owner;

pub use decision::DECISION_OWNER_MODULE;
pub use decision::DECISION_SCHEMA_V1;
pub use decision::DecisionAdapterErrorV1;
pub use decision::DecisionAdapterV1;
pub use decision::DecisionAuthenticationBindingV1;
pub use decision::DecisionExecutionBindingV1;
pub use decision::DecisionExecutionOwnerV1;
pub use decision::DecisionPolicyBindingV1;
pub use decision::DecisionProjectionOwnerV1;
pub use decision::DecisionResultV1;
pub use decision_owner::DecisionCellExecutionV1;
pub use decision_owner::DecisionCellOwnerErrorV1;
pub use decision_owner::DecisionCellOwnerV1;
pub use decision_owner::DecisionCellStateV1;

pub use action_proposal::ACTION_PROPOSAL_EXECUTION_ALLOWED_V1;
pub use action_proposal::ACTION_PROPOSAL_SCHEMA_V1;
pub use action_proposal::ActionProposalAdapterV1;
pub use action_proposal::ActionProposalErrorV1;
pub use action_proposal::ActionProposalExecutionModeV1;
pub use action_proposal::ActionProposalQualificationReceiptV1;
pub use action_proposal::ActionProposalResultV1;
pub use action_proposal::ActionProposalV1;

pub use communication::COMMUNICATION_OWNER_MODULE;
pub use communication::COMMUNICATION_SCHEMA_V1;
pub use communication::CommunicationAdapterV1;
pub use communication::CommunicationEnvelopeV1;
pub use communication::CommunicationErrorV1;
pub use communication::CommunicationMessageV1;
pub use communication::CommunicationQualificationReceiptV1;
pub use communication::CommunicationReplayReceiptV1;
pub use communication::CommunicationResultV1;
pub use communication::CommunicationRouteBindingV1;
pub use control_owner::*;

mod circuit_roles;
mod cognitive_closure;
mod metric_policy;
mod plasticity;
mod production_owner;
mod proposal_planner;
mod role_gates;
mod role_qualification;
mod role_split_admission;
mod role_split_metrics;

pub use circuit_roles::*;
pub use cognitive_closure::*;
pub use metric_policy::*;
pub use plasticity::*;
pub use production_owner::*;
pub use proposal_planner::*;
pub use role_gates::*;
pub use role_qualification::*;
pub use role_split_admission::*;
pub use role_split_metrics::*;

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_bellman_operator::WorldModelPredictionV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_memory_retrieval::RetrievalReceipt;
use codex_hepta_ndu::NduEvaluationReceiptV2;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::CellStepStatusV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const CELL_ROLE_ADAPTER_SCHEMA_V1: &str = "hepta.cell-role-adapter.v1";

/// Common bindings supplied by the circuit owner for one role invocation.
///
/// The owner supplies resource and evidence receipts because those facts are
/// outside a pure adapter.  This prevents an adapter from manufacturing host
/// measurements or learning-ledger witnesses.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellAdapterContextV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub role: CellRoleV1,
    pub capability_digest: Digest32,
    pub input_frontier_digest: Digest32,
    pub state_predecessor_digest: Digest32,
    pub resource_receipt_digest: Digest32,
    pub evidence_digest: Digest32,
}

impl CellAdapterContextV1 {
    pub fn validate(&self, expected_role: CellRoleV1) -> Result<(), CellRoleAdapterErrorV1> {
        if self.cell_id.as_str().is_empty() {
            return Err(CellRoleAdapterErrorV1::EmptyId("cell"));
        }
        if self.role != expected_role {
            return Err(CellRoleAdapterErrorV1::RoleMismatch {
                expected: expected_role,
                actual: self.role,
            });
        }
        for (label, digest) in [
            ("scope", self.scope_digest),
            ("capability", self.capability_digest),
            ("input frontier", self.input_frontier_digest),
            ("state predecessor", self.state_predecessor_digest),
            ("resource receipt", self.resource_receipt_digest),
            ("evidence", self.evidence_digest),
        ] {
            if digest.is_zero() {
                return Err(CellRoleAdapterErrorV1::EmptyDigest(label));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellRoleAdapterErrorV1 {
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    RoleMismatch {
        expected: CellRoleV1,
        actual: CellRoleV1,
    },
    Contract(CellRoleContractErrorV1),
}

impl fmt::Display for CellRoleAdapterErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellRoleAdapterErrorV1 {}

impl From<CellRoleContractErrorV1> for CellRoleAdapterErrorV1 {
    fn from(error: CellRoleContractErrorV1) -> Self {
        Self::Contract(error)
    }
}

/// Every role adapter returns the same immutable step receipt.  The typed
/// result beside it remains role-specific and is never an authority grant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellRoleStepV1<T> {
    pub result: T,
    pub receipt: CellStepReceiptV1,
}

pub(crate) fn step_receipt(
    context: &CellAdapterContextV1,
    role: CellRoleV1,
    state_successor_digest: Digest32,
    output_digest: Digest32,
    uncertainty_ppm: u32,
    ood_ppm: u32,
    status: CellStepStatusV1,
) -> Result<CellStepReceiptV1, CellRoleAdapterErrorV1> {
    // Adapters are projection-only.  They do not own a checkpoint commit, so
    // a role output must not be presented as a newly committed state.  The
    // circuit owner advances this frontier only after its real state owner
    // commits and supplies the next context on a subsequent step.
    context.validate(role)?;
    if state_successor_digest.is_zero() {
        return Err(CellRoleAdapterErrorV1::EmptyDigest("state successor"));
    }
    if output_digest.is_zero() {
        return Err(CellRoleAdapterErrorV1::EmptyDigest("output"));
    }
    let receipt = CellStepReceiptV1 {
        cell_id: context.cell_id.clone(),
        generation: context.generation,
        scope_digest: context.scope_digest,
        role,
        capability_digest: context.capability_digest,
        input_frontier_digest: context.input_frontier_digest,
        state_predecessor_digest: context.state_predecessor_digest,
        state_successor_digest,
        output_digest,
        uncertainty_ppm,
        ood_ppm,
        resource_receipt_digest: context.resource_receipt_digest,
        evidence_digest: context.evidence_digest,
        status,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate()?;
    Ok(receipt)
}

fn digest_bytes(domain: &[u8], fields: &[&[u8]]) -> Digest32 {
    let mut bytes = domain.to_vec();
    for field in fields {
        bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
        bytes.extend_from_slice(field);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_u64s(domain: &[u8], values: &[u64]) -> Digest32 {
    let mut bytes = domain.to_vec();
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn validate_representation_output(
    output: &NeuronRuntimeOutputV1,
) -> Result<(), CellRoleAdapterErrorV1> {
    for (label, digest) in [
        ("signal runtime", output.signal.model_runtime_digest),
        ("temporal state", output.signal.temporal_state_digest),
        ("checkpoint after", output.tick.checkpoint_after),
        ("activation", output.tick.activation_digest),
        ("threshold", output.tick.threshold_digest),
        ("eligibility", output.tick.eligibility_digest),
    ] {
        if digest.is_zero() {
            return Err(CellRoleAdapterErrorV1::EmptyDigest(label));
        }
    }
    if output.signal.authority.grants_any() {
        return Err(CellRoleAdapterErrorV1::Contract(
            CellRoleContractErrorV1::AuthorityGrant,
        ));
    }
    if output.tick.confidence_ppm > 1_000_000
        || output.tick.ood_ppm > 1_000_000
        || output.signal.activation_sparsity_ppm > 1_000_000
        || output.signal.ood_ppm > 1_000_000
    {
        return Err(CellRoleAdapterErrorV1::Contract(
            CellRoleContractErrorV1::InvalidPpm,
        ));
    }
    Ok(())
}

fn digest_retrieval_result(receipt: &RetrievalReceipt) -> Digest32 {
    let result_count = u64::try_from(receipt.results.len()).unwrap_or(u64::MAX);
    let omitted_count = u64::try_from(receipt.omitted_count).unwrap_or(u64::MAX);
    let result_count_bytes = result_count.to_be_bytes();
    let omitted_count_bytes = omitted_count.to_be_bytes();
    let mut bytes = b"hepta.cell-role.memory-read-output.v1".to_vec();
    append_digest_field(&mut bytes, receipt.snapshot_digest);
    append_digest_field(&mut bytes, receipt.receipt_digest);
    append_field(&mut bytes, result_count_bytes.as_slice());
    append_field(&mut bytes, omitted_count_bytes.as_slice());
    for result in &receipt.results {
        let total_score = result.total_score.raw().to_be_bytes();
        let lexical_score = result.lexical_score.raw().to_be_bytes();
        let graph_score = result.graph_score.raw().to_be_bytes();
        let freshness_score = result.freshness_score.raw().to_be_bytes();
        append_field(&mut bytes, result.record_id.as_str().as_bytes());
        append_digest_field(&mut bytes, result.record_digest);
        append_field(&mut bytes, total_score.as_slice());
        append_field(&mut bytes, lexical_score.as_slice());
        append_field(&mut bytes, graph_score.as_slice());
        append_field(&mut bytes, freshness_score.as_slice());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_value_result(result: &ValueResultV1, base_digest: Digest32) -> Digest32 {
    let evaluated_count = result.evaluated_candidate_count.to_be_bytes();
    let rejected_count = result.rejected_candidate_count.to_be_bytes();
    let frontier_count = result.frontier_count.to_be_bytes();
    let advisory = result
        .advisory_recommendation
        .as_ref()
        .map_or(&[][..], |id| id.as_str().as_bytes());
    digest_bytes(
        b"hepta.cell-role.value-output.v1",
        &[
            result.evaluation_digest.as_array(),
            result.evaluation_policy_digest.as_array(),
            result.utility_profile_digest.as_array(),
            base_digest.as_array(),
            advisory,
            evaluated_count.as_slice(),
            rejected_count.as_slice(),
            frontier_count.as_slice(),
        ],
    )
}

fn digest_evaluator_result(result: &EvaluatorResultV1) -> Digest32 {
    let selected = result
        .selected_candidate
        .as_ref()
        .map_or(&[][..], |id| id.as_str().as_bytes());
    digest_bytes(
        b"hepta.cell-role.evaluator-output.v1",
        &[
            result.decision_receipt_digest.as_array(),
            result.calibration_artifact_digest.as_array(),
            result.ood_artifact_digest.as_array(),
            result.disposition_digest.as_array(),
            selected,
            &[u8::from(result.abstained)],
            &[u8::from(result.slow_path)],
        ],
    )
}

fn append_field(bytes: &mut Vec<u8>, field: &[u8]) {
    bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
    bytes.extend_from_slice(field);
}

fn append_digest_field(bytes: &mut Vec<u8>, digest: Digest32) {
    append_field(bytes, digest.as_array());
}

/// Typed representation result backed by the existing `hepta-neuron` model
/// port/runtime receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RepresentationResultV1 {
    pub representation_digest: Digest32,
    pub temporal_state_digest: Digest32,
    pub model_runtime_digest: Digest32,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
}

pub struct RepresentationAdapterV1;

impl RepresentationAdapterV1 {
    pub const OWNER_MODULE: &'static str = "hepta.neuron::NeuronModelPort";

    pub fn adapt(
        context: &CellAdapterContextV1,
        output: &NeuronRuntimeOutputV1,
    ) -> Result<CellRoleStepV1<RepresentationResultV1>, CellRoleAdapterErrorV1> {
        validate_representation_output(output)?;
        let model_runtime_digest = output
            .model_runtime
            .semantic_digest()
            .map_err(|_| CellRoleAdapterErrorV1::EmptyDigest("model runtime"))?;
        let signal_digest = digest_u64s(
            b"hepta.cell-role.representation-output.v1",
            &output
                .signal
                .signals_q24
                .iter()
                .map(|value| *value as u64)
                .collect::<Vec<_>>(),
        );
        let representation_digest = digest_bytes(
            b"hepta.cell-role.representation-binding.v1",
            &[
                signal_digest.as_array(),
                output.signal.model_runtime_digest.as_array(),
                output.signal.temporal_state_digest.as_array(),
                output.tick.tick_id.as_str().as_bytes(),
                output.tick.checkpoint_before.as_array(),
                output.tick.checkpoint_after.as_array(),
                output.tick.activation_digest.as_array(),
                output.tick.threshold_digest.as_array(),
                output.tick.eligibility_digest.as_array(),
                &output.tick.prediction_error_q24.to_be_bytes(),
                &output.tick.confidence_ppm.to_be_bytes(),
                &output.tick.ood_ppm.to_be_bytes(),
                &[u8::from(output.tick.abstain)],
                output.signal.signal_set_id.as_str().as_bytes(),
                &output.signal.activation_sparsity_ppm.to_be_bytes(),
                &output.signal.ood_ppm.to_be_bytes(),
                &[u8::from(output.signal.abstain)],
                model_runtime_digest.as_array(),
            ],
        );
        let result = RepresentationResultV1 {
            representation_digest,
            temporal_state_digest: output.signal.temporal_state_digest,
            model_runtime_digest: output.signal.model_runtime_digest,
            confidence_ppm: output.tick.confidence_ppm,
            ood_ppm: output.tick.ood_ppm,
            abstain: output.tick.abstain || output.signal.abstain,
        };
        let status = if result.abstain {
            CellStepStatusV1::Abstained
        } else {
            CellStepStatusV1::Accepted
        };
        let receipt = step_receipt(
            context,
            CellRoleV1::Representation,
            context.state_predecessor_digest,
            result.representation_digest,
            1_000_000_u32.saturating_sub(result.confidence_ppm),
            result.ood_ppm,
            status,
        )?;
        Ok(CellRoleStepV1 { result, receipt })
    }
}

/// Typed memory recall result backed by `hepta-memory-retrieval`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadResultV1 {
    pub recall_receipt_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub result_count: u32,
    pub omitted_count: u32,
    pub freshness_bound_digest: Digest32,
}

pub struct MemoryReadAdapterV1;

impl MemoryReadAdapterV1 {
    pub const OWNER_MODULE: &'static str = "hepta-memory-retrieval::retrieve";

    pub fn adapt(
        context: &CellAdapterContextV1,
        receipt: &RetrievalReceipt,
    ) -> Result<CellRoleStepV1<MemoryReadResultV1>, CellRoleAdapterErrorV1> {
        let freshness_bound_digest = digest_bytes(
            b"hepta.cell-role.memory-read-freshness.v1",
            &[
                receipt.snapshot_digest.as_array(),
                receipt.receipt_digest.as_array(),
            ],
        );
        if receipt.snapshot_digest.is_zero() {
            return Err(CellRoleAdapterErrorV1::EmptyDigest("snapshot"));
        }
        if receipt.receipt_digest.is_zero() {
            return Err(CellRoleAdapterErrorV1::EmptyDigest("retrieval receipt"));
        }
        let result_digest = digest_retrieval_result(receipt);
        let result = MemoryReadResultV1 {
            recall_receipt_digest: receipt.receipt_digest,
            snapshot_digest: receipt.snapshot_digest,
            result_count: u32::try_from(receipt.results.len()).unwrap_or(u32::MAX),
            omitted_count: u32::try_from(receipt.omitted_count).unwrap_or(u32::MAX),
            freshness_bound_digest,
        };
        let step = step_receipt(
            context,
            CellRoleV1::MemoryRead,
            context.state_predecessor_digest,
            result_digest,
            0,
            0,
            CellStepStatusV1::Accepted,
        )?;
        Ok(CellRoleStepV1 {
            result,
            receipt: step,
        })
    }
}

/// Typed prediction result backed by the action-conditioned Bellman world
/// model. `synthetic` is preserved so predictions cannot become factual
/// outcomes by accident.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PredictorResultV1 {
    pub prediction_digest: Digest32,
    pub model_id: StableId,
    pub dataset_digest: Digest32,
    pub estimate_digest: Digest32,
    pub mean_outcome_raw_q32: i64,
    pub branch_count: u32,
    pub synthetic: bool,
}

pub struct PredictorAdapterV1;

impl PredictorAdapterV1 {
    pub const OWNER_MODULE: &'static str = "hepta-bellman-operator::WorldModel";

    pub fn adapt(
        context: &CellAdapterContextV1,
        prediction: &WorldModelPredictionV1,
    ) -> Result<CellRoleStepV1<PredictorResultV1>, CellRoleAdapterErrorV1> {
        if prediction.dataset_digest.is_zero() {
            return Err(CellRoleAdapterErrorV1::EmptyDigest("world-model dataset"));
        }
        if prediction.estimate_digest.is_zero() {
            return Err(CellRoleAdapterErrorV1::EmptyDigest("world-model estimate"));
        }
        if prediction.authority.grants_any() {
            return Err(CellRoleAdapterErrorV1::Contract(
                CellRoleContractErrorV1::AuthorityGrant,
            ));
        }
        if prediction.branches.is_empty() {
            return Err(CellRoleAdapterErrorV1::EmptyId("prediction branches"));
        }
        let branch_count = u32::try_from(prediction.branches.len()).unwrap_or(u32::MAX);
        let branch_count_bytes = branch_count.to_be_bytes();
        let mean_outcome = prediction.mean_outcome.raw().to_be_bytes();
        let synthetic = [u8::from(prediction.synthetic)];
        let mut prediction_bytes = b"hepta.cell-role.predictor-output.v1".to_vec();
        append_field(
            &mut prediction_bytes,
            prediction.model_id.as_str().as_bytes(),
        );
        append_digest_field(&mut prediction_bytes, prediction.dataset_digest);
        append_field(
            &mut prediction_bytes,
            prediction.state_id.as_str().as_bytes(),
        );
        append_field(
            &mut prediction_bytes,
            prediction.action_id.as_str().as_bytes(),
        );
        append_digest_field(&mut prediction_bytes, prediction.estimate_digest);
        append_field(&mut prediction_bytes, mean_outcome.as_slice());
        append_field(&mut prediction_bytes, synthetic.as_slice());
        append_field(&mut prediction_bytes, branch_count_bytes.as_slice());
        for branch in &prediction.branches {
            if branch.next_state_id.as_str().is_empty() {
                return Err(CellRoleAdapterErrorV1::EmptyId("prediction branch"));
            }
            let count = branch.count.to_be_bytes();
            let probability = branch.probability.raw().to_be_bytes();
            append_field(
                &mut prediction_bytes,
                branch.next_state_id.as_str().as_bytes(),
            );
            append_field(&mut prediction_bytes, count.as_slice());
            append_field(&mut prediction_bytes, probability.as_slice());
        }
        let prediction_digest = Digest32::of_bytes(&prediction_bytes);
        if prediction.model_id.as_str().is_empty()
            || prediction.state_id.as_str().is_empty()
            || prediction.action_id.as_str().is_empty()
        {
            return Err(CellRoleAdapterErrorV1::EmptyId("prediction"));
        }
        let result = PredictorResultV1 {
            prediction_digest,
            model_id: prediction.model_id.clone(),
            dataset_digest: prediction.dataset_digest,
            estimate_digest: prediction.estimate_digest,
            mean_outcome_raw_q32: prediction.mean_outcome.raw(),
            branch_count: u32::try_from(prediction.branches.len()).unwrap_or(u32::MAX),
            synthetic: prediction.synthetic,
        };
        let receipt = step_receipt(
            context,
            CellRoleV1::Predictor,
            context.state_predecessor_digest,
            result.prediction_digest,
            0,
            0,
            CellStepStatusV1::Accepted,
        )?;
        Ok(CellRoleStepV1 { result, receipt })
    }
}

/// Typed value/critic result backed by the policy-bound NDU evaluator.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValueResultV1 {
    pub evaluation_digest: Digest32,
    pub evaluation_policy_digest: Digest32,
    pub utility_profile_digest: Digest32,
    pub advisory_recommendation: Option<StableId>,
    pub evaluated_candidate_count: u32,
    pub rejected_candidate_count: u32,
    pub frontier_count: u32,
}

pub struct ValueAdapterV1;

impl ValueAdapterV1 {
    pub const OWNER_MODULE: &'static str = "hepta-ndu::evaluate_candidates_with_policy";

    pub fn adapt(
        context: &CellAdapterContextV1,
        receipt: &NduEvaluationReceiptV2,
    ) -> Result<CellRoleStepV1<ValueResultV1>, CellRoleAdapterErrorV1> {
        let result = ValueResultV1 {
            evaluation_digest: receipt.evaluation_digest_v2,
            evaluation_policy_digest: receipt.evaluation_policy_digest,
            utility_profile_digest: receipt.base.utility_profile_digest,
            advisory_recommendation: receipt.base.advisory_recommendation.clone(),
            evaluated_candidate_count: u32::try_from(receipt.base.evaluated_candidates.len())
                .unwrap_or(u32::MAX),
            rejected_candidate_count: u32::try_from(receipt.base.rejected_candidates.len())
                .unwrap_or(u32::MAX),
            frontier_count: u32::try_from(receipt.base.pareto_frontier.len()).unwrap_or(u32::MAX),
        };
        for (label, digest) in [
            ("evaluation", result.evaluation_digest),
            ("evaluation policy", result.evaluation_policy_digest),
            ("utility profile", result.utility_profile_digest),
            ("base evaluation", receipt.base.evaluation_digest),
        ] {
            if digest.is_zero() {
                return Err(CellRoleAdapterErrorV1::EmptyDigest(label));
            }
        }
        let result_digest = digest_value_result(&result, receipt.base.evaluation_digest);
        let receipt_step = step_receipt(
            context,
            CellRoleV1::Value,
            context.state_predecessor_digest,
            result_digest,
            0,
            0,
            CellStepStatusV1::Accepted,
        )?;
        Ok(CellRoleStepV1 {
            result,
            receipt: receipt_step,
        })
    }
}

/// Typed evaluator/calibration result backed by intuition's complete-candidate
/// calibrated decision.  It remains advisory and cannot execute an action.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluatorResultV1 {
    pub decision_receipt_digest: Digest32,
    pub calibration_artifact_digest: Digest32,
    pub ood_artifact_digest: Digest32,
    pub disposition_digest: Digest32,
    pub selected_candidate: Option<StableId>,
    pub abstained: bool,
    pub slow_path: bool,
}

pub struct EvaluatorAdapterV1;

impl EvaluatorAdapterV1 {
    pub const OWNER_MODULE: &'static str = "hepta-intuition::decide_calibrated";

    pub fn adapt(
        context: &CellAdapterContextV1,
        receipt: &CalibratedIntuitionReceiptV1,
        uncertainty_ppm: u32,
        ood_ppm: u32,
    ) -> Result<CellRoleStepV1<EvaluatorResultV1>, CellRoleAdapterErrorV1> {
        let (selected_candidate, abstained, slow_path) = match &receipt.disposition {
            CalibratedDispositionV1::Selected(id) => (Some(id.clone()), false, false),
            CalibratedDispositionV1::Abstained(_) => (None, true, false),
            CalibratedDispositionV1::SlowPath(_) => (None, false, true),
        };
        let disposition_digest = digest_bytes(
            b"hepta.cell-role.evaluator-disposition.v1",
            &[
                receipt.receipt_digest.as_array(),
                &[u8::from(abstained), u8::from(slow_path)],
            ],
        );
        let result = EvaluatorResultV1 {
            decision_receipt_digest: receipt.receipt_digest,
            calibration_artifact_digest: receipt.calibration_artifact_digest,
            ood_artifact_digest: receipt.ood_artifact_digest,
            disposition_digest,
            selected_candidate,
            abstained,
            slow_path,
        };
        if receipt.receipt_digest.is_zero() {
            return Err(CellRoleAdapterErrorV1::EmptyDigest("decision receipt"));
        }
        if receipt.calibration_artifact_digest.is_zero() {
            return Err(CellRoleAdapterErrorV1::EmptyDigest("calibration artifact"));
        }
        if receipt.ood_artifact_digest.is_zero() {
            return Err(CellRoleAdapterErrorV1::EmptyDigest("OOD artifact"));
        }
        let result_digest = digest_evaluator_result(&result);
        let status = if result.abstained {
            CellStepStatusV1::Abstained
        } else if result.slow_path {
            CellStepStatusV1::SlowPath
        } else {
            CellStepStatusV1::Accepted
        };
        let step = step_receipt(
            context,
            CellRoleV1::Evaluator,
            context.state_predecessor_digest,
            result_digest,
            uncertainty_ppm,
            ood_ppm,
            status,
        )?;
        Ok(CellRoleStepV1 {
            result,
            receipt: step,
        })
    }
}

/// Returns the stable role-to-owner mapping used by capability profiles.
pub fn default_owner_module(role: CellRoleV1) -> StableId {
    let owner = match role {
        CellRoleV1::Representation => RepresentationAdapterV1::OWNER_MODULE,
        CellRoleV1::MemoryRead => MemoryReadAdapterV1::OWNER_MODULE,
        CellRoleV1::Predictor => PredictorAdapterV1::OWNER_MODULE,
        CellRoleV1::Value => ValueAdapterV1::OWNER_MODULE,
        CellRoleV1::Evaluator => EvaluatorAdapterV1::OWNER_MODULE,
        CellRoleV1::Decision => DecisionAdapterV1::OWNER_MODULE,
        CellRoleV1::Planner => "hepta-automation::taskflow-circuit",
        CellRoleV1::Router => "hepta-cns::route-owner",
        CellRoleV1::ActionProposal => "hepta-intuition::action-proposal",
        CellRoleV1::Plasticity => "hepta-neuron::plasticity",
        CellRoleV1::Communication => "hepta-cns::message-owner",
    };
    match StableId::new(owner) {
        Ok(id) => id,
        Err(_) => unreachable!("static owner module IDs are valid"),
    }
}

/// Small helper used by capability registration and tests. It is deliberately
/// a type-level description: registration remains owned by the host.
pub fn role_schema_digest(role: CellRoleV1) -> Digest32 {
    digest_bytes(
        b"hepta.cell-role.schema.v1",
        &[CELL_ROLE_ADAPTER_SCHEMA_V1.as_bytes(), &[role.tag()]],
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_intuition::AssignmentModeV1;
    use codex_hepta_intuition::CalibratedActionCandidateV1;
    use codex_hepta_intuition::CalibratedDecisionRequestV1;
    use codex_hepta_intuition::CalibrationArtifactV1;
    use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
    use codex_hepta_intuition::OodArtifactV1;
    use codex_hepta_intuition::RiskClass;
    use codex_hepta_intuition::canonical_candidate_order_digest_v1;
    use codex_hepta_intuition::canonical_candidate_set_digest_v1;
    use codex_hepta_intuition::decide_calibrated;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::ProbabilityQ32;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: u8) -> Digest32 {
        Digest32::of_bytes(&[value])
    }

    fn context(role: CellRoleV1) -> CellAdapterContextV1 {
        CellAdapterContextV1 {
            cell_id: id("cell.role.1"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest(1),
            role,
            capability_digest: digest(2),
            input_frontier_digest: digest(3),
            state_predecessor_digest: digest(4),
            resource_receipt_digest: digest(5),
            evidence_digest: digest(6),
        }
    }

    #[test]
    fn role_schema_and_owner_mappings_are_deterministic() {
        for role in [
            CellRoleV1::Representation,
            CellRoleV1::MemoryRead,
            CellRoleV1::Predictor,
            CellRoleV1::Value,
            CellRoleV1::Evaluator,
        ] {
            assert!(!role_schema_digest(role).is_zero());
            assert!(!default_owner_module(role).as_str().is_empty());
        }
        assert_eq!(
            role_schema_digest(CellRoleV1::Value),
            role_schema_digest(CellRoleV1::Value)
        );
    }

    #[test]
    fn context_rejects_wrong_role_and_missing_evidence() {
        let mut value = context(CellRoleV1::Decision);
        assert!(matches!(
            value.validate(CellRoleV1::Value),
            Err(CellRoleAdapterErrorV1::RoleMismatch { .. })
        ));
        value.role = CellRoleV1::Value;
        value.evidence_digest = Digest32::ZERO;
        assert_eq!(
            value.validate(CellRoleV1::Value),
            Err(CellRoleAdapterErrorV1::EmptyDigest("evidence"))
        );
    }

    #[test]
    fn step_receipt_is_authority_free() {
        let receipt = step_receipt(
            &context(CellRoleV1::Value),
            CellRoleV1::Value,
            digest(7),
            digest(8),
            100,
            200,
            CellStepStatusV1::Accepted,
        )
        .expect("receipt");
        assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
        assert!(!receipt.content_digest().expect("digest").is_zero());
    }

    fn calibrated_owner_receipt(risk_class: RiskClass) -> CalibratedIntuitionReceiptV1 {
        let candidates = vec![CalibratedActionCandidateV1 {
            candidate_id: id("candidate:a"),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::from_raw(10),
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ONE,
            support_digest: digest(11),
        }];
        let request = CalibratedDecisionRequestV1 {
            decision_id: id("decision:adapter-test"),
            objective_digest: digest(12),
            objective_class_digest: digest(13),
            state_digest: digest(14),
            policy_digest: digest(15),
            policy_generation: 7,
            sequence: 10,
            minimum_confidence: ProbabilityQ32::from_raw(1_u64 << 31).expect("probability"),
            maximum_ece_ppm: 50_000,
            maximum_ood_false_acceptance_ppm: 5_000,
            risk_class,
            completeness: CandidateSetCompletenessBindingV1 {
                receipt_digest: digest(16),
                generator_digest: digest(17),
                grammar_digest: digest(18),
                hard_filter_digest: digest(19),
                truncation_digest: digest(20),
                candidate_set_digest: canonical_candidate_set_digest_v1(&candidates)
                    .expect("candidate set"),
                canonical_order_digest: canonical_candidate_order_digest_v1(&candidates)
                    .expect("candidate order"),
                candidate_count: 1,
                omitted_count_bound: 0,
            },
            calibration: CalibrationArtifactV1 {
                artifact_digest: digest(21),
                policy_digest: digest(15),
                objective_class_digest: digest(13),
                generation: 7,
                valid_from_sequence: 1,
                expires_after_sequence: 100,
                measured_ece_ppm: 10_000,
                subgroup_audit_digest: digest(22),
            },
            ood: OodArtifactV1 {
                artifact_digest: digest(23),
                policy_digest: digest(15),
                detector_digest: digest(24),
                support_digest: digest(25),
                generation: 7,
                valid_from_sequence: 1,
                expires_after_sequence: 100,
                maximum_in_domain_score: ProbabilityQ32::from_raw(1_u64 << 30)
                    .expect("probability"),
                measured_false_acceptance_ppm: 1_000,
            },
            assignment: AssignmentModeV1::Deterministic,
            candidates,
        };
        decide_calibrated(request).expect("calibrated owner receipt")
    }

    #[test]
    fn evaluator_maps_real_owner_slow_path_without_granting_authority() {
        let receipt = calibrated_owner_receipt(RiskClass::High);
        let step =
            EvaluatorAdapterV1::adapt(&context(CellRoleV1::Evaluator), &receipt, 700_000, 800_000)
                .expect("evaluator adapter");
        assert_eq!(step.receipt.status, CellStepStatusV1::SlowPath);
        assert!(step.result.slow_path);
        assert!(!step.result.abstained);
        assert_eq!(step.receipt.authority, AuthorityPosture::DENY_ALL);
    }

    #[test]
    fn evaluator_maps_real_owner_selection_and_binds_selected_candidate() {
        let receipt = calibrated_owner_receipt(RiskClass::Low);
        let step = EvaluatorAdapterV1::adapt(&context(CellRoleV1::Evaluator), &receipt, 0, 0)
            .expect("evaluator adapter");
        assert_eq!(step.receipt.status, CellStepStatusV1::Accepted);
        assert_eq!(step.result.selected_candidate, Some(id("candidate:a")));
        assert!(!step.result.slow_path);
        assert!(!step.result.abstained);
    }
}
