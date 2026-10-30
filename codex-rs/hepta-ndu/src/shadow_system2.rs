//! Deterministic, owner-local shadow control for bounded System2 depth.
//!
//! This module intentionally contains no learned critic, runtime mutation, or
//! authority grant. It turns an authenticated replay request into a bounded
//! suggestion and a receipt whose digests make the decision replayable.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

/// Maximum number of shadow depth steps admitted by the v1 controller.
pub const MAX_NDU_SHADOW_DEPTH_V1: u16 = 64;
/// Maximum identifier length carried by the replay receipt.
pub const MAX_NDU_SHADOW_ID_BYTES_V1: usize = 256;
/// Maximum budget accepted by one shadow request.
pub const MAX_NDU_SHADOW_BUDGET_MICROS_V1: u64 = 10_000_000;

/// The bounded action recommended by the shadow controller.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduShadowActionV1 {
    /// Continue at the current depth.
    Hold,
    /// Spend one bounded depth step and re-evaluate.
    Deepen,
    /// Stop and abstain because the remaining evidence is unsafe or too weak.
    Abstain,
}

impl NduShadowActionV1 {
    fn tag(self) -> u8 {
        match self {
            Self::Hold => 0,
            Self::Deepen => 1,
            Self::Abstain => 2,
        }
    }
}

/// Immutable parameters for the deterministic shadow controller.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduShadowPolicyV1 {
    pub policy_id: String,
    pub max_depth: u16,
    pub step_cost_micros: u64,
    pub uncertainty_trigger_q32: i64,
    pub risk_trigger_q32: i64,
    pub abstain_uncertainty_q32: i64,
    pub abstain_risk_q32: i64,
    pub uncertainty_decay_q32: i64,
    pub risk_decay_q32: i64,
    pub value_gain_q32: i64,
}

/// A replayable, owner-local input to the shadow controller.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduShadowRequestV1 {
    pub subject_id: String,
    pub run_id: String,
    pub generation: u64,
    pub input_digest: Digest32,
    pub stem_digest: Digest32,
    pub encoder_digest: Digest32,
    pub group_adapter_digest: Digest32,
    pub critic_digest: Digest32,
    pub trajectory_digest: Digest32,
    pub policy_digest: Digest32,
    pub current_depth: u16,
    pub remaining_budget_micros: u64,
    pub value_q32: i64,
    pub risk_q32: i64,
    pub uncertainty_q32: i64,
}

