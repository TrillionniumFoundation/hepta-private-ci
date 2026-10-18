//! Typed, backend-neutral DecisionCell request and receipt contract.
//!
//! This contract freezes complete legal action/target sets and exact effective
//! base/organ/cell/head identities. It carries advisory decisions only. It does
//! not encode executable bytes, dispatch an effect, issue authority, or claim an
//! external terminal outcome.

use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use serde::Deserialize;
use serde::Serialize;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const Q24: i64 = 1 << 24;
const MAX_Q24: i64 = 8 * Q24;
const MAX_FEATURES: usize = 512;
const MAX_ACTIONS: usize = 64;
const MAX_TARGETS: usize = 256;
const MAX_PARAMETERS: usize = 8;
const PPM: u32 = 1_000_000;
const DISPOSITION_COUNT: usize = 6;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellActionCandidateV1 {
    pub action_id: StableId,
    pub action_semantic_digest: Digest32,
    pub target_required: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellTargetCandidateV1 {
    pub target_id: StableId,
    pub target_generation: u64,
    pub target_semantic_digest: Digest32,
}

/// Exact immutable tensors and heads interpreted by one DecisionCell use.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellParameterBundleV1 {
    pub base_bundle_digest: Digest32,
    pub organ_id: StableId,
    pub organ_bundle_digest: Digest32,
    pub cell_slot_id: Option<StableId>,
    pub cell_bundle_digest: Option<Digest32>,
    pub action_head_digest: Digest32,
    pub target_head_digest: Digest32,
    pub parameter_head_digest: Digest32,
    pub disposition_head_digest: Digest32,
    pub postcondition_head_digest: Digest32,
    pub state_head_digest: Digest32,
    pub calibration_artifact_digest: Digest32,
    pub ood_artifact_digest: Digest32,
    pub effective_parameter_digest: Digest32,
}

