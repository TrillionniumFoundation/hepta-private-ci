//! Three-factor next-snapshot plasticity sufficient statistics.
//!
//! Eligibility and low-dimensional modulators are explicitly projected into
//! registered parameter groups before multiplication. This module never reads
//! or mutates selected parameter bytes; the learning.plasticity owner applies
//! the final artifact-relative trust region before proposing a candidate.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::SparseCheckpoint;

const Q: i64 = 1 << 24;
const ELIGIBILITY_L1: i64 = 4 * Q;
const MAX_HISTORY: usize = 1024;
const MAX_ELIGIBILITY_DIMENSION: usize = 256;
const MAX_MODULATORS: usize = 8;
const MAX_GROUPS: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EligibilityTraceSampleV1 {
    checkpoint_digest: Digest32,
    eligibility_q24: Vec<i64>,
}

impl EligibilityTraceSampleV1 {
    #[must_use]
    pub fn from_checkpoint(checkpoint: &SparseCheckpoint) -> Self {
        Self {
            checkpoint_digest: checkpoint.digest(),
            eligibility_q24: checkpoint.eligibility_q24().to_vec(),
        }
    }

    #[must_use]
    pub fn checkpoint_digest(&self) -> Digest32 {
        self.checkpoint_digest
    }

    #[must_use]
    pub fn eligibility_q24(&self) -> &[i64] {
        &self.eligibility_q24
    }

    pub(crate) fn clear_for_ablation(&mut self) {
        self.eligibility_q24.fill(0);
    }

