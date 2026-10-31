//! Explicit opt-in real Python execution through existing inference owners.
//! All authority is supplied by this isolated test fixture, never manufactured
//! by the driver. This does not activate Agentd or qualify neuron calibration.
#![allow(clippy::expect_used, reason = "fixture and integration assertions")]

use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_infer_core::GenerationModelPinsV1;
use codex_hepta_infer_core::GenerationRequestV1;
use codex_hepta_infer_core::durable_control::Assignment;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::InferenceRequest;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::durable_control::Reservation;
use codex_hepta_infer_core::durable_control::TerminalObservation;
use codex_hepta_infer_core::generation_json_digest;
use codex_hepta_infer_worker_host::generation_driver::GenerationDriver;
use codex_hepta_infer_worker_host::generation_driver::GenerationProcessEvidenceV1;
use codex_hepta_infer_worker_host::generation_driver::GenerationRegistrationV1;
use codex_hepta_infer_worker_host::model_worker::Error as WorkerError;
use codex_hepta_infer_worker_host::model_worker::ExecutionStatus;
use codex_hepta_infer_worker_host::model_worker::InferenceWorker;
use codex_hepta_infer_worker_host::model_worker::ResourceGrant;
use codex_hepta_infer_worker_host::model_worker::WorkerRequest;
use codex_hepta_types::Digest32;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Fixture {
    repository: PathBuf,
    python: PathBuf,
    artifact_root: PathBuf,
    checkpoint_name: String,
    model_id: String,
    pins: GenerationModelPinsV1,
    request: GenerationRequestV1,
}

fn fixture(profile: &str) -> Fixture {
    let path = std::env::var_os("HEPTA_GENERATION_TEST_FIXTURE")
        .expect("prepare owner_worker_tests --prepare-fixture, then supply its fixture.json");
    let mut path = PathBuf::from(path);
    if profile != "legacy" {
        path = path
            .parent()
            .expect("fixture parent")
            .join(profile)
            .join("fixture.json");
    }
    serde_json::from_slice(&std::fs::read(path).expect("fixture file")).expect("fixture JSON")
}