/// Deterministic shadow suggestion and receipt.
///
/// `authority` is always deny-all. The receipt is evidence for a later
/// owner-local policy gate; it is not a runtime command or a promotion token.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduShadowSuggestionV1 {
    pub subject_id: String,
    pub run_id: String,
    pub generation: u64,
    pub request_digest: Digest32,
    pub policy_digest: Digest32,
    pub action: NduShadowActionV1,
    pub recommended_depth: u16,
    pub should_deepen: bool,
    pub abstain: bool,
    pub projected_value_q32: i64,
    pub projected_risk_q32: i64,
    pub projected_uncertainty_q32: i64,
    pub remaining_budget_micros: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduShadowError {
    EmptyId(&'static str),
    IdTooLarge(&'static str),
    ZeroDigest(&'static str),
    ZeroGeneration,
    InvalidMaxDepth,
    ZeroStepCost,
    BudgetTooLarge,
    NegativeThreshold(&'static str),
    NegativeObservation(&'static str),
    PolicyDigestMismatch,
    DepthExceedsPolicy,
    ArithmeticOverflow,
}

impl fmt::Display for NduShadowError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduShadowError {}

/// Evaluate one immutable shadow request under one immutable policy.
///
/// The controller is intentionally a fixture for the later learned critic:
/// uncertainty and risk trigger at most one bounded step per call, while a
/// missing budget or exhausted depth produces a fail-closed abstention when
/// the post-step thresholds remain unsafe.
pub fn suggest_ndu_shadow_v1(
    policy: &NduShadowPolicyV1,
    request: &NduShadowRequestV1,
) -> Result<NduShadowSuggestionV1, NduShadowError> {
    validate_policy(policy)?;
    validate_request(policy, request)?;

    let request_digest = canonical_ndu_shadow_request_digest_v1(policy, request);
    let trigger = request.uncertainty_q32 >= policy.uncertainty_trigger_q32
        || request.risk_q32 >= policy.risk_trigger_q32;
    let can_deepen = request.current_depth < policy.max_depth
        && request.remaining_budget_micros >= policy.step_cost_micros;
    let proposed_deepen = trigger && can_deepen;

    let (proposed_depth, proposed_budget, proposed_value) = if proposed_deepen {
        let next_depth = request
            .current_depth
            .checked_add(1)
            .ok_or(NduShadowError::ArithmeticOverflow)?;
        let remaining_budget_micros = request
            .remaining_budget_micros
            .checked_sub(policy.step_cost_micros)
            .ok_or(NduShadowError::ArithmeticOverflow)?;
        let projected_value_q32 = i128::from(request.value_q32)
            .checked_add(i128::from(policy.value_gain_q32))
            .ok_or(NduShadowError::ArithmeticOverflow)?;
        let projected_value_q32 =
            i64::try_from(projected_value_q32).map_err(|_| NduShadowError::ArithmeticOverflow)?;
        (next_depth, remaining_budget_micros, projected_value_q32)
    } else {
        (
            request.current_depth,
            request.remaining_budget_micros,
            request.value_q32,
        )
    };

    let proposed_uncertainty_q32 = if proposed_deepen {
        request
            .uncertainty_q32
            .saturating_sub(policy.uncertainty_decay_q32)
            .max(0)
    } else {
        request.uncertainty_q32
    };
    let proposed_risk_q32 = if proposed_deepen {
        request
            .risk_q32
            .saturating_sub(policy.risk_decay_q32)
            .max(0)
    } else {
        request.risk_q32
    };
    let unsafe_after_available_step = proposed_uncertainty_q32 >= policy.abstain_uncertainty_q32
        || proposed_risk_q32 >= policy.abstain_risk_q32;
    let should_deepen = proposed_deepen && !unsafe_after_available_step;
    let abstain = unsafe_after_available_step;
    let (
        recommended_depth,
        remaining_budget_micros,
        projected_value_q32,
        projected_uncertainty_q32,
        projected_risk_q32,
    ) = if should_deepen {
        (
            proposed_depth,
            proposed_budget,
            proposed_value,
            proposed_uncertainty_q32,
            proposed_risk_q32,
        )
    } else {
        (
            request.current_depth,
            request.remaining_budget_micros,
            request.value_q32,
            request.uncertainty_q32,
            request.risk_q32,
        )
    };
    let action = if abstain {
        NduShadowActionV1::Abstain
    } else if should_deepen {
        NduShadowActionV1::Deepen
    } else {
        NduShadowActionV1::Hold
    };

    let mut suggestion = NduShadowSuggestionV1 {
        subject_id: request.subject_id.clone(),
        run_id: request.run_id.clone(),
        generation: request.generation,
        request_digest,
        policy_digest: request.policy_digest,
        action,
        recommended_depth,
        should_deepen,
        abstain,
        projected_value_q32,
        projected_risk_q32,
        projected_uncertainty_q32,
        remaining_budget_micros,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    suggestion.receipt_digest = canonical_ndu_shadow_receipt_digest_v1(&suggestion);
    Ok(suggestion)
}

/// Canonical digest of a shadow policy definition.
pub fn canonical_ndu_shadow_policy_digest_v1(policy: &NduShadowPolicyV1) -> Digest32 {
    let mut bytes = b"hepta.ndu.shadow-policy.v1\0".to_vec();
    push_text_unchecked(&mut bytes, &policy.policy_id);
    bytes.extend_from_slice(&policy.max_depth.to_be_bytes());
    bytes.extend_from_slice(&policy.step_cost_micros.to_be_bytes());
    for value in [
        policy.uncertainty_trigger_q32,
        policy.risk_trigger_q32,
        policy.abstain_uncertainty_q32,
        policy.abstain_risk_q32,
        policy.uncertainty_decay_q32,
        policy.risk_decay_q32,
        policy.value_gain_q32,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

/// Canonical digest of a replay request and its policy binding.
pub fn canonical_ndu_shadow_request_digest_v1(
    policy: &NduShadowPolicyV1,
    request: &NduShadowRequestV1,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.shadow-request.v1\0".to_vec();
    push_text_unchecked(&mut bytes, &request.subject_id);
    push_text_unchecked(&mut bytes, &request.run_id);
    bytes.extend_from_slice(&request.generation.to_be_bytes());
    for digest in [
        request.input_digest,
        request.stem_digest,
        request.encoder_digest,
        request.group_adapter_digest,
        request.critic_digest,
        request.trajectory_digest,
        request.policy_digest,
        canonical_ndu_shadow_policy_digest_v1(policy),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&request.current_depth.to_be_bytes());
    bytes.extend_from_slice(&request.remaining_budget_micros.to_be_bytes());
    for value in [request.value_q32, request.risk_q32, request.uncertainty_q32] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

/// Canonical digest of the complete shadow receipt.
pub fn canonical_ndu_shadow_receipt_digest_v1(suggestion: &NduShadowSuggestionV1) -> Digest32 {
    let mut bytes = b"hepta.ndu.shadow-receipt.v1\0".to_vec();
    push_text_unchecked(&mut bytes, &suggestion.subject_id);
    push_text_unchecked(&mut bytes, &suggestion.run_id);
    bytes.extend_from_slice(&suggestion.generation.to_be_bytes());
    bytes.extend_from_slice(suggestion.request_digest.as_array());
    bytes.extend_from_slice(suggestion.policy_digest.as_array());
    bytes.push(suggestion.action.tag());
    bytes.extend_from_slice(&suggestion.recommended_depth.to_be_bytes());
    bytes.push(u8::from(suggestion.should_deepen));
    bytes.push(u8::from(suggestion.abstain));
    for value in [
        suggestion.projected_value_q32,
        suggestion.projected_risk_q32,
        suggestion.projected_uncertainty_q32,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&suggestion.remaining_budget_micros.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn validate_policy(policy: &NduShadowPolicyV1) -> Result<(), NduShadowError> {
    validate_id("policy_id", &policy.policy_id)?;
    if policy.max_depth == 0 || policy.max_depth > MAX_NDU_SHADOW_DEPTH_V1 {
        return Err(NduShadowError::InvalidMaxDepth);
    }
    if policy.step_cost_micros == 0 {
        return Err(NduShadowError::ZeroStepCost);
    }
    if policy.step_cost_micros > MAX_NDU_SHADOW_BUDGET_MICROS_V1 {
        return Err(NduShadowError::BudgetTooLarge);
    }
    for (name, value) in [
        ("uncertainty_trigger_q32", policy.uncertainty_trigger_q32),
        ("risk_trigger_q32", policy.risk_trigger_q32),
        ("abstain_uncertainty_q32", policy.abstain_uncertainty_q32),
        ("abstain_risk_q32", policy.abstain_risk_q32),
        ("uncertainty_decay_q32", policy.uncertainty_decay_q32),
        ("risk_decay_q32", policy.risk_decay_q32),
        ("value_gain_q32", policy.value_gain_q32),
    ] {
        if value < 0 {
            return Err(NduShadowError::NegativeThreshold(name));
        }
    }
    Ok(())
}

fn validate_request(
    policy: &NduShadowPolicyV1,
    request: &NduShadowRequestV1,
) -> Result<(), NduShadowError> {
    validate_id("subject_id", &request.subject_id)?;
    validate_id("run_id", &request.run_id)?;
    if request.generation == 0 {
        return Err(NduShadowError::ZeroGeneration);
    }
    for (name, digest) in [
        ("input_digest", request.input_digest),
        ("stem_digest", request.stem_digest),
        ("encoder_digest", request.encoder_digest),
        ("group_adapter_digest", request.group_adapter_digest),
        ("critic_digest", request.critic_digest),
        ("trajectory_digest", request.trajectory_digest),
        ("policy_digest", request.policy_digest),
    ] {
        if digest.is_zero() {
            return Err(NduShadowError::ZeroDigest(name));
        }
    }
    if request.policy_digest != canonical_ndu_shadow_policy_digest_v1(policy) {
        return Err(NduShadowError::PolicyDigestMismatch);
    }
    if request.current_depth > policy.max_depth {
        return Err(NduShadowError::DepthExceedsPolicy);
    }
    if request.remaining_budget_micros > MAX_NDU_SHADOW_BUDGET_MICROS_V1 {
        return Err(NduShadowError::BudgetTooLarge);
    }
    if request.risk_q32 < 0 {
        return Err(NduShadowError::NegativeObservation("risk_q32"));
    }
    if request.uncertainty_q32 < 0 {
        return Err(NduShadowError::NegativeObservation("uncertainty_q32"));
    }
    Ok(())
}

fn validate_id(name: &'static str, value: &str) -> Result<(), NduShadowError> {
    if value.is_empty() {
        return Err(NduShadowError::EmptyId(name));
    }
    if value.len() > MAX_NDU_SHADOW_ID_BYTES_V1 {
        return Err(NduShadowError::IdTooLarge(name));
    }
    if value.bytes().any(|byte| byte == 0) {
        return Err(NduShadowError::EmptyId(name));
    }
    Ok(())
}

fn push_text_unchecked(bytes: &mut Vec<u8>, value: &str) {
    let length = u64::try_from(value.len()).unwrap_or(u64::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
#[path = "shadow_system2_tests.rs"]
mod tests;
