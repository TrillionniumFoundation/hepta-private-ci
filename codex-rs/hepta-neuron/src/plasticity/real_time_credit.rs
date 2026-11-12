//! Native read-only real-time Q24 comparison; no owner attestation or adoption.
//! Clock/receipt declarations require the original StageOwner's independent proof.

use super::MAX_ELIGIBILITY_DIMENSION;
use super::MAX_GROUPS;
use super::MAX_HISTORY;
use super::MAX_MODULATORS;
use super::ParameterGroupMapV1;
use super::PlasticityTrustRegionV1;
use super::Q;
use super::TemporalCreditArmV1;
use super::TemporalCreditContractV1;
use super::TemporalCreditError as Error;
use super::TemporalEligibilityActionV1;
use super::TemporalFeedbackV1;
use super::TemporalGroupDeltaV1;
use super::group_map_digest;
use super::mul_q24;
use super::push_id;
use super::round_q24;
use super::temporal_credit::accumulate_credit_with_decay;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RealTimeClockIdentityV1 {
    pub owner_scope_digest: Digest32,
    pub clock_domain_digest: Digest32,
    pub boot_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RealTimeClocksV1 {
    pub identity: RealTimeClockIdentityV1,
    pub reward_discount_tau_us: u64,
    pub state_response_tau_us: u64,
    pub parameter_update_interval_us: u64,
    pub eligibility_tau_us: u64,
}

impl RealTimeClocksV1 {
    fn validate(self) -> Result<(), Error> {
        if [
            self.identity.owner_scope_digest,
            self.identity.clock_domain_digest,
            self.identity.boot_digest,
        ]
        .iter()
        .copied()
        .any(Digest32::is_zero)
            || [
                self.reward_discount_tau_us,
                self.state_response_tau_us,
                self.parameter_update_interval_us,
                self.eligibility_tau_us,
            ]
            .contains(&0)
        {
            return Err(Error::InvalidContract);
        }
        Ok(())
    }
}

/// exp(-elapsed/tau), deterministic integer Q48 working precision, Q24 RNE output.
/// Six or fewer range halvings, 16 Taylor terms and bounded squarings; no libm.
/// Tail >=32 is below half one Q24 unit. Tests use independent Decimal90 vectors.
/// At x<=1/2, omitted terms are <3e-20 and recurrence truncations <32 Q48 units.
/// Six squarings and argument rounding keep pre-round error <0.001 Q24 unit:
/// at most one integer unit from correctly rounded exp, including tie boundaries.
pub fn real_time_decay_q24(elapsed_us: u64, tau_us: u64) -> Result<i64, Error> {
    if tau_us == 0 {
        return Err(Error::InvalidContract);
    }
    if u128::from(elapsed_us) >= 32 * u128::from(tau_us) {
        return Ok(0);
    }
    let scale = 1_i128 << 48;
    let mut x = i128::from(elapsed_us) * scale / i128::from(tau_us);
    let mut halvings = 0;
    while x > scale / 2 {
        x = (x + 1) / 2;
        halvings += 1;
    }
    let mut term = scale;
    let mut value = scale;
    for index in 1..=16 {
        term = -(term * x) / (scale * index);
        value += term;
    }
    for _ in 0..halvings {
        value = value * value / scale;
    }
    Ok(round_q24(value)?)
}

/// Reward occurrence (including action end), not its later delivery time.
pub fn discount_reward_q24(
    clocks: RealTimeClocksV1,
    reward_q24: i64,
    decision_us: u64,
    reward_us: u64,
) -> Result<i64, Error> {
    clocks.validate()?;
    let elapsed = reward_us
        .checked_sub(decision_us)
        .ok_or(Error::FeedbackBeforeAction)?;
    Ok(mul_q24(
        reward_q24,
        real_time_decay_q24(elapsed, clocks.reward_discount_tau_us)?,
    )?)
}

pub fn respond_state_q24(
    clocks: RealTimeClocksV1,
    previous_q24: i64,
    observed_q24: i64,
    elapsed_us: u64,
) -> Result<i64, Error> {
    clocks.validate()?;
    let rho = real_time_decay_q24(elapsed_us, clocks.state_response_tau_us)?;
    Ok(round_q24(
        i128::from(previous_q24) * i128::from(rho) + i128::from(observed_q24) * i128::from(Q - rho),
    )?)
}

/// Timing only: persistent opportunity consumption/CAS belongs to the real owner.
pub fn update_time_due(
    clocks: RealTimeClocksV1,
    last_update_us: u64,
    now_us: u64,
) -> Result<bool, Error> {
    clocks.validate()?;
    Ok(now_us
        .checked_sub(last_update_us)
        .ok_or(Error::FeedbackBeforeAction)?
        >= clocks.parameter_update_interval_us)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RealTimeActionV1 {
    pub clock: RealTimeClockIdentityV1,
    pub action_us: u64,
    pub group_map_digest: Digest32,
    pub action: TemporalEligibilityActionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RealTimeFeedbackV1 {
    pub clock: RealTimeClockIdentityV1,
    pub action_us: u64,
    pub outcome_us: u64,
    pub available_us: u64,
    pub group_map_digest: Digest32,
    pub feedback: TemporalFeedbackV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RealTimeCreditContractV1 {
    pub clocks: RealTimeClocksV1,
    pub model_digest: Digest32,
    pub generation: u64,
    pub cutoff_us: u64,
    pub maximum_feedback_lag_us: u64,
    pub trust_region: PlasticityTrustRegionV1,
}

/// Frozen prefix only. No future count/digest; values grant no production authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenRealTimeCreditV1 {
    pub arm: TemporalCreditArmV1,
    pub group_deltas: Vec<TemporalGroupDeltaV1>,
    pub matched_feedback_count: u32,
    pub expired_feedback_count: u32,
    pub unobserved_action_count: u32,
    pub projection_count: u32,
    pub causal_training_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Same Q24 projections, multiplication order and clipping as the native comparator.
/// Check every clock envelope before filtering; future non-time payloads are ignored.
/// Bounded raw input may still be refused. This does not verify any signing key.
pub fn accumulate_frozen_real_time_credit_q24(
    actions: &[RealTimeActionV1],
    feedback: &[RealTimeFeedbackV1],
    groups: &[ParameterGroupMapV1],
    contract: RealTimeCreditContractV1,
    arm: TemporalCreditArmV1,
) -> Result<FrozenRealTimeCreditV1, Error> {
    let clocks = contract.clocks;
    clocks.validate()?;
    if actions.is_empty()
        || actions.len() > MAX_HISTORY
        || feedback.len() > MAX_HISTORY
        || !(1..=MAX_GROUPS).contains(&groups.len())
        || groups.iter().any(|g| {
            g.eligibility_projection_q24.len() > MAX_ELIGIBILITY_DIMENSION
                || g.modulator_projection_q24.len() > MAX_MODULATORS
        })
    {
        return Err(Error::InvalidContract);
    }
    let mut group_copy = groups.to_vec();
    group_copy.sort_by(|a, b| a.group_id.cmp(&b.group_id));
    let map_digest = group_map_digest(&group_copy);
    let mut index = BTreeMap::new();
    let mut native_actions = Vec::with_capacity(actions.len());
    for item in actions {
        if item.clock != clocks.identity
            || item.group_map_digest != map_digest
            || item.action.sequence == 0
            || item.action.eligibility_q24.len() > MAX_ELIGIBILITY_DIMENSION
        {
            return Err(Error::InvalidAction);
        }
        if index
            .insert(
                item.action.action_id.clone(),
                (item.action_us, item.action.sequence),
            )
            .is_some()
        {
            return Err(Error::DuplicateAction);
        }
        let mut action = item.action.clone();
        action.sequence = item.action_us;
        native_actions.push(action);
    }
    let mut native_feedback = Vec::new();
    let mut visible = BTreeMap::new();
    for item in feedback {
        if item.clock != clocks.identity {
            return Err(Error::InvalidFeedback);
        }
        if item.available_us > contract.cutoff_us {
            continue;
        }
        let (action_us, sequence) = index
            .get(&item.feedback.action_id)
            .ok_or(Error::UnknownAction)?;
        if item.group_map_digest != map_digest
            || item.action_us != *action_us
            || item.action_us > item.outcome_us
            || item.outcome_us > item.available_us
            || item.feedback.available_sequence < *sequence
            || item.feedback.modulator_q24.len() > MAX_MODULATORS
        {
            return Err(Error::InvalidFeedback);
        }
        if visible
            .insert(item.feedback.feedback_receipt_digest, item)
            .is_some()
        {
            return Err(Error::DuplicateFeedback);
        }
        let mut event = item.feedback.clone();
        event.available_sequence = item.available_us;
        native_feedback.push(event);
    }
    let native_contract = TemporalCreditContractV1 {
        owner_scope_digest: clocks.identity.owner_scope_digest,
        model_digest: contract.model_digest,
        generation: contract.generation,
        cutoff_sequence: contract.cutoff_us,
        maximum_feedback_lag: contract.maximum_feedback_lag_us,
        decay_q24: Q,
        trust_region: contract.trust_region,
    };
    let result = accumulate_credit_with_decay(
        &native_actions,
        &native_feedback,
        groups,
        native_contract,
        arm,
        /*minimum_sequence*/ 0,
        |lag| real_time_decay_q24(lag, clocks.eligibility_tau_us),
    )?;
    let mut bytes = b"hepta.neuron.real-time-credit-shadow.v1".to_vec();
    for digest in [
        result.transcript_digest,
        clocks.identity.clock_domain_digest,
        clocks.identity.boot_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for duration in [
        clocks.reward_discount_tau_us,
        clocks.state_response_tau_us,
        clocks.parameter_update_interval_us,
        clocks.eligibility_tau_us,
    ] {
        bytes.extend_from_slice(&duration.to_be_bytes());
    }
    for (id, (_, sequence)) in index {
        push_id(&mut bytes, &id);
        bytes.extend_from_slice(&sequence.to_be_bytes());
    }
    for (digest, item) in visible {
        bytes.extend_from_slice(digest.as_array());
        bytes.extend_from_slice(&item.feedback.available_sequence.to_be_bytes());
        bytes.extend_from_slice(&item.outcome_us.to_be_bytes());
    }
    Ok(FrozenRealTimeCreditV1 {
        arm,
        group_deltas: result.group_deltas,
        matched_feedback_count: result.matched_feedback_count,
        expired_feedback_count: result.expired_feedback_count,
        unobserved_action_count: result.unobserved_action_count,
        projection_count: result.projection_count,
        causal_training_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "real_time_credit_tests.rs"]
mod tests;
