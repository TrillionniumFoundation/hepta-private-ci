//! Three-factor, next-snapshot-only plasticity sufficient statistics.
//!
//! This module implements the manifest-bound `B_m` broadcast from an
//! independently observed low-dimensional modulator into registered parameter
//! groups. It emits bounded sufficient statistics only; selected weights and
//! topology are never mutated here. Artifact-relative trust regions remain the
//! responsibility of the downstream plasticity owner.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::SparseCheckpoint;

const Q: i64 = 1 << 24;
const MAX_MODULATORS: usize = 8;
const MAX_GROUPS: usize = 256;
const MAX_SAMPLES: usize = 1024;
const MAX_ELIGIBILITY_WIDTH: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterGroupRowV1 {
    pub group_id: StableId,
    pub coefficients_q24: Vec<i64>,
    pub eligibility_indices: Vec<usize>,
    pub learning_rate_q24: i64,
    pub maximum_group_l1_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterGroupMapV1 {
    pub manifest_id: StableId,
    pub modulator_dimension: usize,
    pub rows: Vec<ParameterGroupRowV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IndependentModulatorV1 {
    pub source_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub values_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticitySampleV1 {
    pub eligibility_digest: Digest32,
    pub eligibility_q24: Vec<i64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityTrustRegionV1 {
    pub maximum_global_l1_q24: i64,
    pub maximum_samples: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterGroupStatisticV1 {
    pub group_id: StableId,
    pub modulation_q24: i64,
    pub delta_q24: Vec<i64>,
    pub l1_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticitySufficientStatisticsV1 {
    pub map_digest: Digest32,
    pub modulator_digest: Digest32,
    pub eligibility_digest: Digest32,
    pub broadcast_digest: Digest32,
    pub group_statistics: Vec<ParameterGroupStatisticV1>,
    pub global_l1_q24: i64,
    pub sample_count: u32,
    pub statistics_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticityError {
    InvalidMap,
    InvalidModulator,
    InvalidSample,
    InvalidTrustRegion,
    DuplicateGroup(String),
    DuplicateEligibilityIndex(String),
    DimensionMismatch,
    Arithmetic,
}

impl fmt::Display for PlasticityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlasticityError {}

impl PlasticitySampleV1 {
    pub fn from_checkpoint(checkpoint: &SparseCheckpoint) -> Result<Self, PlasticityError> {
        Self::from_eligibility(checkpoint.eligibility_q24().to_vec())
    }

    pub fn from_eligibility(eligibility_q24: Vec<i64>) -> Result<Self, PlasticityError> {
        if eligibility_q24.is_empty() || eligibility_q24.len() > MAX_ELIGIBILITY_WIDTH {
            return Err(PlasticityError::InvalidSample);
        }
        let eligibility_digest = digest_eligibility(&eligibility_q24)?;
        Ok(Self {
            eligibility_digest,
            eligibility_q24,
        })
    }
}

impl IndependentModulatorV1 {
    pub fn digest(&self) -> Result<Digest32, PlasticityError> {
        if self.source_digest.is_zero()
            || self.evaluation_digest.is_zero()
            || self.values_q24.is_empty()
            || self.values_q24.len() > MAX_MODULATORS
            || self.values_q24.iter().any(|value| !(-Q..=Q).contains(value))
        {
            return Err(PlasticityError::InvalidModulator);
        }
        let mut bytes = b"hepta.neuron.independent-modulator.v1".to_vec();
        bytes.extend_from_slice(self.source_digest.as_array());
        bytes.extend_from_slice(self.evaluation_digest.as_array());
        push_len(&mut bytes, self.values_q24.len())?;
        for value in &self.values_q24 {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl ParameterGroupMapV1 {
    pub fn digest(&self, eligibility_width: usize) -> Result<Digest32, PlasticityError> {
        validate_map(self, eligibility_width)?;
        let mut rows = self.rows.clone();
        rows.sort_by(|left, right| left.group_id.cmp(&right.group_id));
        let mut bytes = b"hepta.neuron.parameter-group-map.v1".to_vec();
        push_id(&mut bytes, &self.manifest_id)?;
        push_len(&mut bytes, self.modulator_dimension)?;
        push_len(&mut bytes, eligibility_width)?;
        push_len(&mut bytes, rows.len())?;
        for row in rows {
            push_id(&mut bytes, &row.group_id)?;
            for value in row.coefficients_q24 {
                bytes.extend_from_slice(&value.to_be_bytes());
            }
            push_len(&mut bytes, row.eligibility_indices.len())?;
            for index in row.eligibility_indices {
                bytes.extend_from_slice(&u64_from_usize(index)?.to_be_bytes());
            }
            bytes.extend_from_slice(&row.learning_rate_q24.to_be_bytes());
            bytes.extend_from_slice(&row.maximum_group_l1_q24.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub fn accumulate_plasticity(
    samples: &[PlasticitySampleV1],
    modulator: &IndependentModulatorV1,
    map: &ParameterGroupMapV1,
    trust_region: PlasticityTrustRegionV1,
) -> Result<PlasticitySufficientStatisticsV1, PlasticityError> {
    if samples.is_empty()
        || samples.len() > MAX_SAMPLES
        || trust_region.maximum_samples == 0
        || trust_region.maximum_samples > MAX_SAMPLES
        || samples.len() > trust_region.maximum_samples
        || trust_region.maximum_global_l1_q24 <= 0
    {
        return Err(PlasticityError::InvalidTrustRegion);
    }
    let width = samples[0].eligibility_q24.len();
    if width == 0 || width > MAX_ELIGIBILITY_WIDTH {
        return Err(PlasticityError::InvalidSample);
    }
    let mut eligibility_bytes = b"hepta.neuron.eligibility-history.v1".to_vec();
    push_len(&mut eligibility_bytes, samples.len())?;
    for sample in samples {
        if sample.eligibility_q24.len() != width
            || sample.eligibility_digest != digest_eligibility(&sample.eligibility_q24)?
        {
            return Err(PlasticityError::InvalidSample);
        }
        eligibility_bytes.extend_from_slice(sample.eligibility_digest.as_array());
    }
    let eligibility_digest = Digest32::of_bytes(&eligibility_bytes);
    let modulator_digest = modulator.digest()?;
    if modulator.values_q24.len() != map.modulator_dimension {
        return Err(PlasticityError::DimensionMismatch);
    }
    let map_digest = map.digest(width)?;
    let mut broadcast_bytes = b"hepta.neuron.modulator-broadcast.v1".to_vec();
    broadcast_bytes.extend_from_slice(map_digest.as_array());
    broadcast_bytes.extend_from_slice(modulator_digest.as_array());
    let broadcast_digest = Digest32::of_bytes(&broadcast_bytes);

    let mut rows = map.rows.clone();
    rows.sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut group_statistics = Vec::with_capacity(rows.len());
    for row in rows {
        let modulation_q24 = dot_q24(&row.coefficients_q24, &modulator.values_q24)?;
        let mut accumulated = vec![0_i128; row.eligibility_indices.len()];
        for sample in samples {
            for (output, index) in accumulated.iter_mut().zip(&row.eligibility_indices) {
                let local = mul_q24(modulation_q24, sample.eligibility_q24[*index]);
                let update = mul_q24(row.learning_rate_q24, local);
                *output = output
                    .checked_add(i128::from(update))
                    .ok_or(PlasticityError::Arithmetic)?;
            }
        }
        let mut delta_q24 = accumulated
            .into_iter()
            .map(|value| i64::try_from(value).map_err(|_| PlasticityError::Arithmetic))
            .collect::<Result<Vec<_>, _>>()?;
        project_l1(&mut delta_q24, row.maximum_group_l1_q24)?;
        let l1_q24 = l1(&delta_q24)?;
        group_statistics.push(ParameterGroupStatisticV1 {
            group_id: row.group_id,
            modulation_q24,
            delta_q24,
            l1_q24,
        });
    }

    let global_before = group_statistics.iter().try_fold(0_i64, |total, group| {
        total
            .checked_add(group.l1_q24)
            .ok_or(PlasticityError::Arithmetic)
    })?;
    if global_before > trust_region.maximum_global_l1_q24 {
        for group in &mut group_statistics {
            for value in &mut group.delta_q24 {
                *value = scale_toward_zero(
                    *value,
                    trust_region.maximum_global_l1_q24,
                    global_before,
                )?;
            }
            group.l1_q24 = l1(&group.delta_q24)?;
        }
    }
    let global_l1_q24 = group_statistics.iter().try_fold(0_i64, |total, group| {
        total
            .checked_add(group.l1_q24)
            .ok_or(PlasticityError::Arithmetic)
    })?;
    if global_l1_q24 > trust_region.maximum_global_l1_q24 {
        return Err(PlasticityError::Arithmetic);
    }

    let sample_count = u32::try_from(samples.len()).map_err(|_| PlasticityError::Arithmetic)?;
    let mut bytes = b"hepta.neuron.plasticity-sufficient-statistics.v1".to_vec();
    for digest in [map_digest, modulator_digest, eligibility_digest, broadcast_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&sample_count.to_be_bytes());
    for group in &group_statistics {
        push_id(&mut bytes, &group.group_id)?;
        bytes.extend_from_slice(&group.modulation_q24.to_be_bytes());
        push_len(&mut bytes, group.delta_q24.len())?;
        for value in &group.delta_q24 {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(&group.l1_q24.to_be_bytes());
    }
    bytes.extend_from_slice(&global_l1_q24.to_be_bytes());
    let statistics_digest = Digest32::of_bytes(&bytes);
    Ok(PlasticitySufficientStatisticsV1 {
        map_digest,
        modulator_digest,
        eligibility_digest,
        broadcast_digest,
        group_statistics,
        global_l1_q24,
        sample_count,
        statistics_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_map(map: &ParameterGroupMapV1, eligibility_width: usize) -> Result<(), PlasticityError> {
    if map.modulator_dimension == 0
        || map.modulator_dimension > MAX_MODULATORS
        || map.rows.is_empty()
        || map.rows.len() > MAX_GROUPS
        || eligibility_width == 0
        || eligibility_width > MAX_ELIGIBILITY_WIDTH
    {
        return Err(PlasticityError::InvalidMap);
    }
    let mut groups = BTreeSet::new();
    for row in &map.rows {
        if !groups.insert(row.group_id.clone()) {
            return Err(PlasticityError::DuplicateGroup(row.group_id.to_string()));
        }
        if row.coefficients_q24.len() != map.modulator_dimension
            || !(0..=Q).contains(&row.learning_rate_q24)
            || row.maximum_group_l1_q24 <= 0
        {
            return Err(PlasticityError::InvalidMap);
        }
        let coefficient_l1 = l1(&row.coefficients_q24)?;
        if coefficient_l1 > Q {
            return Err(PlasticityError::InvalidMap);
        }
        if row.eligibility_indices.is_empty() {
            return Err(PlasticityError::InvalidMap);
        }
        let mut indices = BTreeSet::new();
        for index in &row.eligibility_indices {
            if *index >= eligibility_width {
                return Err(PlasticityError::DimensionMismatch);
            }
            if !indices.insert(*index) {
                return Err(PlasticityError::DuplicateEligibilityIndex(
                    row.group_id.to_string(),
                ));
            }
        }
    }
    Ok(())
}

fn digest_eligibility(values: &[i64]) -> Result<Digest32, PlasticityError> {
    let mut bytes = b"hepta.neuron.eligibility-vector.q24.v1".to_vec();
    push_len(&mut bytes, values.len())?;
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn dot_q24(left: &[i64], right: &[i64]) -> Result<i64, PlasticityError> {
    if left.len() != right.len() {
        return Err(PlasticityError::DimensionMismatch);
    }
    left.iter().zip(right).try_fold(0_i64, |total, (left, right)| {
        total
            .checked_add(mul_q24(*left, *right))
            .ok_or(PlasticityError::Arithmetic)
    })
}

fn mul_q24(left: i64, right: i64) -> i64 {
    let product = i128::from(left) * i128::from(right);
    let magnitude = product.abs();
    let quotient = magnitude / i128::from(Q);
    let remainder = magnitude % i128::from(Q);
    let round_up =
        remainder * 2 > i128::from(Q) || (remainder * 2 == i128::from(Q) && quotient % 2 != 0);
    ((quotient + i128::from(round_up)) * product.signum()) as i64
}

fn project_l1(values: &mut [i64], maximum_l1: i64) -> Result<(), PlasticityError> {
    if maximum_l1 <= 0 {
        return Err(PlasticityError::InvalidTrustRegion);
    }
    let norm = l1(values)?;
    if norm <= maximum_l1 {
        return Ok(());
    }
    for value in values {
        *value = scale_toward_zero(*value, maximum_l1, norm)?;
    }
    Ok(())
}

fn scale_toward_zero(value: i64, numerator: i64, denominator: i64) -> Result<i64, PlasticityError> {
    if numerator < 0 || denominator <= 0 {
        return Err(PlasticityError::Arithmetic);
    }
    let scaled = i128::from(value)
        .checked_mul(i128::from(numerator))
        .ok_or(PlasticityError::Arithmetic)?
        / i128::from(denominator);
    i64::try_from(scaled).map_err(|_| PlasticityError::Arithmetic)
}

fn l1(values: &[i64]) -> Result<i64, PlasticityError> {
    values.iter().try_fold(0_i64, |total, value| {
        let magnitude = value.checked_abs().ok_or(PlasticityError::Arithmetic)?;
        total.checked_add(magnitude).ok_or(PlasticityError::Arithmetic)
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), PlasticityError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| PlasticityError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), PlasticityError> {
    let value = u32::try_from(value).map_err(|_| PlasticityError::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn u64_from_usize(value: usize) -> Result<u64, PlasticityError> {
    u64::try_from(value).map_err(|_| PlasticityError::Arithmetic)
}

#[cfg(test)]
#[path = "plasticity_tests.rs"]
mod tests;
