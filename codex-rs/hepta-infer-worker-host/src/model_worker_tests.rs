use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    fail_unload: bool,
    unload_calls: usize,
    loaded: usize,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        Ok(DriverModelHandle {
            opaque_id: format!("handle.{}", manifest.model_id),
            observed_memory_bytes: 1_024,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        if self.indeterminate {
            return Ok(DriverRunObservation {
                terminal_observed: false,
                succeeded: false,
                output_digest: None,
                consumed_tokens: 4,
                observed_memory_bytes: 1_024,
            });
        }
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            output_digest: Some("9".repeat(64)),
            consumed_tokens: 16,
            observed_memory_bytes: 1_024,
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.unload_calls += 1;
        if self.fail_unload {
            return Err(Error::DriverFailure("injected unload failure".to_string()));
        }
        self.loaded = self.loaded.saturating_sub(1);
        Ok(())
    }
}

impl NeuronFeatureDriver for Driver {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        if self.indeterminate {
            return Ok(DriverNeuronFeatureObservation {
                terminal_observed: false,
                succeeded: false,
                encoder_digest: request.encoder_digest.clone(),
                head_digest: request.head_digest.clone(),
                drive_q24: Vec::new(),
                prediction_q24: Vec::new(),
                observed_memory_bytes: 1_024,
                transient_allocation_bytes: 2_048,
                queue_age_micros: 11,
                latency_micros: 17,
            });
        }
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: if self.corrupt_neuron_head {
                "f".repeat(64)
            } else {
                request.head_digest.clone()
            },
            drive_q24: vec![1 << 24; request.expected_output_width],
            prediction_q24: vec![0; request.expected_output_width],
            observed_memory_bytes: 1_024,
            transient_allocation_bytes: 2_048,
            queue_age_micros: 11,
            latency_micros: 17,
        })
    }
}

fn grant() -> ResourceGrant {
    ResourceGrant {
        grant_id: "grant.1".to_string(),
        authority_epoch: 2,
        generation: 3,
        expires_at_ms: 10_000,
        revoked: false,
        maximum_models: 2,
        maximum_active_requests: 4,
        maximum_memory_bytes: 4_096,
        semantic_digest: "1".repeat(64),
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

fn request() -> WorkerRequest {
    WorkerRequest {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        model_digest: "2".repeat(64),
        payload_digest: "3".repeat(64),
        maximum_tokens: 64,
        deadline_ms: 9_000,
        lease_payload_digest: "3".repeat(64),
        reservation_model_digest: "2".repeat(64),
        reservation_maximum_tokens: 64,
        cancelled: false,
    }
}

#[test]
fn loads_runs_and_unloads_exact_model_tuple() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    let loaded = worker.load_model(100, manifest()).expect("load");
    assert!(loaded.terminal_observed);
    let observed = worker.run(100, "model.1", request()).expect("run");
    assert_eq!(observed.status, ExecutionStatus::Succeeded);
    assert!(observed.terminal_observed);
    assert!(
        worker
            .unload_model(100, "model.1")
            .expect("unload")
            .terminal_observed
    );
}

#[test]
fn rejects_changed_tokenizer_model_or_payload_tuple() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let mut changed = request();
    changed.lease_payload_digest = "4".repeat(64);
    assert_eq!(
        worker.run(100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );
    let mut changed = request();
    changed.reservation_model_digest = "5".repeat(64);
    assert_eq!(
        worker.run(100, "model.1", changed),
        Err(Error::ModelMismatch)
    );
}

#[test]
fn lost_driver_terminality_is_indeterminate() {
    let driver = Driver {
        indeterminate: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let observed = worker.run(100, "model.1", request()).expect("run");
    assert_eq!(observed.status, ExecutionStatus::Indeterminate);
    assert!(!observed.terminal_observed);
    assert_eq!(observed.output_digest, None);
}

#[test]
fn uncertain_unload_remains_accounted_and_rejects_all_future_use() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.unload-failed".to_string(),
        3,
        grant(),
        Driver {
            fail_unload: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::DriverFailure("injected unload failure".to_string()))
    );
    assert_eq!(worker.models.len(), 1, "model capacity remains occupied");
    assert_eq!(
        worker.driver.loaded, 1,
        "driver resource is not claimed freed"
    );
    assert_eq!(worker.driver.unload_calls, 1);
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelUnloadIndeterminate)
    );
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ModelUnloadIndeterminate)
    );
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::ModelUnloadIndeterminate),
        "potentially non-idempotent release is never retried in this generation"
    );
    assert_eq!(worker.driver.unload_calls, 1);
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::ModelAlreadyLoaded),
        "unresolved model cannot be replaced with a fresh handle"
    );
}

#[test]
fn observed_unload_releases_the_registered_handle_once() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.unload-ok".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert!(
        worker
            .unload_model(100, "model.1")
            .expect("unload")
            .terminal_observed
    );
    assert_eq!(worker.driver.loaded, 0);
    assert_eq!(worker.driver.unload_calls, 1);
    assert_eq!(worker.models.len(), 0);
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelNotLoaded)
    );
}

