use super::*;

use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverNeuronFeatureObservation;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;

const Q: i64 = 1 << 24;

#[derive(Debug)]
struct FixtureDriver {
    calls: Arc<AtomicUsize>,
    indeterminate: bool,
    bad_head: bool,
}

impl ModelDriver for FixtureDriver {
    fn load(&mut self, _manifest: &ModelManifest) -> Result<DriverModelHandle, WorkerError> {
        Ok(DriverModelHandle {
            opaque_id: "actual-loaded-fixture-model".to_owned(),
            observed_memory_bytes: 4096,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, WorkerError> {
        Err(WorkerError::DriverFailure("ordinary output disabled".to_owned()))
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), WorkerError> {
        Ok(())
    }
}

impl NeuronFeatureDriver for FixtureDriver {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, WorkerError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let successful = !self.indeterminate;
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: successful,
            succeeded: successful,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: if self.bad_head {
                "f".repeat(64)
            } else {
                request.head_digest.clone()
            },
            drive_q24: if successful {
                vec![Q; request.expected_output_width]
            } else {
                Vec::new()
            },
            prediction_q24: if successful {
                vec![0; request.expected_output_width]
            } else {
                Vec::new()
            },
            observed_memory_bytes: 4096,
            transient_allocation_bytes: 2048,
            queue_age_micros: 7,
            latency_micros: 20,
        })
    }
}

fn digest(v: &str) -> Digest32 {
    v.repeat(64).parse().expect("fixed fixture digest")
}

fn typed_request() -> NeuronFeatureRequestV1 {
    NeuronFeatureRequestV1 {
        request_id: StableId::new("tick.1").unwrap(),
        generation: Generation::new(3).unwrap(),
        model_id: StableId::new("model.1").unwrap(),
        encoder_digest: digest("a"),
        head_digest: digest("b"),
        weights_digest: digest("3"),
        input_digest: digest("c"),
        feature_vector_q24: vec![Q / 4, -(Q / 8)],
        expected_output_width: 5,
    }
}

fn preadmitted_reservation(request: &NeuronFeatureRequestV1) -> WorkerRequest {
    let mut features = NeuronFeatureRequest {
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
    let digest = canonical_neuron_feature_payload_digest(&features);
    features.authorization.payload_digest = digest.clone();
    features.authorization.lease_payload_digest = digest;
    features.authorization
}

fn worker(
    calls: Arc<AtomicUsize>,
    indeterminate: bool,
    bad_head: bool,
) -> InferenceWorker<FixtureDriver> {
    let mut worker = InferenceWorker::new(
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
            calls,
            indeterminate,
            bad_head,
        },
    )
    .unwrap();
    worker
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
    worker
}

fn model_request(request: &NeuronFeatureRequestV1) -> NeuronModelRequestV1 {
    NeuronModelRequestV1 {
        request_id: request.request_id.clone(),
        config_id: StableId::new("neuron.config.1").unwrap(),
        generation: request.generation,
        model_id: request.model_id.clone(),
        encoder_digest: request.encoder_digest,
        head_digest: request.head_digest,
        weights_digest: request.weights_digest,
        input_digest: request.input_digest,
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    }
}

#[test]
fn native_worker_single_use_port_executes_exact_neuron_model_port() {
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker(Arc::clone(&calls), false, false);
    let typed = typed_request();
    let reservation = preadmitted_reservation(&typed);
    let mut control = WorkerNeuronControlPort::from_reserved_worker(
        &mut worker,
        "model.1".to_owned(),
        reservation,
        100,
    );
    assert!(control.reservation_unconsumed());
    let mut model = InferenceControlModelPort::new(&mut control);
    let actual = model.execute(&model_request(&typed)).unwrap();
    assert_eq!(actual.drive_q24, vec![Q; 5]);
    assert_eq!(actual.prediction_q24, vec![0; 5]);
    assert_eq!(actual.runtime_receipt.weights_digest, typed.weights_digest);
    assert_eq!(actual.runtime_receipt.tokenizer_digest, digest("4"));
    assert_eq!(actual.runtime_receipt.runtime_digest, digest("7"));
    assert!(!actual.output_digest.is_zero());
    assert_eq!(actual.runtime_receipt.resident_bytes, 4096);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(!control.reservation_unconsumed());
    assert_eq!(
        control.execute_feature(&typed),
        Err(NeuronModelError::Rejected),
        "a successful reservation cannot be reused"
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn native_worker_port_rejects_wrong_model_generation_and_payload_before_driver() {
    let typed = typed_request();
    for mode in 0..5 {
        let calls = Arc::new(AtomicUsize::new(0));
        let mut worker = worker(Arc::clone(&calls), false, false);
        let mut request = typed.clone();
        let mut reservation = preadmitted_reservation(&typed);
        let mut model_id = "model.1".to_owned();
        match mode {
            0 => model_id = "other-model".to_owned(),
            1 => request.generation = Generation::new(4).unwrap(),
            2 => request.feature_vector_q24[0] += 1,
            3 => reservation.reservation_model_digest = "f".repeat(64),
            _ => reservation.lease_payload_digest = "f".repeat(64),
        }
        let mut port =
            WorkerNeuronControlPort::from_reserved_worker(&mut worker, model_id, reservation, 100);
        assert_eq!(
            port.execute_feature(&request),
            Err(NeuronModelError::Rejected),
            "rejection mode {mode}"
        );
        assert_eq!(
            port.execute_feature(&typed),
            Err(NeuronModelError::Rejected),
            "a rejected reservation must never be reused"
        );
        assert!(!port.reservation_unconsumed());
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}

#[test]
fn native_worker_port_maps_unobserved_terminal_and_driver_drift() {
    let typed = typed_request();
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker(Arc::clone(&calls), true, false);
    let mut port = WorkerNeuronControlPort::from_reserved_worker(
        &mut worker,
        "model.1".to_owned(),
        preadmitted_reservation(&typed),
        100,
    );
    let receipt = port.execute_feature(&typed).unwrap();
    assert_eq!(
        receipt.status,
        NeuronFeatureTerminalStatusV1::Indeterminate
    );
    assert!(receipt.drive_q24.is_empty());
    assert!(receipt.prediction_q24.is_empty());
    assert!(!port.reservation_unconsumed());

    let mut worker = worker(Arc::clone(&calls), false, true);
    let mut port = WorkerNeuronControlPort::from_reserved_worker(
        &mut worker,
        "model.1".to_owned(),
        preadmitted_reservation(&typed),
        100,
    );
    assert_eq!(
        port.execute_feature(&typed),
        Err(NeuronModelError::Rejected),
        "an incorrect driver head cannot produce an accepted receipt"
    );
    assert_eq!(calls.load(Ordering::SeqCst), 2);
}

#[test]
fn native_worker_port_rejects_cancelled_or_expired_worker_reservation() {
    let typed = typed_request();
    for mode in 0..2 {
        let calls = Arc::new(AtomicUsize::new(0));
        let mut worker = worker(Arc::clone(&calls), false, false);
        let mut reservation = preadmitted_reservation(&typed);
        let now_ms = if mode == 0 {
            reservation.cancelled = true;
            100
        } else {
            10_000
        };
        let mut port = WorkerNeuronControlPort::from_reserved_worker(
            &mut worker,
            "model.1".to_owned(),
            reservation,
            now_ms,
        );
        assert_eq!(port.execute_feature(&typed), Err(NeuronModelError::Rejected));
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
}
