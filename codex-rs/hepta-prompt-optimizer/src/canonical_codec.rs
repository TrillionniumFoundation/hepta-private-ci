use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::RawPromptExerciseDecisionV1;
use super::PromptCandidateSetReceiptV1;
use super::PromptDecisionBoundaryV1;
use super::PromptExerciseActionV1;
use super::PromptPortfolioReceiptV1;
use super::PromptPricingReceiptV1;

const MAX_ENCODED_BYTES: usize = 262_144;
const MAX_CANDIDATES: usize = 128;
const MAX_SELECTED: usize = 16;
const MAX_TOKEN_BUDGET: u32 = 1_000_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PromptCandidateSetWireV1 {
    pub set_id: String,
    pub objective_digest: String,
    pub state_digest: String,
    pub registry_digest: String,
    pub candidate_factor_ids: Vec<String>,
    pub selection_grammar_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PromptConfidenceIntervalWireV1 {
    pub lower_q32: i64,
    pub upper_q32: i64,
    pub support_count: u32,
    pub support_audit_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PromptPricingWireV1 {
    pub factor_id: String,
    pub state_digest: String,
    pub expected_utility_q32: i64,
    pub downside_q32: i64,
    pub token_cost: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub confidence_interval: PromptConfidenceIntervalWireV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PromptPortfolioWireV1 {
    pub portfolio_id: String,
    pub candidate_set_digest: String,
    pub factor_ids: Vec<String>,
    pub interaction_digest: String,
    pub expected_utility_q32: i64,
    pub total_token_upper_bound: u32,
    pub valid_until_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PromptDecisionBoundaryWireV1 {
    RequestAccepted,
    ObjectiveCompiled,
    BeforePlanning,
    BeforeCandidateGeneration,
    BeforeModelOrToolDispatch,
    AfterObservation,
    AfterFailureOrUncertaintySpike,
    BeforeIrreversibleMutation,
    BeforeVerification,
    BeforeFinalResponse,
    BeforeCompactOrHandoff,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PromptExerciseActionWireV1 {
    Exercise,
    Wait,
    RejectStale,
    NoIntervention,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PromptExerciseWireV1 {
    pub factor_or_portfolio_id: String,
    pub decision_boundary: PromptDecisionBoundaryWireV1,
    pub exercise_now_value_q32: i64,
    pub wait_value_q32: i64,
    pub decision: PromptExerciseActionWireV1,
    pub policy_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptCodecErrorV1 {
    EncodedSize,
    Json,
    InvalidId(&'static str),
    InvalidDigest(&'static str),
    InvalidOrder(&'static str),
    InvalidBound(&'static str),
    AuthorityGranted,
    SemanticMismatch,
}

impl fmt::Display for PromptCodecErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptCodecErrorV1 {}

pub fn encode_candidate_set_receipt_json_v1(
    value: &PromptCandidateSetReceiptV1,
) -> Result<Vec<u8>, PromptCodecErrorV1> {
    if value.authority.grants_any() {
        return Err(PromptCodecErrorV1::AuthorityGranted);
    }
    encode_candidate_set_wire_json_v1(&PromptCandidateSetWireV1 {
        set_id: value.set_id.to_string(),
        objective_digest: value.objective_digest.to_string(),
        state_digest: value.state_digest.to_string(),
        registry_digest: value.registry_digest.to_string(),
        candidate_factor_ids: value
            .candidate_factor_ids
            .iter()
            .map(ToString::to_string)
            .collect(),
        selection_grammar_digest: value.selection_grammar_digest.to_string(),
    })
}

pub fn encode_candidate_set_wire_json_v1(
    value: &PromptCandidateSetWireV1,
) -> Result<Vec<u8>, PromptCodecErrorV1> {
    validate_candidate_set(value)?;
    encode(value)
}

pub fn decode_candidate_set_receipt_json_v1(
    bytes: &[u8],
) -> Result<PromptCandidateSetWireV1, PromptCodecErrorV1> {
    let value: PromptCandidateSetWireV1 = decode(bytes)?;
    validate_candidate_set(&value)?;
    Ok(value)
}

pub fn encode_pricing_receipt_json_v1(
    value: &PromptPricingReceiptV1,
) -> Result<Vec<u8>, PromptCodecErrorV1> {
    if value.authority.grants_any() {
        return Err(PromptCodecErrorV1::AuthorityGranted);
    }
    encode_pricing_wire_json_v1(&PromptPricingWireV1 {
        factor_id: value.factor_id.to_string(),
        state_digest: value.state_digest.to_string(),
        expected_utility_q32: value.expected_utility_q32.raw(),
        downside_q32: value.downside_q32.raw(),
        token_cost: value.token_cost,
        latency_cost_micros: value.latency_cost_micros,
        interference_ppm: value.interference_ppm,
        confidence_interval: PromptConfidenceIntervalWireV1 {
            lower_q32: value.confidence_interval.lower_q32.raw(),
            upper_q32: value.confidence_interval.upper_q32.raw(),
            support_count: value.confidence_interval.support_count,
            support_audit_digest: value.confidence_interval.support_audit_digest.to_string(),
        },
    })
}

pub fn encode_pricing_wire_json_v1(
    value: &PromptPricingWireV1,
) -> Result<Vec<u8>, PromptCodecErrorV1> {
    validate_pricing(value)?;
    encode(value)
}

pub fn decode_pricing_receipt_json_v1(
    bytes: &[u8],
) -> Result<PromptPricingWireV1, PromptCodecErrorV1> {
    let value: PromptPricingWireV1 = decode(bytes)?;
    validate_pricing(&value)?;
    Ok(value)
}

pub fn encode_portfolio_receipt_json_v1(
    value: &PromptPortfolioReceiptV1,
) -> Result<Vec<u8>, PromptCodecErrorV1> {
    if value.authority.grants_any() {
        return Err(PromptCodecErrorV1::AuthorityGranted);
    }
    encode_portfolio_wire_json_v1(&PromptPortfolioWireV1 {
        portfolio_id: value.portfolio_id.to_string(),
        candidate_set_digest: value.candidate_set_digest.to_string(),
        factor_ids: value.factor_ids.iter().map(ToString::to_string).collect(),
        interaction_digest: value.interaction_digest.to_string(),
        expected_utility_q32: value.expected_utility_q32.raw(),
        total_token_upper_bound: value.total_token_upper_bound,
        valid_until_unix_ms: value.valid_until_unix_ms,
    })
}

pub fn encode_portfolio_wire_json_v1(
    value: &PromptPortfolioWireV1,
) -> Result<Vec<u8>, PromptCodecErrorV1> {
    validate_portfolio(value)?;
    encode(value)
}

pub fn decode_portfolio_receipt_json_v1(
    bytes: &[u8],
) -> Result<PromptPortfolioWireV1, PromptCodecErrorV1> {
    let value: PromptPortfolioWireV1 = decode(bytes)?;
    validate_portfolio(&value)?;
    Ok(value)
}

pub fn encode_exercise_decision_json_v1(
    value: &RawPromptExerciseDecisionV1,
) -> Result<Vec<u8>, PromptCodecErrorV1> {
    if value.authority.grants_any() {
        return Err(PromptCodecErrorV1::AuthorityGranted);
    }
    encode_exercise_wire_json_v1(&PromptExerciseWireV1 {
        factor_or_portfolio_id: value.factor_or_portfolio_id.to_string(),
        decision_boundary: value.decision_boundary.into(),
        exercise_now_value_q32: value.exercise_now_value_q32.raw(),
        wait_value_q32: value.wait_value_q32.raw(),
        decision: value.decision.into(),
        policy_digest: value.policy_digest.to_string(),
    })
}

pub fn encode_exercise_wire_json_v1(
    value: &PromptExerciseWireV1,
) -> Result<Vec<u8>, PromptCodecErrorV1> {
    validate_exercise(value)?;
    encode(value)
}

pub fn decode_exercise_decision_json_v1(
    bytes: &[u8],
) -> Result<PromptExerciseWireV1, PromptCodecErrorV1> {
    let value: PromptExerciseWireV1 = decode(bytes)?;
    validate_exercise(&value)?;
    Ok(value)
}

pub fn candidate_set_wire_digest_v1(
    value: &PromptCandidateSetWireV1,
) -> Result<Digest32, PromptCodecErrorV1> {
    Ok(Digest32::of_bytes(&encode_candidate_set_wire_json_v1(value)?))
}

pub fn pricing_wire_digest_v1(
    value: &PromptPricingWireV1,
) -> Result<Digest32, PromptCodecErrorV1> {
    Ok(Digest32::of_bytes(&encode_pricing_wire_json_v1(value)?))
}

pub fn portfolio_wire_digest_v1(
    value: &PromptPortfolioWireV1,
) -> Result<Digest32, PromptCodecErrorV1> {
    Ok(Digest32::of_bytes(&encode_portfolio_wire_json_v1(value)?))
}

pub fn exercise_wire_digest_v1(
    value: &PromptExerciseWireV1,
) -> Result<Digest32, PromptCodecErrorV1> {
    Ok(Digest32::of_bytes(&encode_exercise_wire_json_v1(value)?))
}

fn validate_candidate_set(value: &PromptCandidateSetWireV1) -> Result<(), PromptCodecErrorV1> {
    validate_id(&value.set_id, "setId")?;
    validate_digest(&value.objective_digest, "objectiveDigest")?;
    validate_digest(&value.state_digest, "stateDigest")?;
    validate_digest(&value.registry_digest, "registryDigest")?;
    validate_digest(&value.selection_grammar_digest, "selectionGrammarDigest")?;
    validate_ids(&value.candidate_factor_ids, MAX_CANDIDATES, "candidateFactorIds")
}

fn validate_pricing(value: &PromptPricingWireV1) -> Result<(), PromptCodecErrorV1> {
    validate_id(&value.factor_id, "factorId")?;
    validate_digest(&value.state_digest, "stateDigest")?;
    validate_digest(
        &value.confidence_interval.support_audit_digest,
        "confidenceInterval.supportAuditDigest",
    )?;
    if value.token_cost == 0
        || value.token_cost > MAX_TOKEN_BUDGET
        || value.interference_ppm > 1_000_000
        || value.downside_q32 < 0
        || value.confidence_interval.support_count == 0
        || value.confidence_interval.lower_q32 > value.expected_utility_q32
        || value.expected_utility_q32 > value.confidence_interval.upper_q32
    {
        return Err(PromptCodecErrorV1::InvalidBound("pricing"));
    }
    Ok(())
}

fn validate_portfolio(value: &PromptPortfolioWireV1) -> Result<(), PromptCodecErrorV1> {
    validate_id(&value.portfolio_id, "portfolioId")?;
    validate_digest(&value.candidate_set_digest, "candidateSetDigest")?;
    validate_digest(&value.interaction_digest, "interactionDigest")?;
    validate_ids(&value.factor_ids, MAX_SELECTED, "factorIds")?;
    if value.total_token_upper_bound > MAX_TOKEN_BUDGET || value.valid_until_unix_ms == 0 {
        return Err(PromptCodecErrorV1::InvalidBound("portfolio"));
    }
    Ok(())
}

fn validate_exercise(value: &PromptExerciseWireV1) -> Result<(), PromptCodecErrorV1> {
    validate_id(&value.factor_or_portfolio_id, "factorOrPortfolioId")?;
    validate_digest(&value.policy_digest, "policyDigest")
}

fn validate_id(value: &str, name: &'static str) -> Result<(), PromptCodecErrorV1> {
    StableId::new(value).map_err(|_| PromptCodecErrorV1::InvalidId(name))?;
    Ok(())
}

fn validate_digest(value: &str, name: &'static str) -> Result<(), PromptCodecErrorV1> {
    let digest = Digest32::from_str(value).map_err(|_| PromptCodecErrorV1::InvalidDigest(name))?;
    if digest.is_zero() {
        return Err(PromptCodecErrorV1::InvalidDigest(name));
    }
    Ok(())
}

fn validate_ids(
    values: &[String],
    maximum: usize,
    name: &'static str,
) -> Result<(), PromptCodecErrorV1> {
    if values.len() > maximum {
        return Err(PromptCodecErrorV1::InvalidBound(name));
    }
    let mut previous: Option<&str> = None;
    for value in values {
        validate_id(value, name)?;
        if previous.is_some_and(|prior| prior >= value.as_str()) {
            return Err(PromptCodecErrorV1::InvalidOrder(name));
        }
        previous = Some(value);
    }
    Ok(())
}

fn encode<T: Serialize>(value: &T) -> Result<Vec<u8>, PromptCodecErrorV1> {
    let bytes = serde_json::to_vec(value).map_err(|_| PromptCodecErrorV1::Json)?;
    if bytes.len() > MAX_ENCODED_BYTES {
        return Err(PromptCodecErrorV1::EncodedSize);
    }
    Ok(bytes)
}

fn decode<T: for<'de> Deserialize<'de>>(bytes: &[u8]) -> Result<T, PromptCodecErrorV1> {
    if bytes.len() > MAX_ENCODED_BYTES {
        return Err(PromptCodecErrorV1::EncodedSize);
    }
    serde_json::from_slice(bytes).map_err(|_| PromptCodecErrorV1::Json)
}

impl From<PromptDecisionBoundaryV1> for PromptDecisionBoundaryWireV1 {
    fn from(value: PromptDecisionBoundaryV1) -> Self {
        match value {
            PromptDecisionBoundaryV1::RequestAccepted => Self::RequestAccepted,
            PromptDecisionBoundaryV1::ObjectiveCompiled => Self::ObjectiveCompiled,
            PromptDecisionBoundaryV1::BeforePlanning => Self::BeforePlanning,
            PromptDecisionBoundaryV1::BeforeCandidateGeneration => Self::BeforeCandidateGeneration,
            PromptDecisionBoundaryV1::BeforeModelOrToolDispatch => Self::BeforeModelOrToolDispatch,
            PromptDecisionBoundaryV1::AfterObservation => Self::AfterObservation,
            PromptDecisionBoundaryV1::AfterFailureOrUncertaintySpike => {
                Self::AfterFailureOrUncertaintySpike
            }
            PromptDecisionBoundaryV1::BeforeIrreversibleMutation => Self::BeforeIrreversibleMutation,
            PromptDecisionBoundaryV1::BeforeVerification => Self::BeforeVerification,
            PromptDecisionBoundaryV1::BeforeFinalResponse => Self::BeforeFinalResponse,
            PromptDecisionBoundaryV1::BeforeCompactOrHandoff => Self::BeforeCompactOrHandoff,
        }
    }
}

impl From<PromptExerciseActionV1> for PromptExerciseActionWireV1 {
    fn from(value: PromptExerciseActionV1) -> Self {
        match value {
            PromptExerciseActionV1::Exercise => Self::Exercise,
            PromptExerciseActionV1::Wait => Self::Wait,
            PromptExerciseActionV1::RejectStale => Self::RejectStale,
            PromptExerciseActionV1::NoIntervention => Self::NoIntervention,
        }
    }
}
