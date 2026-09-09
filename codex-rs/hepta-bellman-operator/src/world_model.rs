//! Deterministic action-conditioned transition/outcome model for qualification.
//!
//! This tabular baseline estimates only combinations present in an immutable
//! dataset. Unsupported state/action pairs return OOD instead of extrapolating.
//! Synthetic predictions remain marked as model output and never become factual
//! outcome evidence or selection authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

const MAX_SAMPLES: usize = 65_536;
const MAX_STATE_ACTIONS: usize = 16_384;
const MAX_BRANCHES_PER_STATE_ACTION: usize = 1_024;
const Q32_SCALE: u64 = 1_u64 << 32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelSampleV1 {
    pub sample_id: StableId,
    pub state_id: StableId,
    pub action_id: StableId,
    pub next_state_id: StableId,
    pub outcome: FixedQ32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransitionBranchV1 {
    pub next_state_id: StableId,
    pub count: u32,
    pub probability: ProbabilityQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransitionEstimateV1 {
    pub state_id: StableId,
    pub action_id: StableId,
    pub sample_count: u32,
    pub mean_outcome: FixedQ32,
    pub branches: Vec<TransitionBranchV1>,
    pub estimate_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TabularWorldModelV1 {
    pub model_id: StableId,
    pub dataset_digest: Digest32,
    pub estimates: Vec<TransitionEstimateV1>,
    pub model_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelPredictionV1 {
    pub model_id: StableId,
    pub dataset_digest: Digest32,
    pub state_id: StableId,
    pub action_id: StableId,
    pub mean_outcome: FixedQ32,
    pub branches: Vec<TransitionBranchV1>,
    pub estimate_digest: Digest32,
    pub synthetic: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WorldModelError {
    EmptyDigest(&'static str),
    EmptyDataset,
    SampleLimit,
    DuplicateSample(String),
    InvalidOutcome,
    StateActionLimit,
    BranchLimit,
    UnsupportedStateAction,
    Arithmetic,
}

impl fmt::Display for WorldModelError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for WorldModelError {}

#[derive(Default)]
struct Group {
    outcome_sum: i128,
    count: u32,
    next_counts: BTreeMap<StableId, u32>,
    evidence_digests: BTreeSet<Digest32>,
}

pub fn fit_transition_model(
    model_id: StableId,
    dataset_digest: Digest32,
    mut samples: Vec<WorldModelSampleV1>,
) -> Result<TabularWorldModelV1, WorldModelError> {
    require_digest(dataset_digest, "world-model dataset")?;
    if samples.is_empty() {
        return Err(WorldModelError::EmptyDataset);
    }
    if samples.len() > MAX_SAMPLES {
        return Err(WorldModelError::SampleLimit);
    }
    samples.sort_by_key(|sample| sample.sample_id.clone());
    if let Some(adjacent) = samples
        .windows(2)
        .find(|adjacent| adjacent[0].sample_id == adjacent[1].sample_id)
    {
        return Err(WorldModelError::DuplicateSample(
            adjacent[0].sample_id.to_string(),
        ));
    }

    let mut groups: BTreeMap<(StableId, StableId), Group> = BTreeMap::new();
    for sample in &samples {
        require_digest(sample.evidence_digest, "world-model sample evidence")?;
        if !(-FixedQ32::ONE.raw()..=FixedQ32::ONE.raw()).contains(&sample.outcome.raw()) {
            return Err(WorldModelError::InvalidOutcome);
        }
        let group = groups
            .entry((sample.state_id.clone(), sample.action_id.clone()))
            .or_default();
        group.outcome_sum = group
            .outcome_sum
            .checked_add(i128::from(sample.outcome.raw()))
            .ok_or(WorldModelError::Arithmetic)?;
        group.count = group
            .count
            .checked_add(1)
            .ok_or(WorldModelError::Arithmetic)?;
        group
            .next_counts
            .entry(sample.next_state_id.clone())
            .and_modify(|count| *count += 1)
            .or_insert(1);
        group.evidence_digests.insert(sample.evidence_digest);
        if group.next_counts.len() > MAX_BRANCHES_PER_STATE_ACTION {
            return Err(WorldModelError::BranchLimit);
        }
    }
    if groups.len() > MAX_STATE_ACTIONS {
        return Err(WorldModelError::StateActionLimit);
    }

    let mut estimates = Vec::with_capacity(groups.len());
    for ((state_id, action_id), group) in groups {
        let mean_outcome = FixedQ32::from_raw(round_ratio_i128(
            group.outcome_sum,
            i128::from(group.count),
        )?);
        let branches = exact_probabilities(group.count, group.next_counts)?;
        let estimate_digest = digest_estimate(
            &state_id,
            &action_id,
            group.count,
            mean_outcome,
            &branches,
            &group.evidence_digests,
        )?;
        estimates.push(TransitionEstimateV1 {
            state_id,
            action_id,
            sample_count: group.count,
            mean_outcome,
            branches,
            estimate_digest,
        });
    }

    let mut bytes = b"hepta.bellman-operator.tabular-world-model.v1".to_vec();
    push_id(&mut bytes, &model_id);
    bytes.extend_from_slice(dataset_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(estimates.len())
            .map_err(|_| WorldModelError::Arithmetic)?
            .to_be_bytes(),
    );
    for estimate in &estimates {
        bytes.extend_from_slice(estimate.estimate_digest.as_array());
    }
    Ok(TabularWorldModelV1 {
        model_id,
        dataset_digest,
        estimates,
        model_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn predict_transition(
    model: &TabularWorldModelV1,
    state_id: &StableId,
    action_id: &StableId,
) -> Result<WorldModelPredictionV1, WorldModelError> {
    let estimate = model
        .estimates
        .iter()
        .find(|estimate| &estimate.state_id == state_id && &estimate.action_id == action_id)
        .ok_or(WorldModelError::UnsupportedStateAction)?;
    Ok(WorldModelPredictionV1 {
        model_id: model.model_id.clone(),
        dataset_digest: model.dataset_digest,
        state_id: estimate.state_id.clone(),
        action_id: estimate.action_id.clone(),
        mean_outcome: estimate.mean_outcome,
        branches: estimate.branches.clone(),
        estimate_digest: estimate.estimate_digest,
        synthetic: true,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn exact_probabilities(
    total: u32,
    counts: BTreeMap<StableId, u32>,
) -> Result<Vec<TransitionBranchV1>, WorldModelError> {
    let denominator = u128::from(total);
    let mut rows = Vec::with_capacity(counts.len());
    let mut assigned = 0_u64;
    for (next_state_id, count) in counts {
        let numerator = u128::from(count)
            .checked_mul(u128::from(Q32_SCALE))
            .ok_or(WorldModelError::Arithmetic)?;
        let base = u64::try_from(numerator / denominator)
            .map_err(|_| WorldModelError::Arithmetic)?;
        let remainder = numerator % denominator;
        assigned = assigned
            .checked_add(base)
            .ok_or(WorldModelError::Arithmetic)?;
        rows.push((next_state_id, count, base, remainder));
    }
    let leftover = Q32_SCALE
        .checked_sub(assigned)
        .ok_or(WorldModelError::Arithmetic)?;
    let mut remainder_order = (0..rows.len()).collect::<Vec<_>>();
    remainder_order.sort_by(|left, right| {
        rows[*right]
            .3
            .cmp(&rows[*left].3)
            .then_with(|| rows[*left].0.cmp(&rows[*right].0))
    });
    let leftover_count = usize::try_from(leftover).map_err(|_| WorldModelError::Arithmetic)?;
    if leftover_count > remainder_order.len() {
        return Err(WorldModelError::Arithmetic);
    }
    for index in remainder_order.into_iter().take(leftover_count) {
        rows[index].2 = rows[index]
            .2
            .checked_add(1)
            .ok_or(WorldModelError::Arithmetic)?;
    }
    rows.sort_by_key(|row| row.0.clone());
    let mut branches = Vec::with_capacity(rows.len());
    let mut check_sum = 0_u64;
    for (next_state_id, count, raw_probability, _) in rows {
        check_sum = check_sum
            .checked_add(raw_probability)
            .ok_or(WorldModelError::Arithmetic)?;
        let probability = ProbabilityQ32::from_raw(raw_probability)
            .map_err(|_| WorldModelError::Arithmetic)?;
        branches.push(TransitionBranchV1 {
            next_state_id,
            count,
            probability,
        });
    }
    if check_sum != Q32_SCALE {
        return Err(WorldModelError::Arithmetic);
    }
    Ok(branches)
}

fn digest_estimate(
    state_id: &StableId,
    action_id: &StableId,
    sample_count: u32,
    mean_outcome: FixedQ32,
    branches: &[TransitionBranchV1],
    evidence_digests: &BTreeSet<Digest32>,
) -> Result<Digest32, WorldModelError> {
    let mut bytes = b"hepta.bellman-operator.transition-estimate.v1".to_vec();
    push_id(&mut bytes, state_id);
    push_id(&mut bytes, action_id);
    bytes.extend_from_slice(&sample_count.to_be_bytes());
    bytes.extend_from_slice(&mean_outcome.raw().to_be_bytes());
    bytes.extend_from_slice(
        &u32::try_from(branches.len())
            .map_err(|_| WorldModelError::Arithmetic)?
            .to_be_bytes(),
    );
    for branch in branches {
        push_id(&mut bytes, &branch.next_state_id);
        bytes.extend_from_slice(&branch.count.to_be_bytes());
        bytes.extend_from_slice(&branch.probability.raw().to_be_bytes());
    }
    bytes.extend_from_slice(
        &u32::try_from(evidence_digests.len())
            .map_err(|_| WorldModelError::Arithmetic)?
            .to_be_bytes(),
    );
    for digest in evidence_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn round_ratio_i128(numerator: i128, denominator: i128) -> Result<i64, WorldModelError> {
    if denominator <= 0 {
        return Err(WorldModelError::Arithmetic);
    }
    let quotient = numerator / denominator;
    let remainder = numerator % denominator;
    let twice = remainder
        .checked_abs()
        .and_then(|value| value.checked_mul(2))
        .ok_or(WorldModelError::Arithmetic)?;
    let rounded = if twice > denominator || (twice == denominator && quotient % 2 != 0) {
        quotient
            .checked_add(numerator.signum())
            .ok_or(WorldModelError::Arithmetic)?
    } else {
        quotient
    };
    i64::try_from(rounded).map_err(|_| WorldModelError::Arithmetic)
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), WorldModelError> {
    if digest.is_zero() {
        return Err(WorldModelError::EmptyDigest(label));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "world_model_tests.rs"]
mod tests;
