use super::*;
use crate::TabularOperatorPlanV1;
use crate::TabularOperatorSampleV1;
use crate::fit_tabular_operator_strict_v2;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Write;
use std::process::Command;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn id(text: &str) -> StableId {
    StableId::new(text).expect("fixture identity")
}
fn hash(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}
fn fitted(generation: u64, target: i64) -> TabularOperatorArtifactV1 {
    fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: id(&format!("operator-{generation}")),
        producer_id: id("trainer"),
        generation: Generation::new(generation).expect("generation"),
        objective_digest: hash("fixed-objective"),
        dataset_digest: hash(&format!("dataset-{generation}")),
        sensor_core_digest: hash("sensor-core"),
        training_profile_digest: hash("tabular"),
        minimum_samples_per_cell: 2,
        sensor_ids: vec![id("state")],
        action_ids: vec![id("read")],
        samples: vec![
            TabularOperatorSampleV1 {
                sample_id: id("observation-a"),
                sensor_id: id("state"),
                action_id: id("read"),
                target: FixedQ32::from_raw(target - 2),
                evidence_digest: hash("independent-a"),
            },
            TabularOperatorSampleV1 {
                sample_id: id("observation-b"),
                sensor_id: id("state"),
                action_id: id("read"),
                target: FixedQ32::from_raw(target + 2),
                evidence_digest: hash("independent-b"),
            },
        ],
    })
    .expect("actual strict tabular fit")
}
fn pin(artifact: &TabularOperatorArtifactV1, bytes: &[u8]) -> TabularPayloadPinV1 {
    TabularPayloadPinV1 {
        payload_digest: Digest32::of_bytes(bytes),
        artifact_digest: artifact.artifact_digest,
        objective_digest: artifact.objective_digest,
        dataset_digest: artifact.dataset_digest,
        sensor_core_digest: artifact.sensor_core_digest,
        training_profile_digest: artifact.training_profile_digest,
        generation: artifact.generation,
    }
}

#[test]
fn actual_fit_serializes_and_predicts_with_no_mutable_loaded_surface() {
    let artifact = fitted(2, 7);
    let bytes = encode_tabular_payload_v1(&artifact).expect("encode");
    let loaded = LoadedTabularOperatorV1::from_pinned_payload(&bytes, &pin(&artifact, &bytes))
        .expect("admit");
    let prediction = loaded.predict(&id("state"), &id("read")).expect("predict");
    assert_eq!(prediction.value.raw(), 7);
    assert!(prediction.synthetic);
    assert!(prediction.learned);
    assert!(!prediction.authority.grants_any());
    assert_eq!(
        loaded.predict(&id("unknown"), &id("read")),
        Err(TabularPayloadError::UnsupportedCell)
    );
}

#[test]
fn independent_pin_and_all_truncations_are_checked() {
    let artifact = fitted(2, 7);
    let bytes = encode_tabular_payload_v1(&artifact).expect("encode");
    let original = pin(&artifact, &bytes);
    for index in 0..bytes.len() {
        let mut altered = bytes.clone();
        altered[index] ^= 1;
        assert!(LoadedTabularOperatorV1::from_pinned_payload(&altered, &original).is_err());
        let truncated = &bytes[..index];
        let mut matching = original.clone();
        matching.payload_digest = Digest32::of_bytes(truncated);
        assert!(LoadedTabularOperatorV1::from_pinned_payload(truncated, &matching).is_err());
    }
    let mut stale = original;
    stale.dataset_digest = hash("other-dataset");
    assert_eq!(
        LoadedTabularOperatorV1::from_pinned_payload(&bytes, &stale),
        Err(TabularPayloadError::Binding)
    );
    let mut trailing = bytes;
    trailing.push(0);
    assert!(
        LoadedTabularOperatorV1::from_pinned_payload(&trailing, &pin(&artifact, &trailing))
            .is_err()
    );
}

#[test]
fn invalid_statistics_grid_and_authority_cannot_be_encoded() {
    let artifact = fitted(2, 7);
    for operation in 0..4 {
        let mut invalid = artifact.clone();
        match operation {
            0 => invalid.cells[0].sample_count = 0,
            1 => invalid.cells[0].minimum_target = FixedQ32::from_raw(20),
            2 => invalid.cells.push(invalid.cells[0].clone()),
            3 => invalid.cells[0].evidence_digest = Digest32::ZERO,
            _ => unreachable!(),
        }
        assert!(encode_tabular_payload_v1(&invalid).is_err());
    }
    let mut empty = artifact;
    empty.cells.clear();
    assert_eq!(
        encode_tabular_payload_v1(&empty),
        Err(TabularPayloadError::Bounds)
    );
}

