//! Cross-owner engineering test: real tabular fit, existing artifact storage,
//! independent process loading and revocation-safe rollback. Fixture pins are
//! not deployment authorization or scientific evidence of task improvement.
use std::fs::File;
use std::path::PathBuf;
use std::process::Command;

use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::TabularOperatorArtifactV1;
use codex_hepta_bellman_operator::TabularOperatorPlanV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_bellman_operator::fit_tabular_operator_strict_v2;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_artifacts::load_pinned_candidate;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn fit(generation: u64, value: i64) -> TabularOperatorArtifactV1 {
    fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: id(&format!("tabular-{generation}")),
        producer_id: id("fixture-trainer"),
        generation: Generation::new(generation).expect("generation"),
        objective_digest: digest("fixed-external-task"),
        dataset_digest: digest(&format!("dataset-{generation}")),
        sensor_core_digest: digest("fixed-grid"),
        training_profile_digest: digest("strict-tabular"),
        minimum_samples_per_cell: 2,
        sensor_ids: vec![id("state")],
        action_ids: vec![id("read")],
        samples: [value - 2, value + 2]
            .into_iter()
            .enumerate()
            .map(|(i, target)| TabularOperatorSampleV1 {
                sample_id: id(&format!("sample-{i}")),
                sensor_id: id("state"),
                action_id: id("read"),
                target: FixedQ32::from_raw(target),
                evidence_digest: digest(&format!("fixture-observation-{generation}-{i}")),
            })
            .collect(),
    })
    .expect("strict learner")
}

/// The parent retains these expected values independently of inspected files.
#[derive(Clone, Serialize, Deserialize)]
struct Request {
    snapshot: PathBuf,
    payload: PathBuf,
    binding: String,
    head: String,
    snapshot_digest: String,
    records: usize,
    snapshot_bytes: usize,
    payload_digest: String,
    payload_bytes: u64,
    generation: u64,
    artifact_digest: String,
    expected: Expected,
}
#[derive(Clone, Serialize, Deserialize)]
enum Expected {
    Value(i64),
    Rejected,
}

impl Request {
    fn manifest(&self) -> ArtifactManifest {
        ArtifactManifest {
            artifact_id: id(&format!("tabular-{}", self.generation)),
            kind: ArtifactKind::Policy,
            generation: Generation::new(self.generation).expect("generation"),
            predecessor_id: (self.generation == 2).then(|| id("tabular-1")),
            content_digest: self.payload_digest.parse().expect("payload digest"),
            objective_digest: digest("fixed-external-task"),
            support_digest: digest(&format!("dataset-{}", self.generation)),
            producer_id: id("fixture-trainer"),
            compatibility_digest: digest("HEPTTB01-fixture-host"),
            encoded_size_bytes: self.payload_bytes,
        }
    }
    fn set_snapshot(&mut self, receipt: RegistrySnapshotReceipt) {
        self.binding = receipt.binding.to_string();
        self.head = receipt.head_digest.to_string();
        self.snapshot_digest = receipt.file_digest.to_string();
        self.records = receipt.records;
        self.snapshot_bytes = receipt.encoded_bytes;
    }
}

#[test]
fn worker() {
    let Ok(raw) = std::env::var("HEPTA_TEST_OWNER_TABULAR_REQUEST") else {
        // Normal invocation still exercises an actual fitted model, not an empty main.
        assert_eq!(fit(1, 1).cells[0].mean_target.raw(), 1);
        return;
    };
    assert!(raw.len() <= 16384);
    let request: Request = serde_json::from_str(&raw).expect("host fixture request");
    let loaded = load_pinned_candidate(
        File::open(&request.snapshot).expect("read-only registry"),
        File::open(&request.payload).expect("read-only payload"),
        PinnedCandidateSpec {
            registry_receipt: RegistrySnapshotReceipt {
                binding: request.binding.parse().expect("binding"),
                head_digest: request.head.parse().expect("head"),
                file_digest: request.snapshot_digest.parse().expect("snapshot digest"),
                records: request.records,
                encoded_bytes: request.snapshot_bytes,
            },
            manifest: request.manifest(),
        },
    );
    match request.expected {
        Expected::Rejected => assert!(
            loaded.is_err(),
            "revoked candidate must not reach predictor"
        ),
        Expected::Value(expected) => {
            let bytes = loaded.expect("existing artifact owner pin");
            let model = LoadedTabularOperatorV1::from_pinned_payload(
                bytes.bytes(),
                &TabularPayloadPinV1 {
                    payload_digest: request.payload_digest.parse().expect("payload digest"),
                    artifact_digest: request.artifact_digest.parse().expect("artifact digest"),
                    objective_digest: digest("fixed-external-task"),
                    dataset_digest: digest(&format!("dataset-{}", request.generation)),
                    sensor_core_digest: digest("fixed-grid"),
                    training_profile_digest: digest("strict-tabular"),
                    generation: Generation::new(request.generation).expect("generation"),
                },
            )
            .expect("loaded model binding");
            assert_eq!(
                model
                    .predict(&id("state"), &id("read"))
                    .expect("prediction")
                    .value
                    .raw(),
                expected
            );
        }
    }
    println!("OWNER_TABULAR_PID={}", std::process::id());
}

