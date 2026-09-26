use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::raw;
use super::types::CanonicalPromptError;

const MAX_PROTOCOL_BYTES: usize = 262_144;
const MAX_ID_BYTES: usize = 128;
const PPM_ONE: u32 = 1_000_000;

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

pub fn encode_candidate_set_v1(
    receipt: &raw::PromptCandidateSetReceiptV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    ensure_internal_receipt(receipt.receipt_digest, receipt.authority.grants_any())?;
    ensure_digest("objective", receipt.objective_digest)?;
    ensure_digest("state", receipt.state_digest)?;
    ensure_digest("registry", receipt.registry_digest)?;
    ensure_digest("selection grammar", receipt.selection_grammar_digest)?;
    ensure_ids(
        &receipt.candidate_factor_ids,
        super::MAX_CANONICAL_PROMPT_FACTORS,
    )?;

    let mut bytes = b"{\"setId\":".to_vec();
    push_json_string(&mut bytes, receipt.set_id.as_str());
    bytes.extend_from_slice(b",\"objectiveDigest\":");
    push_digest(&mut bytes, receipt.objective_digest);
    bytes.extend_from_slice(b",\"stateDigest\":");
    push_digest(&mut bytes, receipt.state_digest);
    bytes.extend_from_slice(b",\"registryDigest\":");
    push_digest(&mut bytes, receipt.registry_digest);
    bytes.extend_from_slice(b",\"candidateFactorIds\":");
    push_id_array(&mut bytes, &receipt.candidate_factor_ids);
    bytes.extend_from_slice(b",\"selectionGrammarDigest\":");
    push_digest(&mut bytes, receipt.selection_grammar_digest);
    bytes.push(b'}');
    finish_encoding(bytes)
}

pub fn decode_candidate_set_v1(
    bytes: &[u8],
) -> Result<PromptCandidateSetProtocolV1, CanonicalPromptError> {
    let mut parser = Parser::new(bytes)?;
    parser.expect(b"{\"setId\":")?;
    let set_id = parse_id(parser.string()?)?;
    parser.expect(b",\"objectiveDigest\":")?;
    let objective_digest = parse_digest(parser.string()?)?;
    parser.expect(b",\"stateDigest\":")?;
    let state_digest = parse_digest(parser.string()?)?;
    parser.expect(b",\"registryDigest\":")?;
    let registry_digest = parse_digest(parser.string()?)?;
    parser.expect(b",\"candidateFactorIds\":")?;
    let candidate_factor_ids = parse_canonical_ids(
        parser.string_array(super::MAX_CANONICAL_PROMPT_FACTORS)?,
        super::MAX_CANONICAL_PROMPT_FACTORS,
    )?;
    parser.expect(b",\"selectionGrammarDigest\":")?;
    let selection_grammar_digest = parse_digest(parser.string()?)?;
    parser.expect(b"}")?;
    parser.finish()?;
    Ok(PromptCandidateSetProtocolV1 {
        set_id,
        objective_digest,
        state_digest,
        registry_digest,
        candidate_factor_ids,
        selection_grammar_digest,
    })
}

pub fn encode_pricing_receipt_v1(
    receipt: &raw::PromptPricingReceiptV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    ensure_internal_receipt(receipt.receipt_digest, receipt.authority.grants_any())?;
    ensure_digest("state", receipt.state_digest)?;
    validate_pricing_bounds(
        receipt.downside_q32.raw(),
        receipt.interference_ppm,
        receipt.confidence_interval.lower_q32.raw(),
        receipt.confidence_interval.upper_q32.raw(),
        receipt.confidence_interval.support_count,
        receipt.confidence_interval.support_audit_digest,
    )?;

    let mut bytes = b"{\"factorId\":".to_vec();
    push_json_string(&mut bytes, receipt.factor_id.as_str());
    bytes.extend_from_slice(b",\"stateDigest\":");
    push_digest(&mut bytes, receipt.state_digest);
    bytes.extend_from_slice(b",\"expectedUtilityQ32\":");
    push_i64(&mut bytes, receipt.expected_utility_q32.raw());
    bytes.extend_from_slice(b",\"downsideQ32\":");
    push_i64(&mut bytes, receipt.downside_q32.raw());
    bytes.extend_from_slice(b",\"tokenCost\":");
    push_u64(&mut bytes, u64::from(receipt.token_cost));
    bytes.extend_from_slice(b",\"latencyCostMicros\":");
    push_u64(&mut bytes, receipt.latency_cost_micros);
    bytes.extend_from_slice(b",\"interferencePpm\":");
    push_u64(&mut bytes, u64::from(receipt.interference_ppm));
    bytes.extend_from_slice(b",\"confidenceInterval\":{\"lowerQ32\":");
    push_i64(&mut bytes, receipt.confidence_interval.lower_q32.raw());
    bytes.extend_from_slice(b",\"upperQ32\":");
    push_i64(&mut bytes, receipt.confidence_interval.upper_q32.raw());
    bytes.extend_from_slice(b",\"supportCount\":");
    push_u64(
        &mut bytes,
        u64::from(receipt.confidence_interval.support_count),
    );
    bytes.extend_from_slice(b",\"supportAuditDigest\":");
    push_digest(
        &mut bytes,
        receipt.confidence_interval.support_audit_digest,
    );
    bytes.extend_from_slice(b"}}");
    finish_encoding(bytes)
}

