//! Worker bookkeeping regression tests. These use a deterministic driver,
//! not a model, provider, durable recovery witness or target-host benchmark.
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_infer_worker_host::model_worker::*;

#[derive(Clone, Copy)]
enum Reply {
    Success,
    Failure,
    Unknown,
    Error,
    Malformed,
}

#[derive(Default)]
struct Calls {
    run: AtomicUsize,
    unload: AtomicUsize,
}

struct Driver {
    reply: Reply,
    fail_unload: bool,
    calls: Arc<Calls>,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        Ok(DriverModelHandle {
            opaque_id: format!("handle.{}", manifest.model_id),
            observed_memory_bytes: 128,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.calls.run.fetch_add(1, Ordering::SeqCst);
        let (terminal_observed, succeeded, output_digest) = match self.reply {
            Reply::Success => (true, true, Some("9".repeat(64))),
            Reply::Failure => (true, false, None),
            Reply::Unknown => (false, false, None),
            Reply::Error => return Err(Error::DriverFailure("lost observation".to_string())),
            Reply::Malformed => (true, true, None),
        };
        Ok(DriverRunObservation {
            terminal_observed,
            succeeded,
            output_digest,
            consumed_tokens: 4,
            observed_memory_bytes: 128,
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.calls.unload.fetch_add(1, Ordering::SeqCst);
        if self.fail_unload {
            return Err(Error::DriverFailure(
                "lost unload acknowledgement".to_string(),
            ));
        }
        Ok(())
    }
}

impl NeuronFeatureDriver for Driver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        let observed = self.run(handle, &request.authorization)?;
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: observed.terminal_observed,
            succeeded: observed.succeeded,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: request.head_digest.clone(),
            drive_q24: match self.reply {
                Reply::Malformed => Vec::new(),
                Reply::Success | Reply::Failure | Reply::Unknown | Reply::Error => {
                    vec![0; request.expected_output_width]
                }
            },
            prediction_q24: vec![0; request.expected_output_width],
            observed_memory_bytes: observed.observed_memory_bytes,
            transient_allocation_bytes: 256,
            queue_age_micros: 0,
            latency_micros: 1,
        })
    }
}

fn manifest() -> ModelManifest {
    ModelManifest {
        model_id: "model.1".to_string(),
        model_digest: "2".repeat(64),
        weights_digest: "3".repeat(64),
        tokenizer_digest: "4".repeat(64),
        preprocessor_digest: "5".repeat(64),
        quantization_digest: "6".repeat(64),
        runtime_digest: "7".repeat(64),
        device_digest: "8".repeat(64),
        maximum_tokens: 128,
    }
}

fn request(id: &str) -> WorkerRequest {
    WorkerRequest {
        request_id: id.to_string(),
        reservation_id: "reservation.1".to_string(),
        model_digest: "2".repeat(64),
        payload_digest: "3".repeat(64),
        maximum_tokens: 64,
        deadline_ms: 9000,
        lease_payload_digest: "3".repeat(64),
        reservation_model_digest: "2".repeat(64),
        reservation_maximum_tokens: 64,
        cancelled: false,
    }
}

fn feature_request(id: &str) -> NeuronFeatureRequest {
    let mut request = NeuronFeatureRequest {
        authorization: request(id),
        encoder_digest: "a".repeat(64),
        head_digest: "b".repeat(64),
        weights_digest: "3".repeat(64),
        input_digest: "c".repeat(64),
        feature_vector_q24: vec![0, 1],
        expected_output_width: 2,
    };
    let digest = canonical_neuron_feature_payload_digest(&request);
    request.authorization.payload_digest = digest.clone();
    request.authorization.lease_payload_digest = digest;
    request
}

fn worker(reply: Reply) -> (InferenceWorker<Driver>, Arc<Calls>) {
    let calls = Arc::new(Calls::default());
    let driver = Driver {
        reply,
        fail_unload: false,
        calls: Arc::clone(&calls),
    };
    (empty_worker(driver), calls)
}

fn empty_worker(driver: Driver) -> InferenceWorker<Driver> {
    InferenceWorker::new(
        /*now_ms*/ 100,
        "worker.1".to_string(),
        /*generation*/ 3,
        ResourceGrant {
            grant_id: "grant.1".to_string(),
            authority_epoch: 2,
            generation: 3,
            expires_at_ms: 10000,
            revoked: false,
            maximum_models: 2,
            maximum_active_requests: 1,
            maximum_memory_bytes: 4096,
            semantic_digest: "1".repeat(64),
        },
        driver,
    )
    .expect("worker")
}

