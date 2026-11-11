//! Research-only, **time-aligned** Q24 credit comparator.
//!
//! The existing production-adjacent `accumulate_plasticity` intentionally
//! aggregates a history before applying an independent modulator. This
//! independent reference keeps the action/feedback pairing and availability
//! time explicit. It is pure; it never authenticates an owner, reads weights,
//! mutates a checkpoint, authorizes effects, or promotes a candidate.
//!
//! Digests below are **declarations checked for consistency**. An actual
//! owner-attested source/feedback proof is an additional, unimplemented gate.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::MAX_ELIGIBILITY_DIMENSION;
use super::MAX_GROUPS;
use super::MAX_HISTORY;
use super::MAX_MODULATORS;
use super::ParameterGroupMapV1;
use super::PlasticityError;
use super::PlasticityTrustRegionV1;
use super::Q;
use super::dot_q24;
use super::group_map_digest;
use super::mul_q24;
use super::push_id;
use super::push_q24;
use super::scale_toward_zero;
use super::validate_projection;
use super::validate_trust_region;

/// A distinct evaluated event must never be quietly treated as training data.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TemporalSplitV1 {
    Training,
    FrozenEvaluation,
}

/// Owner-declared action-time local eligibility (not an attested observation).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemporalEligibilityActionV1 {
    pub action_id: StableId,
    pub owner_scope_digest: Digest32,
    pub model_digest: Digest32,
    pub source_receipt_digest: Digest32,
    pub action_checkpoint_digest: Digest32,
    pub generation: u64,
    pub sequence: u64,
    pub split: TemporalSplitV1,
    pub eligibility_q24: Vec<i64>,
}

/// Independently reported effect signal, linked back to one specific action.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemporalFeedbackV1 {
    pub action_id: StableId,
    pub owner_scope_digest: Digest32,
    pub model_digest: Digest32,
    pub source_receipt_digest: Digest32,
    pub action_checkpoint_digest: Digest32,
    pub feedback_receipt_digest: Digest32,
    pub generation: u64,
    pub available_sequence: u64,
    pub split: TemporalSplitV1,
    pub modulator_q24: Vec<i64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TemporalCreditArmV1 {
    Routed,
    Shuffled,
    Scalar,
    NoEligibility,
}