#[test]
fn impossible_sample_statistics_reject_at_encoding_and_pinned_loading() {
    let artifact = fitted(2, 7);
    let original = encode_tabular_payload_v1(&artifact).expect("encode");
    for (count, minimum, mean, maximum) in [
        (1_u32, 5_i64, 7_i64, 9_i64),
        (2, 5, 6, 9),
        (2, 5, 8, 9),
        (3, 0, 0, 3),
        (3, -3, 0, 0),
        // The exact half-integer mean must use nearest-even rounding.
        (2, -2, -1, 1),
    ] {
        let mut invalid = artifact.clone();
        let cell = &mut invalid.cells[0];
        cell.sample_count = count;
        cell.minimum_target = FixedQ32::from_raw(minimum);
        cell.mean_target = FixedQ32::from_raw(mean);
        cell.maximum_target = FixedQ32::from_raw(maximum);
        assert_eq!(
            encode_tabular_payload_v1(&invalid),
            Err(TabularPayloadError::Grid)
        );

        // Independently pinned bytes still require structural validation.
        // The cell's final 60 bytes contain count, mean, extrema and digest.
        let mut bytes = original.clone();
        let offset = bytes.len() - 60;
        bytes[offset..offset + 4].copy_from_slice(&count.to_be_bytes());
        for (index, value) in [mean, minimum, maximum].into_iter().enumerate() {
            let offset = offset + 4 + index * 8;
            bytes[offset..offset + 8].copy_from_slice(&value.to_be_bytes());
        }
        assert_eq!(
            LoadedTabularOperatorV1::from_pinned_payload(&bytes, &pin(&invalid, &bytes)),
            Err(TabularPayloadError::Grid)
        );
    }
}

#[test]
fn duplicate_cell_evidence_rejects_all_artifact_admission_paths() {
    let original = fitted(2, 7);
    let mut artifact = fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: original.artifact_id,
        producer_id: original.producer_id,
        generation: original.generation,
        objective_digest: original.objective_digest,
        dataset_digest: original.dataset_digest,
        sensor_core_digest: original.sensor_core_digest,
        training_profile_digest: original.training_profile_digest,
        minimum_samples_per_cell: 1,
        sensor_ids: vec![id("state")],
        action_ids: vec![id("read"), id("write")],
        samples: ["read", "write"]
            .into_iter()
            .map(|action| TabularOperatorSampleV1 {
                sample_id: id(&format!("observation-{action}")),
                sensor_id: id("state"),
                action_id: id(action),
                target: FixedQ32::from_raw(7),
                evidence_digest: hash(&format!("independent-{action}")),
            })
            .collect(),
    })
    .expect("independent source observations");
    let mut bytes = encode_tabular_payload_v1(&artifact).expect("canonical cells");
    assert_ne!(
        artifact.cells[0].evidence_digest,
        artifact.cells[1].evidence_digest
    );

    artifact.cells[1].evidence_digest = artifact.cells[0].evidence_digest;
    assert_eq!(
        encode_tabular_payload_v1(&artifact),
        Err(TabularPayloadError::Grid)
    );
    assert_eq!(
        crate::predict_tabular_operator(&artifact, &id("state"), &id("read")),
        Err(crate::LearnedOperatorError::InvalidArtifact)
    );
    assert_eq!(
        crate::predict_tabular_operator_indexed_v2(&artifact, &id("state"), &id("read")),
        Err(crate::StrictLearnedOperatorError::NonCanonicalArtifact)
    );
    let offset = bytes.len() - 32;
    bytes[offset..].copy_from_slice(artifact.cells[0].evidence_digest.as_array());
    assert_eq!(
        LoadedTabularOperatorV1::from_pinned_payload(&bytes, &pin(&artifact, &bytes)),
        Err(TabularPayloadError::Grid)
    );
}

