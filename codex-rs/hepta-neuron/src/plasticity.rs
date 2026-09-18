//! Eligibility-to-parameter-group sufficient-statistics accumulation.
//!
//! This module produces next-snapshot proposal inputs only. It never mutates
//! selected weights. Eligibility coordinates are mapped exactly once into
//! registered parameter groups before the low-dimensional independent modulator
//! is applied through an explicit B_m row with L1 norm <= 1.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::protocol::Q24_ONE;

const MAX_HISTORY: usize = 4096;
const MAX_GROUPS: usize = 256;
const MAX_MODULATORS: usize = 8;
const ELIGIBILITY_L1: i64 = 4 * Q24_ONE;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticitySampleV1 {
    pub checkpoint_digest: Digest32,
    pub eligibility_q24: Vec<i64>,
    pub independent_modulator_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EligibilityParameterGroupV1 {
    pub group_id: StableId,
    pub eligibility_indices: Vec<u32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModulatorBroadcastRowV1 {
    pub group_id: StableId,
    pub weights_q24: Vec<i64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlasticityTrustRegionV1 {
    pub maximum_group_absolute_q24: i64,
    pub maximum_total_l1_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterGroupStatisticV1 {
    pub group_id: StableId,
    pub delta_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticitySufficientStatisticsV1 {
    pub sample_count: u32,
    pub group_statistics: Vec<ParameterGroupStatisticV1>,
    pub eligibility_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub statistics_digest: Digest32,
    pub projected: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticityError {
    HistoryOutOfRange,
    DimensionMismatch,
    EmptyDigest,
    DuplicateCheckpoint,
    EligibilityNormExceeded,
    ModulatorOutOfRange,
    GroupCountOutOfRange,
    DuplicateGroup(String),
    EmptyGroup(String),
    EligibilityIndexOutOfRange,
    EligibilityIndexReused,
    EligibilityIndexUnmapped,
    BroadcastMismatch,
    BroadcastNormExceeded(String),
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
    history: &[PlasticitySampleV1],
    groups: &[EligibilityParameterGroupV1],
    broadcast: &[ModulatorBroadcastRowV1],
    trust_region: PlasticityTrustRegionV1,
) -> Result<PlasticitySufficientStatisticsV1, PlasticityError> {
    if !(1..=MAX_HISTORY).contains(&history.len()) {
        return Err(PlasticityError::HistoryOutOfRange);
    }
    validate_trust_region(trust_region)?;
    let eligibility_width = history[0].eligibility_q24.len();
    let modulator_width = history[0].independent_modulator_q24.len();
    if eligibility_width == 0 || !(1..=MAX_MODULATORS).contains(&modulator_width) {
        return Err(PlasticityError::DimensionMismatch);
    }
    let mut checkpoints = BTreeSet::new();
    for sample in history {
        validate_sample(sample, eligibility_width, modulator_width)?;
        if !checkpoints.insert(sample.checkpoint_digest) {
            return Err(PlasticityError::DuplicateCheckpoint);
        }
    }

    let canonical_groups = canonical_groups(groups, eligibility_width)?;
    let broadcast_by_group = canonical_broadcast(broadcast, &canonical_groups, modulator_width)?;
    let eligibility_digest = digest_eligibility(history);
    let modulator_digest = digest_modulators(history);
    let modulator_broadcast_digest =
        digest_broadcast(&canonical_groups, &broadcast_by_group, modulator_width);

    let mut statistics = Vec::with_capacity(canonical_groups.len());
    let mut projected = false;
    for group in &canonical_groups {
        let row = broadcast_by_group
            .get(&group.group_id)
            .ok_or(PlasticityError::BroadcastMismatch)?;
        let mut delta = 0_i64;
        for sample in history {
            let group_eligibility = mean_group_eligibility(sample, group)?;
            let modulation = dot_q24(&row.weights_q24, &sample.independent_modulator_q24)?;
            let contribution = mul_q24(group_eligibility, modulation);
            delta = delta
                .checked_add(contribution)
                .ok_or(PlasticityError::Arithmetic)?;
        }
        let bounded = delta.clamp(
            -trust_region.maximum_group_absolute_q24,
            trust_region.maximum_group_absolute_q24,
        );
        projected |= bounded != delta;
        statistics.push(ParameterGroupStatisticV1 {
            group_id: group.group_id.clone(),
            delta_q24: bounded,
        });
    }

    let total_l1: i128 = statistics
        .iter()
        .map(|value| i128::from(value.delta_q24).abs())
        .sum();
    if total_l1 > i128::from(trust_region.maximum_total_l1_q24) {
        for value in &mut statistics {
            value.delta_q24 = (i128::from(value.delta_q24)
                * i128::from(trust_region.maximum_total_l1_q24)
                / total_l1) as i64;
        }
        projected = true;
    }

    let sample_count = u32::try_from(history.len()).map_err(|_| PlasticityError::Arithmetic)?;
    let statistics_digest = digest_statistics(
        sample_count,
        &statistics,
        eligibility_digest,
        modulator_digest,
        modulator_broadcast_digest,
        trust_region,
        projected,
    );
    Ok(PlasticitySufficientStatisticsV1 {
        sample_count,
        group_statistics: statistics,
        eligibility_digest,
        modulator_digest,
        modulator_broadcast_digest,
        statistics_digest,
        projected,
    })
}

fn validate_sample(
    sample: &PlasticitySampleV1,
    eligibility_width: usize,
    modulator_width: usize,
) -> Result<(), PlasticityError> {
    if sample.checkpoint_digest.is_zero() {
        return Err(PlasticityError::EmptyDigest);
    }
    if sample.eligibility_q24.len() != eligibility_width
        || sample.independent_modulator_q24.len() != modulator_width
    {
        return Err(PlasticityError::DimensionMismatch);
    }
    let eligibility_l1: i128 = sample
        .eligibility_q24
        .iter()
        .map(|value| i128::from(*value).abs())
        .sum();
    if eligibility_l1 > i128::from(ELIGIBILITY_L1) {
        return Err(PlasticityError::EligibilityNormExceeded);
    }
    if sample
        .independent_modulator_q24
        .iter()
        .any(|value| !(-Q24_ONE..=Q24_ONE).contains(value))
    {
        return Err(PlasticityError::ModulatorOutOfRange);
    }
    Ok(())
}

fn canonical_groups(
    groups: &[EligibilityParameterGroupV1],
    eligibility_width: usize,
) -> Result<Vec<EligibilityParameterGroupV1>, PlasticityError> {
    if !(1..=MAX_GROUPS).contains(&groups.len()) {
        return Err(PlasticityError::GroupCountOutOfRange);
    }
    let mut groups = groups.to_vec();
    groups.sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut group_ids = BTreeSet::new();
    let mut mapped = vec![false; eligibility_width];
    for group in &mut groups {
        if !group_ids.insert(group.group_id.clone()) {
            return Err(PlasticityError::DuplicateGroup(group.group_id.to_string()));
        }
        if group.eligibility_indices.is_empty() {
            return Err(PlasticityError::EmptyGroup(group.group_id.to_string()));
        }
        group.eligibility_indices.sort_unstable();
        if group
            .eligibility_indices
            .windows(2)
            .any(|pair| pair[0] == pair[1])
        {
            return Err(PlasticityError::EligibilityIndexReused);
        }
        for index in &group.eligibility_indices {
            let index =
                usize::try_from(*index).map_err(|_| PlasticityError::EligibilityIndexOutOfRange)?;
            let Some(slot) = mapped.get_mut(index) else {
                return Err(PlasticityError::EligibilityIndexOutOfRange);
            };
            if *slot {
                return Err(PlasticityError::EligibilityIndexReused);
            }
            *slot = true;
        }
    }
    if mapped.iter().any(|mapped| !mapped) {
        return Err(PlasticityError::EligibilityIndexUnmapped);
    }
    Ok(groups)
}

fn canonical_broadcast(
    broadcast: &[ModulatorBroadcastRowV1],
    groups: &[EligibilityParameterGroupV1],
    modulator_width: usize,
) -> Result<BTreeMap<StableId, ModulatorBroadcastRowV1>, PlasticityError> {
    if broadcast.len() != groups.len() {
        return Err(PlasticityError::BroadcastMismatch);
    }
    let expected: BTreeSet<_> = groups.iter().map(|group| group.group_id.clone()).collect();
    let mut rows = BTreeMap::new();
    for row in broadcast {
        if !expected.contains(&row.group_id) || rows.contains_key(&row.group_id) {
            return Err(PlasticityError::BroadcastMismatch);
        }
        if row.weights_q24.len() != modulator_width {
            return Err(PlasticityError::DimensionMismatch);
        }
        let l1: i128 = row
            .weights_q24
            .iter()
            .map(|value| i128::from(*value).abs())
            .sum();
        if l1 > i128::from(Q24_ONE)
            || row
                .weights_q24
                .iter()
                .any(|value| !(-Q24_ONE..=Q24_ONE).contains(value))
        {
            return Err(PlasticityError::BroadcastNormExceeded(
                row.group_id.to_string(),
            ));
        }
        rows.insert(row.group_id.clone(), row.clone());
    }
    if rows.len() != expected.len() {
        return Err(PlasticityError::BroadcastMismatch);
    }
    Ok(rows)
}

fn validate_trust_region(value: PlasticityTrustRegionV1) -> Result<(), PlasticityError> {
    if !(1..=ELIGIBILITY_L1).contains(&value.maximum_group_absolute_q24)
        || !(1..=i64::MAX / 4).contains(&value.maximum_total_l1_q24)
        || value.maximum_total_l1_q24 < value.maximum_group_absolute_q24
    {
        return Err(PlasticityError::InvalidTrustRegion);
    }
    Ok(())
}

fn mean_group_eligibility(
    sample: &PlasticitySampleV1,
    group: &EligibilityParameterGroupV1,
) -> Result<i64, PlasticityError> {
    let mut sum = 0_i128;
    for index in &group.eligibility_indices {
        let index =
            usize::try_from(*index).map_err(|_| PlasticityError::EligibilityIndexOutOfRange)?;
        sum += i128::from(
            *sample
                .eligibility_q24
                .get(index)
                .ok_or(PlasticityError::EligibilityIndexOutOfRange)?,
        );
    }
    let divisor =
        i128::try_from(group.eligibility_indices.len()).map_err(|_| PlasticityError::Arithmetic)?;
    i64::try_from(sum / divisor).map_err(|_| PlasticityError::Arithmetic)
}

fn dot_q24(left: &[i64], right: &[i64]) -> Result<i64, PlasticityError> {
    if left.len() != right.len() {
        return Err(PlasticityError::DimensionMismatch);
    }
    let mut sum = 0_i64;
    for (left, right) in left.iter().zip(right) {
        sum = sum
            .checked_add(mul_q24(*left, *right))
            .ok_or(PlasticityError::Arithmetic)?;
    }
    Ok(sum.clamp(-Q24_ONE, Q24_ONE))
}

fn mul_q24(left: i64, right: i64) -> i64 {
    let product = i128::from(left) * i128::from(right);
    let magnitude = product.abs();
    let quotient = magnitude / i128::from(Q24_ONE);
    let remainder = magnitude % i128::from(Q24_ONE);
    let round_up = remainder * 2 > i128::from(Q24_ONE)
        || (remainder * 2 == i128::from(Q24_ONE) && quotient % 2 != 0);
    ((quotient + i128::from(round_up)) * product.signum()) as i64
}

fn digest_eligibility(history: &[PlasticitySampleV1]) -> Digest32 {
    let mut bytes = b"hepta.neuron.plasticity-eligibility.v1".to_vec();
    for sample in history {
        bytes.extend_from_slice(sample.checkpoint_digest.as_array());
        bytes.extend_from_slice(&(sample.eligibility_q24.len() as u64).to_be_bytes());
        for value in &sample.eligibility_q24 {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn digest_modulators(history: &[PlasticitySampleV1]) -> Digest32 {
    let mut bytes = b"hepta.neuron.plasticity-modulators.v1".to_vec();
    for sample in history {
        bytes.extend_from_slice(sample.checkpoint_digest.as_array());
        bytes.extend_from_slice(&(sample.independent_modulator_q24.len() as u64).to_be_bytes());
        for value in &sample.independent_modulator_q24 {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn digest_broadcast(
    groups: &[EligibilityParameterGroupV1],
    rows: &BTreeMap<StableId, ModulatorBroadcastRowV1>,
    modulator_width: usize,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.modulator-broadcast.v1".to_vec();
    bytes.extend_from_slice(&(modulator_width as u64).to_be_bytes());
    for group in groups {
        push_id(&mut bytes, &group.group_id);
        bytes.extend_from_slice(&(group.eligibility_indices.len() as u64).to_be_bytes());
        for index in &group.eligibility_indices {
            bytes.extend_from_slice(&index.to_be_bytes());
        }
        if let Some(row) = rows.get(&group.group_id) {
            for weight in &row.weights_q24 {
                bytes.extend_from_slice(&weight.to_be_bytes());
            }
        }
    }
    Digest32::of_bytes(&bytes)
}

fn digest_statistics(
    sample_count: u32,
    statistics: &[ParameterGroupStatisticV1],
    eligibility_digest: Digest32,
    modulator_digest: Digest32,
    broadcast_digest: Digest32,
    trust_region: PlasticityTrustRegionV1,
    projected: bool,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.plasticity-sufficient-statistics.v1".to_vec();
    bytes.extend_from_slice(&sample_count.to_be_bytes());
    for digest in [eligibility_digest, modulator_digest, broadcast_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&trust_region.maximum_group_absolute_q24.to_be_bytes());
    bytes.extend_from_slice(&trust_region.maximum_total_l1_q24.to_be_bytes());
    bytes.push(u8::from(projected));
    for statistic in statistics {
        push_id(&mut bytes, &statistic.group_id);
        bytes.extend_from_slice(&statistic.delta_q24.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
