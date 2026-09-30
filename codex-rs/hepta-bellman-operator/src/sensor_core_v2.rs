//! Bounded deterministic sensor-core construction for production qualification.
//!
//! The V1 reference remains byte-compatible. This V2 surface replaces quadratic
//! coordinate duplicate scans with canonical coordinate fingerprints, maintains
//! separation incrementally during FPS, consumes one absolute work budget, and
//! records when a large design uses deterministic fingerprint-stratified
//! approximation before exact FPS on the bounded working set.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::OperatorResourceBudgetV1;
use crate::OperatorSensorCoreManifestV1;
use crate::OperatorWorkErrorV1;
use crate::OperatorWorkMeter;
use crate::OperatorWorkSnapshotV1;
use crate::SensorCoreDesignV1;
use crate::SensorPointV1;
use crate::checked_add;
use crate::checked_mul;
use crate::checked_u64;

const MAX_DESIGN_POINTS: usize = 16_384;
const MAX_DIMENSIONS: usize = 32;
const MAX_SENSORS: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SensorCoreExecutionProfileV2 {
    pub budget: OperatorResourceBudgetV1,
    /// Designs at or below this size execute exact FPS over every candidate.
    pub exact_candidate_limit: usize,
    /// Larger designs are deterministically reduced to this many candidates.
    pub maximum_working_candidates: usize,
}