#[test]
fn unknown_text_keeps_identity_capacity_and_model_loaded() {
    let (mut worker, calls) = worker(Reply::Unknown);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let observed = worker
        .run(/*now_ms*/ 100, "model.1", request("r.1"))
        .expect("observation");
    assert_eq!(
        observed,
        InferenceExecutionObservation {
            request_id: "r.1".to_string(),
            reservation_id: "reservation.1".to_string(),
            worker_generation: 3,
            model_digest: "2".repeat(64),
            payload_digest: "3".repeat(64),
            status: ExecutionStatus::Indeterminate,
            output_digest: None,
            consumed_tokens: 4,
            observed_memory_bytes: 128,
            terminal_observed: false,
        }
    );
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request("r.1")),
        Err(Error::RequestCapacity)
    );
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request("r.2")),
        Err(Error::RequestCapacity)
    );
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::ActiveRequests)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
    assert_eq!(calls.unload.load(Ordering::SeqCst), 0);
}

#[test]
fn driver_error_cannot_be_retried_under_a_new_identity() {
    let (mut worker, calls) = worker(Reply::Error);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request("r.1")),
        Err(Error::DriverFailure("lost observation".to_string()))
    );
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request("r.2")),
        Err(Error::RequestCapacity)
    );
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::ActiveRequests)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

#[test]
fn unknown_feature_holds_the_shared_text_execution_slot() {
    let (mut worker, calls) = worker(Reply::Unknown);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let observed = worker
        .run_neuron_features(/*now_ms*/ 100, "model.1", feature_request("r.1"))
        .expect("observation");
    assert_eq!(observed.status, ExecutionStatus::Indeterminate);
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request("r.2")),
        Err(Error::RequestCapacity)
    );
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", feature_request("r.1")),
        Err(Error::RequestCapacity)
    );
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::ActiveRequests)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

#[test]
fn feature_error_retains_capacity_and_prevents_unload() {
    let (mut worker, calls) = worker(Reply::Error);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", feature_request("r.1")),
        Err(Error::DriverFailure("lost observation".to_string()))
    );
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", feature_request("r.2")),
        Err(Error::RequestCapacity)
    );
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::ActiveRequests)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

#[test]
fn malformed_text_terminal_does_not_release_the_slot() {
    let (mut worker, calls) = worker(Reply::Malformed);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request("r.1")),
        Err(Error::MissingTerminalOutput)
    );
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::ActiveRequests)
    );
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request("r.2")),
        Err(Error::RequestCapacity)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

#[test]
fn malformed_feature_terminal_does_not_release_the_slot() {
    let (mut worker, calls) = worker(Reply::Malformed);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", feature_request("r.1")),
        Err(Error::FeatureOutputMismatch)
    );
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::ActiveRequests)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

#[test]
fn terminal_failure_releases_capacity_without_claiming_success() {
    let (mut worker, calls) = worker(Reply::Failure);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let first = worker
        .run(/*now_ms*/ 100, "model.1", request("r.1"))
        .expect("terminal");
    let next = worker
        .run(/*now_ms*/ 100, "model.1", request("r.2"))
        .expect("next terminal");
    assert_eq!(first.status, ExecutionStatus::Failed);
    assert_eq!(next.status, ExecutionStatus::Failed);
    worker
        .unload_model(/*now_ms*/ 100, "model.1")
        .expect("unload");
    assert_eq!(calls.run.load(Ordering::SeqCst), 2);
    assert_eq!(calls.unload.load(Ordering::SeqCst), 1);
}

#[test]
fn terminal_feature_failure_releases_capacity() {
    let (mut worker, calls) = worker(Reply::Failure);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let observed = worker
        .run_neuron_features(/*now_ms*/ 100, "model.1", feature_request("r.1"))
        .expect("terminal");
    assert_eq!(observed.status, ExecutionStatus::Failed);
    worker
        .run_neuron_features(/*now_ms*/ 100, "model.1", feature_request("r.2"))
        .expect("next terminal");
    worker
        .unload_model(/*now_ms*/ 100, "model.1")
        .expect("unload");
    assert_eq!(calls.run.load(Ordering::SeqCst), 2);
}