fn neuron_feature_request() -> NeuronFeatureRequest {
    let mut value = NeuronFeatureRequest {
        authorization: request(),
        encoder_digest: "a".repeat(64),
        head_digest: "b".repeat(64),
        weights_digest: manifest().weights_digest,
        input_digest: "c".repeat(64),
        feature_vector_q24: vec![1 << 22, -(1 << 21)],
        expected_output_width: 5,
    };
    let payload = canonical_neuron_feature_payload_digest(&value);
    value.authorization.payload_digest = payload.clone();
    value.authorization.lease_payload_digest = payload;
    value
}

#[test]
fn executes_authenticated_neuron_feature_tuple_from_loaded_manifest() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    let expected_manifest = manifest();
    worker
        .load_model(100, expected_manifest.clone())
        .expect("load");
    let observed = worker
        .run_neuron_features(100, "model.1", neuron_feature_request())
        .expect("neuron features");
    assert_eq!(observed.status, ExecutionStatus::Succeeded);
    assert_eq!(observed.manifest, expected_manifest);
    assert_eq!(observed.encoder_digest, "a".repeat(64));
    assert_eq!(observed.head_digest, "b".repeat(64));
    assert_eq!(observed.drive_q24, vec![1 << 24; 5]);
    assert_eq!(observed.prediction_q24, vec![0; 5]);
    assert_eq!(observed.transient_allocation_bytes, 2_048);
    assert!(observed.terminal_observed);
}

#[test]
fn neuron_feature_path_rejects_payload_drift_and_driver_identity_drift() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let mut changed = neuron_feature_request();
    changed.feature_vector_q24[0] += 1;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );

    let driver = Driver {
        corrupt_neuron_head: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.2".to_string(), 3, grant(), driver).expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::FeatureOutputMismatch)
    );
}

#[test]
fn neuron_feature_worker_projects_exact_inference_control_receipt() {
    let mut worker =
        InferenceWorker::new(100, "worker.3".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    let selected = manifest();
    worker.load_model(100, selected.clone()).expect("load");
    let receipt = worker
        .run_neuron_features_receipt(100, "model.1", neuron_feature_request())
        .expect("typed feature receipt");
    assert_eq!(
        receipt.runtime_tuple.weights_digest.to_string(),
        selected.weights_digest
    );
    assert_eq!(
        receipt.runtime_tuple.tokenizer_digest.to_string(),
        selected.tokenizer_digest
    );
    assert_eq!(receipt.drive_q24, vec![1 << 24; 5]);
    assert_eq!(
        receipt.status,
        codex_hepta_infer_core::NeuronFeatureTerminalStatusV1::Succeeded
    );
    assert!(!receipt.receipt_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}

#[derive(Clone, Copy, Debug, Default)]
enum BatchFault {
    #[default]
    None,
    Swapped,
    Missing,
    WrongDigest,
    WrongMemory,
    DriverError,
}

#[derive(Debug, Default)]
struct MockBatchDriver {
    inner: Driver,
    backend_calls: usize,
    fault: BatchFault,
}

impl ModelDriver for MockBatchDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.inner.load(manifest)
    }

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.inner.run(handle, request)
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        self.inner.unload(handle)
    }
}

impl NeuronFeatureDriver for MockBatchDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        self.inner.run_neuron_features(handle, request)
    }
}

impl NeuronBackendBatchDriver for MockBatchDriver {
    fn run_neuron_backend_batch(
        &mut self,
        handle: &DriverModelHandle,
        batch_digest: &str,
        requests: &[NeuronFeatureRequest],
    ) -> Result<DriverNeuronBackendBatch, Error> {
        self.backend_calls += 1;
        if matches!(self.fault, BatchFault::DriverError) {
            return Err(Error::DriverFailure("mock backend failure".to_string()));
        }
        // This mock deliberately loops: it proves worker admission/receipt
        // behavior, NOT execution of a fused tensor batch on target hardware.
        let mut members = requests
            .iter()
            .map(|request| {
                Ok(DriverNeuronBatchMember {
                    request_id: request.authorization.request_id.clone(),
                    input_digest: request.input_digest.clone(),
                    observation: self.inner.run_neuron_features(handle, request)?,
                })
            })
            .collect::<Result<Vec<_>, Error>>()?;
        match self.fault {
            BatchFault::Swapped => members.swap(0, 1),
            BatchFault::Missing => {
                members.pop();
            }
            BatchFault::None
            | BatchFault::WrongDigest
            | BatchFault::WrongMemory
            | BatchFault::DriverError => {}
        }
        Ok(DriverNeuronBackendBatch {
            batch_digest: if matches!(self.fault, BatchFault::WrongDigest) {
                "0".repeat(64)
            } else {
                batch_digest.to_string()
            },
            members,
            observed_peak_memory_bytes: if matches!(self.fault, BatchFault::WrongMemory) {
                8_192
            } else {
                1_024
            },
            backend_elapsed_micros: 120,
        })
    }
}

