//! Strict canonical JSON codecs for the four registered prompt.optimizer V1 protocols.
//!
//! These codecs intentionally encode only the fields registered in
//! `docs/contracts/PROTOCOL_SCHEMAS.json`. Internal semantic digests and
//! authority postures remain in the sealed in-process types and are never
//! silently added to the public wire shape.

use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::canonical as v1;

pub const MAX_PROMPT_PROTOCOL_BYTES_V1: usize = 262_144;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptWireError {
    EncodedSize,
    InvalidJson(String),
    NonCanonicalJson,
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidBounds(&'static str),
    NonCanonicalOrder(&'static str),
}

impl fmt::Display for PromptWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptWireError {}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct PromptCandidateSetWireV1 {
    pub set_id: String,
    pub objective_digest: String,
    pub state_digest: String,
    pub registry_digest: String,
    pub candidate_factor_ids: Vec<String>,
    pub selection_grammar_digest: String,
}

impl PromptCandidateSetWireV1 {
    pub fn validate(&self) -> Result<(), PromptWireError> {
        parse_id(&self.set_id, "setId")?;
        parse_digest(&self.objective_digest, "objectiveDigest")?;
        parse_digest(&self.state_digest, "stateDigest")?;
        parse_digest(&self.registry_digest, "registryDigest")?;
        parse_digest(&self.selection_grammar_digest, "selectionGrammarDigest")?;
        if self.candidate_factor_ids.len() > v1::MAX_CANONICAL_PROMPT_FACTORS {
            return Err(PromptWireError::InvalidBounds("candidateFactorIds"));
        }
        validate_id_list(&self.candidate_factor_ids, "candidateFactorIds")
    }
}

impl TryFrom<&v1::PromptCandidateSetReceiptV1> for PromptCandidateSetWireV1 {
    type Error = PromptWireError;

    fn try_from(value: &v1::PromptCandidateSetReceiptV1) -> Result<Self, Self::Error> {
        let wire = Self {
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
        };
        wire.validate()?;
        Ok(wire)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct PromptConfidenceIntervalWireV1 {
    pub lower_q32: i64,
    pub upper_q32: i64,
    pub support_count: u32,
    pub support_audit_digest: String,
}

impl PromptConfidenceIntervalWireV1 {
    fn validate(&self) -> Result<(), PromptWireError> {
        if self.lower_q32 > self.upper_q32 || self.support_count == 0 {
            return Err(PromptWireError::InvalidBounds("confidenceInterval"));
        }
        parse_digest(&self.support_audit_digest, "supportAuditDigest")?;
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct PromptPricingReceiptWireV1 {
    pub factor_id: String,
    pub state_digest: String,
    pub expected_utility_q32: i64,
    pub downside_q32: i64,
    pub token_cost: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub confidence_interval: PromptConfidenceIntervalWireV1,
}

impl PromptPricingReceiptWireV1 {
    pub fn validate(&self) -> Result<(), PromptWireError> {
        parse_id(&self.factor_id, "factorId")?;
        parse_digest(&self.state_digest, "stateDigest")?;
        if self.downside_q32 < 0
            || self.token_cost == 0
            || self.interference_ppm > 1_000_000
        {
            return Err(PromptWireError::InvalidBounds("pricingReceipt"));
        }
        self.confidence_interval.validate()
    }
}

impl TryFrom<&v1::PromptPricingReceiptV1> for PromptPricingReceiptWireV1 {
    type Error = PromptWireError;

    fn try_from(value: &v1::PromptPricingReceiptV1) -> Result<Self, Self::Error> {
        let wire = Self {
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
        };
        wire.validate()?;
        Ok(wire)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct PromptPortfolioReceiptWireV1 {
    pub portfolio_id: String,
    pub candidate_set_digest: String,
    pub factor_ids: Vec<String>,
    pub interaction_digest: String,
    pub expected_utility_q32: i64,
    pub total_token_upper_bound: u32,
    pub valid_until_unix_ms: u64,
}

impl PromptPortfolioReceiptWireV1 {
    pub fn validate(&self) -> Result<(), PromptWireError> {
        parse_id(&self.portfolio_id, "portfolioId")?;
        parse_digest(&self.candidate_set_digest, "candidateSetDigest")?;
        parse_digest(&self.interaction_digest, "interactionDigest")?;
        if self.factor_ids.len() > v1::MAX_CANONICAL_SELECTED_FACTORS
            || self.total_token_upper_bound
                > u32::try_from(v1::MAX_CANONICAL_TOKEN_BUDGET).unwrap_or(u32::MAX)
            || self.valid_until_unix_ms == 0
        {
            return Err(PromptWireError::InvalidBounds("portfolioReceipt"));
        }
        validate_id_list(&self.factor_ids, "factorIds")
    }
}

impl TryFrom<&v1::PromptPortfolioReceiptV1> for PromptPortfolioReceiptWireV1 {
    type Error = PromptWireError;

    fn try_from(value: &v1::PromptPortfolioReceiptV1) -> Result<Self, Self::Error> {
        let wire = Self {
            portfolio_id: value.portfolio_id.to_string(),
            candidate_set_digest: value.candidate_set_digest.to_string(),
            factor_ids: value.factor_ids.iter().map(ToString::to_string).collect(),
            interaction_digest: value.interaction_digest.to_string(),
            expected_utility_q32: value.expected_utility_q32.raw(),
            total_token_upper_bound: value.total_token_upper_bound,
            valid_until_unix_ms: value.valid_until_unix_ms,
        };
        wire.validate()?;
        Ok(wire)
    }
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

impl From<v1::PromptDecisionBoundaryV1> for PromptDecisionBoundaryWireV1 {
    fn from(value: v1::PromptDecisionBoundaryV1) -> Self {
        match value {
            v1::PromptDecisionBoundaryV1::RequestAccepted => Self::RequestAccepted,
            v1::PromptDecisionBoundaryV1::ObjectiveCompiled => Self::ObjectiveCompiled,
            v1::PromptDecisionBoundaryV1::BeforePlanning => Self::BeforePlanning,
            v1::PromptDecisionBoundaryV1::BeforeCandidateGeneration => {
                Self::BeforeCandidateGeneration
            }
            v1::PromptDecisionBoundaryV1::BeforeModelOrToolDispatch => {
                Self::BeforeModelOrToolDispatch
            }
            v1::PromptDecisionBoundaryV1::AfterObservation => Self::AfterObservation,
            v1::PromptDecisionBoundaryV1::AfterFailureOrUncertaintySpike => {
                Self::AfterFailureOrUncertaintySpike
            }
            v1::PromptDecisionBoundaryV1::BeforeIrreversibleMutation => {
                Self::BeforeIrreversibleMutation
            }
            v1::PromptDecisionBoundaryV1::BeforeVerification => Self::BeforeVerification,
            v1::PromptDecisionBoundaryV1::BeforeFinalResponse => Self::BeforeFinalResponse,
            v1::PromptDecisionBoundaryV1::BeforeCompactOrHandoff => {
                Self::BeforeCompactOrHandoff
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PromptExerciseActionWireV1 {
    Exercise,
    Wait,
    RejectStale,
    NoIntervention,
}

impl From<v1::PromptExerciseActionV1> for PromptExerciseActionWireV1 {
    fn from(value: v1::PromptExerciseActionV1) -> Self {
        match value {
            v1::PromptExerciseActionV1::Exercise => Self::Exercise,
            v1::PromptExerciseActionV1::Wait => Self::Wait,
            v1::PromptExerciseActionV1::RejectStale => Self::RejectStale,
            v1::PromptExerciseActionV1::NoIntervention => Self::NoIntervention,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct PromptExerciseDecisionWireV1 {
    pub factor_or_portfolio_id: String,
    pub decision_boundary: PromptDecisionBoundaryWireV1,
    pub exercise_now_value_q32: i64,
    pub wait_value_q32: i64,
    pub decision: PromptExerciseActionWireV1,
    pub policy_digest: String,
}

impl PromptExerciseDecisionWireV1 {
    pub fn validate(&self) -> Result<(), PromptWireError> {
        parse_id(&self.factor_or_portfolio_id, "factorOrPortfolioId")?;
        parse_digest(&self.policy_digest, "policyDigest")?;
        Ok(())
    }
}

impl TryFrom<&v1::PromptExerciseDecisionV1> for PromptExerciseDecisionWireV1 {
    type Error = PromptWireError;

    fn try_from(value: &v1::PromptExerciseDecisionV1) -> Result<Self, Self::Error> {
        let wire = Self {
            factor_or_portfolio_id: value.factor_or_portfolio_id.to_string(),
            decision_boundary: value.decision_boundary.into(),
            exercise_now_value_q32: value.exercise_now_value_q32.raw(),
            wait_value_q32: value.wait_value_q32.raw(),
            decision: value.decision.into(),
            policy_digest: value.policy_digest.to_string(),
        };
        wire.validate()?;
        Ok(wire)
    }
}

pub trait PromptCanonicalWireV1: Sized + Serialize + for<'de> Deserialize<'de> + Eq {
    fn validate_wire(&self) -> Result<(), PromptWireError>;
}

impl PromptCanonicalWireV1 for PromptCandidateSetWireV1 {
    fn validate_wire(&self) -> Result<(), PromptWireError> {
        self.validate()
    }
}

impl PromptCanonicalWireV1 for PromptPricingReceiptWireV1 {
    fn validate_wire(&self) -> Result<(), PromptWireError> {
        self.validate()
    }
}

impl PromptCanonicalWireV1 for PromptPortfolioReceiptWireV1 {
    fn validate_wire(&self) -> Result<(), PromptWireError> {
        self.validate()
    }
}

impl PromptCanonicalWireV1 for PromptExerciseDecisionWireV1 {
    fn validate_wire(&self) -> Result<(), PromptWireError> {
        self.validate()
    }
}

pub fn to_canonical_json_v1<T: PromptCanonicalWireV1>(
    value: &T,
) -> Result<Vec<u8>, PromptWireError> {
    value.validate_wire()?;
    let encoded = serde_json::to_vec(value)
        .map_err(|error| PromptWireError::InvalidJson(error.to_string()))?;
    if encoded.len() > MAX_PROMPT_PROTOCOL_BYTES_V1 {
        return Err(PromptWireError::EncodedSize);
    }
    Ok(encoded)
}

pub fn from_canonical_json_v1<T: PromptCanonicalWireV1>(
    bytes: &[u8],
) -> Result<T, PromptWireError> {
    if bytes.is_empty() || bytes.len() > MAX_PROMPT_PROTOCOL_BYTES_V1 {
        return Err(PromptWireError::EncodedSize);
    }
    let value = serde_json::from_slice::<T>(bytes)
        .map_err(|error| PromptWireError::InvalidJson(error.to_string()))?;
    value.validate_wire()?;
    if to_canonical_json_v1(&value)? != bytes {
        return Err(PromptWireError::NonCanonicalJson);
    }
    Ok(value)
}

fn validate_id_list(values: &[String], field: &'static str) -> Result<(), PromptWireError> {
    let mut previous: Option<&str> = None;
    for value in values {
        parse_id(value, field)?;
        if previous.is_some_and(|item| item >= value.as_str()) {
            return Err(PromptWireError::NonCanonicalOrder(field));
        }
        previous = Some(value);
    }
    Ok(())
}

fn parse_id(value: &str, field: &'static str) -> Result<StableId, PromptWireError> {
    StableId::new(value.to_owned()).map_err(|_| PromptWireError::InvalidIdentity(field))
}

fn parse_digest(value: &str, field: &'static str) -> Result<Digest32, PromptWireError> {
    let digest = Digest32::from_str(value).map_err(|_| PromptWireError::InvalidDigest(field))?;
    if digest.is_zero() {
        return Err(PromptWireError::InvalidDigest(field));
    }
    Ok(digest)
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