#[test]
fn pre_dispatch_cancellation_does_not_invoke_the_driver() {
    let (mut worker, calls) = worker(Reply::Success);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let mut cancelled = feature_request("r.1");
    cancelled.authorization.cancelled = true;
    let observed = worker
        .run_neuron_features(/*now_ms*/ 100, "model.1", cancelled)
        .expect("cancelled");
    assert_eq!(observed.status, ExecutionStatus::Cancelled);
    assert_eq!(calls.run.load(Ordering::SeqCst), 0);
    worker
        .run(/*now_ms*/ 100, "model.1", request("r.2"))
        .expect("normal run");
    worker
        .unload_model(/*now_ms*/ 100, "model.1")
        .expect("unload");
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

#[test]
fn lost_unload_acknowledgement_quarantines_the_retained_handle() {
    let calls = Arc::new(Calls::default());
    let mut worker = empty_worker(Driver {
        reply: Reply::Success,
        fail_unload: true,
        calls: Arc::clone(&calls),
    });
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::DriverFailure(
            "lost unload acknowledgement".to_string()
        ))
    );
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request("r.1")),
        Err(Error::ModelQuarantined)
    );
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", feature_request("r.2")),
        Err(Error::ModelQuarantined)
    );
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::ModelQuarantined)
    );
    assert_eq!(
        worker.load_model(/*now_ms*/ 100, manifest()),
        Err(Error::ModelAlreadyLoaded)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 0);
    assert_eq!(calls.unload.load(Ordering::SeqCst), 1);
}

#[test]
fn feature_reservation_and_loaded_model_token_caps_are_enforced_before_entry() {
    let (mut worker, calls) = worker(Reply::Success);
    let mut selected = manifest();
    selected.maximum_tokens = 32;
    worker.load_model(/*now_ms*/ 100, selected).expect("load");
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", feature_request("r.1")),
        Err(Error::TokenLimit)
    );
    let mut short_reservation = feature_request("r.2");
    short_reservation.authorization.maximum_tokens = 16;
    short_reservation.authorization.reservation_maximum_tokens = 8;
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", short_reservation),
        Err(Error::TokenLimit)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 0);
    worker
        .unload_model(/*now_ms*/ 100, "model.1")
        .expect("nothing was dispatched");
}

