#![allow(clippy::expect_used)]

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
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::ArtifactSelectionError;
use codex_hepta_learning_artifacts::ArtifactSelectionTrustV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::RegistryHeadRequirementV1;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_artifacts::TrustedArtifactSelectorV1;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::load_selected_candidate;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;

trait FixtureResultExt<T> {
    fn fixture_value(self) -> T;
}

impl<T, E: std::fmt::Debug> FixtureResultExt<T> for Result<T, E> {
    fn fixture_value(self) -> T {
        match self {
            Ok(value) => value,
            Err(error) => panic!("fixture operation failed: {error:?}"),
        }
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).fixture_value()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn fit(generation: u64, value: i64) -> TabularOperatorArtifactV1 {
    fit_tabular_operator_strict_v2(TabularOperatorPlanV1 {
        artifact_id: id(&format!("tabular-{generation}")),
        producer_id: id("fixture-trainer"),
        generation: Generation::new(generation).fixture_value(),
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
    .fixture_value()
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
    current_generation: u64,
    current_predecessor_head: String,
    head_verifying_key: [u8; 32],
    current_signature: Vec<u8>,
    selection_id: String,
    selector_verifying_key: [u8; 32],
    selection_signature: Vec<u8>,
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
            generation: Generation::new(self.generation).fixture_value(),
            predecessor_id: (self.generation == 2).then(|| id("tabular-1")),
            content_digest: self.payload_digest.parse().fixture_value(),
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

fn signature(value: &[u8], label: &str) -> [u8; 64] {
    value
        .try_into()
        .unwrap_or_else(|_| panic!("{label}: expected 64-byte signature"))
}

fn owner_trust(request: &Request) -> ArtifactOwnerTrustV1 {
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("fixture-head-signer"),
        verifying_key: request.head_verifying_key,
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 9,
        valid_from: 1,
        expires_at: 1_000,
        revoked_at: None,
    };
    ArtifactOwnerTrustV1 {
        registry_id: id("fixture-artifact-registry"),
        withdrawal_scope_digest: digest("fixture-withdrawal-scope"),
        minimum_registry_generation: Generation::new(1)
            .unwrap_or_else(|error| panic!("minimum generation: {error:?}")),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    }
}

fn current_head(request: &Request) -> SignedCurrentArtifactHeadV1 {
    SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: digest("fixture-withdrawal-scope"),
        binding: request
            .binding
            .parse()
            .unwrap_or_else(|error| panic!("binding: {error:?}")),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("fixture-artifact-registry"),
            generation: Generation::new(request.current_generation)
                .unwrap_or_else(|error| panic!("current generation: {error:?}")),
            head_digest: request
                .head
                .parse()
                .unwrap_or_else(|error| panic!("head: {error:?}")),
            predecessor_head_digest: request
                .current_predecessor_head
                .parse()
                .unwrap_or_else(|error| panic!("predecessor head: {error:?}")),
            authority_epoch: 1,
            signer_id: id("fixture-head-signer"),
            signing_key_digest: Digest32::of_bytes(&request.head_verifying_key),
            issued_at: 20,
            expires_at: 1_000,
        },
        signature: signature(&request.current_signature, "current head"),
    }
}

fn current_requirement(request: &Request) -> RegistryHeadRequirementV1 {
    RegistryHeadRequirementV1 {
        registry_id: id("fixture-artifact-registry"),
        minimum_generation: Generation::new(request.current_generation)
            .unwrap_or_else(|error| panic!("required generation: {error:?}")),
        expected_predecessor_head_digest: request
            .current_predecessor_head
            .parse()
            .unwrap_or_else(|error| panic!("required predecessor: {error:?}")),
        minimum_authority_epoch: 1,
        now: 30,
    }
}

fn selection_trust(request: &Request) -> ArtifactSelectionTrustV1 {
    ArtifactSelectionTrustV1 {
        registry_id: id("fixture-artifact-registry"),
        withdrawal_scope_digest: digest("fixture-withdrawal-scope"),
        minimum_authority_epoch: 4,
        selectors: vec![TrustedArtifactSelectorV1 {
            selector_id: id("fixture-selector"),
            verifying_key: request.selector_verifying_key,
            minimum_authority_epoch: 4,
            maximum_authority_epoch: 9,
            valid_from: 10,
            expires_at: 1_000,
            revoked_at: None,
        }],
    }
}

fn signed_selection(
    request: &Request,
    current: &VerifiedCurrentRegistryViewV1,
) -> SignedArtifactSelectionV1 {
    let manifest = request.manifest();
    SignedArtifactSelectionV1 {
        selection_id: id(&request.selection_id),
        artifact_id: manifest.artifact_id.clone(),
        registry_id: id("fixture-artifact-registry"),
        withdrawal_scope_digest: digest("fixture-withdrawal-scope"),
        registry_head_digest: current.receipt().head_digest,
        current_witness_digest: current.witness_digest(),
        current_trust_digest: current.trust_digest(),
        artifact_kind: manifest.kind,
        artifact_generation: manifest.generation,
        predecessor_id: manifest.predecessor_id.clone(),
        content_digest: manifest.content_digest,
        objective_digest: manifest.objective_digest,
        support_digest: manifest.support_digest,
        compatibility_digest: manifest.compatibility_digest,
        encoded_size_bytes: manifest.encoded_size_bytes,
        selector_id: id("fixture-selector"),
        selector_credential_digest: digest("fixture-selector-credential"),
        signing_key_digest: Digest32::of_bytes(&request.selector_verifying_key),
        authority_epoch: 4,
        issued_at: 25,
        expires_at: 1_000,
        signature: signature(&request.selection_signature, "selection"),
    }
}

fn verify_current(request: &Request) -> VerifiedCurrentRegistryViewV1 {
    let trust = owner_trust(request);
    let verifier = ArtifactOwnerVerifierV1::new(trust)
        .unwrap_or_else(|error| panic!("owner trust: {error:?}"));
    verifier
        .verify_current_registry_view(
            File::open(&request.snapshot)
                .unwrap_or_else(|error| panic!("read-only current registry: {error:?}")),
            RegistrySnapshotReceipt {
                binding: request
                    .binding
                    .parse()
                    .unwrap_or_else(|error| panic!("binding: {error:?}")),
                head_digest: request
                    .head
                    .parse()
                    .unwrap_or_else(|error| panic!("head: {error:?}")),
                file_digest: request
                    .snapshot_digest
                    .parse()
                    .unwrap_or_else(|error| panic!("snapshot digest: {error:?}")),
                records: request.records,
                encoded_bytes: request.snapshot_bytes,
            },
            &current_head(request),
            &current_requirement(request),
        )
        .unwrap_or_else(|error| panic!("authenticated CURRENT: {error:?}"))
}

fn prepare_authentication(
    request: &mut Request,
    receipt: RegistrySnapshotReceipt,
    predecessor_head: Digest32,
    head_key: &SigningKey,
    selector_key: &SigningKey,
    phase: &str,
) {
    request.set_snapshot(receipt);
    request.current_generation =
        u64::try_from(receipt.records).unwrap_or_else(|error| panic!("record count: {error:?}"));
    request.current_predecessor_head = predecessor_head.to_string();
    request.head_verifying_key = head_key.verifying_key().to_bytes();
    request.selector_verifying_key = selector_key.verifying_key().to_bytes();
    request.current_signature = vec![0; 64];

    let mut head = current_head(request);
    head.signature = head_key.sign(&head.signing_bytes()).to_bytes();
    request.current_signature = head.signature.to_vec();

    let current = verify_current(request);
    request.selection_id = format!("selection-{}-{phase}", request.generation);
    request.selection_signature = vec![0; 64];
    let mut selected = signed_selection(request, &current);
    selected.signature = selector_key.sign(&selected.signing_bytes()).to_bytes();
    request.selection_signature = selected.signature.to_vec();
}

#[test]
fn worker() {
    let Ok(raw) = std::env::var("HEPTA_TEST_OWNER_TABULAR_REQUEST") else {
        // Normal invocation still exercises an actual fitted model, not an empty main.
        assert_eq!(fit(1, 1).cells[0].mean_target.raw(), 1);
        return;
    };
    assert!(raw.len() <= 16384);
    let request: Request = serde_json::from_str(&raw)
        .unwrap_or_else(|error| panic!("host fixture request: {error:?}"));
    let current = verify_current(&request);
    let owner = owner_trust(&request);
    let selection_verifier = ArtifactSelectionVerifierV1::new(selection_trust(&request), &owner)
        .unwrap_or_else(|error| panic!("selection trust: {error:?}"));
    let selected = selection_verifier.verify(&signed_selection(&request, &current), &current, 30);
    match request.expected {
        Expected::Rejected => assert!(
            matches!(selected, Err(ArtifactSelectionError::ArtifactUnavailable)),
            "revoked candidate must fail independent selection at current head: {selected:?}"
        ),
        Expected::Value(expected) => {
            let selection =
                selected.unwrap_or_else(|error| panic!("independent selection: {error:?}"));
            let mut candidate = load_selected_candidate(
                File::open(&request.snapshot)
                    .unwrap_or_else(|error| panic!("selected registry reopen: {error:?}")),
                File::open(&request.payload)
                    .unwrap_or_else(|error| panic!("selected payload reopen: {error:?}")),
                selection,
            )
            .unwrap_or_else(|error| panic!("selected immutable load: {error:?}"));
            let current_for_use = verify_current(&request);
            let bytes = candidate
                .with_current(current_for_use, <[u8]>::to_vec)
                .unwrap_or_else(|error| panic!("final-use CURRENT: {error:?}"));
            let model = LoadedTabularOperatorV1::from_pinned_payload(
                &bytes,
                &TabularPayloadPinV1 {
                    payload_digest: request.payload_digest.parse().fixture_value(),
                    artifact_digest: request.artifact_digest.parse().fixture_value(),
                    objective_digest: digest("fixed-external-task"),
                    dataset_digest: digest(&format!("dataset-{}", request.generation)),
                    sensor_core_digest: digest("fixed-grid"),
                    training_profile_digest: digest("strict-tabular"),
                    generation: Generation::new(request.generation).fixture_value(),
                },
            )
            .fixture_value();
            assert_eq!(
                model
                    .predict(&id("state"), &id("read"))
                    .fixture_value()
                    .value
                    .raw(),
                expected
            );
        }
    }
    println!("OWNER_TABULAR_PID={}", std::process::id());
}

fn run(request: &Request) -> u32 {
    let raw = serde_json::to_string(request).fixture_value();
    let child = Command::new(std::env::current_exe().fixture_value())
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
        .fixture_value();
    let pid = child.id();
    let output = child.wait_with_output().fixture_value();
    assert!(output.status.success(), "{output:?}");
    let stdout = String::from_utf8(output.stdout).fixture_value();
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
    let directory = tempfile::tempdir().fixture_value();
    let snapshot = directory.path().join("registry");
    let mut registry = ArtifactRegistry::new();
    let mut requests = Vec::new();
    let mut final_predecessor_head = Digest32::ZERO;
    for (generation, target) in [(1, 1), (2, 7)] {
        let model = fit(generation, target);
        let bytes = encode_tabular_payload_v1(&model).fixture_value();
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
            current_generation: 0,
            current_predecessor_head: String::new(),
            head_verifying_key: [0; 32],
            current_signature: Vec::new(),
            selection_id: String::new(),
            selector_verifying_key: [0; 32],
            selection_signature: Vec::new(),
            expected: Expected::Value(target),
        };
        let manifest = request.manifest();
        let predecessor_head = registry.snapshot().head_digest;
        if generation == 2 {
            final_predecessor_head = predecessor_head;
        }
        registry
            .append(ArtifactEvent::Register {
                event_id: id(&format!("register-{generation}")),
                manifest: manifest.clone(),
            })
            .fixture_value();
        write_candidate_payload(
            CreateOnlyArtifactFile::create(&request.payload).fixture_value(),
            &registry,
            &manifest.artifact_id,
            &bytes,
        )
        .unwrap_or_else(|error| panic!("owner payload sync: {error:?}"));
        requests.push(request);
    }
    let receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&snapshot)
            .unwrap_or_else(|error| panic!("create-only registry: {error:?}")),
        &registry,
        digest("fixture-current-host-binding"),
    )
    .unwrap_or_else(|error| panic!("owner snapshot sync: {error:?}"));
    let head_key = SigningKey::from_bytes(&[71; 32]);
    let selector_key = SigningKey::from_bytes(&[91; 32]);
    for request in &mut requests {
        prepare_authentication(
            request,
            receipt,
            final_predecessor_head,
            &head_key,
            &selector_key,
            "initial",
        );
    }
    // Generation 2 is selected in one process, then the exact compatible
    // predecessor generation 1 is independently selected and loaded again.
    let pids = [run(&requests[0]), run(&requests[1]), run(&requests[0])];
    assert_eq!(
        pids.into_iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len(),
        3
    );
    let revoked_predecessor_head = registry.snapshot().head_digest;
    registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke-predecessor"),
            artifact_id: id("tabular-1"),
            evaluator_id: id("fixture-independent-evaluator"),
            reason_digest: digest("withdrawn-support"),
        }))
        .fixture_value();
    let revoked_snapshot = directory.path().join("registry-revoked");
    let current = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&revoked_snapshot).fixture_value(),
        &registry,
        receipt.binding,
    )
    .fixture_value();
    for request in &mut requests {
        request.snapshot = revoked_snapshot.clone();
        request.expected = Expected::Rejected;
        prepare_authentication(
            request,
            current,
            revoked_predecessor_head,
            &head_key,
            &selector_key,
            "revoked",
        );
        run(request); // Fresh signed selection attempts fail on current revocation.
    }
}
