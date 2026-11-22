use codex_hepta_bellman_operator::ControlledSensorCoreError;
use codex_hepta_bellman_operator::OperatorClosureError;
use codex_hepta_bellman_operator::SensorCoreDesignV1;
use codex_hepta_bellman_operator::SensorPointV1;
use codex_hepta_bellman_operator::WorkControlError;
use codex_hepta_bellman_operator::WorkControlV1;
use codex_hepta_bellman_operator::build_sensor_core;
use codex_hepta_bellman_operator::build_sensor_core_controlled_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

type TestResult<T> = Result<T, Box<dyn std::error::Error>>;

fn design() -> TestResult<SensorCoreDesignV1> {
    Ok(SensorCoreDesignV1 {
        sensor_core_id: StableId::new("controlled-sensor-core")?,
        state_axis_digest: Digest32::of_bytes(b"axis"),
        candidate_design_digest: Digest32::of_bytes(b"design"),
        seed_digest: Digest32::of_bytes(b"seed"),
        requested_count: 2,
        candidates: [0, FixedQ32::ONE.raw() / 2, FixedQ32::ONE.raw()]
            .into_iter()
            .enumerate()
            .map(|(index, raw)| {
                Ok(SensorPointV1 {
                    point_id: StableId::new(format!("point-{index}"))?,
                    coordinates: vec![FixedQ32::from_raw(raw)],
                })
            })
            .collect::<TestResult<Vec<_>>>()?,
    })
}

#[test]
fn controlled_selection_matches_reference_geometry_and_is_order_independent() -> TestResult<()> {
    let original = design()?;
    let reference = build_sensor_core(original.clone())?;
    let (control, _) = WorkControlV1::new(10_000, 10_000)?;
    let actual = build_sensor_core_controlled_v2(original.clone(), &control)?;
    assert_eq!(actual.selected_points, reference.selected_points);
    assert_eq!(
        actual.fill_distance_q32,
        FixedQ32::from_raw(FixedQ32::ONE.raw() / 2)
    );
    assert_eq!(
        actual.separation_radius_q32,
        reference.separation_radius_q32
    );
    assert_eq!(actual.mesh_ratio_q32, FixedQ32::ONE);
    assert!(!actual.authority.grants_any());
    assert!(!actual.manifest_digest.is_zero());
    let mut reversed = original;
    reversed.candidates.reverse();
    assert_eq!(build_sensor_core_controlled_v2(reversed, &control)?, actual);
    Ok(())
}

#[test]
fn controlled_selection_enforces_work_budget_before_returning_a_manifest() -> TestResult<()> {
    let (control, _) = WorkControlV1::new(10_000, 1)?;
    assert_eq!(
        build_sensor_core_controlled_v2(design()?, &control),
        Err(ControlledSensorCoreError::WorkControl(
            WorkControlError::OperationBudgetExceeded
        ))
    );
    Ok(())
}

#[test]
fn controlled_selection_rejects_ambiguous_and_out_of_domain_designs() -> TestResult<()> {
    let (control, _) = WorkControlV1::new(10_000, 10_000)?;
    let mut duplicate_id = design()?;
    duplicate_id.candidates[1].point_id = duplicate_id.candidates[0].point_id.clone();
    assert!(matches!(
        build_sensor_core_controlled_v2(duplicate_id, &control),
        Err(ControlledSensorCoreError::Operator(
            OperatorClosureError::DuplicateSensorId(_)
        ))
    ));
    let mut outside = design()?;
    outside.candidates[0].coordinates[0] = FixedQ32::from_raw(-1);
    assert_eq!(
        build_sensor_core_controlled_v2(outside, &control),
        Err(ControlledSensorCoreError::Operator(
            OperatorClosureError::SensorCoordinate
        ))
    );
    let mut unbound = design()?;
    unbound.state_axis_digest = Digest32::ZERO;
    assert!(matches!(
        build_sensor_core_controlled_v2(unbound, &control),
        Err(ControlledSensorCoreError::Operator(
            OperatorClosureError::EmptyDigest(_)
        ))
    ));
    Ok(())
}
