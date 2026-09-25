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