fn two_batch_requests() -> Vec<NeuronFeatureRequest> {
    let first = neuron_feature_request();
    let mut second = neuron_feature_request();
    second.authorization.request_id = "request.2".to_string();
    second.authorization.reservation_id = "reservation.2".to_string();
    second.head_digest = "d".repeat(64);
    second.input_digest = "e".repeat(64);
    second.feature_vector_q24 = vec![1 << 21, -(1 << 20)];
    let payload = canonical_neuron_feature_payload_digest(&second);
    second.authorization.payload_digest = payload.clone();
    second.authorization.lease_payload_digest = payload;
    vec![first, second]
}

fn batch_worker(fault: BatchFault) -> InferenceWorker<MockBatchDriver> {
    let mut worker = InferenceWorker::new(
        100,
        "worker.batch".to_string(),
        3,
        grant(),
        MockBatchDriver {
            fault,
            ..MockBatchDriver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("model");
    worker
}

#[test]
fn native_batch_boundary_calls_driver_once_and_binds_distinct_cell_heads() {
    let mut worker = batch_worker(BatchFault::None);
    let requests = two_batch_requests();
    let expected = canonical_neuron_batch_digest("model.1", 3, &requests);
    let result = worker
        .run_neuron_features_backend_batch(100, "model.1", requests)
        .expect("batch");
    assert_eq!(worker.driver.backend_calls, 1);
    assert_eq!(result.batch_digest, expected);
    assert_eq!(result.backend_elapsed_micros, 120);
    assert_eq!(result.receipts.len(), 2);
    assert_ne!(
        result.receipts[0].request_digest,
        result.receipts[1].request_digest
    );
    assert_ne!(
        result.receipts[0].receipt_digest,
        result.receipts[1].receipt_digest
    );
    assert_eq!(result.receipts[0].head_digest.to_string(), "b".repeat(64));
    assert_eq!(result.receipts[1].head_digest.to_string(), "d".repeat(64));
    assert!(result.receipts.iter().all(|r| !r.authority.grants_any()));
    worker.unload_model(100, "model.1").expect("released");
}

#[test]
fn batch_preflight_rejects_partial_payload_and_duplicate_without_dispatch() {
    let mut worker = batch_worker(BatchFault::None);
    let mut changed = two_batch_requests();
    changed[1].feature_vector_q24[0] += 1;
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );
    let mut duplicate = two_batch_requests();
    duplicate[1].authorization.request_id = duplicate[0].authorization.request_id.clone();
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", duplicate),
        Err(Error::FeatureBatchMismatch)
    );
    let mut mixed = two_batch_requests();
    mixed[1].encoder_digest = "f".repeat(64);
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", mixed),
        Err(Error::FeatureBatchMismatch)
    );
    assert_eq!(worker.driver.backend_calls, 0);
    worker.unload_model(100, "model.1").expect("released");
}

#[test]
fn batch_rejects_wrong_member_order_and_missing_or_forged_driver_evidence() {
    for fault in [
        BatchFault::Swapped,
        BatchFault::Missing,
        BatchFault::WrongDigest,
        BatchFault::WrongMemory,
    ] {
        let mut worker = batch_worker(fault);
        assert!(
            worker
                .run_neuron_features_backend_batch(100, "model.1", two_batch_requests())
                .is_err()
        );
        assert_eq!(worker.driver.backend_calls, 1);
        worker.unload_model(100, "model.1").expect("released");
    }
}

#[test]
fn batch_driver_error_releases_active_ids_and_allows_retry() {
    let mut worker = batch_worker(BatchFault::DriverError);
    assert!(matches!(
        worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
        Err(Error::DriverFailure(_))
    ));
    worker.driver.fault = BatchFault::None;
    assert_eq!(
        worker
            .run_neuron_features_backend_batch(100, "model.1", two_batch_requests())
            .expect("retry")
            .receipts
            .len(),
        2
    );
    worker.unload_model(100, "model.1").expect("released");
}

#[test]
fn batch_capacity_and_cancelled_requests_fail_closed() {
    let mut worker = batch_worker(BatchFault::None);
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", vec![neuron_feature_request()]),
        Err(Error::FeatureBatchLimit)
    );
    let mut cancelled = two_batch_requests();
    cancelled[1].authorization.cancelled = true;
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", cancelled),
        Err(Error::FeatureBatchMismatch)
    );
    let mut too_many = Vec::new();
    for i in 0..5 {
        let mut request = neuron_feature_request();
        request.authorization.request_id = format!("request.{i}");
        too_many.push(request);
    }
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", too_many),
        Err(Error::RequestCapacity)
    );
    assert_eq!(worker.driver.backend_calls, 0);
    worker.unload_model(100, "model.1").expect("released");
}

#[test]
fn failed_release_blocks_native_backend_batch_without_dispatch() {
    let mut worker = batch_worker(BatchFault::None);
    worker.driver.inner.fail_unload = true;
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::DriverFailure("injected unload failure".to_string()))
    );
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
        Err(Error::ModelUnloadIndeterminate)
    );
    assert_eq!(worker.driver.backend_calls, 0);
    assert_eq!(worker.driver.inner.unload_calls, 1);
    assert_eq!(worker.models.len(), 1);
}