#[test]
fn attainable_statistics_preserve_nearest_even_means_at_integer_extremes() {
    let artifact = fitted(2, 7);
    for (count, minimum, mean, maximum) in [
        (1_u32, i64::MIN, i64::MIN, i64::MIN),
        (1, i64::MAX, i64::MAX, i64::MAX),
        (2, -2, 0, 1),
        (2, -3, -2, 0),
        (2, 0, 2, 3),
        (2, i64::MIN, 0, i64::MAX),
        (3, 0, 1, 3),
        (3, -3, -1, 0),
    ] {
        let mut valid = artifact.clone();
        let cell = &mut valid.cells[0];
        cell.sample_count = count;
        cell.minimum_target = FixedQ32::from_raw(minimum);
        cell.mean_target = FixedQ32::from_raw(mean);
        cell.maximum_target = FixedQ32::from_raw(maximum);
        let bytes = encode_tabular_payload_v1(&valid).expect("attainable statistics");
        let loaded = LoadedTabularOperatorV1::from_pinned_payload(&bytes, &pin(&valid, &bytes))
            .expect("attainable pinned payload");
        assert_eq!(
            loaded.predict(&id("state"), &id("read")).unwrap().value,
            FixedQ32::from_raw(mean)
        );
    }
}

#[test]
fn loaded_process_predicts_only_the_host_pinned_candidate() {
    if let Some(path) = std::env::var_os("HEPTA_TEST_TABULAR_PAYLOAD") {
        let bytes = fs::read(path).expect("candidate payload");
        let generation: u64 = std::env::var("HEPTA_TEST_TABULAR_GENERATION")
            .expect("generation")
            .parse()
            .expect("u64");
        let expected: i64 = std::env::var("HEPTA_TEST_TABULAR_VALUE")
            .expect("value")
            .parse()
            .expect("i64");
        // Fixture-only independent host metadata. No training occurs in this child.
        let digest = std::env::var("HEPTA_TEST_TABULAR_PIN")
            .expect("pin")
            .parse::<Digest32>()
            .expect("digest");
        let mut decoded = decode(&bytes).expect("bounded payload");
        let mut admission = pin(&decoded, &bytes);
        admission.payload_digest = digest;
        admission.generation = Generation::new(generation).expect("generation");
        // Public source values cannot mutate the already-loaded private value.
        let loaded =
            LoadedTabularOperatorV1::from_pinned_payload(&bytes, &admission).expect("pinned load");
        decoded.cells[0].mean_target = FixedQ32::from_raw(999);
        let actual = loaded
            .predict(&id("state"), &id("read"))
            .expect("predict")
            .value
            .raw();
        assert_eq!(actual, expected);
        println!("tabular-observation:{}:{actual}", std::process::id());
    } else {
        actual_fit_serializes_and_predicts_with_no_mutable_loaded_surface();
    }
}

#[test]
fn distinct_process_load_changes_prediction_and_rolls_back_without_retraining() {
    let root = std::env::temp_dir().join(format!(
        "hepta-tabular-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos()
    ));
    fs::create_dir(&root).expect("private fixture directory");
    let mut pids = BTreeSet::new();
    let baseline = fitted(1, 1);
    let candidate = fitted(2, 7);
    let mut persisted = Vec::new();
    for artifact in [&baseline, &candidate] {
        let bytes = encode_tabular_payload_v1(artifact).expect("encode");
        let path = root.join(artifact.artifact_id.as_str());
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .expect("create-only");
        file.write_all(&bytes).expect("write");
        file.sync_all().expect("sync");
        drop(file);
        persisted.push((path, Digest32::of_bytes(&bytes)));
    }
    // Select the same immutable predecessor file for rollback; no fitting or
    // rewriting occurs between these three independent process launches.
    for (index, generation, target) in [(0, 1, 1), (1, 2, 7), (0, 1, 1)] {
        let (path, payload_digest) = &persisted[index];
        let output = Command::new(std::env::current_exe().expect("executable"))
            .args([
                "--exact",
                "loaded::tests::loaded_process_predicts_only_the_host_pinned_candidate",
                "--nocapture",
            ])
            .env("HEPTA_TEST_TABULAR_PAYLOAD", path)
            .env("HEPTA_TEST_TABULAR_GENERATION", generation.to_string())
            .env("HEPTA_TEST_TABULAR_VALUE", target.to_string())
            .env("HEPTA_TEST_TABULAR_PIN", payload_digest.to_string())
            .output()
            .expect("new process");
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let stdout = String::from_utf8(output.stdout).expect("output");
        let observed = stdout
            .lines()
            .find(|line| line.starts_with("tabular-observation:"))
            .expect("observed prediction");
        let pid: u32 = observed
            .split(':')
            .nth(1)
            .expect("pid")
            .parse()
            .expect("pid integer");
        assert_ne!(pid, std::process::id());
        assert!(pids.insert(pid));
    }
    fs::remove_dir_all(root).expect("cleanup");
}