pub fn decode_pricing_receipt_v1(
    bytes: &[u8],
) -> Result<PromptPricingProtocolV1, CanonicalPromptError> {
    let mut parser = Parser::new(bytes)?;
    parser.expect(b"{\"factorId\":")?;
    let factor_id = parse_id(parser.string()?)?;
    parser.expect(b",\"stateDigest\":")?;
    let state_digest = parse_digest(parser.string()?)?;
    parser.expect(b",\"expectedUtilityQ32\":")?;
    let expected_utility = parser.i64()?;
    parser.expect(b",\"downsideQ32\":")?;
    let downside = parser.i64()?;
    parser.expect(b",\"tokenCost\":")?;
    let token_cost = parser.u32()?;
    parser.expect(b",\"latencyCostMicros\":")?;
    let latency_cost_micros = parser.u64()?;
    parser.expect(b",\"interferencePpm\":")?;
    let interference_ppm = parser.u32()?;
    parser.expect(b",\"confidenceInterval\":{\"lowerQ32\":")?;
    let lower = parser.i64()?;
    parser.expect(b",\"upperQ32\":")?;
    let upper = parser.i64()?;
    parser.expect(b",\"supportCount\":")?;
    let support_count = parser.u32()?;
    parser.expect(b",\"supportAuditDigest\":")?;
    let support_audit_digest = parse_digest(parser.string()?)?;
    parser.expect(b"}}")?;
    parser.finish()?;
    validate_pricing_bounds(
        downside,
        interference_ppm,
        lower,
        upper,
        support_count,
        support_audit_digest,
    )?;
    Ok(PromptPricingProtocolV1 {
        factor_id,
        state_digest,
        expected_utility_q32: FixedQ32::from_raw(expected_utility),
        downside_q32: FixedQ32::from_raw(downside),
        token_cost,
        latency_cost_micros,
        interference_ppm,
        confidence_interval: PromptConfidenceIntervalProtocolV1 {
            lower_q32: FixedQ32::from_raw(lower),
            upper_q32: FixedQ32::from_raw(upper),
            support_count,
            support_audit_digest,
        },
    })
}

pub fn encode_portfolio_receipt_v1(
    receipt: &raw::PromptPortfolioReceiptV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    ensure_internal_receipt(receipt.receipt_digest, receipt.authority.grants_any())?;
    ensure_digest("candidate set", receipt.candidate_set_digest)?;
    ensure_digest("interaction", receipt.interaction_digest)?;
    ensure_ids(
        &receipt.factor_ids,
        super::MAX_CANONICAL_SELECTED_FACTORS,
    )?;
    validate_portfolio_bounds(receipt.total_token_upper_bound, receipt.valid_until_unix_ms)?;

    let mut bytes = b"{\"portfolioId\":".to_vec();
    push_json_string(&mut bytes, receipt.portfolio_id.as_str());
    bytes.extend_from_slice(b",\"candidateSetDigest\":");
    push_digest(&mut bytes, receipt.candidate_set_digest);
    bytes.extend_from_slice(b",\"factorIds\":");
    push_id_array(&mut bytes, &receipt.factor_ids);
    bytes.extend_from_slice(b",\"interactionDigest\":");
    push_digest(&mut bytes, receipt.interaction_digest);
    bytes.extend_from_slice(b",\"expectedUtilityQ32\":");
    push_i64(&mut bytes, receipt.expected_utility_q32.raw());
    bytes.extend_from_slice(b",\"totalTokenUpperBound\":");
    push_u64(&mut bytes, u64::from(receipt.total_token_upper_bound));
    bytes.extend_from_slice(b",\"validUntilUnixMs\":");
    push_u64(&mut bytes, receipt.valid_until_unix_ms);
    bytes.push(b'}');
    finish_encoding(bytes)
}

