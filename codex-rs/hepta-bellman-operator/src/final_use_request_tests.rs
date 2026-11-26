//! Request admission rejects values the actual fitter cannot consume.

use super::*;

fn world_request(
    measurements: [FixedQ32; 3],
    outcome: FixedQ32,
) -> Result<WorldModelTrainingRequestV1, FinalUseErrorV1> {
    let id = |name| StableId::new(name).unwrap();
    let digest = Digest32::of_bytes(b"request-fixture");
    world_request_with_samples(
        measurements,
        vec![WorldModelSampleV1 {
            sample_id: id("sample"),
            state_id: id("state"),
            action_id: id("action"),
            next_state_id: id("next-state"),
            outcome,
            evidence_digest: digest,
        }],
    )
}

fn world_request_with_samples(
    measurements: [FixedQ32; 3],
    samples: Vec<WorldModelSampleV1>,
) -> Result<WorldModelTrainingRequestV1, FinalUseErrorV1> {
    let id = |name| StableId::new(name).unwrap();
    let digest = Digest32::of_bytes(b"request-fixture");
    let profile = WorldModelProfileV1::new(
        digest,
        digest,
        /*dataset_generation*/ 1,
        /*minimum_support*/ 1,
        FixedQ32::ONE,
        FixedQ32::ONE,
        ProbabilityQ32::ONE,
        FixedQ32::ONE,
        OperatorResourceBudgetV1::qualification_default(),
    )
    .unwrap();
    WorldModelTrainingRequestV1::new(
        id("model"),
        Generation::new(1).unwrap(),
        profile,
        digest,
        digest,
        digest,
        digest,
        digest,
        /*predecessor_model_digest*/ None,
        measurements[0],
        measurements[1],
        ProbabilityQ32::ZERO,
        measurements[2],
        digest,
        /*retained_until*/ 70,
        /*expires_at*/ 80,
        samples,
    )
}

#[test]
fn negative_measurements_cannot_reach_world_final_use_capability_admission() {
    assert!(world_request([FixedQ32::ONE; 3], FixedQ32::ZERO).is_ok());
    for index in 0..3 {
        let mut measurements = [FixedQ32::ZERO; 3];
        measurements[index] = FixedQ32::from_raw(-1);
        assert!(matches!(
            world_request(measurements, FixedQ32::ZERO),
            Err(FinalUseErrorV1::Binding(
                "world-model measurements outside the unit interval"
            ))
        ));
    }
}

#[test]
fn world_request_rejects_outcomes_the_transition_fitter_cannot_consume() {
    for valid in [-FixedQ32::ONE.raw(), FixedQ32::ONE.raw()] {
        assert!(world_request([FixedQ32::ZERO; 3], FixedQ32::from_raw(valid)).is_ok());
    }
    for invalid in [-FixedQ32::ONE.raw() - 1, FixedQ32::ONE.raw() + 1] {
        assert!(matches!(
            world_request([FixedQ32::ZERO; 3], FixedQ32::from_raw(invalid)),
            Err(FinalUseErrorV1::Binding("invalid world-model sample"))
        ));
    }
}

fn tabular_request(
    sensors: Vec<StableId>,
    actions: Vec<StableId>,
    samples: Vec<TabularOperatorSampleV1>,
    minimum: usize,
) -> Result<TabularTrainingRequestV1, FinalUseErrorV1> {
    let digest = Digest32::of_bytes(b"tabular-request-fixture");
    TabularTrainingRequestV1::new(
        StableId::new("artifact").unwrap(),
        StableId::new("producer").unwrap(),
        Generation::new(1).unwrap(),
        TrainingProfileV1::new(
            digest,
            digest,
            1,
            minimum,
            FixedQ32::ONE,
            OperatorResourceBudgetV1::qualification_default(),
        )
        .unwrap(),
        sensors,
        actions,
        samples,
    )
}

fn tabular_rows(count: usize) -> Vec<TabularOperatorSampleV1> {
    (0..count)
        .map(|index| TabularOperatorSampleV1 {
            sample_id: StableId::new(format!("sample-{index}")).unwrap(),
            sensor_id: StableId::new("sensor-0").unwrap(),
            action_id: StableId::new("action-0").unwrap(),
            target: FixedQ32::ZERO,
            evidence_digest: Digest32::of_bytes(format!("evidence-{index}").as_bytes()),
        })
        .collect()
}

#[test]
fn tabular_constructor_rejects_oversized_or_impossible_signed_profile_before_cloning() {
    let request = |sensors, actions, rows, minimum| {
        tabular_request(
            (0..sensors)
                .map(|i| StableId::new(format!("sensor-{i}")).unwrap())
                .collect(),
            (0..actions)
                .map(|i| StableId::new(format!("action-{i}")).unwrap())
                .collect(),
            tabular_rows(rows),
            minimum,
        )
    };
    for shape in [(4096, 1, 4096, 1), (1, 128, 128, 1), (32, 128, 4096, 1)] {
        assert!(request(shape.0, shape.1, shape.2, shape.3).is_ok());
    }
    for shape in [
        (4097, 1, 4096, 1),
        (1, 129, 129, 1),
        (1, 1, 4097, 1),
        (32, 128, 4096, 2),
    ] {
        assert!(matches!(
            request(shape.0, shape.1, shape.2, shape.3),
            Err(FinalUseErrorV1::Source(OperatorDatasetBindingError::Bounds))
        ));
    }
}

#[test]
fn accepted_requests_do_not_retain_caller_vectors_spare_allocation() {
    let mut sensors = Vec::with_capacity(8192);
    sensors.push(StableId::new("sensor-0").unwrap());
    let mut actions = Vec::with_capacity(8192);
    actions.push(StableId::new("action-0").unwrap());
    let mut samples = Vec::with_capacity(8192);
    samples.extend(tabular_rows(1));
    let tabular = tabular_request(sensors, actions, samples, 1).unwrap();
    assert_eq!(tabular.sensor_ids.capacity(), tabular.sensor_ids.len());
    assert_eq!(tabular.action_ids.capacity(), tabular.action_ids.len());
    assert_eq!(tabular.samples.capacity(), tabular.samples.len());
    let original = world_request([FixedQ32::ZERO; 3], FixedQ32::ZERO).unwrap();
    let mut samples = Vec::with_capacity(8192);
    samples.extend(original.samples);
    let world = world_request_with_samples([FixedQ32::ZERO; 3], samples).unwrap();
    assert_eq!(world.samples.capacity(), world.samples.len());
}
