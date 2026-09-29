use super::*;
use codex_hepta_types::ProbabilityQ32;
use std::time::Instant;

fn profile_id(prefix: &str, index: usize) -> StableId {
    StableId::new(format!("{prefix}-{index}")).unwrap()
}

fn profile_digest(prefix: &str, index: usize) -> Digest32 {
    Digest32::of_bytes(format!("{prefix}-{index}").as_bytes())
}

#[test]
fn offline_integrity_candidate_is_metadata_only() {
    let artifact = fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: StableId::new("offline-integrity-artifact").unwrap(),
        producer_id: StableId::new("offline-integrity-producer").unwrap(),
        generation: Generation::new(1).unwrap(),
        objective_digest: Digest32::of_bytes(b"offline-objective"),
        dataset_digest: Digest32::of_bytes(b"offline-dataset"),
        sensor_core_digest: Digest32::of_bytes(b"offline-sensor"),
        training_profile_digest: Digest32::of_bytes(b"offline-training"),
        minimum_samples_per_cell: 1,
        sensor_ids: vec![StableId::new("offline-state").unwrap()],
        action_ids: vec![StableId::new("offline-action").unwrap()],
        samples: vec![TabularOperatorSampleV1 {
            sample_id: StableId::new("offline-sample").unwrap(),
            sensor_id: StableId::new("offline-state").unwrap(),
            action_id: StableId::new("offline-action").unwrap(),
            target: FixedQ32::from_raw(7),
            evidence_digest: Digest32::of_bytes(b"offline-evidence"),
        }],
    })
    .unwrap();
    let payload = encode_tabular_payload_v1(&artifact).unwrap();
    let pin = TabularPayloadPinV2 {
        artifact_id: artifact.artifact_id.clone(),
        producer_id: artifact.producer_id.clone(),
        artifact_schema_version: TABULAR_ARTIFACT_SCHEMA_V1,
        payload_schema_version: TABULAR_PAYLOAD_SCHEMA_V1,
        payload_digest: Digest32::of_bytes(&payload),
        artifact_digest: artifact.artifact_digest,
        objective_digest: artifact.objective_digest,
        dataset_digest: artifact.dataset_digest,
        sensor_core_digest: artifact.sensor_core_digest,
        training_profile_digest: artifact.training_profile_digest,
        runtime_profile_digest: Digest32::of_bytes(b"offline-runtime"),
        trust_digest: Digest32::of_bytes(b"offline-trust"),
        registry_head_digest: Digest32::of_bytes(b"offline-registry"),
        authority_epoch: 3,
        generation: artifact.generation,
    };
    let verified = verify_offline_tabular_integrity_v1(&payload, &pin).unwrap();
    assert_eq!(verified.artifact_id(), &artifact.artifact_id);
    assert_eq!(verified.artifact_digest(), artifact.artifact_digest);
    assert_eq!(verified.payload_digest(), Digest32::of_bytes(&payload));
    assert_eq!(verified.authority_epoch(), 3);
}

