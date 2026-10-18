//! Evaluated, row-committed world-model artifact with bounded shared lookup.
//!
//! V1 remains the deterministic compatibility baseline. V2 binds support,
//! variance/confidence, train/holdout/future windows, calibration, OOD, drift,
//! row commitment, runtime/trust/registry identity, retention, expiry, and
//! predecessor lineage. Sorted estimates use binary lookup and predictions
//! share immutable branch arrays instead of cloning branch vectors.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::OperatorResourceBudgetV1;
use crate::OperatorWorkErrorV1;
use crate::OperatorWorkMeter;
use crate::OperatorWorkSnapshotV1;
use crate::WorldModelSampleV1;
use crate::checked_add;
use crate::checked_mul;
use crate::checked_u64;
use crate::sort_work;

#[path = "world_model_v2_integrity.rs"]
mod integrity;
use integrity::digest_prediction_metadata;

#[path = "world_model_v2_memory.rs"]
mod memory;
use memory::estimate_fit_bytes;

pub const WORLD_MODEL_ARTIFACT_SCHEMA_V2: u32 = 2;
const MAX_SAMPLES: usize = 65_536;
const MAX_STATE_ACTIONS: usize = 16_384;
const MAX_BRANCHES_PER_STATE_ACTION: usize = 1_024;
const Q32_SCALE: u64 = 1_u64 << 32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelPlanV2 {
    pub model_id: StableId,
    pub generation: Generation,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub training_profile_digest: Digest32,
    pub runtime_profile_digest: Digest32,
    pub trust_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub row_commitment_root: Digest32,
    pub train_window_digest: Digest32,
    pub holdout_window_digest: Digest32,
    pub future_window_digest: Digest32,
    pub predecessor_model_digest: Option<Digest32>,
    pub authority_epoch: u64,
    pub minimum_support: u32,
    pub one_step_calibration_error: FixedQ32,
    pub multistep_calibration_error: FixedQ32,
    pub ood_false_acceptance: ProbabilityQ32,
    pub drift_score: FixedQ32,
    pub change_point_digest: Digest32,
    pub retained_until: u64,
    pub expires_at: u64,
    pub samples: Vec<WorldModelSampleV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransitionBranchV2 {
    pub next_state_id: StableId,
    pub count: u32,
    pub probability: ProbabilityQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransitionEstimateV2 {
    pub state_id: StableId,
    pub action_id: StableId,
    pub sample_count: u32,
    pub mean_outcome: FixedQ32,
    pub conditional_variance: FixedQ32,
    /// Empirical standard error radius, not a universal statistical guarantee.
    pub confidence_radius: FixedQ32,
    pub branches: Arc<[TransitionBranchV2]>,
    pub support_digest: Digest32,
    pub estimate_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelArtifactV2 {
    pub schema_version: u32,
    pub model_id: StableId,
    pub generation: Generation,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub training_profile_digest: Digest32,
    pub runtime_profile_digest: Digest32,
    pub trust_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub row_commitment_root: Digest32,
    pub train_window_digest: Digest32,
    pub holdout_window_digest: Digest32,
    pub future_window_digest: Digest32,
    pub predecessor_model_digest: Option<Digest32>,
    pub authority_epoch: u64,
    pub minimum_support: u32,
    pub one_step_calibration_error: FixedQ32,
    pub multistep_calibration_error: FixedQ32,
    pub ood_false_acceptance: ProbabilityQ32,
    pub drift_score: FixedQ32,
    pub change_point_digest: Digest32,
    pub retained_until: u64,
    pub expires_at: u64,
    pub estimates: Arc<[TransitionEstimateV2]>,
    pub model_digest: Digest32,
    pub work: OperatorWorkSnapshotV1,
    pub authority: AuthorityPosture,
    // A second strong reference prevents public Arc::make_mut/get_mut calls
    // from modifying the fitted estimates in place. Metadata remains sealed
    // separately, so repeated prediction needs no full-table rehash.
    fitted_estimates: Arc<[TransitionEstimateV2]>,
    prediction_integrity: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelUsePinV2 {
    pub runtime_profile_digest: Digest32,
    pub trust_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub minimum_authority_epoch: u64,
    pub expected_predecessor_model_digest: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorldModelPredictionV2 {
    pub model_id: StableId,
    pub model_digest: Digest32,
    pub state_id: StableId,
    pub action_id: StableId,
    pub sample_count: u32,
    pub mean_outcome: FixedQ32,
    pub conditional_variance: FixedQ32,
    pub confidence_radius: FixedQ32,
    pub branches: Arc<[TransitionBranchV2]>,
    pub one_step_calibration_error: FixedQ32,
    pub multistep_calibration_error: FixedQ32,
    pub ood_false_acceptance: ProbabilityQ32,
    pub drift_score: FixedQ32,
    pub synthetic: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WorldModelV2Error {
    Work(OperatorWorkErrorV1),
    EmptyDigest(&'static str),
    EmptyDataset,
    SampleLimit,
    DuplicateSample(String),
    DuplicateEvidence,
    InvalidOutcome,
    InvalidProfile,
    StateActionLimit,
    BranchLimit,
    InsufficientSupport {
        state: String,
        action: String,
        observed: u32,
        required: u32,
    },
    UnsupportedStateAction,
    Expired,
    Binding,
    Arithmetic,
}

impl fmt::Display for WorldModelV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for WorldModelV2Error {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Work(error) => Some(error),
            Self::EmptyDigest(_)
            | Self::EmptyDataset
            | Self::SampleLimit
            | Self::DuplicateSample(_)
            | Self::DuplicateEvidence
            | Self::InvalidOutcome
            | Self::InvalidProfile
            | Self::StateActionLimit
            | Self::BranchLimit
            | Self::InsufficientSupport { .. }
            | Self::UnsupportedStateAction
            | Self::Expired
            | Self::Binding
            | Self::Arithmetic => None,
        }
    }
}

impl From<OperatorWorkErrorV1> for WorldModelV2Error {
    fn from(value: OperatorWorkErrorV1) -> Self {
        Self::Work(value)
    }
}

#[derive(Default)]
struct Group {
    outcome_sum: i128,
    outcome_square_sum: u128,
    count: u32,
    next_counts: BTreeMap<StableId, u32>,
    evidence: Vec<Digest32>,
}

pub fn fit_world_model_v2(
    mut plan: WorldModelPlanV2,
    budget: OperatorResourceBudgetV1,
) -> Result<WorldModelArtifactV2, WorldModelV2Error> {
    validate_plan(&plan)?;
    let mut meter = OperatorWorkMeter::new(budget)?;
    let samples = checked_u64(plan.samples.len())?;
    let operations = checked_add(
        checked_add(checked_mul(samples, /*right*/ 121)?, /*right*/ 32)?,
        checked_mul(sort_work(plan.samples.len())?, /*right*/ 4)?,
    )?;
    meter.preflight_operations(operations)?;
    meter.reserve_total_bytes(estimate_fit_bytes(&plan)?)?;

    plan.samples
        .sort_by(|left, right| left.sample_id.cmp(&right.sample_id));
    meter.consume(sort_work(plan.samples.len())?)?;
    if let Some(pair) = plan
        .samples
        .windows(2)
        .find(|pair| pair[0].sample_id == pair[1].sample_id)
    {
        return Err(WorldModelV2Error::DuplicateSample(
            pair[0].sample_id.to_string(),
        ));
    }
    let mut evidence = plan
        .samples
        .iter()
        .map(|sample| sample.evidence_digest)
        .collect::<Vec<_>>();
    evidence.sort_unstable();
    meter.consume(sort_work(evidence.len())?)?;
    if evidence.iter().copied().any(Digest32::is_zero) {
        return Err(WorldModelV2Error::EmptyDigest("world-model evidence"));
    }
    if evidence.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(WorldModelV2Error::DuplicateEvidence);
    }

    let mut groups = BTreeMap::<(StableId, StableId), Group>::new();
    for (index, sample) in plan.samples.iter().enumerate() {
        if !(-FixedQ32::ONE.raw()..=FixedQ32::ONE.raw()).contains(&sample.outcome.raw()) {
            return Err(WorldModelV2Error::InvalidOutcome);
        }
        let group = groups
            .entry((sample.state_id.clone(), sample.action_id.clone()))
            .or_default();
        group.outcome_sum = group
            .outcome_sum
            .checked_add(i128::from(sample.outcome.raw()))
            .ok_or(WorldModelV2Error::Arithmetic)?;
        let magnitude = i128::from(sample.outcome.raw()).unsigned_abs();
        group.outcome_square_sum = group
            .outcome_square_sum
            .checked_add(
                magnitude
                    .checked_mul(magnitude)
                    .ok_or(WorldModelV2Error::Arithmetic)?,
            )
            .ok_or(WorldModelV2Error::Arithmetic)?;
        group.count = group
            .count
            .checked_add(1)
            .ok_or(WorldModelV2Error::Arithmetic)?;
        group
            .next_counts
            .entry(sample.next_state_id.clone())
            .and_modify(|count| *count += 1)
            .or_insert(1);
        if group.next_counts.len() > MAX_BRANCHES_PER_STATE_ACTION {
            return Err(WorldModelV2Error::BranchLimit);
        }
        group.evidence.push(sample.evidence_digest);
        if groups.len() > MAX_STATE_ACTIONS {
            return Err(WorldModelV2Error::StateActionLimit);
        }
        meter.consume(/*amount*/ 20)?;
        if index % 256 == 0 {
            meter.checkpoint()?;
        }
    }
    let mut estimates = Vec::with_capacity(groups.len());
    for ((state_id, action_id), mut group) in groups {
        if group.count < plan.minimum_support {
            return Err(WorldModelV2Error::InsufficientSupport {
                state: state_id.to_string(),
                action: action_id.to_string(),
                observed: group.count,
                required: plan.minimum_support,
            });
        }
        meter.consume(checked_add(
            checked_add(sort_work(group.evidence.len())?, /*right*/ 96)?,
            checked_add(
                sort_work(group.next_counts.len())?,
                checked_mul(checked_u64(group.next_counts.len())?, /*right*/ 5)?,
            )?,
        )?)?;
        group.evidence.sort_unstable();
        let mean_raw = round_ratio_i128(group.outcome_sum, i128::from(group.count))?;
        let mean_outcome = FixedQ32::from_raw(mean_raw);
        // Compute the exact central moment before the single Q32 rounding.
        // Separately rounding E[x²] and the mean can create positive variance
        // even when every observed outcome is the same constant.
        let count = u128::from(group.count);
        let sum_magnitude = group.outcome_sum.unsigned_abs();
        let variance_numerator = count
            .checked_mul(group.outcome_square_sum)
            .and_then(|value| {
                sum_magnitude
                    .checked_mul(sum_magnitude)
                    .and_then(|square| value.checked_sub(square))
            })
            .ok_or(WorldModelV2Error::Arithmetic)?;
        let denominator = count
            .checked_mul(count)
            .and_then(|value| value.checked_mul(u128::from(Q32_SCALE)))
            .ok_or(WorldModelV2Error::Arithmetic)?;
        let variance_raw = round_ratio_u128(variance_numerator, denominator)?;
        let variance_i64 =
            i64::try_from(variance_raw).map_err(|_| WorldModelV2Error::Arithmetic)?;
        let conditional_variance = FixedQ32::from_raw(variance_i64);
        // The standard error has Q32 units rather than variance's Q64 units.
        // Use the exact moment here too: rounding variance first can discard
        // all uncertainty while a Q32 standard error is still representable.
        let confidence_denominator = count
            .checked_mul(count)
            .and_then(|value| value.checked_mul(count))
            .ok_or(WorldModelV2Error::Arithmetic)?;
        let confidence_radicand = variance_numerator / confidence_denominator;
        let confidence_radius = FixedQ32::from_raw(
            i64::try_from(integer_sqrt(confidence_radicand)?)
                .map_err(|_| WorldModelV2Error::Arithmetic)?,
        );
        let branches = exact_probabilities(group.count, group.next_counts)?;
        let support_digest = digest_support(&group.evidence)?;
        let estimate_digest = digest_estimate(
            &state_id,
            &action_id,
            group.count,
            mean_outcome,
            conditional_variance,
            confidence_radius,
            &branches,
            support_digest,
        )?;
        estimates.push(TransitionEstimateV2 {
            state_id,
            action_id,
            sample_count: group.count,
            mean_outcome,
            conditional_variance,
            confidence_radius,
            branches,
            support_digest,
            estimate_digest,
        });
    }
    meter.consume(/*amount*/ 32)?;
    let work = meter.finish()?;
    let model_digest = digest_model(&plan, &estimates, work)?;
    let estimates: Arc<[TransitionEstimateV2]> = estimates.into();
    let mut artifact = WorldModelArtifactV2 {
        schema_version: WORLD_MODEL_ARTIFACT_SCHEMA_V2,
        model_id: plan.model_id,
        generation: plan.generation,
        objective_digest: plan.objective_digest,
        dataset_digest: plan.dataset_digest,
        training_profile_digest: plan.training_profile_digest,
        runtime_profile_digest: plan.runtime_profile_digest,
        trust_digest: plan.trust_digest,
        registry_head_digest: plan.registry_head_digest,
        row_commitment_root: plan.row_commitment_root,
        train_window_digest: plan.train_window_digest,
        holdout_window_digest: plan.holdout_window_digest,
        future_window_digest: plan.future_window_digest,
        predecessor_model_digest: plan.predecessor_model_digest,
        authority_epoch: plan.authority_epoch,
        minimum_support: plan.minimum_support,
        one_step_calibration_error: plan.one_step_calibration_error,
        multistep_calibration_error: plan.multistep_calibration_error,
        ood_false_acceptance: plan.ood_false_acceptance,
        drift_score: plan.drift_score,
        change_point_digest: plan.change_point_digest,
        retained_until: plan.retained_until,
        expires_at: plan.expires_at,
        estimates: Arc::clone(&estimates),
        model_digest,
        work,
        authority: AuthorityPosture::DENY_ALL,
        fitted_estimates: estimates,
        prediction_integrity: Digest32::ZERO,
    };
    artifact.work = meter.finish()?;
    artifact.prediction_integrity = digest_prediction_metadata(&artifact)?;
    meter.checkpoint()?;
    Ok(artifact)
}

pub fn predict_world_model_v2(
    artifact: &WorldModelArtifactV2,
    state_id: &StableId,
    action_id: &StableId,
    pin: &WorldModelUsePinV2,
    now: u64,
) -> Result<WorldModelPredictionV2, WorldModelV2Error> {
    if !Arc::ptr_eq(&artifact.estimates, &artifact.fitted_estimates)
        || artifact.prediction_integrity.is_zero()
        || digest_prediction_metadata(artifact)? != artifact.prediction_integrity
    {
        return Err(WorldModelV2Error::Binding);
    }
    if now > artifact.retained_until || now > artifact.expires_at {
        return Err(WorldModelV2Error::Expired);
    }
    if artifact.schema_version != WORLD_MODEL_ARTIFACT_SCHEMA_V2
        || artifact.runtime_profile_digest != pin.runtime_profile_digest
        || artifact.trust_digest != pin.trust_digest
        || artifact.registry_head_digest != pin.registry_head_digest
        || artifact.authority_epoch < pin.minimum_authority_epoch
        || artifact.predecessor_model_digest != pin.expected_predecessor_model_digest
        || artifact.authority.grants_any()
    {
        return Err(WorldModelV2Error::Binding);
    }
    let index = artifact
        .estimates
        .binary_search_by(|estimate| {
            (&estimate.state_id, &estimate.action_id).cmp(&(state_id, action_id))
        })
        .map_err(|_| WorldModelV2Error::UnsupportedStateAction)?;
    let estimate = &artifact.estimates[index];
    Ok(WorldModelPredictionV2 {
        model_id: artifact.model_id.clone(),
        model_digest: artifact.model_digest,
        state_id: estimate.state_id.clone(),
        action_id: estimate.action_id.clone(),
        sample_count: estimate.sample_count,
        mean_outcome: estimate.mean_outcome,
        conditional_variance: estimate.conditional_variance,
        confidence_radius: estimate.confidence_radius,
        branches: Arc::clone(&estimate.branches),
        one_step_calibration_error: artifact.one_step_calibration_error,
        multistep_calibration_error: artifact.multistep_calibration_error,
        ood_false_acceptance: artifact.ood_false_acceptance,
        drift_score: artifact.drift_score,
        synthetic: true,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_plan(plan: &WorldModelPlanV2) -> Result<(), WorldModelV2Error> {
    for (label, digest) in [
        ("objective", plan.objective_digest),
        ("dataset", plan.dataset_digest),
        ("training profile", plan.training_profile_digest),
        ("runtime profile", plan.runtime_profile_digest),
        ("trust", plan.trust_digest),
        ("registry head", plan.registry_head_digest),
        ("row commitment", plan.row_commitment_root),
        ("train window", plan.train_window_digest),
        ("holdout window", plan.holdout_window_digest),
        ("future window", plan.future_window_digest),
        ("change point", plan.change_point_digest),
    ] {
        if digest.is_zero() {
            return Err(WorldModelV2Error::EmptyDigest(label));
        }
    }
    if plan.predecessor_model_digest.is_some_and(Digest32::is_zero) {
        return Err(WorldModelV2Error::EmptyDigest("predecessor model"));
    }
    if plan.samples.is_empty() {
        return Err(WorldModelV2Error::EmptyDataset);
    }
    if plan.samples.len() > MAX_SAMPLES {
        return Err(WorldModelV2Error::SampleLimit);
    }
    if plan.authority_epoch == 0
        || plan.minimum_support == 0
        || plan.retained_until == 0
        || plan.retained_until > plan.expires_at
        || !in_unit_interval(plan.one_step_calibration_error)
        || !in_unit_interval(plan.multistep_calibration_error)
        || !in_unit_interval(plan.drift_score)
    {
        return Err(WorldModelV2Error::InvalidProfile);
    }
    Ok(())
}

fn in_unit_interval(value: FixedQ32) -> bool {
    (FixedQ32::ZERO..=FixedQ32::ONE).contains(&value)
}

fn exact_probabilities(
    total: u32,
    counts: BTreeMap<StableId, u32>,
) -> Result<Arc<[TransitionBranchV2]>, WorldModelV2Error> {
    let denominator = u128::from(total);
    let mut rows = Vec::with_capacity(counts.len());
    let mut assigned = 0_u64;
    for (next_state_id, count) in counts {
        let numerator = u128::from(count)
            .checked_mul(u128::from(Q32_SCALE))
            .ok_or(WorldModelV2Error::Arithmetic)?;
        let base =
            u64::try_from(numerator / denominator).map_err(|_| WorldModelV2Error::Arithmetic)?;
        let remainder = numerator % denominator;
        assigned = assigned
            .checked_add(base)
            .ok_or(WorldModelV2Error::Arithmetic)?;
        rows.push((next_state_id, count, base, remainder));
    }
    let leftover = Q32_SCALE
        .checked_sub(assigned)
        .ok_or(WorldModelV2Error::Arithmetic)?;
    let mut order = (0..rows.len()).collect::<Vec<_>>();
    order.sort_by(|left, right| {
        rows[*right]
            .3
            .cmp(&rows[*left].3)
            .then_with(|| rows[*left].0.cmp(&rows[*right].0))
    });
    let leftover_count = usize::try_from(leftover).map_err(|_| WorldModelV2Error::Arithmetic)?;
    if leftover_count > order.len() {
        return Err(WorldModelV2Error::Arithmetic);
    }
    for index in order.into_iter().take(leftover_count) {
        rows[index].2 = rows[index]
            .2
            .checked_add(1)
            .ok_or(WorldModelV2Error::Arithmetic)?;
    }
    // The rows retain the canonical order of the source BTreeMap; only the
    // separate remainder-index array is sorted for probability allocation.
    let mut branches = Vec::with_capacity(rows.len());
    let mut check_sum = 0_u64;
    for (next_state_id, count, raw_probability, _) in rows {
        check_sum = check_sum
            .checked_add(raw_probability)
            .ok_or(WorldModelV2Error::Arithmetic)?;
        branches.push(TransitionBranchV2 {
            next_state_id,
            count,
            probability: ProbabilityQ32::from_raw(raw_probability)
                .map_err(|_| WorldModelV2Error::Arithmetic)?,
        });
    }
    if check_sum != Q32_SCALE {
        return Err(WorldModelV2Error::Arithmetic);
    }
    Ok(branches.into())
}

fn digest_support(evidence: &[Digest32]) -> Result<Digest32, WorldModelV2Error> {
    let mut bytes = b"hepta.bellman-operator.world-model-support.v2\0".to_vec();
    bytes.extend_from_slice(
        &u32::try_from(evidence.len())
            .map_err(|_| WorldModelV2Error::Arithmetic)?
            .to_be_bytes(),
    );
    for digest in evidence {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

#[allow(clippy::too_many_arguments)]
fn digest_estimate(
    state_id: &StableId,
    action_id: &StableId,
    sample_count: u32,
    mean: FixedQ32,
    variance: FixedQ32,
    confidence: FixedQ32,
    branches: &[TransitionBranchV2],
    support_digest: Digest32,
) -> Result<Digest32, WorldModelV2Error> {
    let mut bytes = b"hepta.bellman-operator.transition-estimate.v2\0".to_vec();
    push_id(&mut bytes, state_id)?;
    push_id(&mut bytes, action_id)?;
    bytes.extend_from_slice(&sample_count.to_be_bytes());
    bytes.extend_from_slice(&mean.raw().to_be_bytes());
    bytes.extend_from_slice(&variance.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.raw().to_be_bytes());
    bytes.extend_from_slice(support_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(branches.len())
            .map_err(|_| WorldModelV2Error::Arithmetic)?
            .to_be_bytes(),
    );
    for branch in branches {
        push_id(&mut bytes, &branch.next_state_id)?;
        bytes.extend_from_slice(&branch.count.to_be_bytes());
        bytes.extend_from_slice(&branch.probability.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_model(
    plan: &WorldModelPlanV2,
    estimates: &[TransitionEstimateV2],
    work: OperatorWorkSnapshotV1,
) -> Result<Digest32, WorldModelV2Error> {
    let mut bytes = b"hepta.bellman-operator.world-model-artifact.v2\0".to_vec();
    bytes.extend_from_slice(&WORLD_MODEL_ARTIFACT_SCHEMA_V2.to_be_bytes());
    push_id(&mut bytes, &plan.model_id)?;
    bytes.extend_from_slice(&plan.generation.get().to_be_bytes());
    for digest in [
        plan.objective_digest,
        plan.dataset_digest,
        plan.training_profile_digest,
        plan.runtime_profile_digest,
        plan.trust_digest,
        plan.registry_head_digest,
        plan.row_commitment_root,
        plan.train_window_digest,
        plan.holdout_window_digest,
        plan.future_window_digest,
        plan.change_point_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    match plan.predecessor_model_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&plan.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&plan.minimum_support.to_be_bytes());
    bytes.extend_from_slice(&plan.one_step_calibration_error.raw().to_be_bytes());
    bytes.extend_from_slice(&plan.multistep_calibration_error.raw().to_be_bytes());
    bytes.extend_from_slice(&plan.ood_false_acceptance.raw().to_be_bytes());
    bytes.extend_from_slice(&plan.drift_score.raw().to_be_bytes());
    bytes.extend_from_slice(&plan.retained_until.to_be_bytes());
    bytes.extend_from_slice(&plan.expires_at.to_be_bytes());
    bytes.extend_from_slice(&work.operations.to_be_bytes());
    bytes.extend_from_slice(&work.estimated_bytes.to_be_bytes());
    bytes.extend_from_slice(
        &u32::try_from(estimates.len())
            .map_err(|_| WorldModelV2Error::Arithmetic)?
            .to_be_bytes(),
    );
    for estimate in estimates {
        bytes.extend_from_slice(estimate.estimate_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn round_ratio_i128(numerator: i128, denominator: i128) -> Result<i64, WorldModelV2Error> {
    if denominator <= 0 {
        return Err(WorldModelV2Error::Arithmetic);
    }
    let quotient = numerator / denominator;
    let remainder = numerator % denominator;
    let twice = remainder
        .checked_abs()
        .and_then(|value| value.checked_mul(2))
        .ok_or(WorldModelV2Error::Arithmetic)?;
    let rounded = if twice > denominator || (twice == denominator && quotient % 2 != 0) {
        quotient
            .checked_add(numerator.signum())
            .ok_or(WorldModelV2Error::Arithmetic)?
    } else {
        quotient
    };
    i64::try_from(rounded).map_err(|_| WorldModelV2Error::Arithmetic)
}

fn round_ratio_u128(numerator: u128, denominator: u128) -> Result<u128, WorldModelV2Error> {
    if denominator == 0 {
        return Err(WorldModelV2Error::Arithmetic);
    }
    let quotient = numerator / denominator;
    let remainder = numerator % denominator;
    let twice = remainder
        .checked_mul(2)
        .ok_or(WorldModelV2Error::Arithmetic)?;
    if twice > denominator || (twice == denominator && !quotient.is_multiple_of(2)) {
        quotient.checked_add(1).ok_or(WorldModelV2Error::Arithmetic)
    } else {
        Ok(quotient)
    }
}

fn integer_sqrt(value: u128) -> Result<u128, WorldModelV2Error> {
    if value < 2 {
        return Ok(value);
    }
    let mut left = 1_u128;
    let mut right = value.min(u128::from(u64::MAX));
    while left <= right {
        let middle = left + (right - left) / 2;
        let quotient = value / middle;
        if middle == quotient {
            return Ok(middle);
        }
        if middle < quotient {
            left = middle.checked_add(1).ok_or(WorldModelV2Error::Arithmetic)?;
        } else {
            right = middle - 1;
        }
    }
    Ok(right)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), WorldModelV2Error> {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| WorldModelV2Error::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
#[path = "world_model_v2_tests.rs"]
mod tests;