fn execute_case(mut fixture: Fixture, expected: RequestState, timeout: Duration) {
    if expected == RequestState::Failed {
        // Hash-valid but incompatible registration must fail in the real loader.
        fixture.pins.config_sha256 = "a".repeat(64);
        fixture.request.model = fixture.pins.clone();
    }
    let payload = generation_json_digest(&fixture.request).expect("payload");
    let request_id = fixture.request.request_id.clone();
    // Retain exact process output and the real owner journal under the explicit
    // fixture root, so the CI artifact includes successful and failed evidence.
    let directory = tempfile::Builder::new()
        .prefix("owner-evidence-")
        .tempdir_in(&fixture.artifact_root)
        .expect("isolated owner directory")
        .keep();
    let driver = GenerationDriver::new(
        GenerationRegistrationV1 {
            repository: fixture.repository,
            python: fixture.python,
            artifact_root: fixture.artifact_root,
            checkpoint_name: fixture.checkpoint_name,
            model_id: fixture.model_id.clone(),
            pins: fixture.pins,
            timeout,
        },
        vec![fixture.request.clone()],
    )
    .expect("registered driver");
    let manifest = driver.manifest().expect("manifest");
    let evidence = driver.evidence();
    let mut worker = InferenceWorker::new(
        /*now_ms*/ 100,
        "qualification.worker".into(),
        /*generation*/ 1,
        ResourceGrant {
            grant_id: "test-only-resource-grant".into(),
            authority_epoch: 1,
            generation: 1,
            expires_at_ms: 100_000,
            revoked: false,
            maximum_models: 1,
            maximum_active_requests: 1,
            maximum_memory_bytes: 2 * 1024 * 1024 * 1024,
            semantic_digest: "1".repeat(64),
        },
        driver,
    )
    .expect("existing worker");
    worker
        .load_model(/*now_ms*/ 100, manifest.clone())
        .expect("registration load");
    let journal = directory.join("inference.journal");
    let mut control =
        DurableInferenceControl::open(&journal, /*capacity*/ 8).expect("control owner");
    let submitted = control
        .submit(
            /*now_ms*/ 100,
            InferenceRequest {
                request_id: request_id.clone(),
                principal_id: "qualification.host".into(),
                model_digest: manifest.model_digest.clone(),
                payload_digest: payload.clone(),
                maximum_tokens: 8,
                deadline_ms: 90_000,
                semantic_digest: Digest32::of_bytes(format!("generation:{payload}").as_bytes())
                    .to_string(),
            },
        )
        .expect("submit");
    let reservation = Reservation {
        reservation_id: "test.reservation".into(),
        quota_units: 60_000_000_000,
        maximum_tokens: 8,
        authority_epoch: 1,
        valid_until_ms: 90_000,
    };
    assert!(
        control
            .reserve(
                /*now_ms*/ 100,
                &request_id,
                submitted.revision + 1,
                reservation.clone()
            )
            .is_err()
    );
    let reserved = control
        .reserve(
            /*now_ms*/ 100,
            &request_id,
            submitted.revision,
            reservation,
        )
        .expect("reserve");
    let assigned = control
        .assign(
            &request_id,
            reserved.revision,
            Assignment {
                worker_id: worker.worker_id().into(),
                worker_generation: 1,
                assignment_digest: "2".repeat(64),
            },
        )
        .expect("assign");
    let request = WorkerRequest {
        request_id: request_id.clone(),
        reservation_id: "test.reservation".into(),
        model_digest: manifest.model_digest.clone(),
        payload_digest: payload.clone(),
        maximum_tokens: 8,
        deadline_ms: 90_000,
        lease_payload_digest: payload.clone(),
        reservation_model_digest: manifest.model_digest.clone(),
        reservation_maximum_tokens: 8,
        cancelled: false,
    };
    let observed = worker
        .run(/*now_ms*/ 100, &fixture.model_id, request.clone())
        .expect("real worker execution");
    let process = evidence.get(&payload).expect("retained process evidence");
    let evidence_path = directory.join("execution.json");
    std::fs::write(
        &evidence_path,
        serde_json::to_vec(&process).expect("evidence JSON"),
    )
    .expect("retain raw outputs");
    let retained: GenerationProcessEvidenceV1 =
        serde_json::from_slice(&std::fs::read(&evidence_path).expect("reopen"))
            .expect("retained receipt");
    assert_eq!(retained, process);
    let status = match observed.status {
        ExecutionStatus::Succeeded => RequestState::Completed,
        ExecutionStatus::Failed => RequestState::Failed,
        ExecutionStatus::Cancelled => RequestState::Cancelled,
        ExecutionStatus::Indeterminate => RequestState::Indeterminate,
    };
    assert_eq!(status, expected, "{process:?}");
    if let Some(execution) = &process.execution {
        execution
            .verify(&fixture.request)
            .expect("cross-language state/output binding");
        assert_ne!(execution.states.first(), execution.states.last());
        assert_eq!(execution.authority, "deny_all");
        assert_eq!(&execution.png[16..24], &[0, 0, 0, 56, 0, 0, 0, 28]);
    } else {
        assert!(observed.output_digest.is_none());
        assert!(process.timed_out || process.exit_code.is_some_and(|value| value != 0));
    }
    let terminal = TerminalObservation {
        request_id: request_id.clone(),
        reservation_id: "test.reservation".into(),
        worker_id: worker.worker_id().into(),
        worker_generation: 1,
        model_digest: manifest.model_digest,
        payload_digest: payload.clone(),
        terminal_observed: observed.terminal_observed,
        terminal_status: if status == RequestState::Indeterminate {
            None
        } else {
            Some(status)
        },
        output_digest: observed.output_digest.clone(),
        consumed_tokens: observed.consumed_tokens,
        usage_units: process.host_wall_ns, // This fixture reserves measured wall nanoseconds.
    };
    let observation_digest =
        Digest32::of_bytes(&std::fs::read(&evidence_path).expect("evidence bytes")).to_string();
    let settled = control
        .settle(
            &request_id,
            assigned.revision,
            observation_digest.clone(),
            terminal.clone(),
        )
        .expect("settle real observation");
    assert_eq!(settled.state, expected);
    assert!(
        control
            .settle(&request_id, settled.revision, observation_digest, terminal)
            .expect("idempotent settle")
            .idempotent
    );
    assert_eq!(
        worker
            .run(/*now_ms*/ 100, &fixture.model_id, request.clone())
            .expect("cached exact retry"),
        observed
    );
    let mut underfunded = request;
    underfunded.maximum_tokens = 7;
    assert_eq!(
        worker.run(/*now_ms*/ 100, &fixture.model_id, underfunded),
        Err(WorkerError::TokenLimit)
    );
    assert_eq!(evidence.get(&payload), Some(process));
    drop(control);
    let recovered = DurableInferenceControl::open(journal, /*capacity*/ 8)
        .expect("recover existing owner journal");
    assert_eq!(
        recovered.get(&request_id).expect("recovered request").state,
        expected
    );
    worker
        .unload_model(/*now_ms*/ 100, &fixture.model_id)
        .expect("unload registration");
}

#[test]
#[ignore = "requires explicitly prepared, pinned Python/Torch model fixture"]
fn existing_owners_execute_legacy_generation() {
    execute_case(
        fixture("legacy"),
        RequestState::Completed,
        Duration::from_secs(30),
    );
}

#[test]
#[ignore = "requires explicitly prepared, pinned Python/Torch model fixture"]
fn existing_owners_execute_conditioned_generation() {
    execute_case(
        fixture("conditioned"),
        RequestState::Completed,
        Duration::from_secs(30),
    );
}

#[test]
#[ignore = "requires explicitly prepared, pinned Python/Torch model fixture"]
fn existing_owners_execute_controlled_generation() {
    execute_case(
        fixture("controlled"),
        RequestState::Completed,
        Duration::from_secs(30),
    );
}

#[test]
#[ignore = "requires explicitly prepared, pinned Python/Torch model fixture"]
fn existing_owners_preserve_failed_generation() {
    execute_case(
        fixture("legacy"),
        RequestState::Failed,
        Duration::from_secs(30),
    );
}

#[test]
#[ignore = "requires explicitly prepared, pinned Python/Torch model fixture"]
fn existing_owners_preserve_indeterminate_generation() {
    execute_case(
        fixture("legacy"),
        RequestState::Indeterminate,
        Duration::from_millis(1),
    );
}
