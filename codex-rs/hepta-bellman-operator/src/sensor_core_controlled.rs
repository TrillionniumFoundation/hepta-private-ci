use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

use crate::OperatorClosureError;
use crate::OperatorSensorCoreManifestV1;
use crate::SensorCoreDesignV1;
use crate::SensorPointV1;
use crate::WorkControlError;
use crate::WorkControlV1;

const MAX_DESIGN_POINTS: usize = 16_384;
const MAX_DIMENSIONS: usize = 32;
const MAX_SENSORS: usize = 4_096;
const CHECKPOINT_INTERVAL: u64 = 512;

/// Controlled deterministic farthest-point construction for qualification-scale
/// sensor cores. Coordinate uniqueness is O(n log n), and all large scans are
/// bounded by the supplied work capability.
pub fn build_sensor_core_controlled_v2(
    mut design: SensorCoreDesignV1,
    control: &WorkControlV1,
) -> Result<OperatorSensorCoreManifestV1, ControlledSensorCoreError> {
    control.checkpoint(0)?;
    for digest in [
        design.state_axis_digest,
        design.candidate_design_digest,
        design.seed_digest,
    ] {
        if digest.is_zero() {
            return Err(OperatorClosureError::EmptyDigest("sensor-core identity").into());
        }
    }
    if design.candidates.len() < 2
        || design.candidates.len() > MAX_DESIGN_POINTS
        || design.requested_count < 2
        || design.requested_count > MAX_SENSORS
        || design.requested_count > design.candidates.len()
    {
        return Err(OperatorClosureError::SensorCount.into());
    }
    design
        .candidates
        .sort_by_key(|candidate| candidate.point_id.clone());
    if let Some(adjacent) = design
        .candidates
        .windows(2)
        .find(|adjacent| adjacent[0].point_id == adjacent[1].point_id)
    {
        return Err(OperatorClosureError::DuplicateSensorId(
            adjacent[0].point_id.to_string(),
        )
        .into());
    }
    let dimensions = design.candidates[0].coordinates.len();
    if !(1..=MAX_DIMENSIONS).contains(&dimensions) {
        return Err(OperatorClosureError::SensorDimension.into());
    }

    let mut operations = 0_u64;
    let mut coordinate_keys = BTreeSet::new();
    for candidate in &design.candidates {
        checkpoint_increment(control, &mut operations)?;
        if candidate.coordinates.len() != dimensions
            || candidate
                .coordinates
                .iter()
                .any(|coordinate| !(FixedQ32::ZERO..=FixedQ32::ONE).contains(coordinate))
        {
            return Err(OperatorClosureError::SensorCoordinate.into());
        }
        let key = candidate
            .coordinates
            .iter()
            .map(|coordinate| coordinate.raw())
            .collect::<Vec<_>>();
        if !coordinate_keys.insert(key) {
            return Err(OperatorClosureError::DuplicateSensorCoordinates.into());
        }
    }

    let seed_bytes: [u8; 8] = design.seed_digest.as_array()[..8]
        .try_into()
        .map_err(|_| OperatorClosureError::InternalInvariant)?;
    let first_index = usize::try_from(u64::from_be_bytes(seed_bytes))
        .map_err(|_| OperatorClosureError::Arithmetic)?
        % design.candidates.len();
    let mut selected_flags = vec![false; design.candidates.len()];
    let mut selected_indices = vec![first_index];
    selected_flags[first_index] = true;
    let mut nearest_squared = Vec::with_capacity(design.candidates.len());
    for candidate in &design.candidates {
        checkpoint_increment(control, &mut operations)?;
        nearest_squared.push(distance_squared(
            candidate,
            &design.candidates[first_index],
        )?);
    }

    while selected_indices.len() < design.requested_count {
        control.checkpoint(operations)?;
        let mut best: Option<(usize, u128)> = None;
        for (index, distance) in nearest_squared.iter().copied().enumerate() {
            checkpoint_increment(control, &mut operations)?;
            if selected_flags[index] {
                continue;
            }
            if best.is_none_or(|(_, best_distance)| distance > best_distance) {
                best = Some((index, distance));
            }
        }
        let Some((selected_index, _)) = best else {
            return Err(OperatorClosureError::InternalInvariant.into());
        };
        selected_flags[selected_index] = true;
        selected_indices.push(selected_index);
        for (index, candidate) in design.candidates.iter().enumerate() {
            checkpoint_increment(control, &mut operations)?;
            if selected_flags[index] {
                nearest_squared[index] = 0;
                continue;
            }
            let distance = distance_squared(candidate, &design.candidates[selected_index])?;
            nearest_squared[index] = nearest_squared[index].min(distance);
        }
    }

    let selected_points = selected_indices
        .iter()
        .map(|index| design.candidates[*index].clone())
        .collect::<Vec<_>>();
    let fill_distance_raw = integer_sqrt(
        nearest_squared
            .iter()
            .copied()
            .max()
            .ok_or(OperatorClosureError::InternalInvariant)?,
    )?;
    let mut minimum_separation_squared = u128::MAX;
    for left in 0..selected_points.len() {
        for right in left + 1..selected_points.len() {
            checkpoint_increment(control, &mut operations)?;
            minimum_separation_squared = minimum_separation_squared.min(distance_squared(
                &selected_points[left],
                &selected_points[right],
            )?);
        }
    }
    control.checkpoint(operations)?;
    let separation_radius_raw = integer_sqrt(minimum_separation_squared)? / 2;
    if separation_radius_raw == 0 {
        return Err(OperatorClosureError::SensorSeparation.into());
    }
    let mesh_ratio_raw = fill_distance_raw
        .checked_shl(32)
        .ok_or(OperatorClosureError::Arithmetic)?
        / separation_radius_raw;
    let fill_distance_q32 = fixed_from_u128(fill_distance_raw)?;
    let separation_radius_q32 = fixed_from_u128(separation_radius_raw)?;
    let mesh_ratio_q32 = fixed_from_u128(mesh_ratio_raw)?;
    if mesh_ratio_q32.raw() > 4 * FixedQ32::ONE.raw() {
        return Err(OperatorClosureError::MeshRatio.into());
    }

    let hull_digest = digest_sensor_points(
        b"hepta.bellman-operator.sensor-hull.v2",
        &selected_points,
    )?;
    let mut bytes = b"hepta.bellman-operator.sensor-core.v2".to_vec();
    push_id(&mut bytes, design.sensor_core_id.as_str())?;
    bytes.extend_from_slice(design.state_axis_digest.as_array());
    bytes.extend_from_slice(design.candidate_design_digest.as_array());
    bytes.extend_from_slice(design.seed_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(selected_points.len())
            .map_err(|_| OperatorClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for point in &selected_points {
        push_sensor_point(&mut bytes, point)?;
    }
    for value in [fill_distance_q32, separation_radius_q32, mesh_ratio_q32] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(hull_digest.as_array());
    Ok(OperatorSensorCoreManifestV1 {
        sensor_core_id: design.sensor_core_id,
        state_axis_digest: design.state_axis_digest,
        candidate_design_digest: design.candidate_design_digest,
        seed_digest: design.seed_digest,
        selected_points,
        fill_distance_q32,
        separation_radius_q32,
        mesh_ratio_q32,
        hull_digest,
        manifest_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlledSensorCoreError {
    Operator(OperatorClosureError),
    WorkControl(WorkControlError),
}

impl fmt::Display for ControlledSensorCoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ControlledSensorCoreError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Operator(error) => Some(error),
            Self::WorkControl(error) => Some(error),
        }
    }
}

impl From<OperatorClosureError> for ControlledSensorCoreError {
    fn from(value: OperatorClosureError) -> Self {
        Self::Operator(value)
    }
}

impl From<WorkControlError> for ControlledSensorCoreError {
    fn from(value: WorkControlError) -> Self {
        Self::WorkControl(value)
    }
}

fn checkpoint_increment(
    control: &WorkControlV1,
    operations: &mut u64,
) -> Result<(), ControlledSensorCoreError> {
    *operations = operations
        .checked_add(1)
        .ok_or(OperatorClosureError::Arithmetic)?;
    if *operations % CHECKPOINT_INTERVAL == 0 {
        control.checkpoint(*operations)?;
    }
    Ok(())
}

fn distance_squared(
    left: &SensorPointV1,
    right: &SensorPointV1,
) -> Result<u128, OperatorClosureError> {
    if left.coordinates.len() != right.coordinates.len() {
        return Err(OperatorClosureError::SensorDimension);
    }
    left.coordinates
        .iter()
        .zip(&right.coordinates)
        .try_fold(0_u128, |sum, (left, right)| {
            let delta = i128::from(left.raw()) - i128::from(right.raw());
            let magnitude = delta.unsigned_abs();
            sum.checked_add(
                magnitude
                    .checked_mul(magnitude)
                    .ok_or(OperatorClosureError::Arithmetic)?,
            )
            .ok_or(OperatorClosureError::Arithmetic)
        })
}

fn integer_sqrt(value: u128) -> Result<u128, OperatorClosureError> {
    if value == u128::MAX {
        return Err(OperatorClosureError::InternalInvariant);
    }
    Ok(value.isqrt())
}

fn fixed_from_u128(value: u128) -> Result<FixedQ32, OperatorClosureError> {
    Ok(FixedQ32::from_raw(
        i64::try_from(value).map_err(|_| OperatorClosureError::Arithmetic)?,
    ))
}

fn digest_sensor_points(
    domain: &[u8],
    points: &[SensorPointV1],
) -> Result<Digest32, OperatorClosureError> {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(
        &u32::try_from(points.len())
            .map_err(|_| OperatorClosureError::Arithmetic)?
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
) -> Result<(), OperatorClosureError> {
    push_id(bytes, point.point_id.as_str())?;
    bytes.extend_from_slice(
        &u32::try_from(point.coordinates.len())
            .map_err(|_| OperatorClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for coordinate in &point.coordinates {
        bytes.extend_from_slice(&coordinate.raw().to_be_bytes());
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &str) -> Result<(), OperatorClosureError> {
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .map_err(|_| OperatorClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::StableId;

    fn point(name: &str, x: i64, y: i64) -> SensorPointV1 {
        SensorPointV1 {
            point_id: StableId::new(name).unwrap(),
            coordinates: vec![FixedQ32::from_raw(x), FixedQ32::from_raw(y)],
        }
    }

    #[test]
    fn duplicate_coordinates_fail_before_quadratic_selection() {
        let design = SensorCoreDesignV1 {
            sensor_core_id: StableId::new("core").unwrap(),
            state_axis_digest: Digest32::of_bytes(b"axis"),
            candidate_design_digest: Digest32::of_bytes(b"design"),
            seed_digest: Digest32::of_bytes(b"seed"),
            requested_count: 2,
            candidates: vec![point("a", 1, 1), point("b", 1, 1)],
        };
        let (control, _) = WorkControlV1::new(1_000, 100).unwrap();
        assert!(matches!(
            build_sensor_core_controlled_v2(design, &control),
            Err(ControlledSensorCoreError::Operator(
                OperatorClosureError::DuplicateSensorCoordinates
            ))
        ));
    }

    #[test]
    fn cancellation_is_observed_during_candidate_scans() {
        let design = SensorCoreDesignV1 {
            sensor_core_id: StableId::new("core").unwrap(),
            state_axis_digest: Digest32::of_bytes(b"axis"),
            candidate_design_digest: Digest32::of_bytes(b"design"),
            seed_digest: Digest32::of_bytes(b"seed"),
            requested_count: 2,
            candidates: vec![
                point("a", 0, 0),
                point("b", FixedQ32::ONE.raw(), 0),
                point("c", 0, FixedQ32::ONE.raw()),
            ],
        };
        let (control, cancellation) = WorkControlV1::new(1_000, 1_000).unwrap();
        cancellation.cancel();
        assert!(matches!(
            build_sensor_core_controlled_v2(design, &control),
            Err(ControlledSensorCoreError::WorkControl(
                WorkControlError::Cancelled
            ))
        ));
    }
}