impl DecisionCellParameterBundleV1 {
    pub fn semantic_digest(&self) -> Result<Digest32, DecisionCellContractError> {
        for (name, digest) in [
            ("base bundle", self.base_bundle_digest),
            ("organ bundle", self.organ_bundle_digest),
            ("action head", self.action_head_digest),
            ("target head", self.target_head_digest),
            ("parameter head", self.parameter_head_digest),
            ("disposition head", self.disposition_head_digest),
            ("postcondition head", self.postcondition_head_digest),
            ("state head", self.state_head_digest),
            ("calibration artifact", self.calibration_artifact_digest),
            ("ood artifact", self.ood_artifact_digest),
            ("effective parameters", self.effective_parameter_digest),
        ] {
            require_digest(digest, name)?;
        }
        if self.cell_slot_id.is_some() != self.cell_bundle_digest.is_some()
            || self.cell_bundle_digest.is_some_and(Digest32::is_zero)
        {
            return Err(DecisionCellContractError::InvalidParameterBundle);
        }

        let mut bytes = b"hepta.inference.decision-cell-parameter-bundle.v1".to_vec();
        push_digest(&mut bytes, self.base_bundle_digest);
        push_id(&mut bytes, &self.organ_id)?;
        push_digest(&mut bytes, self.organ_bundle_digest);
        match (&self.cell_slot_id, self.cell_bundle_digest) {
            (Some(slot), Some(bundle)) => {
                bytes.push(1);
                push_id(&mut bytes, slot)?;
                push_digest(&mut bytes, bundle);
            }
            (None, None) => bytes.push(0),
            _ => return Err(DecisionCellContractError::InvalidParameterBundle),
        }
        for digest in [
            self.action_head_digest,
            self.target_head_digest,
            self.parameter_head_digest,
            self.disposition_head_digest,
            self.postcondition_head_digest,
            self.state_head_digest,
            self.calibration_artifact_digest,
            self.ood_artifact_digest,
            self.effective_parameter_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub fn decision_cell_head_set_digest_v1(
    bundle: &DecisionCellParameterBundleV1,
) -> Result<Digest32, DecisionCellContractError> {
    bundle.semantic_digest()?;
    Ok(Digest32::of_parts(&[
        b"hepta.inference.decision-cell-head-set.v1",
        bundle.action_head_digest.as_array(),
        bundle.target_head_digest.as_array(),
        bundle.parameter_head_digest.as_array(),
        bundle.disposition_head_digest.as_array(),
        bundle.postcondition_head_digest.as_array(),
        bundle.state_head_digest.as_array(),
    ]))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellRequestV1 {
    pub request_id: StableId,
    pub generation: Generation,
    pub model_id: StableId,
    pub model_manifest_digest: Digest32,
    pub weights_digest: Digest32,
    pub objective_digest: Digest32,
    pub ndu_digest: Digest32,
    pub body_digest: Digest32,
    pub observation_frontier_digest: Digest32,
    pub legal_action_set_digest: Digest32,
    pub candidate_target_set_digest: Digest32,
    pub parameter_bundle_digest: Digest32,
    pub previous_state_digest: Option<Digest32>,
    pub actions: Vec<DecisionCellActionCandidateV1>,
    pub targets: Vec<DecisionCellTargetCandidateV1>,
    pub feature_vector_q24: Vec<i64>,
    pub deadline_monotonic_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellRuntimeTupleV1 {
    pub model_id: StableId,
    pub model_manifest_digest: Digest32,
    pub weights_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub quantization_digest: Digest32,
    pub runtime_digest: Digest32,
    pub device_digest: Digest32,
    pub parameter_bundle: DecisionCellParameterBundleV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DecisionCellTerminalStatusV1 {
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DecisionCellDispositionV1 {
    Continue,
    Stop,
    Abstain,
    RequestEvidence,
    SlowPath,
    Success,
}

impl DecisionCellDispositionV1 {
    const fn from_index(index: usize) -> Self {
        match index {
            0 => Self::Continue,
            1 => Self::Stop,
            2 => Self::Abstain,
            3 => Self::RequestEvidence,
            4 => Self::SlowPath,
            _ => Self::Success,
        }
    }

    const fn code(self) -> u8 {
        match self {
            Self::Continue => 0,
            Self::Stop => 1,
            Self::Abstain => 2,
            Self::RequestEvidence => 3,
            Self::SlowPath => 4,
            Self::Success => 5,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellObservationV1 {
    pub action_scores_q24: Vec<i64>,
    pub target_scores_q24: Vec<i64>,
    pub parameter_values_q24: Vec<i64>,
    pub disposition_scores_q24: [i64; DISPOSITION_COUNT],
    pub expected_postcondition_digest: Digest32,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub value_q24: i64,
    pub cost_q24: i64,
    pub state_successor_digest: Digest32,
    pub observed_memory_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub queue_age_micros: u64,
    pub latency_micros: u64,
    pub status: DecisionCellTerminalStatusV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellReceiptV1 {
    pub request_digest: Digest32,
    pub runtime_tuple: DecisionCellRuntimeTupleV1,
    pub runtime_tuple_digest: Digest32,
    pub output_digest: Digest32,
    pub action_scores_q24: Vec<i64>,
    pub target_scores_q24: Vec<i64>,
    pub selected_action_id: Option<StableId>,
    pub selected_action_semantic_digest: Option<Digest32>,
    pub selected_target_id: Option<StableId>,
    pub selected_target_generation: Option<u64>,
    pub selected_target_semantic_digest: Option<Digest32>,
    pub parameter_values_q24: Vec<i64>,
    pub disposition_scores_q24: [i64; DISPOSITION_COUNT],
    pub expected_postcondition_digest: Digest32,
    pub disposition: Option<DecisionCellDispositionV1>,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub value_q24: i64,
    pub cost_q24: i64,
    pub state_successor_digest: Digest32,
    pub observed_memory_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub queue_age_micros: u64,
    pub latency_micros: u64,
    pub status: DecisionCellTerminalStatusV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DecisionCellContractError {
    EmptyDigest(&'static str),
    InvalidDeadline,
    ActionLimit,
    TargetLimit,
    FeatureLimit,
    ParameterLimit,
    InvalidCandidateOrder,
    CandidateSetDigestMismatch,
    InvalidParameterBundle,
    RuntimeBindingMismatch,
    OutputLimit,
    InvalidProbability,
    InvalidEncoding,
    MissingTarget,
    NonTerminalOutputPresent,
    ReceiptDigestMismatch,
    AuthorityGranted,
    Arithmetic,
}

impl fmt::Display for DecisionCellContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DecisionCellContractError {}

pub fn decision_cell_action_set_digest_v1(
    actions: &[DecisionCellActionCandidateV1],
) -> Result<Digest32, DecisionCellContractError> {
    validate_actions(actions)?;
    let mut bytes = b"hepta.inference.decision-cell-actions.v1".to_vec();
    push_len(&mut bytes, actions.len())?;
    for action in actions {
        push_id(&mut bytes, &action.action_id)?;
        push_digest(&mut bytes, action.action_semantic_digest);
        bytes.push(u8::from(action.target_required));
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn decision_cell_target_set_digest_v1(
    targets: &[DecisionCellTargetCandidateV1],
) -> Result<Digest32, DecisionCellContractError> {
    validate_targets(targets)?;
    let mut bytes = b"hepta.inference.decision-cell-targets.v1".to_vec();
    push_len(&mut bytes, targets.len())?;
    for target in targets {
        push_id(&mut bytes, &target.target_id)?;
        bytes.extend_from_slice(&target.target_generation.to_be_bytes());
        push_digest(&mut bytes, target.target_semantic_digest);
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn decision_cell_request_digest_v1(
    request: &DecisionCellRequestV1,
) -> Result<Digest32, DecisionCellContractError> {
    validate_request(request)?;
    let mut bytes = b"hepta.inference.decision-cell-request.v1".to_vec();
    push_id(&mut bytes, &request.request_id)?;
    bytes.extend_from_slice(&request.generation.get().to_be_bytes());
    push_id(&mut bytes, &request.model_id)?;
    for digest in [
        request.model_manifest_digest,
        request.weights_digest,
        request.objective_digest,
        request.ndu_digest,
        request.body_digest,
        request.observation_frontier_digest,
        request.legal_action_set_digest,
        request.candidate_target_set_digest,
        request.parameter_bundle_digest,
    ] {
        push_digest(&mut bytes, digest);
    }
    push_optional_digest(&mut bytes, request.previous_state_digest);
    push_len(&mut bytes, request.actions.len())?;
    for action in &request.actions {
        push_id(&mut bytes, &action.action_id)?;
        push_digest(&mut bytes, action.action_semantic_digest);
        bytes.push(u8::from(action.target_required));
    }
    push_len(&mut bytes, request.targets.len())?;
    for target in &request.targets {
        push_id(&mut bytes, &target.target_id)?;
        bytes.extend_from_slice(&target.target_generation.to_be_bytes());
        push_digest(&mut bytes, target.target_semantic_digest);
    }
    push_q24(&mut bytes, &request.feature_vector_q24)?;
    bytes.extend_from_slice(&request.deadline_monotonic_micros.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn build_decision_cell_receipt_v1(
    request: &DecisionCellRequestV1,
    runtime_tuple: DecisionCellRuntimeTupleV1,
    observation: DecisionCellObservationV1,
) -> Result<DecisionCellReceiptV1, DecisionCellContractError> {
    let request_digest = decision_cell_request_digest_v1(request)?;
    validate_runtime_tuple(request, &runtime_tuple)?;
    validate_observation(request, &observation)?;
    let runtime_tuple_digest = digest_runtime_tuple(&runtime_tuple)?;
    let output_digest = digest_output(runtime_tuple_digest, &observation)?;
    let (selected_action, selected_target, disposition) = build_selection(request, &observation)?;

    let mut receipt = DecisionCellReceiptV1 {
        request_digest,
        runtime_tuple,
        runtime_tuple_digest,
        output_digest,
        action_scores_q24: observation.action_scores_q24,
        target_scores_q24: observation.target_scores_q24,
        selected_action_id: selected_action.map(|value| value.action_id.clone()),
        selected_action_semantic_digest: selected_action.map(|value| value.action_semantic_digest),
        selected_target_id: selected_target.map(|value| value.target_id.clone()),
        selected_target_generation: selected_target.map(|value| value.target_generation),
        selected_target_semantic_digest: selected_target.map(|value| value.target_semantic_digest),
        parameter_values_q24: observation.parameter_values_q24,
        disposition_scores_q24: observation.disposition_scores_q24,
        expected_postcondition_digest: observation.expected_postcondition_digest,
        disposition,
        confidence_ppm: observation.confidence_ppm,
        ood_ppm: observation.ood_ppm,
        value_q24: observation.value_q24,
        cost_q24: observation.cost_q24,
        state_successor_digest: observation.state_successor_digest,
        observed_memory_bytes: observation.observed_memory_bytes,
        transient_allocation_bytes: observation.transient_allocation_bytes,
        queue_age_micros: observation.queue_age_micros,
        latency_micros: observation.latency_micros,
        status: observation.status,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = digest_receipt(&receipt)?;
    verify_decision_cell_receipt_v1(request, &receipt)?;
    Ok(receipt)
}

pub fn verify_decision_cell_receipt_v1(
    request: &DecisionCellRequestV1,
    receipt: &DecisionCellReceiptV1,
) -> Result<(), DecisionCellContractError> {
    if receipt.authority.grants_any() {
        return Err(DecisionCellContractError::AuthorityGranted);
    }
    if receipt.request_digest != decision_cell_request_digest_v1(request)? {
        return Err(DecisionCellContractError::RuntimeBindingMismatch);
    }
    validate_runtime_tuple(request, &receipt.runtime_tuple)?;
    if receipt.runtime_tuple_digest != digest_runtime_tuple(&receipt.runtime_tuple)? {
        return Err(DecisionCellContractError::RuntimeBindingMismatch);
    }
    let observation = observation_from_receipt(receipt);
    validate_observation(request, &observation)?;
    if receipt.output_digest != digest_output(receipt.runtime_tuple_digest, &observation)? {
        return Err(DecisionCellContractError::ReceiptDigestMismatch);
    }
    let selected = build_selection(request, &observation)?;
    if receipt.selected_action_id != selected.0.map(|value| value.action_id.clone())
        || receipt.selected_action_semantic_digest
            != selected.0.map(|value| value.action_semantic_digest)
        || receipt.selected_target_id != selected.1.map(|value| value.target_id.clone())
        || receipt.selected_target_generation != selected.1.map(|value| value.target_generation)
        || receipt.selected_target_semantic_digest
            != selected.1.map(|value| value.target_semantic_digest)
        || receipt.disposition != selected.2
        || receipt.receipt_digest.is_zero()
        || receipt.receipt_digest != digest_receipt(receipt)?
    {
        return Err(DecisionCellContractError::ReceiptDigestMismatch);
    }
    Ok(())
}

type Selection<'a> = (
    Option<&'a DecisionCellActionCandidateV1>,
    Option<&'a DecisionCellTargetCandidateV1>,
    Option<DecisionCellDispositionV1>,
);

fn build_selection<'a>(
    request: &'a DecisionCellRequestV1,
    observation: &DecisionCellObservationV1,
) -> Result<Selection<'a>, DecisionCellContractError> {
    if !matches!(observation.status, DecisionCellTerminalStatusV1::Succeeded) {
        return Ok((None, None, None));
    }
    let disposition_index = argmax(&observation.disposition_scores_q24)
        .ok_or(DecisionCellContractError::OutputLimit)?;
    let disposition = DecisionCellDispositionV1::from_index(disposition_index);
    if !matches!(disposition, DecisionCellDispositionV1::Continue) {
        return Ok((None, None, Some(disposition)));
    }
    let action_index =
        argmax(&observation.action_scores_q24).ok_or(DecisionCellContractError::OutputLimit)?;
    let action = request
        .actions
        .get(action_index)
        .ok_or(DecisionCellContractError::OutputLimit)?;
    let target = if action.target_required {
        let target_index = argmax(&observation.target_scores_q24)
            .ok_or(DecisionCellContractError::MissingTarget)?;
        Some(
            request
                .targets
                .get(target_index)
                .ok_or(DecisionCellContractError::MissingTarget)?,
        )
    } else {
        None
    };
    Ok((Some(action), target, Some(disposition)))
}

fn observation_from_receipt(receipt: &DecisionCellReceiptV1) -> DecisionCellObservationV1 {
    DecisionCellObservationV1 {
        action_scores_q24: receipt.action_scores_q24.clone(),
        target_scores_q24: receipt.target_scores_q24.clone(),
        parameter_values_q24: receipt.parameter_values_q24.clone(),
        disposition_scores_q24: receipt.disposition_scores_q24,
        expected_postcondition_digest: receipt.expected_postcondition_digest,
        confidence_ppm: receipt.confidence_ppm,
        ood_ppm: receipt.ood_ppm,
        value_q24: receipt.value_q24,
        cost_q24: receipt.cost_q24,
        state_successor_digest: receipt.state_successor_digest,
        observed_memory_bytes: receipt.observed_memory_bytes,
        transient_allocation_bytes: receipt.transient_allocation_bytes,
        queue_age_micros: receipt.queue_age_micros,
        latency_micros: receipt.latency_micros,
        status: receipt.status,
    }
}

fn validate_request(request: &DecisionCellRequestV1) -> Result<(), DecisionCellContractError> {
    if request.deadline_monotonic_micros == 0 {
        return Err(DecisionCellContractError::InvalidDeadline);
    }
    for (name, digest) in [
        ("model manifest", request.model_manifest_digest),
        ("weights", request.weights_digest),
        ("objective", request.objective_digest),
        ("ndu", request.ndu_digest),
        ("body", request.body_digest),
        ("observation frontier", request.observation_frontier_digest),
        ("legal action set", request.legal_action_set_digest),
        ("candidate target set", request.candidate_target_set_digest),
        ("parameter bundle", request.parameter_bundle_digest),
    ] {
        require_digest(digest, name)?;
    }
    if request.previous_state_digest.is_some_and(Digest32::is_zero) {
        return Err(DecisionCellContractError::EmptyDigest("previous state"));
    }
    if request.feature_vector_q24.is_empty()
        || request.feature_vector_q24.len() > MAX_FEATURES
        || !q24_slice_valid(&request.feature_vector_q24)
    {
        return Err(DecisionCellContractError::FeatureLimit);
    }
    if decision_cell_action_set_digest_v1(&request.actions)? != request.legal_action_set_digest
        || decision_cell_target_set_digest_v1(&request.targets)?
            != request.candidate_target_set_digest
    {
        return Err(DecisionCellContractError::CandidateSetDigestMismatch);
    }
    Ok(())
}

fn validate_actions(
    actions: &[DecisionCellActionCandidateV1],
) -> Result<(), DecisionCellContractError> {
    if actions.is_empty() || actions.len() > MAX_ACTIONS {
        return Err(DecisionCellContractError::ActionLimit);
    }
    if actions
        .windows(2)
        .any(|pair| pair[0].action_id >= pair[1].action_id)
    {
        return Err(DecisionCellContractError::InvalidCandidateOrder);
    }
    for action in actions {
        require_digest(action.action_semantic_digest, "action semantic")?;
    }
    Ok(())
}

fn validate_targets(
    targets: &[DecisionCellTargetCandidateV1],
) -> Result<(), DecisionCellContractError> {
    if targets.len() > MAX_TARGETS {
        return Err(DecisionCellContractError::TargetLimit);
    }
    if targets
        .windows(2)
        .any(|pair| pair[0].target_id >= pair[1].target_id)
    {
        return Err(DecisionCellContractError::InvalidCandidateOrder);
    }
    for target in targets {
        if target.target_generation == 0 {
            return Err(DecisionCellContractError::TargetLimit);
        }
        require_digest(target.target_semantic_digest, "target semantic")?;
    }
    Ok(())
}

fn validate_runtime_tuple(
    request: &DecisionCellRequestV1,
    runtime: &DecisionCellRuntimeTupleV1,
) -> Result<(), DecisionCellContractError> {
    if runtime.model_id != request.model_id
        || runtime.model_manifest_digest != request.model_manifest_digest
        || runtime.weights_digest != request.weights_digest
        || runtime.parameter_bundle.semantic_digest()? != request.parameter_bundle_digest
    {
        return Err(DecisionCellContractError::RuntimeBindingMismatch);
    }
    for (name, digest) in [
        ("tokenizer", runtime.tokenizer_digest),
        ("preprocessor", runtime.preprocessor_digest),
        ("quantization", runtime.quantization_digest),
        ("runtime", runtime.runtime_digest),
        ("device", runtime.device_digest),
    ] {
        require_digest(digest, name)?;
    }
    Ok(())
}

fn validate_observation(
    request: &DecisionCellRequestV1,
    observation: &DecisionCellObservationV1,
) -> Result<(), DecisionCellContractError> {
    if observation.confidence_ppm > PPM || observation.ood_ppm > PPM {
        return Err(DecisionCellContractError::InvalidProbability);
    }
    match observation.status {
        DecisionCellTerminalStatusV1::Succeeded => {
            if observation.action_scores_q24.len() != request.actions.len()
                || observation.target_scores_q24.len() != request.targets.len()
                || observation.parameter_values_q24.len() > MAX_PARAMETERS
                || !q24_slice_valid(&observation.action_scores_q24)
                || !q24_slice_valid(&observation.target_scores_q24)
                || !q24_slice_valid(&observation.parameter_values_q24)
                || !q24_slice_valid(&observation.disposition_scores_q24)
                || !q24_valid(observation.value_q24)
                || !q24_valid(observation.cost_q24)
            {
                return Err(DecisionCellContractError::OutputLimit);
            }
            require_digest(
                observation.expected_postcondition_digest,
                "expected postcondition",
            )?;
            require_digest(observation.state_successor_digest, "state successor")?;
            let action = request
                .actions
                .get(
                    argmax(&observation.action_scores_q24)
                        .ok_or(DecisionCellContractError::OutputLimit)?,
                )
                .ok_or(DecisionCellContractError::OutputLimit)?;
            if action.target_required && request.targets.is_empty() {
                return Err(DecisionCellContractError::MissingTarget);
            }
        }
        DecisionCellTerminalStatusV1::Failed
        | DecisionCellTerminalStatusV1::Cancelled
        | DecisionCellTerminalStatusV1::Indeterminate => {
            if !observation.action_scores_q24.is_empty()
                || !observation.target_scores_q24.is_empty()
                || !observation.parameter_values_q24.is_empty()
                || observation.disposition_scores_q24 != [0; DISPOSITION_COUNT]
                || !observation.expected_postcondition_digest.is_zero()
                || observation.confidence_ppm != 0
                || observation.ood_ppm != 0
                || observation.value_q24 != 0
                || observation.cost_q24 != 0
                || !observation.state_successor_digest.is_zero()
            {
                return Err(DecisionCellContractError::NonTerminalOutputPresent);
            }
        }
    }
    Ok(())
}

pub fn decision_cell_runtime_tuple_digest_v1(
    runtime: &DecisionCellRuntimeTupleV1,
) -> Result<Digest32, DecisionCellContractError> {
    digest_runtime_tuple(runtime)
}

fn digest_runtime_tuple(
    runtime: &DecisionCellRuntimeTupleV1,
) -> Result<Digest32, DecisionCellContractError> {
    let mut bytes = b"hepta.inference.decision-cell-runtime-tuple.v1".to_vec();
    push_id(&mut bytes, &runtime.model_id)?;
    for digest in [
        runtime.model_manifest_digest,
        runtime.weights_digest,
        runtime.tokenizer_digest,
        runtime.preprocessor_digest,
        runtime.quantization_digest,
        runtime.runtime_digest,
        runtime.device_digest,
        runtime.parameter_bundle.semantic_digest()?,
    ] {
        push_digest(&mut bytes, digest);
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_output(
    runtime_tuple_digest: Digest32,
    observation: &DecisionCellObservationV1,
) -> Result<Digest32, DecisionCellContractError> {
    let mut bytes = b"hepta.inference.decision-cell-output.v1".to_vec();
    push_digest(&mut bytes, runtime_tuple_digest);
    push_q24(&mut bytes, &observation.action_scores_q24)?;
    push_q24(&mut bytes, &observation.target_scores_q24)?;
    push_q24(&mut bytes, &observation.parameter_values_q24)?;
    push_q24(&mut bytes, &observation.disposition_scores_q24)?;
    push_digest(&mut bytes, observation.expected_postcondition_digest);
    bytes.extend_from_slice(&observation.confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&observation.ood_ppm.to_be_bytes());
    bytes.extend_from_slice(&observation.value_q24.to_be_bytes());
    bytes.extend_from_slice(&observation.cost_q24.to_be_bytes());
    push_digest(&mut bytes, observation.state_successor_digest);
    for value in [
        observation.observed_memory_bytes,
        observation.transient_allocation_bytes,
        observation.queue_age_micros,
        observation.latency_micros,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.push(status_code(observation.status));
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_receipt(receipt: &DecisionCellReceiptV1) -> Result<Digest32, DecisionCellContractError> {
    let mut bytes = b"hepta.inference.decision-cell-receipt.v1".to_vec();
    for digest in [
        receipt.request_digest,
        receipt.runtime_tuple_digest,
        receipt.output_digest,
    ] {
        push_digest(&mut bytes, digest);
    }
    push_optional_id(&mut bytes, receipt.selected_action_id.as_ref())?;
    push_optional_digest(&mut bytes, receipt.selected_action_semantic_digest);
    push_optional_id(&mut bytes, receipt.selected_target_id.as_ref())?;
    match receipt.selected_target_generation {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
    push_optional_digest(&mut bytes, receipt.selected_target_semantic_digest);
    bytes.push(
        receipt
            .disposition
            .map_or(u8::MAX, DecisionCellDispositionV1::code),
    );
    bytes.push(status_code(receipt.status));
    Ok(Digest32::of_bytes(&bytes))
}

const fn status_code(status: DecisionCellTerminalStatusV1) -> u8 {
    match status {
        DecisionCellTerminalStatusV1::Succeeded => 0,
        DecisionCellTerminalStatusV1::Failed => 1,
        DecisionCellTerminalStatusV1::Cancelled => 2,
        DecisionCellTerminalStatusV1::Indeterminate => 3,
    }
}

fn argmax(values: &[i64]) -> Option<usize> {
    values
        .iter()
        .enumerate()
        .max_by(|(left_index, left), (right_index, right)| {
            left.cmp(right).then_with(|| right_index.cmp(left_index))
        })
        .map(|(index, _)| index)
}

fn q24_valid(value: i64) -> bool {
    (-MAX_Q24..=MAX_Q24).contains(&value)
}

fn q24_slice_valid(values: &[i64]) -> bool {
    values.iter().copied().all(q24_valid)
}

fn require_digest(digest: Digest32, name: &'static str) -> Result<(), DecisionCellContractError> {
    if digest.is_zero() {
        Err(DecisionCellContractError::EmptyDigest(name))
    } else {
        Ok(())
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), DecisionCellContractError> {
    let raw = value.as_str().as_bytes();
    let len = u32::try_from(raw.len()).map_err(|_| DecisionCellContractError::Arithmetic)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_optional_id(
    bytes: &mut Vec<u8>,
    value: Option<&StableId>,
) -> Result<(), DecisionCellContractError> {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value)?;
        }
        None => bytes.push(0),
    }
    Ok(())
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_digest(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), DecisionCellContractError> {
    let value = u64::try_from(value).map_err(|_| DecisionCellContractError::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn push_q24(bytes: &mut Vec<u8>, values: &[i64]) -> Result<(), DecisionCellContractError> {
    push_len(bytes, values.len())?;
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(())
}

const MAX_DECISION_CELL_RECEIPT_BYTES: usize = 1024 * 1024;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ParameterBundleWireV1 {
    base_bundle_digest: String,
    organ_id: String,
    organ_bundle_digest: String,
    cell_slot_id: Option<String>,
    cell_bundle_digest: Option<String>,
    action_head_digest: String,
    target_head_digest: String,
    parameter_head_digest: String,
    disposition_head_digest: String,
    postcondition_head_digest: String,
    state_head_digest: String,
    calibration_artifact_digest: String,
    ood_artifact_digest: String,
    effective_parameter_digest: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeTupleWireV1 {
    model_id: String,
    model_manifest_digest: String,
    weights_digest: String,
    tokenizer_digest: String,
    preprocessor_digest: String,
    quantization_digest: String,
    runtime_digest: String,
    device_digest: String,
    parameter_bundle: ParameterBundleWireV1,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DecisionCellReceiptWireV1 {
    schema: String,
    request_digest: String,
    runtime_tuple: RuntimeTupleWireV1,
    runtime_tuple_digest: String,
    output_digest: String,
    action_scores_q24: Vec<i64>,
    target_scores_q24: Vec<i64>,
    selected_action_id: Option<String>,
    selected_action_semantic_digest: Option<String>,
    selected_target_id: Option<String>,
    selected_target_generation: Option<u64>,
    selected_target_semantic_digest: Option<String>,
    parameter_values_q24: Vec<i64>,
    disposition_scores_q24: [i64; DISPOSITION_COUNT],
    expected_postcondition_digest: String,
    disposition: Option<u8>,
    confidence_ppm: u32,
    ood_ppm: u32,
    value_q24: i64,
    cost_q24: i64,
    state_successor_digest: String,
    observed_memory_bytes: u64,
    transient_allocation_bytes: u64,
    queue_age_micros: u64,
    latency_micros: u64,
    status: u8,
    receipt_digest: String,
    authority_granted: bool,
}

pub fn encode_decision_cell_receipt_v1(
    request: &DecisionCellRequestV1,
    receipt: &DecisionCellReceiptV1,
) -> Result<Vec<u8>, DecisionCellContractError> {
    verify_decision_cell_receipt_v1(request, receipt)?;
    let wire = DecisionCellReceiptWireV1 {
        schema: "hepta.inference.decision-cell-receipt.v1".to_owned(),
        request_digest: receipt.request_digest.to_string(),
        runtime_tuple: runtime_to_wire(&receipt.runtime_tuple),
        runtime_tuple_digest: receipt.runtime_tuple_digest.to_string(),
        output_digest: receipt.output_digest.to_string(),
        action_scores_q24: receipt.action_scores_q24.clone(),
        target_scores_q24: receipt.target_scores_q24.clone(),
        selected_action_id: receipt.selected_action_id.as_ref().map(ToString::to_string),
        selected_action_semantic_digest: receipt
            .selected_action_semantic_digest
            .map(|value| value.to_string()),
        selected_target_id: receipt.selected_target_id.as_ref().map(ToString::to_string),
        selected_target_generation: receipt.selected_target_generation,
        selected_target_semantic_digest: receipt
            .selected_target_semantic_digest
            .map(|value| value.to_string()),
        parameter_values_q24: receipt.parameter_values_q24.clone(),
        disposition_scores_q24: receipt.disposition_scores_q24,
        expected_postcondition_digest: receipt.expected_postcondition_digest.to_string(),
        disposition: receipt.disposition.map(DecisionCellDispositionV1::code),
        confidence_ppm: receipt.confidence_ppm,
        ood_ppm: receipt.ood_ppm,
        value_q24: receipt.value_q24,
        cost_q24: receipt.cost_q24,
        state_successor_digest: receipt.state_successor_digest.to_string(),
        observed_memory_bytes: receipt.observed_memory_bytes,
        transient_allocation_bytes: receipt.transient_allocation_bytes,
        queue_age_micros: receipt.queue_age_micros,
        latency_micros: receipt.latency_micros,
        status: status_code(receipt.status),
        receipt_digest: receipt.receipt_digest.to_string(),
        authority_granted: receipt.authority.grants_any(),
    };
    let bytes =
        serde_json::to_vec(&wire).map_err(|_| DecisionCellContractError::InvalidEncoding)?;
    if bytes.len() > MAX_DECISION_CELL_RECEIPT_BYTES {
        return Err(DecisionCellContractError::OutputLimit);
    }
    Ok(bytes)
}

pub fn decode_decision_cell_receipt_v1(
    request: &DecisionCellRequestV1,
    bytes: &[u8],
) -> Result<DecisionCellReceiptV1, DecisionCellContractError> {
    if bytes.is_empty() || bytes.len() > MAX_DECISION_CELL_RECEIPT_BYTES {
        return Err(DecisionCellContractError::OutputLimit);
    }
    let wire: DecisionCellReceiptWireV1 =
        serde_json::from_slice(bytes).map_err(|_| DecisionCellContractError::InvalidEncoding)?;
    if wire.schema != "hepta.inference.decision-cell-receipt.v1" || wire.authority_granted {
        return Err(DecisionCellContractError::InvalidEncoding);
    }
    let receipt = DecisionCellReceiptV1 {
        request_digest: parse_digest(&wire.request_digest)?,
        runtime_tuple: runtime_from_wire(wire.runtime_tuple)?,
        runtime_tuple_digest: parse_digest(&wire.runtime_tuple_digest)?,
        output_digest: parse_digest(&wire.output_digest)?,
        action_scores_q24: wire.action_scores_q24,
        target_scores_q24: wire.target_scores_q24,
        selected_action_id: parse_optional_id(wire.selected_action_id)?,
        selected_action_semantic_digest: parse_optional_digest(
            wire.selected_action_semantic_digest,
        )?,
        selected_target_id: parse_optional_id(wire.selected_target_id)?,
        selected_target_generation: wire.selected_target_generation,
        selected_target_semantic_digest: parse_optional_digest(
            wire.selected_target_semantic_digest,
        )?,
        parameter_values_q24: wire.parameter_values_q24,
        disposition_scores_q24: wire.disposition_scores_q24,
        expected_postcondition_digest: parse_digest(&wire.expected_postcondition_digest)?,
        disposition: wire.disposition.map(disposition_from_code).transpose()?,
        confidence_ppm: wire.confidence_ppm,
        ood_ppm: wire.ood_ppm,
        value_q24: wire.value_q24,
        cost_q24: wire.cost_q24,
        state_successor_digest: parse_digest(&wire.state_successor_digest)?,
        observed_memory_bytes: wire.observed_memory_bytes,
        transient_allocation_bytes: wire.transient_allocation_bytes,
        queue_age_micros: wire.queue_age_micros,
        latency_micros: wire.latency_micros,
        status: status_from_code(wire.status)?,
        receipt_digest: parse_digest(&wire.receipt_digest)?,
        authority: AuthorityPosture::DENY_ALL,
    };
    verify_decision_cell_receipt_v1(request, &receipt)?;
    Ok(receipt)
}

fn runtime_to_wire(value: &DecisionCellRuntimeTupleV1) -> RuntimeTupleWireV1 {
    RuntimeTupleWireV1 {
        model_id: value.model_id.to_string(),
        model_manifest_digest: value.model_manifest_digest.to_string(),
        weights_digest: value.weights_digest.to_string(),
        tokenizer_digest: value.tokenizer_digest.to_string(),
        preprocessor_digest: value.preprocessor_digest.to_string(),
        quantization_digest: value.quantization_digest.to_string(),
        runtime_digest: value.runtime_digest.to_string(),
        device_digest: value.device_digest.to_string(),
        parameter_bundle: bundle_to_wire(&value.parameter_bundle),
    }
}

fn bundle_to_wire(value: &DecisionCellParameterBundleV1) -> ParameterBundleWireV1 {
    ParameterBundleWireV1 {
        base_bundle_digest: value.base_bundle_digest.to_string(),
        organ_id: value.organ_id.to_string(),
        organ_bundle_digest: value.organ_bundle_digest.to_string(),
        cell_slot_id: value.cell_slot_id.as_ref().map(ToString::to_string),
        cell_bundle_digest: value.cell_bundle_digest.map(|value| value.to_string()),
        action_head_digest: value.action_head_digest.to_string(),
        target_head_digest: value.target_head_digest.to_string(),
        parameter_head_digest: value.parameter_head_digest.to_string(),
        disposition_head_digest: value.disposition_head_digest.to_string(),
        postcondition_head_digest: value.postcondition_head_digest.to_string(),
        state_head_digest: value.state_head_digest.to_string(),
        calibration_artifact_digest: value.calibration_artifact_digest.to_string(),
        ood_artifact_digest: value.ood_artifact_digest.to_string(),
        effective_parameter_digest: value.effective_parameter_digest.to_string(),
    }
}

fn runtime_from_wire(
    value: RuntimeTupleWireV1,
) -> Result<DecisionCellRuntimeTupleV1, DecisionCellContractError> {
    Ok(DecisionCellRuntimeTupleV1 {
        model_id: parse_id(&value.model_id)?,
        model_manifest_digest: parse_digest(&value.model_manifest_digest)?,
        weights_digest: parse_digest(&value.weights_digest)?,
        tokenizer_digest: parse_digest(&value.tokenizer_digest)?,
        preprocessor_digest: parse_digest(&value.preprocessor_digest)?,
        quantization_digest: parse_digest(&value.quantization_digest)?,
        runtime_digest: parse_digest(&value.runtime_digest)?,
        device_digest: parse_digest(&value.device_digest)?,
        parameter_bundle: bundle_from_wire(value.parameter_bundle)?,
    })
}

fn bundle_from_wire(
    value: ParameterBundleWireV1,
) -> Result<DecisionCellParameterBundleV1, DecisionCellContractError> {
    Ok(DecisionCellParameterBundleV1 {
        base_bundle_digest: parse_digest(&value.base_bundle_digest)?,
        organ_id: parse_id(&value.organ_id)?,
        organ_bundle_digest: parse_digest(&value.organ_bundle_digest)?,
        cell_slot_id: parse_optional_id(value.cell_slot_id)?,
        cell_bundle_digest: parse_optional_digest(value.cell_bundle_digest)?,
        action_head_digest: parse_digest(&value.action_head_digest)?,
        target_head_digest: parse_digest(&value.target_head_digest)?,
        parameter_head_digest: parse_digest(&value.parameter_head_digest)?,
        disposition_head_digest: parse_digest(&value.disposition_head_digest)?,
        postcondition_head_digest: parse_digest(&value.postcondition_head_digest)?,
        state_head_digest: parse_digest(&value.state_head_digest)?,
        calibration_artifact_digest: parse_digest(&value.calibration_artifact_digest)?,
        ood_artifact_digest: parse_digest(&value.ood_artifact_digest)?,
        effective_parameter_digest: parse_digest(&value.effective_parameter_digest)?,
    })
}

fn parse_id(value: &str) -> Result<StableId, DecisionCellContractError> {
    StableId::new(value.to_owned()).map_err(|_| DecisionCellContractError::InvalidEncoding)
}

fn parse_optional_id(value: Option<String>) -> Result<Option<StableId>, DecisionCellContractError> {
    value.map(|value| parse_id(&value)).transpose()
}

fn parse_digest(value: &str) -> Result<Digest32, DecisionCellContractError> {
    Digest32::from_str(value).map_err(|_| DecisionCellContractError::InvalidEncoding)
}

fn parse_optional_digest(
    value: Option<String>,
) -> Result<Option<Digest32>, DecisionCellContractError> {
    value.map(|value| parse_digest(&value)).transpose()
}

const fn disposition_from_code(
    value: u8,
) -> Result<DecisionCellDispositionV1, DecisionCellContractError> {
    match value {
        0 => Ok(DecisionCellDispositionV1::Continue),
        1 => Ok(DecisionCellDispositionV1::Stop),
        2 => Ok(DecisionCellDispositionV1::Abstain),
        3 => Ok(DecisionCellDispositionV1::RequestEvidence),
        4 => Ok(DecisionCellDispositionV1::SlowPath),
        5 => Ok(DecisionCellDispositionV1::Success),
        _ => Err(DecisionCellContractError::InvalidEncoding),
    }
}

const fn status_from_code(
    value: u8,
) -> Result<DecisionCellTerminalStatusV1, DecisionCellContractError> {
    match value {
        0 => Ok(DecisionCellTerminalStatusV1::Succeeded),
        1 => Ok(DecisionCellTerminalStatusV1::Failed),
        2 => Ok(DecisionCellTerminalStatusV1::Cancelled),
        3 => Ok(DecisionCellTerminalStatusV1::Indeterminate),
        _ => Err(DecisionCellContractError::InvalidEncoding),
    }
}

#[cfg(test)]
#[path = "decision_cell_tests.rs"]
mod tests;