fn run(request: &Request) -> u32 {
    let raw = serde_json::to_string(request).expect("fixture request");
    let child = Command::new(std::env::current_exe().expect("test executable"))
        .args([
            "--exact",
            "tabular_reload::worker",
            "--nocapture",
            "--test-threads=1",
        ])
        .env("HEPTA_TEST_OWNER_TABULAR_REQUEST", raw)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .expect("new host process");
    let pid = child.id();
    let output = child.wait_with_output().expect("process terminality");
    assert!(output.status.success(), "{output:?}");
    let stdout = String::from_utf8(output.stdout).expect("utf8");
    let observations: Vec<_> = stdout
        .lines()
        .filter_map(|line| {
            line.split_once("OWNER_TABULAR_PID=")
                .map(|(_, value)| value)
        })
        .collect();
    assert_eq!(observations, vec![pid.to_string().as_str()]);
    assert_ne!(pid, std::process::id());
    pid
}

#[test]
fn existing_artifact_owner_new_process_predictions_and_revoked_rollback() {
    let directory = tempfile::tempdir().expect("private fixture namespace");
    let snapshot = directory.path().join("registry");
    let mut registry = ArtifactRegistry::new();
    let mut requests = Vec::new();
    for (generation, target) in [(1, 1), (2, 7)] {
        let model = fit(generation, target);
        let bytes = encode_tabular_payload_v1(&model).expect("encode model");
        let request = Request {
            snapshot: snapshot.clone(),
            payload: directory.path().join(format!("payload-{generation}")),
            binding: String::new(),
            head: String::new(),
            snapshot_digest: String::new(),
            records: 0,
            snapshot_bytes: 0,
            payload_digest: Digest32::of_bytes(&bytes).to_string(),
            payload_bytes: bytes.len() as u64,
            generation,
            artifact_digest: model.artifact_digest.to_string(),
            expected: Expected::Value(target),
        };
        let manifest = request.manifest();
        registry
            .append(ArtifactEvent::Register {
                event_id: id(&format!("register-{generation}")),
                manifest: manifest.clone(),
            })
            .expect("owner registration");
        write_candidate_payload(
            CreateOnlyArtifactFile::create(&request.payload).expect("create-only payload"),
            &registry,
            &manifest.artifact_id,
            &bytes,
        )
        .expect("owner payload sync");
        requests.push(request);
    }
    let receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&snapshot).expect("create-only registry"),
        &registry,
        digest("fixture-current-host-binding"),
    )
    .expect("owner snapshot sync");
    for request in &mut requests {
        request.set_snapshot(receipt);
    }
    let pids = [run(&requests[0]), run(&requests[1]), run(&requests[0])];
    assert_eq!(
        pids.into_iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len(),
        3
    );
    registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke-predecessor"),
            artifact_id: id("tabular-1"),
            evaluator_id: id("fixture-independent-evaluator"),
            reason_digest: digest("withdrawn-support"),
        }))
        .expect("owner revoke");
    let revoked_snapshot = directory.path().join("registry-revoked");
    let current = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&revoked_snapshot).expect("new registry"),
        &registry,
        receipt.binding,
    )
    .expect("current revocation sync");
    for request in &mut requests {
        request.snapshot = revoked_snapshot.clone();
        request.set_snapshot(current);
        request.expected = Expected::Rejected;
        run(request); // Both the predecessor and its descendant must remain revoked.
    }
}
