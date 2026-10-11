use super::*;

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;

use codex_hepta_infer_core::durable_control::Assignment;
use codex_hepta_infer_core::durable_control::InferenceRequest;
use codex_hepta_infer_core::durable_control::Reservation;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;

struct FixtureDriver {
    _calls: Arc<AtomicUsize>,
}

impl ModelDriver for FixtureDriver {
    fn load(&mut self, _: &ModelManifest) -> Result<DriverModelHandle, WorkerError> {
        Ok(DriverModelHandle {
            opaque_id: "frozen-model-handle".to_owned(),
            observed_memory_bytes: 4096,
        })
    }

    fn run(
        &mut self,
        _: &DriverModelHandle,
        _: &WorkerRequest,
    ) -> Result<DriverRunObservation, WorkerError> {
        Err(WorkerError::MissingTerminalOutput)
    }

    fn unload(&mut self, _: DriverModelHandle) -> Result<(), WorkerError> {
        Ok(())
    }
}

fn typed_request() -> NeuronFeatureRequestV1 {
    NeuronFeatureRequestV1 {
        request_id: StableId::new("tick.1").unwrap(),
        generation: Generation::new(3).unwrap(),
        model_id: StableId::new("model.1").unwrap(),
        encoder_digest: "a".repeat(64).parse().unwrap(),
        head_digest: "b".repeat(64).parse().unwrap(),
        weights_digest: "3".repeat(64).parse().unwrap(),
        input_digest: "c".repeat(64).parse().unwrap(),
        feature_vector_q24: vec![1 << 22, -(1 << 21)],
        expected_output_width: 5,
    }
}

fn worker() -> InferenceWorker<FixtureDriver> {
    let mut value = InferenceWorker::new(
        100,
        "worker.1".to_owned(),
        3,
        ResourceGrant {
            grant_id: "grant.1".to_owned(),
            authority_epoch: 2,
            generation: 3,
            expires_at_ms: 10_000,
            revoked: false,
            maximum_models: 2,
            maximum_active_requests: 4,
            maximum_memory_bytes: 8192,
            semantic_digest: "1".repeat(64),
        },
        FixtureDriver {
            _calls: Arc::new(AtomicUsize::new(0)),
        },
    )
    .unwrap();
    value
        .load_model(
            100,
            ModelManifest {
                model_id: "model.1".to_owned(),
                model_digest: "2".repeat(64),
                weights_digest: "3".repeat(64),
                tokenizer_digest: "4".repeat(64),
                preprocessor_digest: "5".repeat(64),
                quantization_digest: "6".repeat(64),
                runtime_digest: "7".repeat(64),
                device_digest: "8".repeat(64),
                maximum_tokens: 128,
            },
        )
        .unwrap();
    value
}

fn control(
    directory: &tempfile::TempDir,
    request: &NeuronFeatureRequestV1,
) -> DurableInferenceControl {
    let mut feature = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: request.request_id.to_string(),
            reservation_id: "reservation.1".to_owned(),
            model_digest: "2".repeat(64),
            payload_digest: "e".repeat(64),
            maximum_tokens: 64,
            deadline_ms: 9_000,
            lease_payload_digest: "e".repeat(64),
            reservation_model_digest: "2".repeat(64),
            reservation_maximum_tokens: 64,
            cancelled: false,
        },
        encoder_digest: request.encoder_digest.to_string(),
        head_digest: request.head_digest.to_string(),
        weights_digest: request.weights_digest.to_string(),
        input_digest: request.input_digest.to_string(),
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    };
    let payload = canonical_neuron_feature_payload_digest(&feature);
    feature.authorization.payload_digest = payload.clone();
    feature.authorization.lease_payload_digest = payload.clone();

    let mut owner =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    owner
        .submit(
            100,
            InferenceRequest {
                request_id: request.request_id.to_string(),
                principal_id: "principal.1".to_owned(),
                model_digest: "2".repeat(64),
                payload_digest: payload,
                maximum_tokens: 64,
                deadline_ms: 9_000,
                semantic_digest: "d".repeat(64),
            },
        )
        .unwrap();
    owner
        .reserve(
            100,
            request.request_id.as_str(),
            1,
            Reservation {
                reservation_id: "reservation.1".to_owned(),
                quota_units: 100,
                maximum_tokens: 64,
                authority_epoch: 4,
                valid_until_ms: 8_000,
            },
        )
        .unwrap();
    owner
        .assign(
            request.request_id.as_str(),
            2,
            Assignment {
                worker_id: "worker.1".to_owned(),
                worker_generation: 3,
                assignment_digest: "f".repeat(64),
            },
        )
        .unwrap();
    owner
}

#[test]
fn assigned_durable_owner_and_loaded_worker_match_exact_neuron_features() {
    let temporary = tempfile::tempdir().unwrap();
    let typed = typed_request();
    let durable = control(&temporary, &typed);
    let worker = worker();
    let diag = read_neuron_durable_assignment_v1(&durable, &worker, &typed, 100).unwrap();
    assert!(diag.validate_integrity());
    assert_eq!(diag.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(diag.control_revision, 3);
    assert_eq!(diag.worker_generation, worker.worker_generation());
    assert_eq!(
        diag.payload_digest.to_string(),
        durable.get("tick.1").unwrap().request.payload_digest
    );
    let mut forged = diag.clone();
    forged.control_revision += 1;
    assert!(!forged.validate_integrity());
    drop(durable);
    let recovered =
        DurableInferenceControl::open(temporary.path().join("inference.journal"), 32).unwrap();
    assert_eq!(
        read_neuron_durable_assignment_v1(&recovered, &worker, &typed, 100).unwrap(),
        diag
    );
}

#[test]
fn missing_reserved_cancelling_expired_and_drifted_requests_are_rejected() {
    let temporary = tempfile::tempdir().unwrap();
    let typed = typed_request();
    let worker = worker();
    let mut durable = control(&temporary, &typed);
    assert_eq!(
        read_neuron_durable_assignment_v1(&durable, &worker, &typed, 8_000),
        Err(NeuronDurableAssignmentErrorV1::Expired)
    );
    let mut forged = typed.clone();
    forged.feature_vector_q24[0] += 1;
    assert_eq!(
        read_neuron_durable_assignment_v1(&durable, &worker, &forged, 100),
        Err(NeuronDurableAssignmentErrorV1::Mismatch)
    );
    let mut wrong_model = typed.clone();
    wrong_model.weights_digest = "4".repeat(64).parse().unwrap();
    assert_eq!(
        read_neuron_durable_assignment_v1(&durable, &worker, &wrong_model, 100),
        Err(NeuronDurableAssignmentErrorV1::Mismatch)
    );
    assert_eq!(
        read_neuron_durable_assignment_v1(&durable, &worker, &typed, 100)
            .unwrap()
            .control_revision,
        3
    );
    durable.cancel("tick.1", 3).unwrap();
    assert_eq!(
        read_neuron_durable_assignment_v1(&durable, &worker, &typed, 100),
        Err(NeuronDurableAssignmentErrorV1::NotAssigned)
    );
}
