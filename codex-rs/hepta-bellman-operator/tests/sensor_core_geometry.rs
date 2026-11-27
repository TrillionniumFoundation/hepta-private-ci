use std::error::Error;

use codex_hepta_bellman_operator::ControlledSensorCoreError;
use codex_hepta_bellman_operator::OperatorClosureError;
use codex_hepta_bellman_operator::SensorCoreDesignV1;
use codex_hepta_bellman_operator::SensorPointV1;
use codex_hepta_bellman_operator::WorkControlError;
use codex_hepta_bellman_operator::WorkControlV1;
use codex_hepta_bellman_operator::build_sensor_core_controlled_v2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

fn line_design() -> Result<SensorCoreDesignV1, Box<dyn Error>> {
    let mut candidates = Vec::new();
    for (position, name) in (0_i64..).zip(["a", "b", "c", "d", "e"]) {
        candidates.push(SensorPointV1 {
            point_id: StableId::new(name)?,
            coordinates: vec![FixedQ32::from_raw(position * (FixedQ32::ONE.raw() / 4))],
        });
    }
    Ok(SensorCoreDesignV1 {
        sensor_core_id: StableId::new("line")?,
        state_axis_digest: Digest32::of_bytes(b"axis"),
        candidate_design_digest: Digest32::of_bytes(b"five equally spaced points"),
        seed_digest: Digest32::of_bytes(b"seed"),
        requested_count: 3,
        candidates,
    })
}

#[test]
fn farthest_points_reproduce_the_line_geometry_under_permutation() -> Result<(), Box<dyn Error>> {
    let (control, _) = WorkControlV1::new(1_000, 1_000)?;
    let mut design = line_design()?;
    let original = build_sensor_core_controlled_v2(design.clone(), &control)?;
    let selected: Vec<_> = original
        .selected_points
        .iter()
        .map(|p| p.point_id.as_str())
        .collect();
    // The seed starts at the midpoint. Equal endpoint distances use sorted point IDs.
    assert_eq!(selected, ["c", "a", "e"]);
    let quarter = FixedQ32::from_raw(FixedQ32::ONE.raw() / 4);
    assert_eq!(original.fill_distance_q32, quarter);
    assert_eq!(original.separation_radius_q32, quarter);
    assert_eq!(original.mesh_ratio_q32, FixedQ32::ONE);
    assert_eq!(original.authority, AuthorityPosture::DENY_ALL);
    assert!(!original.hull_digest.is_zero());
    assert!(!original.manifest_digest.is_zero());

    design.candidates.reverse();
    assert_eq!(build_sensor_core_controlled_v2(design, &control)?, original);
    Ok(())
}

#[test]
fn malformed_designs_return_the_expected_geometry_errors() -> Result<(), Box<dyn Error>> {
    let (control, _) = WorkControlV1::new(1_000, 1_000)?;
    let design = line_design()?;
    let reject = |d, reason| {
        assert_eq!(
            build_sensor_core_controlled_v2(d, &control),
            Err(ControlledSensorCoreError::Operator(reason)),
        );
    };
    let mut bad = design.clone();
    bad.requested_count = bad.candidates.len() + 1;
    reject(bad, OperatorClosureError::SensorCount);
    let mut bad = design.clone();
    bad.candidates[1].point_id = bad.candidates[0].point_id.clone();
    reject(bad, OperatorClosureError::DuplicateSensorId("a".into()));
    let mut bad = design.clone();
    bad.candidates[0].coordinates.clear();
    reject(bad, OperatorClosureError::SensorDimension);
    let mut bad = design.clone();
    bad.candidates[1].coordinates.push(FixedQ32::ZERO);
    reject(bad, OperatorClosureError::SensorCoordinate);
    let mut bad = design.clone();
    bad.candidates[1].coordinates[0] = FixedQ32::from_raw(-1);
    reject(bad, OperatorClosureError::SensorCoordinate);
    let mut nearly_coincident = design;
    nearly_coincident.candidates.truncate(2);
    nearly_coincident.requested_count = 2;
    nearly_coincident.candidates[1].coordinates[0] = FixedQ32::from_raw(1);
    reject(nearly_coincident, OperatorClosureError::SensorSeparation);
    Ok(())
}

#[test]
fn candidate_scan_consumes_the_supplied_operation_budget() -> Result<(), Box<dyn Error>> {
    let mut design = line_design()?;
    design.candidates.clear();
    for index in 0_i64..513 {
        design.candidates.push(SensorPointV1 {
            point_id: StableId::new(format!("sensor-{index}"))?,
            coordinates: vec![FixedQ32::from_raw(index)],
        });
    }
    let (control, _) = WorkControlV1::new(1_000, 511)?;
    assert_eq!(
        build_sensor_core_controlled_v2(design, &control),
        Err(ControlledSensorCoreError::WorkControl(
            WorkControlError::OperationBudgetExceeded
        )),
    );
    Ok(())
}
