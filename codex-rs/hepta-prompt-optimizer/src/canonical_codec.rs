use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::raw;
use super::types::CanonicalPromptError;

const MAX_PROTOCOL_BYTES: usize = 262_144;
const MAX_ID_BYTES: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetProtocolV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub registry_digest: Digest32,
    pub candidate_factor_ids: Vec<StableId>,
    pub selection_grammar_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptConfidenceIntervalProtocolV1 {
    pub lower_q32: FixedQ32,
    pub upper_q32: FixedQ32,
    pub support_count: u32,
    pub support_audit_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingProtocolV1 {
    pub factor_id: StableId,
    pub state_digest: Digest32,
    pub expected_utility_q32: FixedQ32,
    pub downside_q32: FixedQ32,
    pub token_cost: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub confidence_interval: PromptConfidenceIntervalProtocolV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioProtocolV1 {
    pub portfolio_id: StableId,
    pub candidate_set_digest: Digest32,
    pub factor_ids: Vec<StableId>,
    pub interaction_digest: Digest32,
    pub expected_utility_q32: FixedQ32,
    pub total_token_upper_bound: u32,
    pub valid_until_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseProtocolV1 {
    pub factor_or_portfolio_id: StableId,
    pub decision_boundary: raw::PromptDecisionBoundaryV1,
    pub exercise_now_value_q32: FixedQ32,
    pub wait_value_q32: FixedQ32,
    pub decision: raw::PromptExerciseActionV1,
    pub policy_digest: Digest32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct CandidateWireV1 {
    set_id: String,
    objective_digest: String,
    state_digest: String,
    registry_digest: String,
    candidate_factor_ids: Vec<String>,
    selection_grammar_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct ConfidenceWireV1 {
    lower_q32: i64,
    upper_q32: i64,
    support_count: u32,
    support_audit_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct PricingWireV1 {
    factor_id: String,
    state_digest: String,
    expected_utility_q32: i64,
    downside_q32: i64,
    token_cost: u32,
    latency_cost_micros: u64,
    interference_ppm: u32,
    confidence_interval: ConfidenceWireV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct PortfolioWireV1 {
    portfolio_id: String,
    candidate_set_digest: String,
    factor_ids: Vec<String>,
    interaction_digest: String,
    expected_utility_q32: i64,
    total_token_upper_bound: u32,
    valid_until_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct ExerciseWireV1 {
    factor_or_portfolio_id: String,
    decision_boundary: String,
    exercise_now_value_q32: i64,
    wait_value_q32: i64,
    decision: String,
    policy_digest: String,
}

pub fn encode_candidate_set_v1(
    receipt: &raw::PromptCandidateSetReceiptV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    encode_wire(&CandidateWireV1 {
        set_id: receipt.set_id.to_string(),
        objective_digest: receipt.objective_digest.to_string(),
        state_digest: receipt.state_digest.to_string(),
        registry_digest: receipt.registry_digest.to_string(),
        candidate_factor_ids: receipt
            .candidate_factor_ids
            .iter()
            .map(ToString::to_string)
            .collect(),
        selection_grammar_digest: receipt.selection_grammar_digest.to_string(),
    })
}

pub fn decode_candidate_set_v1(
    bytes: &[u8],
) -> Result<PromptCandidateSetProtocolV1, CanonicalPromptError> {
    let wire: CandidateWireV1 = decode_wire(bytes)?;
    let factor_ids = parse_canonical_ids(
        wire.candidate_factor_ids,
        super::MAX_CANONICAL_PROMPT_FACTORS,
    )?;
    Ok(PromptCandidateSetProtocolV1 {
        set_id: parse_id(wire.set_id)?,
        objective_digest: parse_digest(wire.objective_digest)?,
        state_digest: parse_digest(wire.state_digest)?,
        registry_digest: parse_digest(wire.registry_digest)?,
        candidate_factor_ids: factor_ids,
        selection_grammar_digest: parse_digest(wire.selection_grammar_digest)?,
    })
}

pub fn encode_pricing_receipt_v1(
    receipt: &raw::PromptPricingReceiptV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    encode_wire(&PricingWireV1 {
        factor_id: receipt.factor_id.to_string(),
        state_digest: receipt.state_digest.to_string(),
        expected_utility_q32: receipt.expected_utility_q32.raw(),
        downside_q32: receipt.downside_q32.raw(),
        token_cost: receipt.token_cost,
        latency_cost_micros: receipt.latency_cost_micros,
        interference_ppm: receipt.interference_ppm,
        confidence_interval: ConfidenceWireV1 {
            lower_q32: receipt.confidence_interval.lower_q32.raw(),
            upper_q32: receipt.confidence_interval.upper_q32.raw(),
            support_count: receipt.confidence_interval.support_count,
            support_audit_digest: receipt.confidence_interval.support_audit_digest.to_string(),
        },
    })
}

pub fn decode_pricing_receipt_v1(
    bytes: &[u8],
) -> Result<PromptPricingProtocolV1, CanonicalPromptError> {
    let wire: PricingWireV1 = decode_wire(bytes)?;
    if wire.interference_ppm > 1_000_000
        || wire.downside_q32 < 0
        || wire.confidence_interval.support_count == 0
        || wire.confidence_interval.lower_q32 > wire.confidence_interval.upper_q32
    {
        return Err(CanonicalPromptError::Codec(
            "invalid pricing bounds".to_owned(),
        ));
    }
    Ok(PromptPricingProtocolV1 {
        factor_id: parse_id(wire.factor_id)?,
        state_digest: parse_digest(wire.state_digest)?,
        expected_utility_q32: FixedQ32::from_raw(wire.expected_utility_q32),
        downside_q32: FixedQ32::from_raw(wire.downside_q32),
        token_cost: wire.token_cost,
        latency_cost_micros: wire.latency_cost_micros,
        interference_ppm: wire.interference_ppm,
        confidence_interval: PromptConfidenceIntervalProtocolV1 {
            lower_q32: FixedQ32::from_raw(wire.confidence_interval.lower_q32),
            upper_q32: FixedQ32::from_raw(wire.confidence_interval.upper_q32),
            support_count: wire.confidence_interval.support_count,
            support_audit_digest: parse_digest(
                wire.confidence_interval.support_audit_digest,
            )?,
        },
    })
}

pub fn encode_portfolio_receipt_v1(
    receipt: &raw::PromptPortfolioReceiptV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    encode_wire(&PortfolioWireV1 {
        portfolio_id: receipt.portfolio_id.to_string(),
        candidate_set_digest: receipt.candidate_set_digest.to_string(),
        factor_ids: receipt.factor_ids.iter().map(ToString::to_string).collect(),
        interaction_digest: receipt.interaction_digest.to_string(),
        expected_utility_q32: receipt.expected_utility_q32.raw(),
        total_token_upper_bound: receipt.total_token_upper_bound,
        valid_until_unix_ms: receipt.valid_until_unix_ms,
    })
}

pub fn decode_portfolio_receipt_v1(
    bytes: &[u8],
) -> Result<PromptPortfolioProtocolV1, CanonicalPromptError> {
    let wire: PortfolioWireV1 = decode_wire(bytes)?;
    if wire.total_token_upper_bound
        > u32::try_from(super::MAX_CANONICAL_TOKEN_BUDGET).unwrap_or(u32::MAX)
        || wire.valid_until_unix_ms == 0
    {
        return Err(CanonicalPromptError::Codec(
            "invalid portfolio bounds".to_owned(),
        ));
    }
    Ok(PromptPortfolioProtocolV1 {
        portfolio_id: parse_id(wire.portfolio_id)?,
        candidate_set_digest: parse_digest(wire.candidate_set_digest)?,
        factor_ids: parse_canonical_ids(
            wire.factor_ids,
            super::MAX_CANONICAL_SELECTED_FACTORS,
        )?,
        interaction_digest: parse_digest(wire.interaction_digest)?,
        expected_utility_q32: FixedQ32::from_raw(wire.expected_utility_q32),
        total_token_upper_bound: wire.total_token_upper_bound,
        valid_until_unix_ms: wire.valid_until_unix_ms,
    })
}

pub fn encode_exercise_decision_v1(
    receipt: &raw::PromptExerciseDecisionV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    encode_wire(&ExerciseWireV1 {
        factor_or_portfolio_id: receipt.factor_or_portfolio_id.to_string(),
        decision_boundary: boundary_name(receipt.decision_boundary).to_owned(),
        exercise_now_value_q32: receipt.exercise_now_value_q32.raw(),
        wait_value_q32: receipt.wait_value_q32.raw(),
        decision: exercise_action_name(receipt.decision).to_owned(),
        policy_digest: receipt.policy_digest.to_string(),
    })
}

pub fn decode_exercise_decision_v1(
    bytes: &[u8],
) -> Result<PromptExerciseProtocolV1, CanonicalPromptError> {
    let wire: ExerciseWireV1 = decode_wire(bytes)?;
    Ok(PromptExerciseProtocolV1 {
        factor_or_portfolio_id: parse_id(wire.factor_or_portfolio_id)?,
        decision_boundary: parse_boundary(&wire.decision_boundary)?,
        exercise_now_value_q32: FixedQ32::from_raw(wire.exercise_now_value_q32),
        wait_value_q32: FixedQ32::from_raw(wire.wait_value_q32),
        decision: parse_exercise_action(&wire.decision)?,
        policy_digest: parse_digest(wire.policy_digest)?,
    })
}

fn encode_wire<T: Serialize>(value: &T) -> Result<Vec<u8>, CanonicalPromptError> {
    let bytes = serde_json::to_vec(value)
        .map_err(|error| CanonicalPromptError::Codec(error.to_string()))?;
    if bytes.is_empty() || bytes.len() > MAX_PROTOCOL_BYTES {
        return Err(CanonicalPromptError::Codec(
            "encoded protocol size".to_owned(),
        ));
    }
    Ok(bytes)
}

fn decode_wire<T>(bytes: &[u8]) -> Result<T, CanonicalPromptError>
where
    T: for<'de> Deserialize<'de> + Serialize,
{
    if bytes.is_empty() || bytes.len() > MAX_PROTOCOL_BYTES {
        return Err(CanonicalPromptError::Codec(
            "encoded protocol size".to_owned(),
        ));
    }
    let value: T = serde_json::from_slice(bytes)
        .map_err(|error| CanonicalPromptError::Codec(error.to_string()))?;
    let canonical = serde_json::to_vec(&value)
        .map_err(|error| CanonicalPromptError::Codec(error.to_string()))?;
    if canonical != bytes {
        return Err(CanonicalPromptError::Codec(
            "non-canonical JSON encoding".to_owned(),
        ));
    }
    Ok(value)
}

fn parse_id(value: String) -> Result<StableId, CanonicalPromptError> {
    if value.len() > MAX_ID_BYTES {
        return Err(CanonicalPromptError::Codec("identifier bound".to_owned()));
    }
    StableId::new(value).map_err(|error| CanonicalPromptError::Codec(error.to_string()))
}

fn parse_digest(value: String) -> Result<Digest32, CanonicalPromptError> {
    let digest = Digest32::from_str(&value)
        .map_err(|error| CanonicalPromptError::Codec(error.to_string()))?;
    if digest.is_zero() {
        return Err(CanonicalPromptError::Codec("zero digest".to_owned()));
    }
    Ok(digest)
}

fn parse_canonical_ids(
    values: Vec<String>,
    maximum: usize,
) -> Result<Vec<StableId>, CanonicalPromptError> {
    if values.len() > maximum {
        return Err(CanonicalPromptError::Codec(
            "identifier array bound".to_owned(),
        ));
    }
    let ids = values
        .into_iter()
        .map(parse_id)
        .collect::<Result<Vec<_>, _>>()?;
    if ids.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(CanonicalPromptError::Codec(
            "non-canonical identifier order".to_owned(),
        ));
    }
    Ok(ids)
}

fn boundary_name(value: raw::PromptDecisionBoundaryV1) -> &'static str {
    match value {
        raw::PromptDecisionBoundaryV1::RequestAccepted => "requestAccepted",
        raw::PromptDecisionBoundaryV1::ObjectiveCompiled => "objectiveCompiled",
        raw::PromptDecisionBoundaryV1::BeforePlanning => "beforePlanning",
        raw::PromptDecisionBoundaryV1::BeforeCandidateGeneration => {
            "beforeCandidateGeneration"
        }
        raw::PromptDecisionBoundaryV1::BeforeModelOrToolDispatch => {
            "beforeModelOrToolDispatch"
        }
        raw::PromptDecisionBoundaryV1::AfterObservation => "afterObservation",
        raw::PromptDecisionBoundaryV1::AfterFailureOrUncertaintySpike => {
            "afterFailureOrUncertaintySpike"
        }
        raw::PromptDecisionBoundaryV1::BeforeIrreversibleMutation => {
            "beforeIrreversibleMutation"
        }
        raw::PromptDecisionBoundaryV1::BeforeVerification => "beforeVerification",
        raw::PromptDecisionBoundaryV1::BeforeFinalResponse => "beforeFinalResponse",
        raw::PromptDecisionBoundaryV1::BeforeCompactOrHandoff => "beforeCompactOrHandoff",
    }
}

fn parse_boundary(value: &str) -> Result<raw::PromptDecisionBoundaryV1, CanonicalPromptError> {
    match value {
        "requestAccepted" => Ok(raw::PromptDecisionBoundaryV1::RequestAccepted),
        "objectiveCompiled" => Ok(raw::PromptDecisionBoundaryV1::ObjectiveCompiled),
        "beforePlanning" => Ok(raw::PromptDecisionBoundaryV1::BeforePlanning),
        "beforeCandidateGeneration" => {
            Ok(raw::PromptDecisionBoundaryV1::BeforeCandidateGeneration)
        }
        "beforeModelOrToolDispatch" => {
            Ok(raw::PromptDecisionBoundaryV1::BeforeModelOrToolDispatch)
        }
        "afterObservation" => Ok(raw::PromptDecisionBoundaryV1::AfterObservation),
        "afterFailureOrUncertaintySpike" => {
            Ok(raw::PromptDecisionBoundaryV1::AfterFailureOrUncertaintySpike)
        }
        "beforeIrreversibleMutation" => {
            Ok(raw::PromptDecisionBoundaryV1::BeforeIrreversibleMutation)
        }
        "beforeVerification" => Ok(raw::PromptDecisionBoundaryV1::BeforeVerification),
        "beforeFinalResponse" => Ok(raw::PromptDecisionBoundaryV1::BeforeFinalResponse),
        "beforeCompactOrHandoff" => {
            Ok(raw::PromptDecisionBoundaryV1::BeforeCompactOrHandoff)
        }
        _ => Err(CanonicalPromptError::Codec(
            "unknown decision boundary".to_owned(),
        )),
    }
}

fn exercise_action_name(value: raw::PromptExerciseActionV1) -> &'static str {
    match value {
        raw::PromptExerciseActionV1::Exercise => "exercise",
        raw::PromptExerciseActionV1::Wait => "wait",
        raw::PromptExerciseActionV1::RejectStale => "rejectStale",
        raw::PromptExerciseActionV1::NoIntervention => "noIntervention",
    }
}

fn parse_exercise_action(
    value: &str,
) -> Result<raw::PromptExerciseActionV1, CanonicalPromptError> {
    match value {
        "exercise" => Ok(raw::PromptExerciseActionV1::Exercise),
        "wait" => Ok(raw::PromptExerciseActionV1::Wait),
        "rejectStale" => Ok(raw::PromptExerciseActionV1::RejectStale),
        "noIntervention" => Ok(raw::PromptExerciseActionV1::NoIntervention),
        _ => Err(CanonicalPromptError::Codec(
            "unknown exercise decision".to_owned(),
        )),
    }
}