pub fn decode_portfolio_receipt_v1(
    bytes: &[u8],
) -> Result<PromptPortfolioProtocolV1, CanonicalPromptError> {
    let mut parser = Parser::new(bytes)?;
    parser.expect(b"{\"portfolioId\":")?;
    let portfolio_id = parse_id(parser.string()?)?;
    parser.expect(b",\"candidateSetDigest\":")?;
    let candidate_set_digest = parse_digest(parser.string()?)?;
    parser.expect(b",\"factorIds\":")?;
    let factor_ids = parse_canonical_ids(
        parser.string_array(super::MAX_CANONICAL_SELECTED_FACTORS)?,
        super::MAX_CANONICAL_SELECTED_FACTORS,
    )?;
    parser.expect(b",\"interactionDigest\":")?;
    let interaction_digest = parse_digest(parser.string()?)?;
    parser.expect(b",\"expectedUtilityQ32\":")?;
    let expected_utility = parser.i64()?;
    parser.expect(b",\"totalTokenUpperBound\":")?;
    let total_token_upper_bound = parser.u32()?;
    parser.expect(b",\"validUntilUnixMs\":")?;
    let valid_until_unix_ms = parser.u64()?;
    parser.expect(b"}")?;
    parser.finish()?;
    validate_portfolio_bounds(total_token_upper_bound, valid_until_unix_ms)?;
    Ok(PromptPortfolioProtocolV1 {
        portfolio_id,
        candidate_set_digest,
        factor_ids,
        interaction_digest,
        expected_utility_q32: FixedQ32::from_raw(expected_utility),
        total_token_upper_bound,
        valid_until_unix_ms,
    })
}

pub fn encode_exercise_decision_v1(
    receipt: &raw::PromptExerciseDecisionV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    ensure_internal_receipt(receipt.receipt_digest, receipt.authority.grants_any())?;
    ensure_digest("exercise policy", receipt.policy_digest)?;

    let mut bytes = b"{\"factorOrPortfolioId\":".to_vec();
    push_json_string(&mut bytes, receipt.factor_or_portfolio_id.as_str());
    bytes.extend_from_slice(b",\"decisionBoundary\":");
    push_json_string(&mut bytes, boundary_name(receipt.decision_boundary));
    bytes.extend_from_slice(b",\"exerciseNowValueQ32\":");
    push_i64(&mut bytes, receipt.exercise_now_value_q32.raw());
    bytes.extend_from_slice(b",\"waitValueQ32\":");
    push_i64(&mut bytes, receipt.wait_value_q32.raw());
    bytes.extend_from_slice(b",\"decision\":");
    push_json_string(&mut bytes, exercise_action_name(receipt.decision));
    bytes.extend_from_slice(b",\"policyDigest\":");
    push_digest(&mut bytes, receipt.policy_digest);
    bytes.push(b'}');
    finish_encoding(bytes)
}

pub fn decode_exercise_decision_v1(
    bytes: &[u8],
) -> Result<PromptExerciseProtocolV1, CanonicalPromptError> {
    let mut parser = Parser::new(bytes)?;
    parser.expect(b"{\"factorOrPortfolioId\":")?;
    let factor_or_portfolio_id = parse_id(parser.string()?)?;
    parser.expect(b",\"decisionBoundary\":")?;
    let decision_boundary = parse_boundary(&parser.string()?)?;
    parser.expect(b",\"exerciseNowValueQ32\":")?;
    let exercise_now = parser.i64()?;
    parser.expect(b",\"waitValueQ32\":")?;
    let wait = parser.i64()?;
    parser.expect(b",\"decision\":")?;
    let decision = parse_exercise_action(&parser.string()?)?;
    parser.expect(b",\"policyDigest\":")?;
    let policy_digest = parse_digest(parser.string()?)?;
    parser.expect(b"}")?;
    parser.finish()?;
    Ok(PromptExerciseProtocolV1 {
        factor_or_portfolio_id,
        decision_boundary,
        exercise_now_value_q32: FixedQ32::from_raw(exercise_now),
        wait_value_q32: FixedQ32::from_raw(wait),
        decision,
        policy_digest,
    })
}