impl SensorCoreExecutionProfileV2 {
    #[must_use]
    pub const fn qualification_default() -> Self {
        Self {
            budget: OperatorResourceBudgetV1::qualification_default(),
            exact_candidate_limit: 4_096,
            maximum_working_candidates: 4_096,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorSensorCoreBuildReceiptV2 {
    pub manifest: OperatorSensorCoreManifestV1,
    pub input_candidate_count: u32,
    pub working_candidate_count: u32,
    pub approximation_applied: bool,
    pub profile: SensorCoreExecutionProfileV2,
    pub work: OperatorWorkSnapshotV1,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SensorCoreBuildErrorV2 {
    Work(OperatorWorkErrorV1),
    EmptyDigest(&'static str),
    InvalidProfile,
    SensorCount,
    DuplicateSensorId(String),
    SensorDimension,
    SensorCoordinate,
    DuplicateSensorCoordinates,
    SensorSeparation,
    MeshRatio,
    Arithmetic,
    InternalInvariant,
}

impl fmt::Display for SensorCoreBuildErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SensorCoreBuildErrorV2 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Work(error) => Some(error),
            Self::EmptyDigest(_)
            | Self::InvalidProfile
            | Self::SensorCount
            | Self::DuplicateSensorId(_)
            | Self::SensorDimension
            | Self::SensorCoordinate
            | Self::DuplicateSensorCoordinates
            | Self::SensorSeparation
            | Self::MeshRatio
            | Self::Arithmetic
            | Self::InternalInvariant => None,
        }
    }
}

impl From<OperatorWorkErrorV1> for SensorCoreBuildErrorV2 {
    fn from(value: OperatorWorkErrorV1) -> Self {
        Self::Work(value)
    }
}

pub fn build_sensor_core_v2(
    mut design: SensorCoreDesignV1,
    profile: SensorCoreExecutionProfileV2,
) -> Result<OperatorSensorCoreBuildReceiptV2, SensorCoreBuildErrorV2> {
    for (label, digest) in [
        ("state axis", design.state_axis_digest),
        ("candidate design", design.candidate_design_digest),
        ("sensor seed", design.seed_digest),
    ] {
        if digest.is_zero() {
            return Err(SensorCoreBuildErrorV2::EmptyDigest(label));
        }
    }
    let input_count = design.candidates.len();
    if input_count < 2
        || input_count > MAX_DESIGN_POINTS
        || design.requested_count < 2
        || design.requested_count > MAX_SENSORS
        || design.requested_count > input_count
    {
        return Err(SensorCoreBuildErrorV2::SensorCount);
    }
    if profile.exact_candidate_limit < 2
        || profile.exact_candidate_limit > MAX_DESIGN_POINTS
        || profile.maximum_working_candidates < design.requested_count
        || profile.maximum_working_candidates > MAX_DESIGN_POINTS
    {
        return Err(SensorCoreBuildErrorV2::InvalidProfile);
    }

    let mut meter = OperatorWorkMeter::new(profile.budget)?;
    design
        .candidates
        .sort_by_key(|candidate| candidate.point_id.clone());
    if let Some(adjacent) = design
        .candidates
        .windows(2)
        .find(|pair| pair[0].point_id == pair[1].point_id)
    {
        return Err(SensorCoreBuildErrorV2::DuplicateSensorId(
            adjacent[0].point_id.to_string(),
        ));
    }
    let dimensions = design.candidates[0].coordinates.len();
    if !(1..=MAX_DIMENSIONS).contains(&dimensions) {
        return Err(SensorCoreBuildErrorV2::SensorDimension);
    }

    let mut fingerprints = Vec::with_capacity(input_count);
    let mut coordinate_buckets = BTreeMap::<Digest32, Vec<usize>>::new();
    for (index, candidate) in design.candidates.iter().enumerate() {
        if candidate.coordinates.len() != dimensions
            || candidate
                .coordinates
                .iter()
                .any(|value| !(FixedQ32::ZERO..=FixedQ32::ONE).contains(value))
        {
            return Err(SensorCoreBuildErrorV2::SensorCoordinate);
        }
        let fingerprint = coordinate_fingerprint(candidate)?;
        let bucket = coordinate_buckets.entry(fingerprint).or_default();
        if bucket
            .iter()
            .any(|other| design.candidates[*other].coordinates == candidate.coordinates)
        {
            return Err(SensorCoreBuildErrorV2::DuplicateSensorCoordinates);
        }
        bucket.push(index);
        fingerprints.push((fingerprint, candidate.point_id.clone(), index));
        meter.consume(checked_u64(dimensions)?)?;
    }

    let approximation_applied = input_count > profile.exact_candidate_limit;
    let mut working = if approximation_applied {
        let limit = profile.maximum_working_candidates.min(input_count);
        fingerprints.sort_by(|left, right| {
            left.0
                .cmp(&right.0)
                .then_with(|| left.1.cmp(&right.1))
        });
        let mut reduced = Vec::with_capacity(limit);
        for slot in 0..limit {
            let position = if limit == 1 {
                0
            } else {
                slot.checked_mul(input_count - 1)
                    .ok_or(SensorCoreBuildErrorV2::Arithmetic)?
                    / (limit - 1)
            };
            reduced.push(design.candidates[fingerprints[position].2].clone());
        }
        reduced.sort_by_key(|candidate| candidate.point_id.clone());
        reduced
    } else {
        design.candidates
    };

    if working.len() < design.requested_count {
        return Err(SensorCoreBuildErrorV2::InvalidProfile);
    }
    let working_count = working.len();
    let n = checked_u64(working_count)?;
    let d = checked_u64(dimensions)?;
    let k = checked_u64(design.requested_count)?;
    let fingerprint_work = checked_mul(checked_u64(input_count)?, d)?;
    let initial_distances = checked_mul(n, d)?;
    let per_round = checked_mul(n, checked_add(d, 1)?)?;
    let fps_work = checked_mul(k.saturating_sub(1), per_round)?;
    meter.preflight_operations(checked_add(
        checked_add(fingerprint_work, initial_distances)?,
        fps_work,
    )?)?;
    let coordinate_bytes = checked_mul(
        checked_mul(checked_u64(input_count)?, d)?,
        u64::try_from(std::mem::size_of::<FixedQ32>())
            .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?,
    )?;
    let working_bytes = checked_mul(
        n,
        u64::try_from(
            std::mem::size_of::<SensorPointV1>()
                + std::mem::size_of::<u128>()
                + std::mem::size_of::<bool>(),
        )
        .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?,
    )?;
    meter.reserve_total_bytes(checked_add(coordinate_bytes, working_bytes)?)?;

    // Canonical point-id ordering determines ties on both exact and approximate
    // paths. Approximation changes only the explicit working set above.
    working.sort_by_key(|candidate| candidate.point_id.clone());
    let mut selected_flags = vec![false; working_count];
    let mut selected_indices = vec![0_usize];
    selected_flags[0] = true;
    let mut nearest_squared = Vec::with_capacity(working_count);
    for candidate in &working {
        nearest_squared.push(distance_squared(candidate, &working[0], &mut meter)?);
    }
    let mut minimum_selected_squared = u128::MAX;
    while selected_indices.len() < design.requested_count {
        let mut best: Option<(usize, u128)> = None;
        for (index, distance) in nearest_squared.iter().copied().enumerate() {
            meter.consume(1)?;
            if selected_flags[index] {
                continue;
            }
            if best.is_none_or(|(_, current)| distance > current) {
                best = Some((index, distance));
            }
        }
        let Some((selected_index, selected_distance)) = best else {
            return Err(SensorCoreBuildErrorV2::InternalInvariant);
        };
        if selected_distance == 0 {
            return Err(SensorCoreBuildErrorV2::SensorSeparation);
        }
        minimum_selected_squared = minimum_selected_squared.min(selected_distance);
        selected_flags[selected_index] = true;
        selected_indices.push(selected_index);
        for (index, candidate) in working.iter().enumerate() {
            let distance = distance_squared(candidate, &working[selected_index], &mut meter)?;
            nearest_squared[index] = nearest_squared[index].min(distance);
        }
    }

    let selected_points = selected_indices
        .iter()
        .map(|index| working[*index].clone())
        .collect::<Vec<_>>();
    let fill_distance_raw = integer_sqrt(
        nearest_squared
            .iter()
            .copied()
            .max()
            .ok_or(SensorCoreBuildErrorV2::InternalInvariant)?,
    )?;
    let separation_radius_raw = integer_sqrt(minimum_selected_squared)? / 2;
    if separation_radius_raw == 0 {
        return Err(SensorCoreBuildErrorV2::SensorSeparation);
    }
    let mesh_ratio_raw = fill_distance_raw
        .checked_shl(32)
        .ok_or(SensorCoreBuildErrorV2::Arithmetic)?
        / separation_radius_raw;
    let fill_distance_q32 = fixed_from_u128(fill_distance_raw)?;
    let separation_radius_q32 = fixed_from_u128(separation_radius_raw)?;
    let mesh_ratio_q32 = fixed_from_u128(mesh_ratio_raw)?;
    if mesh_ratio_q32.raw() > 4 * FixedQ32::ONE.raw() {
        return Err(SensorCoreBuildErrorV2::MeshRatio);
    }

    let hull_digest = digest_sensor_points(
        b"hepta.bellman-operator.sensor-hull.v1",
        &selected_points,
    )?;
    let mut manifest_bytes = b"hepta.bellman-operator.sensor-core.v1".to_vec();
    push_id(&mut manifest_bytes, &design.sensor_core_id)?;
    manifest_bytes.extend_from_slice(design.state_axis_digest.as_array());
    manifest_bytes.extend_from_slice(design.candidate_design_digest.as_array());
    manifest_bytes.extend_from_slice(design.seed_digest.as_array());
    manifest_bytes.extend_from_slice(
        &u32::try_from(selected_points.len())
            .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?
            .to_be_bytes(),
    );
    for point in &selected_points {
        push_sensor_point(&mut manifest_bytes, point)?;
    }
    for value in [fill_distance_q32, separation_radius_q32, mesh_ratio_q32] {
        manifest_bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    manifest_bytes.extend_from_slice(hull_digest.as_array());
    let manifest = OperatorSensorCoreManifestV1 {
        sensor_core_id: design.sensor_core_id,
        state_axis_digest: design.state_axis_digest,
        candidate_design_digest: design.candidate_design_digest,
        seed_digest: design.seed_digest,
        selected_points,
        fill_distance_q32,
        separation_radius_q32,
        mesh_ratio_q32,
        hull_digest,
        manifest_digest: Digest32::of_bytes(&manifest_bytes),
        authority: AuthorityPosture::DENY_ALL,
    };
    let work = meter.finish()?;
    let input_candidate_count = u32::try_from(input_count)
        .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?;
    let working_candidate_count = u32::try_from(working_count)
        .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?;
    let mut receipt_bytes = b"hepta.bellman-operator.sensor-core-build.v2\0".to_vec();
    receipt_bytes.extend_from_slice(manifest.manifest_digest.as_array());
    receipt_bytes.extend_from_slice(&input_candidate_count.to_be_bytes());
    receipt_bytes.extend_from_slice(&working_candidate_count.to_be_bytes());
    receipt_bytes.push(u8::from(approximation_applied));
    receipt_bytes.extend_from_slice(&profile.exact_candidate_limit.to_be_bytes());
    receipt_bytes.extend_from_slice(&profile.maximum_working_candidates.to_be_bytes());
    receipt_bytes.extend_from_slice(&profile.budget.max_operations.to_be_bytes());
    receipt_bytes.extend_from_slice(&profile.budget.max_estimated_bytes.to_be_bytes());
    receipt_bytes.extend_from_slice(&profile.budget.max_elapsed_micros.to_be_bytes());
    receipt_bytes.extend_from_slice(&work.operations.to_be_bytes());
    receipt_bytes.extend_from_slice(&work.estimated_bytes.to_be_bytes());
    Ok(OperatorSensorCoreBuildReceiptV2 {
        manifest,
        input_candidate_count,
        working_candidate_count,
        approximation_applied,
        profile,
        work,
        receipt_digest: Digest32::of_bytes(&receipt_bytes),
    })
}

fn coordinate_fingerprint(point: &SensorPointV1) -> Result<Digest32, SensorCoreBuildErrorV2> {
    let mut bytes = b"hepta.bellman-operator.sensor-coordinate.v2\0".to_vec();
    bytes.extend_from_slice(
        &u32::try_from(point.coordinates.len())
            .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?
            .to_be_bytes(),
    );
    for value in &point.coordinates {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn distance_squared(
    left: &SensorPointV1,
    right: &SensorPointV1,
    meter: &mut OperatorWorkMeter,
) -> Result<u128, SensorCoreBuildErrorV2> {
    let mut total = 0_u128;
    for (left, right) in left.coordinates.iter().zip(&right.coordinates) {
        meter.consume(1)?;
        let delta = i128::from(left.raw()) - i128::from(right.raw());
        let magnitude = delta.unsigned_abs();
        total = total
            .checked_add(
                magnitude
                    .checked_mul(magnitude)
                    .ok_or(SensorCoreBuildErrorV2::Arithmetic)?,
            )
            .ok_or(SensorCoreBuildErrorV2::Arithmetic)?;
    }
    Ok(total)
}

fn digest_sensor_points(
    domain: &[u8],
    points: &[SensorPointV1],
) -> Result<Digest32, SensorCoreBuildErrorV2> {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(
        &u32::try_from(points.len())
            .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?
            .to_be_bytes(),
    );
    for point in points {
        push_sensor_point(&mut bytes, point)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_sensor_point(
    bytes: &mut Vec<u8>,
    point: &SensorPointV1,
) -> Result<(), SensorCoreBuildErrorV2> {
    push_id(bytes, &point.point_id)?;
    bytes.extend_from_slice(
        &u32::try_from(point.coordinates.len())
            .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?
            .to_be_bytes(),
    );
    for coordinate in &point.coordinates {
        bytes.extend_from_slice(&coordinate.raw().to_be_bytes());
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), SensorCoreBuildErrorV2> {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

fn integer_sqrt(value: u128) -> Result<u128, SensorCoreBuildErrorV2> {
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
            left = middle
                .checked_add(1)
                .ok_or(SensorCoreBuildErrorV2::Arithmetic)?;
        } else {
            right = middle - 1;
        }
    }
    Ok(right)
}

fn fixed_from_u128(value: u128) -> Result<FixedQ32, SensorCoreBuildErrorV2> {
    let raw = i64::try_from(value).map_err(|_| SensorCoreBuildErrorV2::Arithmetic)?;
    Ok(FixedQ32::from_raw(raw))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn point(name: &str, raw: i64) -> SensorPointV1 {
        SensorPointV1 {
            point_id: id(name),
            coordinates: vec![FixedQ32::from_raw(raw)],
        }
    }

    fn design(count: usize, requested: usize) -> SensorCoreDesignV1 {
        SensorCoreDesignV1 {
            sensor_core_id: id("core"),
            state_axis_digest: digest("axis"),
            candidate_design_digest: digest("design"),
            seed_digest: digest("seed"),
            requested_count: requested,
            candidates: (0..count)
                .map(|index| {
                    let denominator = i64::try_from(count - 1).unwrap();
                    point(
                        &format!("point-{index:05}"),
                        i64::try_from(index).unwrap() * FixedQ32::ONE.raw() / denominator,
                    )
                })
                .collect(),
        }
    }

    #[test]
    fn exact_profile_preserves_canonical_fps() {
        let receipt = build_sensor_core_v2(
            design(3, 2),
            SensorCoreExecutionProfileV2::qualification_default(),
        )
        .unwrap();
        assert!(!receipt.approximation_applied);
        assert_eq!(
            receipt
                .manifest
                .selected_points
                .iter()
                .map(|point| point.point_id.as_str())
                .collect::<Vec<_>>(),
            vec!["point-00000", "point-00002"]
        );
    }

    #[test]
    fn duplicate_coordinates_reject_without_pairwise_scan() {
        let mut value = design(3, 2);
        value.candidates[2].coordinates = value.candidates[1].coordinates.clone();
        assert_eq!(
            build_sensor_core_v2(
                value,
                SensorCoreExecutionProfileV2::qualification_default()
            ),
            Err(SensorCoreBuildErrorV2::DuplicateSensorCoordinates)
        );
    }

    #[test]
    fn large_design_records_deterministic_approximation() {
        let profile = SensorCoreExecutionProfileV2 {
            exact_candidate_limit: 8,
            maximum_working_candidates: 8,
            ..SensorCoreExecutionProfileV2::qualification_default()
        };
        let left = build_sensor_core_v2(design(32, 4), profile).unwrap();
        let right = build_sensor_core_v2(design(32, 4), profile).unwrap();
        assert!(left.approximation_applied);
        assert_eq!(left.manifest, right.manifest);
        assert_eq!(left.receipt_digest, right.receipt_digest);
    }

    #[test]
    fn operation_budget_fails_before_expensive_fps() {
        let profile = SensorCoreExecutionProfileV2 {
            budget: OperatorResourceBudgetV1 {
                max_operations: 8,
                max_estimated_bytes: 1_000_000,
                max_elapsed_micros: 1_000_000,
            },
            ..SensorCoreExecutionProfileV2::qualification_default()
        };
        assert!(matches!(
            build_sensor_core_v2(design(32, 4), profile),
            Err(SensorCoreBuildErrorV2::Work(
                OperatorWorkErrorV1::ResourceExhausted { .. }
            ))
        ));
    }
}