#[test]
fn unknown_request_cannot_escape_capacity_by_switching_models() {
    let (mut worker, calls) = worker(Reply::Unknown);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let mut other = manifest();
    other.model_id = "model.2".to_string();
    worker
        .load_model(/*now_ms*/ 100, other)
        .expect("load other");
    worker
        .run(/*now_ms*/ 100, "model.1", request("r.1"))
        .expect("unknown");
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.2", request("r.2")),
        Err(Error::RequestCapacity)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

impl SemanticRetrievalDriver for Driver {
    fn run_semantic_retrieval(
        &mut self,
        _handle: &DriverModelHandle,
        request_wire: &[u8],
    ) -> Result<DriverSemanticRetrievalReplyV1, Error> {
        self.calls.run.fetch_add(1, Ordering::SeqCst);
        let reply_wire = match self.reply {
            Reply::Unknown | Reply::Error | Reply::Failure => {
                return Err(Error::DriverFailure(
                    "no complete retrieval reply".to_string(),
                ));
            }
            Reply::Malformed => b"partial reply".to_vec(),
            Reply::Success => {
                let mut bytes = b"HPTARS\x01\x00".to_vec();
                bytes.extend_from_slice(
                    codex_hepta_types::Digest32::of_bytes(request_wire).as_array(),
                );
                bytes.extend_from_slice(&[0x22; 32]);
                for value in [2_u32, 100_000, 900_000] {
                    bytes.extend_from_slice(&value.to_be_bytes());
                }
                for value in [12_u64, 0, 7] {
                    bytes.extend_from_slice(&value.to_be_bytes());
                }
                bytes
            }
        };
        Ok(DriverSemanticRetrievalReplyV1 {
            reply_wire,
            observed_memory_bytes: 128,
        })
    }
}

fn semantic_call(id: &str) -> SemanticRetrievalCallV1 {
    let input = codex_hepta_infer_core::SemanticRetrievalRequestV1 {
        operation_id: id.to_string(),
        workspace_id: "ws.1".to_string(),
        generation: 3,
        objective_digest: "1".repeat(64),
        observation_digest: "2".repeat(64),
        bundle_digest: "2".repeat(64),
        deadline_ms: 9000,
        query: "q".to_string(),
        sources: vec![codex_hepta_infer_core::RetrievalSourceV1 {
            source_id: "src.1".to_string(),
            revision: 7,
            content_sha256: codex_hepta_types::Digest32::of_bytes(b"alpha").to_string(),
            text: "alpha".to_string(),
        }],
    };
    let payload = codex_hepta_types::Digest32::of_bytes(&input.encode().expect("wire")).to_string();
    let mut authorization = request(id);
    authorization.payload_digest = payload.clone();
    authorization.lease_payload_digest = payload;
    SemanticRetrievalCallV1 {
        authorization,
        input,
    }
}

#[test]
fn semantic_retrieval_consumes_loaded_model_and_releases_valid_completion() {
    let (mut worker, calls) = worker(Reply::Success);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let call = semantic_call("r.1");
    let expected_input = call.input.clone();
    let observed = worker
        .run_semantic_retrieval(/*now_ms*/ 100, "model.1", call)
        .expect("semantic reply");
    assert_eq!(observed.reply.prediction_ppm, vec![100_000, 900_000]);
    assert_eq!(
        observed.reply.request_digest,
        codex_hepta_types::Digest32::of_bytes(&expected_input.encode().expect("wire"))
    );
    worker
        .unload_model(/*now_ms*/ 100, "model.1")
        .expect("completed model can unload");
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

#[test]
fn semantic_generation_drift_is_rejected_before_entry() {
    let (mut worker, calls) = worker(Reply::Success);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let mut call = semantic_call("r.1");
    call.input.generation += 1;
    assert_eq!(
        worker.run_semantic_retrieval(/*now_ms*/ 100, "model.1", call),
        Err(Error::PayloadMismatch)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 0);
}

#[test]
fn semantic_request_mutation_invalidates_exact_payload() {
    let (mut worker, calls) = worker(Reply::Success);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let mut call = semantic_call("r.1");
    call.input.query = "different query".to_string();
    assert_eq!(
        worker.run_semantic_retrieval(/*now_ms*/ 100, "model.1", call),
        Err(Error::PayloadMismatch)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 0);
}

#[test]
fn semantic_error_retains_the_shared_worker_slot() {
    let (mut worker, calls) = worker(Reply::Error);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    assert!(
        worker
            .run_semantic_retrieval(/*now_ms*/ 100, "model.1", semantic_call("r.1"))
            .is_err()
    );
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request("r.2")),
        Err(Error::RequestCapacity)
    );
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::ActiveRequests)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

#[test]
fn semantic_unknown_cannot_be_relabelled_pre_entry_cancelled() {
    let (mut worker, calls) = worker(Reply::Unknown);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    assert!(
        worker
            .run_semantic_retrieval(/*now_ms*/ 100, "model.1", semantic_call("r.1"))
            .is_err()
    );
    let mut cancelled = semantic_call("r.1");
    cancelled.authorization.cancelled = true;
    assert_eq!(
        worker.run_semantic_retrieval(/*now_ms*/ 100, "model.1", cancelled),
        Err(Error::RequestCapacity)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

#[test]
fn semantic_malformed_reply_retains_unknown_state() {
    let (mut worker, calls) = worker(Reply::Malformed);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    assert_eq!(
        worker.run_semantic_retrieval(/*now_ms*/ 100, "model.1", semantic_call("r.1")),
        Err(Error::FeatureContract)
    );
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::ActiveRequests)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}

#[test]
fn semantic_pre_entry_cancel_is_a_distinct_non_execution() {
    let (mut worker, calls) = worker(Reply::Success);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let mut call = semantic_call("r.1");
    call.authorization.cancelled = true;
    assert_eq!(
        worker.run_semantic_retrieval(/*now_ms*/ 100, "model.1", call),
        Err(Error::RequestCancelled)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 0);
    worker
        .unload_model(/*now_ms*/ 100, "model.1")
        .expect("unload");
}

#[test]
fn semantic_observed_token_overrun_is_not_a_valid_completion() {
    let (mut worker, calls) = worker(Reply::Success);
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    let mut call = semantic_call("r.1");
    call.authorization.maximum_tokens = 8;
    call.authorization.reservation_maximum_tokens = 8;
    assert_eq!(
        worker.run_semantic_retrieval(/*now_ms*/ 100, "model.1", call),
        Err(Error::TokenLimit)
    );
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::ActiveRequests)
    );
    assert_eq!(calls.run.load(Ordering::SeqCst), 1);
}
