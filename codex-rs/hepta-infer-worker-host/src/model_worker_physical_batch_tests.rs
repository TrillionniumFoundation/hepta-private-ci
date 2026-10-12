use super::*;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[derive(Clone, Copy)]
enum Fault {
    None,
    SwappedItem,
    WrongSubmission,
    TooManyForwards,
    ExcessPeak,
}

struct FixtureBackend {
    fault: Fault,
    calls: Arc<AtomicUsize>,
}

impl ModelDriver for FixtureBackend {
    fn load(&mut self, _manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        Ok(DriverModelHandle {
            opaque_id: "backend-handle".into(),
            observed_memory_bytes: 512,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Err(Error::DriverFailure("not single-item".into()))
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        Ok(())
    }
}

impl NeuronFeatureDriver for FixtureBackend {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        Err(Error::DriverFailure("no single-item fallback".into()))
    }
}

impl NeuronPhysicalBatchDriver for FixtureBackend {
    fn run_neuron_feature_batch(
        &mut self,
        _handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<PhysicalBatchRunObservationV1, Error> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let mut items: Vec<_> = requests
            .iter()
            .map(|request| PhysicalBatchItemObservationV1 {
                request_id: request.authorization.request_id.clone(),
                payload_digest: request.authorization.payload_digest.clone(),
                observation: DriverNeuronFeatureObservation {
                    terminal_observed: true,
                    succeeded: true,
                    encoder_digest: request.encoder_digest.clone(),
                    head_digest: request.head_digest.clone(),
                    drive_q24: vec![1 << 24; request.expected_output_width],
                    prediction_q24: vec![0; request.expected_output_width],
                    observed_memory_bytes: 512,
                    transient_allocation_bytes: 1024,
                    queue_age_micros: 5,
                    latency_micros: 7,
                },
            })
            .collect();
        if matches!(self.fault, Fault::SwappedItem) {
            items.swap(0, 1);
        }
        Ok(PhysicalBatchRunObservationV1 {
            submission_digest: if matches!(self.fault, Fault::WrongSubmission) {
                Digest32::of_bytes(b"foreign-request-order").to_string()
            } else {
                canonical_physical_batch_submission_digest_v1("worker", "model", 3, requests)
                    .to_string()
            },
            batch_execution_digest: Digest32::of_bytes(b"test-batch").to_string(),
            claimed_encoder_forward_count: if matches!(self.fault, Fault::TooManyForwards) {
                2
            } else {
                1
            },
            observed_peak_memory_bytes: if matches!(self.fault, Fault::ExcessPeak) {
                5000
            } else {
                3000
            },
            items,
        })
    }
}

fn digest(name: &[u8]) -> String {
    Digest32::of_bytes(name).to_string()
}

fn fixture(
    fault: Fault,
) -> (
    InferenceWorker<FixtureBackend>,
    Arc<AtomicUsize>,
    Vec<NeuronFeatureRequest>,
) {
    let manifest = ModelManifest {
        model_id: "model".into(),
        model_digest: digest(b"model"),
        weights_digest: digest(b"weights"),
        tokenizer_digest: digest(b"tokenizer"),
        preprocessor_digest: digest(b"preprocessor"),
        quantization_digest: digest(b"quantization"),
        runtime_digest: digest(b"runtime"),
        device_digest: digest(b"device"),
        maximum_tokens: 128,
    };
    let grant = ResourceGrant {
        grant_id: "resource".into(),
        authority_epoch: 9,
        generation: 3,
        expires_at_ms: 10_000,
        revoked: false,
        maximum_models: 2,
        maximum_active_requests: 4,
        maximum_memory_bytes: 4096,
        semantic_digest: digest(b"resource"),
    };
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = InferenceWorker::new(
        100,
        "worker".into(),
        3,
        grant,
        FixtureBackend {
            fault,
            calls: Arc::clone(&calls),
        },
    )
    .unwrap();
    worker.load_model(100, manifest.clone()).unwrap();

    let requests = (0..2)
        .map(|i| {
            let mut request = NeuronFeatureRequest {
                authorization: WorkerRequest {
                    request_id: format!("batch-request-{i}"),
                    reservation_id: format!("reservation-{i}"),
                    model_digest: manifest.model_digest.clone(),
                    payload_digest: String::new(),
                    maximum_tokens: 8,
                    deadline_ms: 9000,
                    lease_payload_digest: String::new(),
                    reservation_model_digest: manifest.model_digest.clone(),
                    reservation_maximum_tokens: 8,
                    cancelled: false,
                },
                encoder_digest: digest(b"encoder"),
                head_digest: digest(b"head"),
                weights_digest: manifest.weights_digest.clone(),
                input_digest: digest(b"input"),
                feature_vector_q24: vec![i << 24, 1 << 24],
                expected_output_width: 3,
            };
            let payload = canonical_neuron_feature_payload_digest(&request);
            request.authorization.payload_digest = payload.clone();
            request.authorization.lease_payload_digest = payload;
            request
        })
        .collect();
    (worker, calls, requests)
}

#[test]
fn verified_one_call_batch_emits_one_bound_receipt_per_item() {
    let (mut worker, calls, requests) = fixture(Fault::None);
    let receipts = worker
        .run_physical_batch_receipts(100, "model", requests)
        .unwrap();
    assert_eq!(receipts.len(), 2);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[test]
fn no_receipts_on_item_swap_or_untrusted_batch_envelope() {
    for fault in [
        Fault::SwappedItem,
        Fault::WrongSubmission,
        Fault::TooManyForwards,
        Fault::ExcessPeak,
    ] {
        let (mut worker, calls, requests) = fixture(fault);
        assert_eq!(
            worker.run_physical_batch_receipts(100, "model", requests),
            Err(Error::FeatureContract)
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
}