fn validate_pricing_bounds(
    downside_q32: i64,
    interference_ppm: u32,
    lower_q32: i64,
    upper_q32: i64,
    support_count: u32,
    support_audit_digest: Digest32,
) -> Result<(), CanonicalPromptError> {
    if downside_q32 < 0
        || interference_ppm > PPM_ONE
        || support_count == 0
        || lower_q32 > upper_q32
        || support_audit_digest.is_zero()
    {
        return Err(codec("invalid pricing bounds"));
    }
    Ok(())
}

fn validate_portfolio_bounds(
    total_token_upper_bound: u32,
    valid_until_unix_ms: u64,
) -> Result<(), CanonicalPromptError> {
    if u64::from(total_token_upper_bound) > super::MAX_CANONICAL_TOKEN_BUDGET
        || valid_until_unix_ms == 0
    {
        return Err(codec("invalid portfolio bounds"));
    }
    Ok(())
}

fn ensure_internal_receipt(
    receipt_digest: Digest32,
    grants_any: bool,
) -> Result<(), CanonicalPromptError> {
    if receipt_digest.is_zero() || grants_any {
        return Err(codec("invalid internal receipt"));
    }
    Ok(())
}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), CanonicalPromptError> {
    if digest.is_zero() {
        return Err(codec(name));
    }
    Ok(())
}

fn ensure_ids(values: &[StableId], maximum: usize) -> Result<(), CanonicalPromptError> {
    if values.len() > maximum || values.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(codec("non-canonical identifier array"));
    }
    Ok(())
}

fn finish_encoding(bytes: Vec<u8>) -> Result<Vec<u8>, CanonicalPromptError> {
    if bytes.is_empty() || bytes.len() > MAX_PROTOCOL_BYTES {
        return Err(codec("encoded protocol size"));
    }
    Ok(bytes)
}

fn push_json_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.push(b'"');
    bytes.extend_from_slice(value.as_bytes());
    bytes.push(b'"');
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    push_json_string(bytes, &value.to_string());
}

fn push_id_array(bytes: &mut Vec<u8>, values: &[StableId]) {
    bytes.push(b'[');
    for (index, value) in values.iter().enumerate() {
        if index != 0 {
            bytes.push(b',');
        }
        push_json_string(bytes, value.as_str());
    }
    bytes.push(b']');
}

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(value.to_string().as_bytes());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(value.to_string().as_bytes());
}

fn parse_id(value: String) -> Result<StableId, CanonicalPromptError> {
    if value.len() > MAX_ID_BYTES {
        return Err(codec("identifier bound"));
    }
    StableId::new(value).map_err(|error| CanonicalPromptError::Codec(error.to_string()))
}

fn parse_digest(value: String) -> Result<Digest32, CanonicalPromptError> {
    let digest = Digest32::from_str(&value)
        .map_err(|error| CanonicalPromptError::Codec(error.to_string()))?;
    if digest.is_zero() || digest.to_string() != value {
        return Err(codec("non-canonical digest"));
    }
    Ok(digest)
}

fn parse_canonical_ids(
    values: Vec<String>,
    maximum: usize,
) -> Result<Vec<StableId>, CanonicalPromptError> {
    if values.len() > maximum {
        return Err(codec("identifier array bound"));
    }
    let ids = values
        .into_iter()
        .map(parse_id)
        .collect::<Result<Vec<_>, _>>()?;
    ensure_ids(&ids, maximum)?;
    Ok(ids)
}

fn boundary_name(value: raw::PromptDecisionBoundaryV1) -> &'static str {
    match value {
        raw::PromptDecisionBoundaryV1::RequestAccepted => "requestAccepted",
        raw::PromptDecisionBoundaryV1::ObjectiveCompiled => "objectiveCompiled",
        raw::PromptDecisionBoundaryV1::BeforePlanning => "beforePlanning",
        raw::PromptDecisionBoundaryV1::BeforeCandidateGeneration => "beforeCandidateGeneration",
        raw::PromptDecisionBoundaryV1::BeforeModelOrToolDispatch => "beforeModelOrToolDispatch",
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
        _ => Err(codec("unknown decision boundary")),
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
        _ => Err(codec("unknown exercise decision")),
    }
}