/// Frozen run manifest. Every action and feedback must bind to this scope.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TemporalCreditContractV1 {
    pub owner_scope_digest: Digest32,
    pub model_digest: Digest32,
    pub generation: u64,
    pub cutoff_sequence: u64,
    pub maximum_feedback_lag: u64,
    pub decay_q24: i64,
    pub trust_region: PlasticityTrustRegionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemporalGroupDeltaV1 {
    pub group_id: StableId,
    pub delta_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TemporalCreditReceiptV1 {
    pub arm: TemporalCreditArmV1,
    pub group_deltas: Vec<TemporalGroupDeltaV1>,
    pub matched_feedback_count: u32,
    pub expired_feedback_count: u32,
    pub withheld_future_feedback_count: u32,
    /// Actions with no supplied effect receipt (not zero-valued successes).
    pub unobserved_action_count: u32,
    pub projection_count: u32,
    pub transcript_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TemporalCreditError {
    InvalidContract,
    InvalidAction,
    InvalidFeedback,
    DuplicateAction,
    DuplicateFeedback,
    UnknownAction,
    FutureAction,
    FeedbackBeforeAction,
    FrozenEvaluationLeak,
    OwnerOrModelDrift,
    SourceOrCheckpointDrift,
    InvalidGroup,
    Arithmetic,
    Projection(PlasticityError),
}

impl fmt::Display for TemporalCreditError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl StdError for TemporalCreditError {}

impl From<PlasticityError> for TemporalCreditError {
    fn from(value: PlasticityError) -> Self {
        Self::Projection(value)
    }
}

fn valid_eligibility(values: &[i64]) -> bool {
    if !(1..=MAX_ELIGIBILITY_DIMENSION).contains(&values.len()) {
        return false;
    }
    let mut norm = 0_i128;
    for &value in values {
        if !(-4 * Q..=4 * Q).contains(&value) {
            return false;
        }
        norm += i128::from(value.abs());
    }
    norm <= i128::from(4 * Q)
}

fn valid_modulator(values: &[i64]) -> bool {
    (1..=MAX_MODULATORS).contains(&values.len())
        && values.iter().all(|value| (-Q..=Q).contains(value))
}

fn decay_power_q24(mut base: i64, mut exponent: u64) -> Result<i64, TemporalCreditError> {
    let mut result = Q;
    while exponent > 0 {
        if exponent & 1 == 1 {
            result = mul_q24(result, base)?;
        }
        exponent >>= 1;
        if exponent > 0 {
            base = mul_q24(base, base)?;
        }
    }
    Ok(result)
}

/// Pure read-only reference. Group order and action/feedback order are canonical.
///
/// No cryptographic attestation or independent effect verification occurs here.
pub fn accumulate_temporal_credit_q24(
    actions: &[TemporalEligibilityActionV1],
    feedback: &[TemporalFeedbackV1],
    parameter_groups: &[ParameterGroupMapV1],
    contract: TemporalCreditContractV1,
    arm: TemporalCreditArmV1,
) -> Result<TemporalCreditReceiptV1, TemporalCreditError> {
    if contract.owner_scope_digest.is_zero()
        || contract.model_digest.is_zero()
        || contract.generation == 0
        || contract.cutoff_sequence == 0
        || !(0..=Q).contains(&contract.decay_q24)
        || actions.is_empty()
        || actions.len() > MAX_HISTORY
        || feedback.len() > MAX_HISTORY
        || !(1..=MAX_GROUPS).contains(&parameter_groups.len())
    {
        return Err(TemporalCreditError::InvalidContract);
    }
    validate_trust_region(contract.trust_region)?;

    let dim = actions[0].eligibility_q24.len();
    let mod_dim = parameter_groups[0].modulator_projection_q24.len();
    if !(1..=MAX_ELIGIBILITY_DIMENSION).contains(&dim) || !(1..=MAX_MODULATORS).contains(&mod_dim) {
        return Err(TemporalCreditError::InvalidContract);
    }

    let mut by_id = BTreeMap::<StableId, &TemporalEligibilityActionV1>::new();
    for action in actions {
        if action.sequence == 0
            || !valid_eligibility(&action.eligibility_q24)
            || action.eligibility_q24.len() != dim
            || action.source_receipt_digest.is_zero()
            || action.action_checkpoint_digest.is_zero()
        {
            return Err(TemporalCreditError::InvalidAction);
        }
        if action.owner_scope_digest != contract.owner_scope_digest
            || action.model_digest != contract.model_digest
            || action.generation != contract.generation
        {
            return Err(TemporalCreditError::OwnerOrModelDrift);
        }
        if action.split != TemporalSplitV1::Training {
            return Err(TemporalCreditError::FrozenEvaluationLeak);
        }
        if action.sequence > contract.cutoff_sequence {
            return Err(TemporalCreditError::FutureAction);
        }
        if by_id.insert(action.action_id.clone(), action).is_some() {
            return Err(TemporalCreditError::DuplicateAction);
        }
    }

    let mut groups = parameter_groups.to_vec();
    groups.sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut seen_groups = BTreeSet::new();
    for group in &groups {
        if !seen_groups.insert(group.group_id.clone()) {
            return Err(TemporalCreditError::InvalidGroup);
        }
        validate_projection(&group.group_id, &group.eligibility_projection_q24, dim)?;
        validate_projection(&group.group_id, &group.modulator_projection_q24, mod_dim)?;
    }
    if matches!(arm, TemporalCreditArmV1::Shuffled) && groups.len() < 2 {
        return Err(TemporalCreditError::InvalidGroup);
    }

    let mut feedback_sorted = feedback.to_vec();
    feedback_sorted.sort_by(|a, b| {
        a.action_id
            .cmp(&b.action_id)
            .then_with(|| a.feedback_receipt_digest.cmp(&b.feedback_receipt_digest))
    });
    let mut seen_receipts = BTreeSet::new();
    let mut seen_targets = BTreeSet::new();
    let mut sums = vec![0_i128; groups.len()];
    let mut matched = 0_u32;
    let mut expired = 0_u32;
    let mut withheld = 0_u32;
    for item in &feedback_sorted {
        if item.feedback_receipt_digest.is_zero()
            || !valid_modulator(&item.modulator_q24)
            || item.modulator_q24.len() != mod_dim
        {
            return Err(TemporalCreditError::InvalidFeedback);
        }
        if !seen_receipts.insert(item.feedback_receipt_digest)
            || !seen_targets.insert(item.action_id.clone())
        {
            return Err(TemporalCreditError::DuplicateFeedback);
        }
        let action = by_id
            .get(&item.action_id)
            .ok_or(TemporalCreditError::UnknownAction)?;
        if item.owner_scope_digest != contract.owner_scope_digest
            || item.model_digest != contract.model_digest
            || item.generation != contract.generation
        {
            return Err(TemporalCreditError::OwnerOrModelDrift);
        }
        if item.source_receipt_digest != action.source_receipt_digest
            || item.action_checkpoint_digest != action.action_checkpoint_digest
        {
            return Err(TemporalCreditError::SourceOrCheckpointDrift);
        }
        if item.split != TemporalSplitV1::Training {
            return Err(TemporalCreditError::FrozenEvaluationLeak);
        }
        let lag = item
            .available_sequence
            .checked_sub(action.sequence)
            .ok_or(TemporalCreditError::FeedbackBeforeAction)?;
        if item.available_sequence > contract.cutoff_sequence {
            withheld += 1;
            continue;
        }
        if lag > contract.maximum_feedback_lag {
            expired += 1;
            continue;
        }
        matched += 1;
        let decay = decay_power_q24(contract.decay_q24, lag)?;
        let projections = groups
            .iter()
            .map(|group| dot_q24(&group.modulator_projection_q24, &item.modulator_q24))
            .collect::<Result<Vec<_>, _>>()?;
        let scalar_mean = if matches!(arm, TemporalCreditArmV1::Scalar) {
            let total: i128 = projections.iter().map(|x| i128::from(*x)).sum();
            i64::try_from(
                total
                    / i128::try_from(projections.len())
                        .map_err(|_| TemporalCreditError::Arithmetic)?,
            )
            .map_err(|_| TemporalCreditError::Arithmetic)?
        } else {
            0
        };
        for (index, group) in groups.iter().enumerate() {
            let eligibility = dot_q24(&group.eligibility_projection_q24, &action.eligibility_q24)?;
            let signal = match arm {
                TemporalCreditArmV1::Routed => projections[index],
                TemporalCreditArmV1::Shuffled => projections[(index + 1) % groups.len()],
                TemporalCreditArmV1::Scalar => scalar_mean,
                TemporalCreditArmV1::NoEligibility => 0,
            };
            let eligible_lagged = mul_q24(eligibility, decay)?;
            let raw = mul_q24(
                mul_q24(contract.trust_region.learning_rate_q24, eligible_lagged)?,
                signal,
            )?;
            sums[index] = sums[index]
                .checked_add(i128::from(raw))
                .ok_or(TemporalCreditError::Arithmetic)?;
        }
    }

    let unobserved = u32::try_from(actions.len() - seen_targets.len())
        .map_err(|_| TemporalCreditError::Arithmetic)?;
    let mut projection_count = 0_u32;
    let mut deltas = Vec::with_capacity(groups.len());
    for (group, sum) in groups.iter().zip(sums) {
        let raw = i64::try_from(sum).map_err(|_| TemporalCreditError::Arithmetic)?;
        let delta = raw.clamp(
            -contract.trust_region.maximum_group_delta_q24,
            contract.trust_region.maximum_group_delta_q24,
        );
        projection_count += u32::from(delta != raw);
        deltas.push(TemporalGroupDeltaV1 {
            group_id: group.group_id.clone(),
            delta_q24: delta,
        });
    }
    let l1 = deltas.iter().try_fold(0_i64, |total, group| {
        total
            .checked_add(group.delta_q24.abs())
            .ok_or(TemporalCreditError::Arithmetic)
    })?;
    if l1 > contract.trust_region.maximum_global_l1_q24 {
        for delta in &mut deltas {
            delta.delta_q24 = scale_toward_zero(
                delta.delta_q24,
                contract.trust_region.maximum_global_l1_q24,
                l1,
            )?;
        }
        projection_count += 1;
    }

    let mut canonical = b"hepta.neuron.temporal-credit-shadow.v1".to_vec();
    canonical.extend_from_slice(contract.owner_scope_digest.as_array());
    canonical.extend_from_slice(contract.model_digest.as_array());
    canonical.extend_from_slice(&contract.generation.to_be_bytes());
    canonical.extend_from_slice(&contract.cutoff_sequence.to_be_bytes());
    canonical.extend_from_slice(&contract.maximum_feedback_lag.to_be_bytes());
    canonical.extend_from_slice(&contract.decay_q24.to_be_bytes());
    for amount in [
        contract.trust_region.learning_rate_q24,
        contract.trust_region.maximum_group_delta_q24,
        contract.trust_region.maximum_global_l1_q24,
    ] {
        canonical.extend_from_slice(&amount.to_be_bytes());
    }
    canonical.push(match arm {
        TemporalCreditArmV1::Routed => 0,
        TemporalCreditArmV1::Shuffled => 1,
        TemporalCreditArmV1::Scalar => 2,
        TemporalCreditArmV1::NoEligibility => 3,
    });
    canonical.extend_from_slice(group_map_digest(&groups).as_array());
    canonical.extend_from_slice(&(by_id.len() as u64).to_be_bytes());
    for action in by_id.values() {
        push_id(&mut canonical, &action.action_id);
        for digest in [
            action.source_receipt_digest,
            action.action_checkpoint_digest,
        ] {
            canonical.extend_from_slice(digest.as_array());
        }
        canonical.extend_from_slice(&action.sequence.to_be_bytes());
        push_q24(&mut canonical, &action.eligibility_q24);
    }
    canonical.extend_from_slice(&(feedback_sorted.len() as u64).to_be_bytes());
    for item in &feedback_sorted {
        push_id(&mut canonical, &item.action_id);
        canonical.extend_from_slice(item.feedback_receipt_digest.as_array());
        canonical.extend_from_slice(&item.available_sequence.to_be_bytes());
        push_q24(&mut canonical, &item.modulator_q24);
    }
    for group in &deltas {
        push_id(&mut canonical, &group.group_id);
        canonical.extend_from_slice(&group.delta_q24.to_be_bytes());
    }
    for count in [matched, expired, withheld, unobserved, projection_count] {
        canonical.extend_from_slice(&count.to_be_bytes());
    }

    Ok(TemporalCreditReceiptV1 {
        arm,
        group_deltas: deltas,
        matched_feedback_count: matched,
        expired_feedback_count: expired,
        withheld_future_feedback_count: withheld,
        unobserved_action_count: unobserved,
        projection_count,
        transcript_digest: Digest32::of_bytes(&canonical),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "temporal_credit_tests.rs"]
mod tests;
