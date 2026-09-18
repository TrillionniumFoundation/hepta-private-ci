//! Bounded eligibility-to-parameter-group sufficient statistics.
//!
//! This module never mutates selected weights or topology. It maps a bounded
//! eligibility history and an independently supplied low-dimensional modulator
//! through explicit manifest rows, then applies a trust region to next-snapshot
//! sufficient statistics.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::Q24_ELIGIBILITY_LIMIT;
use crate::Q24_ONE;

const MAX_HISTORY: usize = 4096;
const MAX_GROUPS: usize = 256;
const MAX_GROUP_INDICES: usize = 512;
const MAX_MODULATORS: usize = 8;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EligibilitySnapshotV1 {
    pub sequence: u64,
    pub checkpoint_digest: Digest32,
    pub eligibility_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EligibilityGroupMapV1 {
    pub group_id: StableId,
    pub eligibility_indices: Vec<u32>,
    /// Signed Q24 weights. Each row has L1 norm <= 1.
    pub weights_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModulatorBroadcastRowV1 {
    pub group_id: StableId,
    /// B_m row over the low-dimensional independent modulator.
    pub weights_q24: Vec<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityTrustRegionV1 {
    pub maximum_group_abs_q24: i64,
    pub maximum_total_l1_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityStatisticsRequestV1 {
    pub signal_history: Vec<EligibilitySnapshotV1>,
    pub independent_modulator_q24: Vec<i64>,
    pub eligibility_mapping: Vec<EligibilityGroupMapV1>,
    pub modulator_broadcast: Vec<ModulatorBroadcastRowV1>,
    pub trust_region: PlasticityTrustRegionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterGroupStatisticV1 {
    pub group_id: StableId,
    pub eligibility_q24: i64,
    pub modulator_q24: i64,
    pub sufficient_statistic_q24: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticitySufficientStatisticsV1 {
    pub groups: Vec<ParameterGroupStatisticV1>,
    pub eligibility_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub statistics_digest: Digest32,
    pub projection_count: u32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticityError {
    EmptyHistory,
    HistoryLimit,
    InvalidSequence,
    InvalidCheckpoint,
    TraceWidth,
    TraceBound,
    InvalidModulator,
    InvalidGroupCount,
    DuplicateGroup(String),
    MappingMismatch,
    InvalidMappingRow(String),
    InvalidBroadcastRow(String),
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
    request: &PlasticityStatisticsRequestV1,
) -> Result<PlasticitySufficientStatisticsV1, PlasticityError> {
    validate_request(request)?;
    let eligibility_digest = digest_history(&request.signal_history)?;
    let modulator_digest = digest_q24(
        b"hepta.neuron.independent-modulator.v1",
        &request.independent_modulator_q24,
    )?;
    let modulator_broadcast_digest = digest_broadcast(&request.modulator_broadcast)?;

    let history_len =
        i128::try_from(request.signal_history.len()).map_err(|_| PlasticityError::Arithmetic)?;
    let mut groups = Vec::with_capacity(request.eligibility_mapping.len());
    let mut projections = 0_u32;

    for mapping in &request.eligibility_mapping {
        let broadcast = request
            .modulator_broadcast
            .iter()
            .find(|row| row.group_id == mapping.group_id)
            .ok_or(PlasticityError::MappingMismatch)?;
        let mut accumulated = 0_i128;
        for snapshot in &request.signal_history {
            let mut local = 0_i128;
            for (index, weight) in mapping.eligibility_indices.iter().zip(&mapping.weights_q24) {
                let value = snapshot
                    .eligibility_q24
                    .get(usize::try_from(*index).map_err(|_| PlasticityError::Arithmetic)?)
                    .ok_or_else(|| {
                        PlasticityError::InvalidMappingRow(mapping.group_id.to_string())
                    })?;
                local = local
                    .checked_add(i128::from(q24_mul(*weight, *value)?))
                    .ok_or(PlasticityError::Arithmetic)?;
            }
            accumulated = accumulated
                .checked_add(local)
                .ok_or(PlasticityError::Arithmetic)?;
        }
        let eligibility_q24 =
            i64::try_from(accumulated / history_len).map_err(|_| PlasticityError::Arithmetic)?;
        let mut modulator_q24 = 0_i64;
        for (weight, value) in broadcast
            .weights_q24
            .iter()
            .zip(&request.independent_modulator_q24)
        {
            modulator_q24 = modulator_q24
                .checked_add(q24_mul(*weight, *value)?)
                .ok_or(PlasticityError::Arithmetic)?;
        }
        let raw = q24_mul(eligibility_q24, modulator_q24)?;
        let bounded = raw.clamp(
            -request.trust_region.maximum_group_abs_q24,
            request.trust_region.maximum_group_abs_q24,
        );
        projections = projections
            .checked_add(u32::from(raw != bounded))
            .ok_or(PlasticityError::Arithmetic)?;
        groups.push(ParameterGroupStatisticV1 {
            group_id: mapping.group_id.clone(),
            eligibility_q24,
            modulator_q24,
            sufficient_statistic_q24: bounded,
        });
    }

    let total_l1 = groups.iter().try_fold(0_i128, |sum, group| {
        sum.checked_add(i128::from(group.sufficient_statistic_q24).abs())
            .ok_or(PlasticityError::Arithmetic)
    })?;
    let maximum_total = i128::from(request.trust_region.maximum_total_l1_q24);
    if total_l1 > maximum_total {
        for group in &mut groups {
            let numerator = i128::from(group.sufficient_statistic_q24)
                .checked_mul(maximum_total)
                .ok_or(PlasticityError::Arithmetic)?;
            group.sufficient_statistic_q24 =
                i64::try_from(numerator / total_l1).map_err(|_| PlasticityError::Arithmetic)?;
        }
        projections = projections
            .checked_add(1)
            .ok_or(PlasticityError::Arithmetic)?;
    }

    let statistics_digest = digest_statistics(
        eligibility_digest,
        modulator_digest,
        modulator_broadcast_digest,
        &request.trust_region,
        &groups,
    )?;
    Ok(PlasticitySufficientStatisticsV1 {
        groups,
        eligibility_digest,
        modulator_digest,
        modulator_broadcast_digest,
        statistics_digest,
        projection_count: projections,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_request(request: &PlasticityStatisticsRequestV1) -> Result<(), PlasticityError> {
    if request.signal_history.is_empty() {
        return Err(PlasticityError::EmptyHistory);
    }
    if request.signal_history.len() > MAX_HISTORY {
        return Err(PlasticityError::HistoryLimit);
    }
    let width = request.signal_history[0].eligibility_q24.len();
    if width == 0 || width > MAX_GROUP_INDICES {
        return Err(PlasticityError::TraceWidth);
    }
    let mut prior_sequence = 0_u64;
    for snapshot in &request.signal_history {
        if snapshot.sequence == 0 || snapshot.sequence <= prior_sequence {
            return Err(PlasticityError::InvalidSequence);
        }
        prior_sequence = snapshot.sequence;
        if snapshot.checkpoint_digest.is_zero() {
            return Err(PlasticityError::InvalidCheckpoint);
        }
        if snapshot.eligibility_q24.len() != width {
            return Err(PlasticityError::TraceWidth);
        }
        let l1 = snapshot
            .eligibility_q24
            .iter()
            .try_fold(0_i128, |sum, value| {
                sum.checked_add(i128::from(*value).abs())
                    .ok_or(PlasticityError::Arithmetic)
            })?;
        if l1 > i128::from(Q24_ELIGIBILITY_LIMIT) {
            return Err(PlasticityError::TraceBound);
        }
    }
    if request.independent_modulator_q24.is_empty()
        || request.independent_modulator_q24.len() > MAX_MODULATORS
        || request
            .independent_modulator_q24
            .iter()
            .any(|value| !(-Q24_ONE..=Q24_ONE).contains(value))
    {
        return Err(PlasticityError::InvalidModulator);
    }
    if request.eligibility_mapping.is_empty()
        || request.eligibility_mapping.len() > MAX_GROUPS
        || request.modulator_broadcast.len() != request.eligibility_mapping.len()
    {
        return Err(PlasticityError::InvalidGroupCount);
    }
    if request.trust_region.maximum_group_abs_q24 <= 0
        || request.trust_region.maximum_group_abs_q24 > Q24_ELIGIBILITY_LIMIT
        || request.trust_region.maximum_total_l1_q24 <= 0
    {
        return Err(PlasticityError::InvalidTrustRegion);
    }

    let mut eligibility_groups = BTreeSet::new();
    for row in &request.eligibility_mapping {
        if !eligibility_groups.insert(row.group_id.clone()) {
            return Err(PlasticityError::DuplicateGroup(row.group_id.to_string()));
        }
        if row.eligibility_indices.is_empty()
            || row.eligibility_indices.len() > MAX_GROUP_INDICES
            || row.eligibility_indices.len() != row.weights_q24.len()
            || !strictly_increasing(&row.eligibility_indices)
            || row
                .eligibility_indices
                .iter()
                .any(|index| usize::try_from(*index).map_or(true, |value| value >= width))
            || q24_l1(&row.weights_q24)? > i128::from(Q24_ONE)
        {
            return Err(PlasticityError::InvalidMappingRow(row.group_id.to_string()));
        }
    }

    let mut broadcast_groups = BTreeSet::new();
    for row in &request.modulator_broadcast {
        if !broadcast_groups.insert(row.group_id.clone()) {
            return Err(PlasticityError::DuplicateGroup(row.group_id.to_string()));
        }
        if row.weights_q24.len() != request.independent_modulator_q24.len()
            || q24_l1(&row.weights_q24)? > i128::from(Q24_ONE)
        {
            return Err(PlasticityError::InvalidBroadcastRow(
                row.group_id.to_string(),
            ));
        }
    }
    if eligibility_groups != broadcast_groups {
        return Err(PlasticityError::MappingMismatch);
    }
    Ok(())
}

fn q24_mul(left: i64, right: i64) -> Result<i64, PlasticityError> {
    let product = i128::from(left)
        .checked_mul(i128::from(right))
        .ok_or(PlasticityError::Arithmetic)?;
    let magnitude = product.abs();
    let denominator = i128::from(Q24_ONE);
    let quotient = magnitude / denominator;
    let remainder = magnitude % denominator;
    let round_up =
        remainder * 2 > denominator || (remainder * 2 == denominator && quotient % 2 != 0);
    i64::try_from((quotient + i128::from(round_up)) * product.signum())
        .map_err(|_| PlasticityError::Arithmetic)
}

fn q24_l1(values: &[i64]) -> Result<i128, PlasticityError> {
    values.iter().try_fold(0_i128, |sum, value| {
        sum.checked_add(i128::from(*value).abs())
            .ok_or(PlasticityError::Arithmetic)
    })
}

fn strictly_increasing(values: &[u32]) -> bool {
    values.windows(2).all(|pair| pair[0] < pair[1])
}

fn digest_history(history: &[EligibilitySnapshotV1]) -> Result<Digest32, PlasticityError> {
    let mut bytes = b"hepta.neuron.eligibility-history.v1".to_vec();
    let length = u32::try_from(history.len()).map_err(|_| PlasticityError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for snapshot in history {
        bytes.extend_from_slice(&snapshot.sequence.to_be_bytes());
        bytes.extend_from_slice(snapshot.checkpoint_digest.as_array());
        append_q24(&mut bytes, &snapshot.eligibility_q24)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_broadcast(rows: &[ModulatorBroadcastRowV1]) -> Result<Digest32, PlasticityError> {
    let mut rows = rows.to_vec();
    rows.sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut bytes = b"hepta.neuron.modulator-broadcast.v1".to_vec();
    let length = u32::try_from(rows.len()).map_err(|_| PlasticityError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for row in rows {
        push_id(&mut bytes, &row.group_id)?;
        append_q24(&mut bytes, &row.weights_q24)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_statistics(
    eligibility_digest: Digest32,
    modulator_digest: Digest32,
    broadcast_digest: Digest32,
    trust_region: &PlasticityTrustRegionV1,
    groups: &[ParameterGroupStatisticV1],
) -> Result<Digest32, PlasticityError> {
    let mut bytes = b"hepta.neuron.plasticity-statistics.v1".to_vec();
    for digest in [eligibility_digest, modulator_digest, broadcast_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&trust_region.maximum_group_abs_q24.to_be_bytes());
    bytes.extend_from_slice(&trust_region.maximum_total_l1_q24.to_be_bytes());
    let length = u32::try_from(groups.len()).map_err(|_| PlasticityError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for group in groups {
        push_id(&mut bytes, &group.group_id)?;
        bytes.extend_from_slice(&group.eligibility_q24.to_be_bytes());
        bytes.extend_from_slice(&group.modulator_q24.to_be_bytes());
        bytes.extend_from_slice(&group.sufficient_statistic_q24.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_q24(domain: &[u8], values: &[i64]) -> Result<Digest32, PlasticityError> {
    let mut bytes = domain.to_vec();
    append_q24(&mut bytes, values)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn append_q24(bytes: &mut Vec<u8>, values: &[i64]) -> Result<(), PlasticityError> {
    let length = u32::try_from(values.len()).map_err(|_| PlasticityError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), PlasticityError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| PlasticityError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
#[path = "plasticity_tests.rs"]
mod tests;