fn codec(message: &str) -> CanonicalPromptError {
    CanonicalPromptError::Codec(message.to_owned())
}

struct Parser<'a> {
    input: &'a [u8],
    position: usize,
}

impl<'a> Parser<'a> {
    fn new(input: &'a [u8]) -> Result<Self, CanonicalPromptError> {
        if input.is_empty() || input.len() > MAX_PROTOCOL_BYTES {
            return Err(codec("encoded protocol size"));
        }
        Ok(Self { input, position: 0 })
    }

    fn expect(&mut self, expected: &[u8]) -> Result<(), CanonicalPromptError> {
        if !self.input[self.position..].starts_with(expected) {
            return Err(codec("invalid canonical JSON shape"));
        }
        self.position = self.position.saturating_add(expected.len());
        Ok(())
    }

    fn finish(&self) -> Result<(), CanonicalPromptError> {
        if self.position != self.input.len() {
            return Err(codec("trailing JSON content"));
        }
        Ok(())
    }

    fn string(&mut self) -> Result<String, CanonicalPromptError> {
        self.expect(b"\"")?;
        let start = self.position;
        while let Some(byte) = self.input.get(self.position).copied() {
            match byte {
                b'"' => {
                    let value = std::str::from_utf8(&self.input[start..self.position])
                        .map_err(|error| CanonicalPromptError::Codec(error.to_string()))?
                        .to_owned();
                    self.position = self.position.saturating_add(1);
                    return Ok(value);
                }
                b'\\' | 0..=31 | 127..=255 => {
                    return Err(codec("non-canonical JSON string"));
                }
                _ => self.position = self.position.saturating_add(1),
            }
        }
        Err(codec("unterminated JSON string"))
    }

    fn string_array(&mut self, maximum: usize) -> Result<Vec<String>, CanonicalPromptError> {
        self.expect(b"[")?;
        let mut values = Vec::new();
        if self.consume(b"]") {
            return Ok(values);
        }
        loop {
            if values.len() >= maximum {
                return Err(codec("identifier array bound"));
            }
            values.push(self.string()?);
            if self.consume(b"]") {
                return Ok(values);
            }
            self.expect(b",")?;
        }
    }

    fn consume(&mut self, expected: &[u8]) -> bool {
        if self.input[self.position..].starts_with(expected) {
            self.position = self.position.saturating_add(expected.len());
            true
        } else {
            false
        }
    }

    fn i64(&mut self) -> Result<i64, CanonicalPromptError> {
        self.integer_token(true)?
            .parse::<i64>()
            .map_err(|error| CanonicalPromptError::Codec(error.to_string()))
    }

    fn u64(&mut self) -> Result<u64, CanonicalPromptError> {
        self.integer_token(false)?
            .parse::<u64>()
            .map_err(|error| CanonicalPromptError::Codec(error.to_string()))
    }

    fn u32(&mut self) -> Result<u32, CanonicalPromptError> {
        self.integer_token(false)?
            .parse::<u32>()
            .map_err(|error| CanonicalPromptError::Codec(error.to_string()))
    }

    fn integer_token(&mut self, signed: bool) -> Result<&'a str, CanonicalPromptError> {
        let start = self.position;
        let negative = signed && self.input.get(self.position) == Some(&b'-');
        if negative {
            self.position = self.position.saturating_add(1);
        }
        let digits_start = self.position;
        while self
            .input
            .get(self.position)
            .is_some_and(u8::is_ascii_digit)
        {
            self.position = self.position.saturating_add(1);
        }
        if digits_start == self.position {
            return Err(codec("invalid JSON integer"));
        }
        let digits = &self.input[digits_start..self.position];
        if (digits.len() > 1 && digits[0] == b'0') || (negative && digits == b"0") {
            return Err(codec("non-canonical JSON integer"));
        }
        std::str::from_utf8(&self.input[start..self.position])
            .map_err(|error| CanonicalPromptError::Codec(error.to_string()))
    }
}
