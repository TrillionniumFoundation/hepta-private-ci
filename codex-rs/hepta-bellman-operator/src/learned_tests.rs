use super::*;

fn id(value: &str) -> StableId {
    match StableId::new(value.to_owned()) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id {value}: {error}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    match Generation::new(value) {
        Ok(value) => value,
        Err(error) => panic!("invalid test generation {value}: {error}"),
    }
}

fn sample(name: &str, sensor: &str, action: &str, target: i64) -> TabularOperatorSampleV1 {
    TabularOperatorSampleV1 {
        sample_id: id(name),
        sensor_id: id(sensor),
        action_id: id(action),
        target: FixedQ32::from_raw(target),
        evidence_digest: digest(&format!("evidence-{name}")),
    }
}

fn plan(samples: Vec<TabularOperatorSampleV1>) -> TabularOperatorPlanV1 {
    TabularOperatorPlanV1 {
        artifact_id: id("operator-artifact"),
        producer_id: id("operator-trainer"),
        generation: generation(2),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        sensor_core_digest: digest("sensor-core"),
        training_profile_digest: digest("tabular-mean-ties-even"),
        minimum_samples_per_cell: 2,
        sensor_ids: vec![id("sensor-b"), id("sensor-a")],
        action_ids: vec![id("action-b"), id("action-a")],
        samples,
    }
}

#[test]
fn op_05_tabular_operator_fits_complete_grid_deterministically() {
    let samples = vec![
        sample("s8", "sensor-b", "action-b", 41),
        sample("s1", "sensor-a", "action-a", 10),
        sample("s4", "sensor-a", "action-b", 21),
        sample("s6", "sensor-b", "action-a", 31),
        sample("s2", "sensor-a", "action-a", 20),
        sample("s3", "sensor-a", "action-b", 19),
        sample("s5", "sensor-b", "action-a", 29),
        sample("s7", "sensor-b", "action-b", 39),
    ];
    let artifact = match fit_tabular_operator(plan(samples.clone())) {
        Ok(artifact) => artifact,
        Err(error) => panic!("valid tabular operator fit failed: {error}"),
    };
    assert_eq!(artifact.cells.len(), 4);
    assert_eq!(artifact.cells[0].sensor_id, id("sensor-a"));
    assert_eq!(artifact.cells[0].action_id, id("action-a"));
    assert_eq!(artifact.cells[0].mean_target, FixedQ32::from_raw(15));
    assert_eq!(artifact.cells[3].mean_target, FixedQ32::from_raw(40));
    assert!(!artifact.artifact_digest.is_zero());
    assert!(!artifact.authority.grants_any());

    let mut reordered = samples;
    reordered.reverse();
    let reordered = match fit_tabular_operator(plan(reordered)) {
        Ok(artifact) => artifact,
        Err(error) => panic!("reordered tabular operator fit failed: {error}"),
    };
    assert_eq!(reordered, artifact);
}

#[test]
fn op_05_tabular_operator_rejects_missing_or_underfilled_cells() {
    let missing = vec![
        sample("s1", "sensor-a", "action-a", 10),
        sample("s2", "sensor-a", "action-a", 20),
        sample("s3", "sensor-a", "action-b", 10),
        sample("s4", "sensor-a", "action-b", 20),
        sample("s5", "sensor-b", "action-a", 10),
        sample("s6", "sensor-b", "action-a", 20),
    ];
    assert_eq!(
        fit_tabular_operator(plan(missing)),
        Err(LearnedOperatorError::MissingCell {
            sensor: "sensor-b".to_owned(),
            action: "action-b".to_owned(),
        })
    );

    let underfilled = vec![
        sample("s1", "sensor-a", "action-a", 10),
        sample("s2", "sensor-a", "action-a", 20),
        sample("s3", "sensor-a", "action-b", 10),
        sample("s4", "sensor-a", "action-b", 20),
        sample("s5", "sensor-b", "action-a", 10),
        sample("s6", "sensor-b", "action-a", 20),
        sample("s7", "sensor-b", "action-b", 10),
    ];
    assert_eq!(
        fit_tabular_operator(plan(underfilled)),
        Err(LearnedOperatorError::InsufficientCellSamples {
            sensor: "sensor-b".to_owned(),
            action: "action-b".to_owned(),
        })
    );
}

#[test]
fn op_05_tabular_prediction_is_synthetic_and_domain_bounded() {
    let samples = vec![
        sample("s1", "sensor-a", "action-a", 10),
        sample("s2", "sensor-a", "action-a", 20),
        sample("s3", "sensor-a", "action-b", 10),
        sample("s4", "sensor-a", "action-b", 20),
        sample("s5", "sensor-b", "action-a", 10),
        sample("s6", "sensor-b", "action-a", 20),
        sample("s7", "sensor-b", "action-b", 10),
        sample("s8", "sensor-b", "action-b", 20),
    ];
    let artifact = match fit_tabular_operator(plan(samples)) {
        Ok(artifact) => artifact,
        Err(error) => panic!("valid tabular operator fit failed: {error}"),
    };
    let prediction = match predict_tabular_operator(&artifact, &id("sensor-a"), &id("action-a")) {
        Ok(prediction) => prediction,
        Err(error) => panic!("supported tabular prediction failed: {error}"),
    };
    assert_eq!(prediction.value, FixedQ32::from_raw(15));
    assert!(prediction.learned);
    assert!(prediction.synthetic);
    assert!(!prediction.authority.grants_any());
    assert_eq!(
        predict_tabular_operator(&artifact, &id("sensor-unknown"), &id("action-a")),
        Err(LearnedOperatorError::UnsupportedCell)
    );
}