    #[cfg(test)]
    pub(crate) fn fixture(checkpoint_digest: Digest32, eligibility_q24: Vec<i64>) -> Self {
        Self {
            checkpoint_digest,
            eligibility_q24,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IndependentModulatorV1 {
    observation_receipt_digest: Digest32,
    values_q24: Vec<i64>,
}

impl IndependentModulatorV1 {
    #[must_use]
    pub fn observation_receipt_digest(&self) -> Digest32 {
        self.observation_receipt_digest
    }

    #[must_use]
    pub fn values_q24(&self) -> &[i64] {
        &self.values_q24
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterGroupMapV1 {
    pub group_id: StableId,
    pub eligibility_projection_q24: Vec<i64>,
    pub modulator_projection_q24: Vec<i64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityTrustRegionV1 {
    pub learning_rate_q24: i64,
    pub maximum_group_delta_q24: i64,
    pub maximum_global_l1_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterGroupDeltaV1 {
    pub group_id: StableId,
    pub eligibility_q24: i64,
    pub modulator_q24: i64,
    pub delta_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticitySufficientStatisticsV1 {
    pub eligibility_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub trust_region_digest: Digest32,
    pub group_deltas: Vec<ParameterGroupDeltaV1>,
    pub projection_count: u32,
    pub statistics_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticityError {
    HistoryCountOutOfRange,
    EligibilityDimensionOutOfRange,
    EligibilityDimensionMismatch,
    EligibilityNormExceeded,
    EmptyCheckpointDigest,
    ModulatorDimensionOutOfRange,
    InvalidModulator,
    EmptyObservationReceipt,
    GroupCountOutOfRange,
    DuplicateGroup(String),
    ProjectionDimensionMismatch(String),
    ProjectionNormExceeded(String),
    InvalidTrustRegion,
    Arithmetic,
}

impl fmt::Display for PlasticityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlasticityError {}

pub fn accumulate_plasticity(
    signal_history: &[EligibilityTraceSampleV1],
    independent_modulator: &IndependentModulatorV1,
    parameter_groups: &[ParameterGroupMapV1],
    trust_region: PlasticityTrustRegionV1,
) -> Result<PlasticitySufficientStatisticsV1, PlasticityError> {
    let eligibility = aggregate_eligibility(signal_history)?;
    validate_modulator(independent_modulator)?;
    validate_trust_region(trust_region)?;
    let mut groups = parameter_groups.to_vec();
    if !(1..=MAX_GROUPS).contains(&groups.len()) {
        return Err(PlasticityError::GroupCountOutOfRange);
    }
    groups.sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut seen = BTreeSet::new();
    for group in &groups {
        if !seen.insert(group.group_id.clone()) {
            return Err(PlasticityError::DuplicateGroup(group.group_id.to_string()));
        }
        validate_projection(
            &group.group_id,
            &group.eligibility_projection_q24,
            eligibility.len(),
        )?;
        validate_projection(
            &group.group_id,
            &group.modulator_projection_q24,
            independent_modulator.values_q24.len(),
        )?;
    }

    let mut projection_count = 0_u32;
    let mut group_deltas = Vec::with_capacity(groups.len());
    for group in &groups {
        let eligibility_q24 = dot_q24(&group.eligibility_projection_q24, &eligibility)?;
        let modulator_q24 = dot_q24(
            &group.modulator_projection_q24,
            &independent_modulator.values_q24,
        )?;
        let raw_delta = mul_q24(
            mul_q24(trust_region.learning_rate_q24, modulator_q24)?,
            eligibility_q24,
        )?;
        let delta_q24 = raw_delta.clamp(
            -trust_region.maximum_group_delta_q24,
            trust_region.maximum_group_delta_q24,
        );
        projection_count += u32::from(delta_q24 != raw_delta);
        group_deltas.push(ParameterGroupDeltaV1 {
            group_id: group.group_id.clone(),
            eligibility_q24,
            modulator_q24,
            delta_q24,
        });
    }

    let global_l1 = group_deltas.iter().try_fold(0_i64, |sum, group| {
        sum.checked_add(group.delta_q24.abs())
            .ok_or(PlasticityError::Arithmetic)
    })?;
    if global_l1 > trust_region.maximum_global_l1_q24 {
        for group in &mut group_deltas {
            group.delta_q24 = scale_toward_zero(
                group.delta_q24,
                trust_region.maximum_global_l1_q24,
                global_l1,
            )?;
        }
        projection_count = projection_count
            .checked_add(1)
            .ok_or(PlasticityError::Arithmetic)?;
    }

    let eligibility_digest = eligibility_history_digest(signal_history);
    let modulator_digest = modulator_digest(independent_modulator);
    let modulator_broadcast_digest = group_map_digest(&groups);
    let trust_region_digest = trust_region_digest(trust_region);
    let statistics_digest = statistics_digest(
        eligibility_digest,
        modulator_digest,
        modulator_broadcast_digest,
        trust_region_digest,
        &group_deltas,
        projection_count,
    );
    Ok(PlasticitySufficientStatisticsV1 {
        eligibility_digest,
        modulator_digest,
        modulator_broadcast_digest,
        trust_region_digest,
        group_deltas,
        projection_count,
        statistics_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn aggregate_eligibility(
    history: &[EligibilityTraceSampleV1],
) -> Result<Vec<i64>, PlasticityError> {
    if !(1..=MAX_HISTORY).contains(&history.len()) {
        return Err(PlasticityError::HistoryCountOutOfRange);
    }
    let dimension = history[0].eligibility_q24.len();
    if !(1..=MAX_ELIGIBILITY_DIMENSION).contains(&dimension) {
        return Err(PlasticityError::EligibilityDimensionOutOfRange);
    }
    let mut sums = vec![0_i128; dimension];
    for sample in history {
        if sample.checkpoint_digest.is_zero() {
            return Err(PlasticityError::EmptyCheckpointDigest);
        }
        if sample.eligibility_q24.len() != dimension {
            return Err(PlasticityError::EligibilityDimensionMismatch);
        }
        if sample
            .eligibility_q24
            .iter()
            .any(|value| !(-ELIGIBILITY_L1..=ELIGIBILITY_L1).contains(value))
        {
            return Err(PlasticityError::EligibilityNormExceeded);
        }
        let l1 = sample
            .eligibility_q24
            .iter()
            .try_fold(0_i64, |sum, value| {
                sum.checked_add(value.abs())
                    .ok_or(PlasticityError::Arithmetic)
            })?;
        if l1 > ELIGIBILITY_L1 {
            return Err(PlasticityError::EligibilityNormExceeded);
        }
        for (sum, value) in sums.iter_mut().zip(&sample.eligibility_q24) {
            *sum += i128::from(*value);
        }
    }
    let count = i128::try_from(history.len()).map_err(|_| PlasticityError::Arithmetic)?;
    sums.into_iter()
        .map(|value| i64::try_from(value / count).map_err(|_| PlasticityError::Arithmetic))
        .collect()
}

fn validate_modulator(value: &IndependentModulatorV1) -> Result<(), PlasticityError> {
    if value.observation_receipt_digest.is_zero() {
        return Err(PlasticityError::EmptyObservationReceipt);
    }
    if !(1..=MAX_MODULATORS).contains(&value.values_q24.len()) {
        return Err(PlasticityError::ModulatorDimensionOutOfRange);
    }
    if value.values_q24.iter().any(|item| !(-Q..=Q).contains(item)) {
        return Err(PlasticityError::InvalidModulator);
    }
    Ok(())
}

fn validate_projection(
    group_id: &StableId,
    row: &[i64],
    expected_dimension: usize,
) -> Result<(), PlasticityError> {
    if row.len() != expected_dimension {
        return Err(PlasticityError::ProjectionDimensionMismatch(
            group_id.to_string(),
        ));
    }
    let norm = row.iter().try_fold(0_i64, |sum, value| {
        if !(-Q..=Q).contains(value) {
            return Err(PlasticityError::ProjectionNormExceeded(
                group_id.to_string(),
            ));
        }
        sum.checked_add(value.abs())
            .ok_or(PlasticityError::Arithmetic)
    })?;
    if norm > Q {
        return Err(PlasticityError::ProjectionNormExceeded(
            group_id.to_string(),
        ));
    }
    Ok(())
}

fn validate_trust_region(value: PlasticityTrustRegionV1) -> Result<(), PlasticityError> {
    if !(0..=Q).contains(&value.learning_rate_q24)
        || !(1..=ELIGIBILITY_L1).contains(&value.maximum_group_delta_q24)
        || !(1..=ELIGIBILITY_L1).contains(&value.maximum_global_l1_q24)
    {
        return Err(PlasticityError::InvalidTrustRegion);
    }
    Ok(())
}

fn dot_q24(left: &[i64], right: &[i64]) -> Result<i64, PlasticityError> {
    let mut sum = 0_i128;
    for (left, right) in left.iter().zip(right) {
        sum = sum
            .checked_add(i128::from(*left) * i128::from(*right))
            .ok_or(PlasticityError::Arithmetic)?;
    }
    round_q24(sum)
}

fn mul_q24(left: i64, right: i64) -> Result<i64, PlasticityError> {
    round_q24(i128::from(left) * i128::from(right))
}

fn round_q24(product: i128) -> Result<i64, PlasticityError> {
    let scale = i128::from(Q);
    let magnitude = product.abs();
    let quotient = magnitude / scale;
    let remainder = magnitude % scale;
    let round_up = remainder * 2 > scale || (remainder * 2 == scale && quotient % 2 != 0);
    let rounded = (quotient + i128::from(round_up)) * product.signum();
    i64::try_from(rounded).map_err(|_| PlasticityError::Arithmetic)
}

fn scale_toward_zero(value: i64, numerator: i64, denominator: i64) -> Result<i64, PlasticityError> {
    let scaled = i128::from(value)
        .checked_mul(i128::from(numerator))
        .ok_or(PlasticityError::Arithmetic)?
        / i128::from(denominator);
    i64::try_from(scaled).map_err(|_| PlasticityError::Arithmetic)
}

fn eligibility_history_digest(history: &[EligibilityTraceSampleV1]) -> Digest32 {
    let mut bytes = b"hepta.neuron.eligibility-history.v1".to_vec();
    bytes.extend_from_slice(&(history.len() as u64).to_be_bytes());
    for sample in history {
        bytes.extend_from_slice(sample.checkpoint_digest.as_array());
        push_q24(&mut bytes, &sample.eligibility_q24);
    }
    Digest32::of_bytes(&bytes)
}

fn modulator_digest(modulator: &IndependentModulatorV1) -> Digest32 {
    let mut bytes = b"hepta.neuron.independent-modulator.v1".to_vec();
    bytes.extend_from_slice(modulator.observation_receipt_digest.as_array());
    push_q24(&mut bytes, &modulator.values_q24);
    Digest32::of_bytes(&bytes)
}

fn group_map_digest(groups: &[ParameterGroupMapV1]) -> Digest32 {
    let mut bytes = b"hepta.neuron.parameter-group-map.v1".to_vec();
    for group in groups {
        push_id(&mut bytes, &group.group_id);
        push_q24(&mut bytes, &group.eligibility_projection_q24);
        push_q24(&mut bytes, &group.modulator_projection_q24);
    }
    Digest32::of_bytes(&bytes)
}

fn trust_region_digest(value: PlasticityTrustRegionV1) -> Digest32 {
    let mut bytes = b"hepta.neuron.plasticity-trust-region.v1".to_vec();
    bytes.extend_from_slice(&value.learning_rate_q24.to_be_bytes());
    bytes.extend_from_slice(&value.maximum_group_delta_q24.to_be_bytes());
    bytes.extend_from_slice(&value.maximum_global_l1_q24.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn statistics_digest(
    eligibility_digest: Digest32,
    modulator_digest: Digest32,
    broadcast_digest: Digest32,
    trust_region_digest: Digest32,
    groups: &[ParameterGroupDeltaV1],
    projection_count: u32,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.plasticity-statistics.v1".to_vec();
    for digest in [
        eligibility_digest,
        modulator_digest,
        broadcast_digest,
        trust_region_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for group in groups {
        push_id(&mut bytes, &group.group_id);
        bytes.extend_from_slice(&group.eligibility_q24.to_be_bytes());
        bytes.extend_from_slice(&group.modulator_q24.to_be_bytes());
        bytes.extend_from_slice(&group.delta_q24.to_be_bytes());
    }
    bytes.extend_from_slice(&projection_count.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_q24(bytes: &mut Vec<u8>, values: &[i64]) {
    bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
}

#[cfg(test)]
#[path = "plasticity_tests.rs"]
mod tests;
