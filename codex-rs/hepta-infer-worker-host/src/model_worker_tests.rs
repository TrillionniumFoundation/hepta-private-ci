use super::*;

#[path = "model_load_tests.rs"]
mod load_owner_tests;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    fail_run: bool,
    unload_failures: usize,
    dispatch_count: usize,
    unload_handles: Vec<DriverModelHandle>,
    loaded: usize,
}

impl ModelDriver for Driver {
    fn load(&mut self, attempt: &DriverLoadAttempt) -> Result<DriverLoadObservation, Error> {
        self.loaded += 1;
        Ok(DriverLoadObservation {
            attempt: attempt.clone(),
            state: DriverLoadState::Owned(DriverModelHandle {
                opaque_id: format!("handle.{}", attempt.manifest.model_id),
                observed_memory_bytes: 1_024,
            }),
        })
    }

    fn reconcile_load(
        &mut self,
        _attempt: &DriverLoadAttempt,
    ) -> Result<DriverLoadObservation, Error> {
        Err(Error::DriverFailure("no pending test load".to_string()))
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.dispatch_count += 1;
        if self.fail_run {
            return Err(Error::DriverFailure("execution unresolved".to_string()));
        }
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

    fn unload(&mut self, attempt: &DriverLoadAttempt) -> Result<DriverLoadObservation, Error> {
        self.unload_handles.push(DriverModelHandle {
            opaque_id: format!("handle.{}", attempt.manifest.model_id),
            observed_memory_bytes: 1_024,
        });
        if self.unload_failures != 0 {
            self.unload_failures -= 1;
            return Err(Error::DriverFailure("unload unresolved".to_string()));
        }
        self.loaded = self.loaded.saturating_sub(1);
        Ok(DriverLoadObservation {
            attempt: attempt.clone(),
            state: DriverLoadState::Released,
        })
    }
}

impl NeuronFeatureDriver for Driver {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        self.dispatch_count += 1;
        if self.fail_run {
            return Err(Error::DriverFailure("execution unresolved".to_string()));
        }
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

fn load(
    worker: &mut InferenceWorker<Driver>,
    manifest: ModelManifest,
) -> Result<ModelLoadObservation, Error> {
    worker.load_model(
        /*now_ms*/ 100, manifest, /*reserved_memory_bytes*/ 2_048,
    )
}

#[test]
fn loads_runs_and_unloads_exact_model_tuple() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    let loaded = load(&mut worker, manifest()).expect("load");
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
    load(&mut worker, manifest()).expect("load");
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
    load(&mut worker, manifest()).expect("load");
    let observed = worker.run(100, "model.1", request()).expect("run");
    assert_eq!(observed.status, ExecutionStatus::Indeterminate);
    assert!(!observed.terminal_observed);
    assert_eq!(observed.output_digest, None);
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
    load(&mut worker, expected_manifest.clone()).expect("load");
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
    load(&mut worker, manifest()).expect("load");
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
    load(&mut worker, manifest()).expect("load");
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
    load(&mut worker, selected.clone()).expect("load");
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

#[derive(Clone, Copy, Debug)]
enum DispatchPath {
    Tokens,
    NeuronFeatures,
}

fn dispatch(
    worker: &mut InferenceWorker<Driver>,
    path: DispatchPath,
    model_id: &str,
    request_id: &str,
) -> Result<ExecutionStatus, Error> {
    match path {
        DispatchPath::Tokens => {
            let mut value = request();
            value.request_id = request_id.to_string();
            worker
                .run(/*now_ms*/ 100, model_id, value)
                .map(|value| value.status)
        }
        DispatchPath::NeuronFeatures => {
            let mut value = neuron_feature_request();
            value.authorization.request_id = request_id.to_string();
            let digest = canonical_neuron_feature_payload_digest(&value);
            value.authorization.payload_digest = digest.clone();
            value.authorization.lease_payload_digest = digest;
            worker
                .run_neuron_features(/*now_ms*/ 100, model_id, value)
                .map(|value| value.status)
        }
    }
}

#[test]
fn unresolved_execution_keeps_original_request_and_freezes_both_dispatch_paths() {
    for path in [DispatchPath::Tokens, DispatchPath::NeuronFeatures] {
        for fail_run in [false, true] {
            let driver = Driver {
                indeterminate: !fail_run,
                fail_run,
                ..Driver::default()
            };
            let mut worker = InferenceWorker::new(
                /*now_ms*/ 100,
                "worker.1".to_string(),
                /*generation*/ 3,
                grant(),
                driver,
            )
            .expect("worker");
            load(&mut worker, manifest()).expect("load");
            let handle = worker.models["model.1"].handle.clone();
            let expected = if fail_run {
                Err(Error::DriverFailure("execution unresolved".to_string()))
            } else {
                Ok(ExecutionStatus::Indeterminate)
            };
            assert_eq!(
                dispatch(&mut worker, path, "model.1", "request.1"),
                expected
            );
            assert_eq!(
                worker.active_requests,
                BTreeMap::from([("request.1".to_string(), "model.1".to_string())])
            );
            assert_eq!(worker.models["model.1"].active_requests, 1);
            assert_eq!(
                worker.models["model.1"].lifecycle,
                ModelLifecycle::ExecutionUnresolved
            );
            // Even a now-healthy driver cannot silently reconcile the old run.
            worker.driver.fail_run = false;
            worker.driver.indeterminate = false;
            for retry_path in [DispatchPath::Tokens, DispatchPath::NeuronFeatures] {
                assert_eq!(
                    dispatch(&mut worker, retry_path, "model.1", "request.1"),
                    Err(Error::RequestCapacity)
                );
                assert_eq!(
                    dispatch(&mut worker, retry_path, "model.1", "request.2"),
                    Err(Error::ActiveRequests)
                );
            }
            assert_eq!(
                worker.unload_model(/*now_ms*/ 100, "model.1"),
                Err(Error::ActiveRequests)
            );
            assert_eq!(worker.models["model.1"].handle, handle);
            assert_eq!(worker.driver.dispatch_count, 1);
            assert!(worker.driver.unload_handles.is_empty());
            assert_eq!(worker.driver.loaded, 1);
        }
    }
}

#[test]
fn unresolved_execution_keeps_its_worker_capacity_reservation() {
    for path in [DispatchPath::Tokens, DispatchPath::NeuronFeatures] {
        let mut limits = grant();
        limits.maximum_active_requests = 1;
        let driver = Driver {
            indeterminate: true,
            ..Driver::default()
        };
        let mut worker = InferenceWorker::new(
            /*now_ms*/ 100,
            "worker.1".to_string(),
            /*generation*/ 3,
            limits,
            driver,
        )
        .expect("worker");
        load(&mut worker, manifest()).expect("load");
        let mut other = manifest();
        other.model_id = "model.2".to_string();
        load(&mut worker, other).expect("other load");
        assert_eq!(
            dispatch(&mut worker, path, "model.1", "request.1"),
            Ok(ExecutionStatus::Indeterminate)
        );
        assert_eq!(
            dispatch(&mut worker, path, "model.2", "request.2"),
            Err(Error::RequestCapacity)
        );
        assert_eq!(worker.driver.dispatch_count, 1);
    }
}

#[test]
fn observed_terminal_success_and_failure_release_requests_on_both_paths() {
    for path in [DispatchPath::Tokens, DispatchPath::NeuronFeatures] {
        for fail_terminal in [false, true] {
            let driver = Driver {
                fail_terminal,
                ..Driver::default()
            };
            let mut worker = InferenceWorker::new(
                /*now_ms*/ 100,
                "worker.1".to_string(),
                /*generation*/ 3,
                grant(),
                driver,
            )
            .expect("worker");
            load(&mut worker, manifest()).expect("load");
            let expected = if fail_terminal {
                ExecutionStatus::Failed
            } else {
                ExecutionStatus::Succeeded
            };
            assert_eq!(
                dispatch(&mut worker, path, "model.1", "request.1"),
                Ok(expected)
            );
            assert!(worker.active_requests.is_empty());
            assert_eq!(worker.models["model.1"].active_requests, 0);
            assert_eq!(worker.models["model.1"].lifecycle, ModelLifecycle::Ready);
            worker.driver.fail_terminal = false;
            assert_eq!(
                dispatch(&mut worker, path, "model.1", "request.2"),
                Ok(ExecutionStatus::Succeeded)
            );
            assert!(worker.active_requests.is_empty());
            worker
                .unload_model(/*now_ms*/ 100, "model.1")
                .expect("unload");
            assert!(worker.models.is_empty());
            assert_eq!(worker.driver.loaded, 0);
        }
    }
}

#[test]
fn failed_unload_retains_and_freezes_original_handle_until_successful_retry() {
    let driver = Driver {
        unload_failures: 1,
        ..Driver::default()
    };
    let mut worker = InferenceWorker::new(
        /*now_ms*/ 100,
        "worker.1".to_string(),
        /*generation*/ 3,
        grant(),
        driver,
    )
    .expect("worker");
    load(&mut worker, manifest()).expect("load");
    let handle = worker.models["model.1"].handle.clone();
    assert_eq!(
        worker.unload_model(/*now_ms*/ 100, "model.1"),
        Err(Error::DriverFailure("unload unresolved".to_string()))
    );
    assert_eq!(worker.models["model.1"].handle, handle);
    assert_eq!(
        worker.models["model.1"].lifecycle,
        ModelLifecycle::UnloadUnresolved
    );
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(
        load(&mut worker, manifest()),
        Err(Error::ModelAlreadyLoaded)
    );
    for path in [DispatchPath::Tokens, DispatchPath::NeuronFeatures] {
        assert_eq!(
            dispatch(&mut worker, path, "model.1", "request.2"),
            Err(Error::ActiveRequests)
        );
    }
    worker
        .unload_model(/*now_ms*/ 100, "model.1")
        .expect("reconcile unload");
    assert_eq!(
        worker.driver.unload_handles,
        vec![handle.clone().expect("handle"), handle.expect("handle")]
    );
    assert_eq!(worker.driver.dispatch_count, 0);
    assert!(worker.models.is_empty());
    assert!(worker.active_requests.is_empty());
    assert_eq!(worker.driver.loaded, 0);
}