#[test]
#[ignore = "qualification performance profile; executed explicitly by CI"]
fn operator_performance_profile_v1() {
    const SENSOR_COUNT: usize = 64;
    const ACTION_COUNT: usize = 64;
    const LOOKUPS: usize = 100_000;
    const WORLD_GROUPS: usize = 4_096;

    let sensors = (0..SENSOR_COUNT)
        .map(|index| profile_id("sensor", index))
        .collect::<Vec<_>>();
    let actions = (0..ACTION_COUNT)
        .map(|index| profile_id("action", index))
        .collect::<Vec<_>>();
    let mut samples = Vec::with_capacity(SENSOR_COUNT * ACTION_COUNT);
    for (sensor_index, sensor_id) in sensors.iter().enumerate() {
        for (action_index, action_id) in actions.iter().enumerate() {
            let index = sensor_index * ACTION_COUNT + action_index;
            samples.push(TabularOperatorSampleV1 {
                sample_id: profile_id("sample", index),
                sensor_id: sensor_id.clone(),
                action_id: action_id.clone(),
                target: FixedQ32::from_raw(i64::try_from(index % 1_024).unwrap()),
                evidence_digest: profile_digest("tabular-evidence", index),
            });
        }
    }

    let fit_started = Instant::now();
    let artifact = fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: StableId::new("profile-tabular").unwrap(),
        producer_id: StableId::new("profile-producer").unwrap(),
        generation: Generation::new(2).unwrap(),
        objective_digest: Digest32::of_bytes(b"profile-objective"),
        dataset_digest: Digest32::of_bytes(b"profile-dataset"),
        sensor_core_digest: Digest32::of_bytes(b"profile-sensor-core"),
        training_profile_digest: Digest32::of_bytes(b"profile-training"),
        minimum_samples_per_cell: 1,
        sensor_ids: sensors.clone(),
        action_ids: actions.clone(),
        samples,
    })
    .unwrap();
    let fit_micros = fit_started.elapsed().as_micros();

    let encode_started = Instant::now();
    let payload = encode_tabular_payload_v1(&artifact).unwrap();
    let encode_micros = encode_started.elapsed().as_micros();
    let pin = TabularPayloadPinV2 {
        artifact_id: artifact.artifact_id.clone(),
        producer_id: artifact.producer_id.clone(),
        artifact_schema_version: TABULAR_ARTIFACT_SCHEMA_V1,
        payload_schema_version: TABULAR_PAYLOAD_SCHEMA_V1,
        payload_digest: Digest32::of_bytes(&payload),
        artifact_digest: artifact.artifact_digest,
        objective_digest: artifact.objective_digest,
        dataset_digest: artifact.dataset_digest,
        sensor_core_digest: artifact.sensor_core_digest,
        training_profile_digest: artifact.training_profile_digest,
        runtime_profile_digest: Digest32::of_bytes(b"profile-runtime"),
        trust_digest: Digest32::of_bytes(b"profile-trust"),
        registry_head_digest: Digest32::of_bytes(b"profile-registry"),
        authority_epoch: 7,
        generation: artifact.generation,
    };
    let decode_started = Instant::now();
    let loaded = LoadedTabularOperatorV2::from_pinned_payload_v2(&payload, &pin).unwrap();
    let decode_micros = decode_started.elapsed().as_micros();

    let lookup_started = Instant::now();
    for index in 0..LOOKUPS {
        let sensor = &sensors[index % SENSOR_COUNT];
        let action = &actions[(index / SENSOR_COUNT) % ACTION_COUNT];
        std::hint::black_box(loaded.predict(sensor, action).unwrap());
    }
    let lookup_micros = lookup_started.elapsed().as_micros();

    let world_action = StableId::new("world-action").unwrap();
    let mut world_samples = Vec::with_capacity(WORLD_GROUPS * 2);
    for index in 0..WORLD_GROUPS {
        for branch in 0..2 {
            let sample_index = index * 2 + branch;
            world_samples.push(WorldModelSampleV1 {
                sample_id: profile_id("world-sample", sample_index),
                state_id: profile_id("world-state", index),
                action_id: world_action.clone(),
                next_state_id: profile_id("world-next", branch),
                outcome: FixedQ32::from_raw(i64::try_from(branch).unwrap()),
                evidence_digest: profile_digest("world-evidence", sample_index),
            });
        }
    }
    let world_started = Instant::now();
    let world = fit_world_model_v2(
        WorldModelPlanV2 {
            model_id: StableId::new("profile-world-model").unwrap(),
            generation: Generation::new(2).unwrap(),
            objective_digest: Digest32::of_bytes(b"profile-objective"),
            dataset_digest: Digest32::of_bytes(b"profile-world-dataset"),
            training_profile_digest: Digest32::of_bytes(b"profile-world-training"),
            runtime_profile_digest: Digest32::of_bytes(b"profile-world-runtime"),
            trust_digest: Digest32::of_bytes(b"profile-world-trust"),
            registry_head_digest: Digest32::of_bytes(b"profile-world-registry"),
            row_commitment_root: Digest32::of_bytes(b"profile-world-rows"),
            train_window_digest: Digest32::of_bytes(b"profile-train-window"),
            holdout_window_digest: Digest32::of_bytes(b"profile-holdout-window"),
            future_window_digest: Digest32::of_bytes(b"profile-future-window"),
            predecessor_model_digest: Some(Digest32::of_bytes(b"profile-world-predecessor")),
            authority_epoch: 7,
            minimum_support: 2,
            one_step_calibration_error: FixedQ32::ZERO,
            multistep_calibration_error: FixedQ32::ZERO,
            ood_false_acceptance: ProbabilityQ32::from_raw(0).unwrap(),
            drift_score: FixedQ32::ZERO,
            change_point_digest: Digest32::of_bytes(b"profile-change-point"),
            retained_until: 200,
            expires_at: 300,
            samples: world_samples,
        },
        OperatorResourceBudgetV1::qualification_default(),
    )
    .unwrap();
    let world_fit_micros = world_started.elapsed().as_micros();
    let world_pin = WorldModelUsePinV2 {
        runtime_profile_digest: world.runtime_profile_digest,
        trust_digest: world.trust_digest,
        registry_head_digest: world.registry_head_digest,
        minimum_authority_epoch: world.authority_epoch,
        expected_predecessor_model_digest: world.predecessor_model_digest,
    };
    let world_lookup_started = Instant::now();
    for index in 0..LOOKUPS {
        let state = profile_id("world-state", index % WORLD_GROUPS);
        std::hint::black_box(
            predict_world_model_v2(&world, &state, &world_action, &world_pin, 100).unwrap(),
        );
    }
    let world_lookup_micros = world_lookup_started.elapsed().as_micros();

    println!(
        concat!(
            "learning-operator-profile:{{",
            "\"sensor_count\":{},",
            "\"action_count\":{},",
            "\"tabular_cells\":{},",
            "\"payload_bytes\":{},",
            "\"tabular_fit_micros\":{},",
            "\"encode_micros\":{},",
            "\"decode_micros\":{},",
            "\"batch_lookups\":{},",
            "\"batch_lookup_micros\":{},",
            "\"world_groups\":{},",
            "\"world_estimated_bytes\":{},",
            "\"world_fit_micros\":{},",
            "\"world_lookup_micros\":{}",
            "}}"
        ),
        SENSOR_COUNT,
        ACTION_COUNT,
        artifact.cells.len(),
        payload.len(),
        fit_micros,
        encode_micros,
        decode_micros,
        LOOKUPS,
        lookup_micros,
        world.estimates.len(),
        world.work.estimated_bytes,
        world_fit_micros,
        world_lookup_micros,
    );
}
