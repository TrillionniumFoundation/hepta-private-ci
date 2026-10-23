use super::*;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    partial_neuron_output: bool,
    corrupt_neuron_head: bool,
    invalid_model_handle: bool,
    fail_load: bool,
    fail_run: bool,
    fail_unload: bool,
    loaded: usize,
    run_calls: usize,
    unload_calls: usize,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        if self.fail_load {
            return Err(Error::DriverFailure("load outcome unknown".to_string()));
        }
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_model_handle {
                "invalid/handle".to_string()
            } else {
                format!("handle.{}", manifest.model_id)
            },
            observed_memory_bytes: 1_024,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.run_calls += 1;
        if self.fail_run {
            return Err(Error::DriverFailure(
                "execution outcome unknown".to_string(),
            ));
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

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.unload_calls += 1;
        if self.fail_unload {
            return Err(Error::DriverFailure("unload outcome unknown".to_string()));
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
        self.run_calls += 1;
        if self.fail_run {
            return Err(Error::DriverFailure(
                "execution outcome unknown".to_string(),
            ));
        }
        if self.indeterminate {
            return Ok(DriverNeuronFeatureObservation {
                terminal_observed: false,
                succeeded: false,
                encoder_digest: request.encoder_digest.clone(),
                head_digest: request.head_digest.clone(),
                drive_q24: if self.partial_neuron_output {
                    vec![1 << 24; request.expected_output_width]
                } else {
                    Vec::new()
                },
                prediction_q24: if self.partial_neuron_output {
                    vec![0; request.expected_output_width]
                } else {
                    Vec::new()
                },
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
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        grant(),
        Driver::default(),
    ));
    let loaded = checked(worker.load_model(100, manifest()));
    assert!(loaded.terminal_observed);
    let observed = checked(worker.run(100, "model.1", request()));
    assert_eq!(observed.status, ExecutionStatus::Succeeded);
    assert!(observed.terminal_observed);
    worker.driver.fail_terminal = true;
    let failed = checked(worker.run(100, "model.1", request()));
    assert_eq!(failed.status, ExecutionStatus::Failed);
    assert!(worker.active_requests.is_empty());
    assert!(checked(worker.unload_model(100, "model.1")).terminal_observed);
}

#[test]
fn rejected_model_handle_is_unloaded_before_returning_identity_error() {
    let driver = Driver {
        invalid_model_handle: true,
        ..Driver::default()
    };
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.invalid-handle".to_string(),
        3,
        grant(),
        driver,
    ));
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::InvalidIdentity("model handle")),
    );
    assert_eq!(worker.driver.loaded, 0);
    assert_eq!(worker.driver.unload_calls, 1);
    assert!(worker.models.is_empty());
}

#[test]
fn failed_rejected_handle_cleanup_prevents_further_model_loads() {
    let driver = Driver {
        invalid_model_handle: true,
        fail_unload: true,
        ..Driver::default()
    };
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.failed-cleanup".to_string(),
        3,
        grant(),
        driver,
    ));
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::DriverFailure("unload outcome unknown".to_string())),
    );
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.driver.unload_calls, 1);
}

#[test]
fn failed_model_unload_retains_record_and_prevents_further_model_loads() {
    let driver = Driver {
        fail_unload: true,
        ..Driver::default()
    };
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.failed-unload".to_string(),
        3,
        grant(),
        driver,
    ));
    checked(worker.load_model(100, manifest()));
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::DriverFailure("unload outcome unknown".to_string())),
    );
    assert!(worker.models.contains_key("model.1"));
    let mut additional_model = manifest();
    additional_model.model_id = "model.2".to_string();
    assert_eq!(
        worker.load_model(100, additional_model),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(
        worker.run_neuron_features_receipt(100, "model.1", neuron_feature_request()),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.driver.unload_calls, 1);
}

#[test]
fn over_capacity_model_handle_is_unloaded_without_quarantining_worker() {
    let mut limited_grant = grant();
    limited_grant.maximum_memory_bytes = 512;
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.capacity-cleanup".to_string(),
        3,
        limited_grant,
        Driver::default(),
    ));
    for expected_unloads in 1..=2 {
        assert_eq!(
            worker.load_model(100, manifest()),
            Err(Error::ModelCapacity)
        );
        assert_eq!(worker.driver.loaded, 0);
        assert_eq!(worker.driver.unload_calls, expected_unloads);
        assert!(worker.models.is_empty());
    }
}

#[test]
fn failed_capacity_cleanup_prevents_further_model_operations() {
    let mut limited_grant = grant();
    limited_grant.maximum_memory_bytes = 512;
    let driver = Driver {
        fail_unload: true,
        ..Driver::default()
    };
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.capacity-uncertain".to_string(),
        3,
        limited_grant,
        driver,
    ));
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::DriverFailure("unload outcome unknown".to_string())),
    );
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::DriverStateUncertain),
    );
    assert!(worker.models.is_empty());
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.driver.unload_calls, 1);
}

#[test]
fn failed_model_load_prevents_further_model_operations() {
    let driver = Driver {
        fail_load: true,
        ..Driver::default()
    };
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.load-uncertain".to_string(),
        3,
        grant(),
        driver,
    ));
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::DriverFailure("load outcome unknown".to_string())),
    );
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::DriverStateUncertain),
    );
    assert!(worker.models.is_empty());
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.driver.unload_calls, 0);
}

#[derive(Clone, Copy)]
enum ExecutionPath {
    Token,
    NeuronFeature,
}

#[derive(Clone, Copy)]
enum DriverOutcome {
    Indeterminate,
    Failure,
}

fn assert_uncertain_execution_retains_model(path: ExecutionPath, outcome: DriverOutcome) {
    let driver = Driver {
        indeterminate: matches!(outcome, DriverOutcome::Indeterminate),
        fail_run: matches!(outcome, DriverOutcome::Failure),
        ..Driver::default()
    };
    let mut limited_grant = grant();
    limited_grant.maximum_active_requests = 1;
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.execution-uncertain".to_string(),
        3,
        limited_grant,
        driver,
    ));
    checked(worker.load_model(100, manifest()));
    let first = match path {
        ExecutionPath::NeuronFeature => worker
            .run_neuron_features(100, "model.1", neuron_feature_request())
            .map(|observed| observed.status),
        ExecutionPath::Token => worker
            .run(100, "model.1", request())
            .map(|observed| observed.status),
    };
    match outcome {
        DriverOutcome::Failure => assert_eq!(
            first,
            Err(Error::DriverFailure(
                "execution outcome unknown".to_string()
            )),
        ),
        DriverOutcome::Indeterminate => assert_eq!(first, Ok(ExecutionStatus::Indeterminate)),
    }

    let second = match path {
        ExecutionPath::NeuronFeature => worker
            .run_neuron_features(100, "model.1", neuron_feature_request())
            .map(|observed| observed.status),
        ExecutionPath::Token => worker
            .run(100, "model.1", request())
            .map(|observed| observed.status),
    };
    assert_eq!(second, Err(Error::DriverStateUncertain));
    let another_request = match path {
        ExecutionPath::NeuronFeature => {
            let mut another = neuron_feature_request();
            another.authorization.request_id = "request.2".to_string();
            worker
                .run_neuron_features(100, "model.1", another)
                .map(|observed| observed.status)
        }
        ExecutionPath::Token => {
            let mut another = request();
            another.request_id = "request.2".to_string();
            worker
                .run(100, "model.1", another)
                .map(|observed| observed.status)
        }
    };
    assert_eq!(another_request, Err(Error::DriverStateUncertain));
    assert_eq!(
        worker.run_neuron_features_receipt(100, "model.1", neuron_feature_request()),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(worker.driver.run_calls, 1);
    let mut additional_model = manifest();
    additional_model.model_id = "model.2".to_string();
    assert_eq!(
        worker.load_model(100, additional_model),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(
        worker.active_requests.get("request.1").map(String::as_str),
        Some("model.1")
    );
    assert_eq!(
        worker
            .models
            .get("model.1")
            .map(|loaded| loaded.active_requests),
        Some(1)
    );
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.driver.unload_calls, 0);
}

#[test]
fn nonterminal_execution_retains_request_and_prevents_model_operations() {
    assert_uncertain_execution_retains_model(ExecutionPath::Token, DriverOutcome::Indeterminate);
}

#[test]
fn failed_execution_retains_request_and_prevents_model_operations() {
    assert_uncertain_execution_retains_model(ExecutionPath::Token, DriverOutcome::Failure);
}

#[test]
fn nonterminal_feature_execution_retains_request_and_prevents_model_operations() {
    assert_uncertain_execution_retains_model(
        ExecutionPath::NeuronFeature,
        DriverOutcome::Indeterminate,
    );
}

#[test]
fn failed_feature_execution_retains_request_and_prevents_model_operations() {
    assert_uncertain_execution_retains_model(ExecutionPath::NeuronFeature, DriverOutcome::Failure);
}

#[test]
fn rejects_changed_tokenizer_model_or_payload_tuple() {
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        grant(),
        Driver::default(),
    ));
    checked(worker.load_model(100, manifest()));
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
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        grant(),
        driver,
    ));
    checked(worker.load_model(100, manifest()));
    let observed = checked(worker.run(100, "model.1", request()));
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
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        grant(),
        Driver::default(),
    ));
    let expected_manifest = manifest();
    checked(worker.load_model(100, expected_manifest.clone()));
    let observed = checked(worker.run_neuron_features(100, "model.1", neuron_feature_request()));
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
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        grant(),
        Driver::default(),
    ));
    checked(worker.load_model(100, manifest()));
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
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.2".to_string(),
        3,
        grant(),
        driver,
    ));
    checked(worker.load_model(100, manifest()));
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::FeatureOutputMismatch)
    );
}

#[test]
fn neuron_feature_worker_projects_exact_inference_control_receipt() {
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.3".to_string(),
        3,
        grant(),
        Driver::default(),
    ));
    let selected = manifest();
    checked(worker.load_model(100, selected.clone()));
    let receipt =
        checked(worker.run_neuron_features_receipt(100, "model.1", neuron_feature_request()));
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

#[test]
fn failed_neuron_feature_receipt_preserves_status_without_outputs() {
    let driver = Driver {
        fail_terminal: true,
        ..Driver::default()
    };
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.failed".to_string(),
        3,
        grant(),
        driver,
    ));
    checked(worker.load_model(100, manifest()));
    let receipt =
        checked(worker.run_neuron_features_receipt(100, "model.1", neuron_feature_request()));
    assert_eq!(
        (
            receipt.observed_memory_bytes,
            receipt.transient_allocation_bytes,
            receipt.queue_age_micros,
            receipt.latency_micros
        ),
        (1_024, 2_048, 11, 17),
    );
    assert_eq!(
        (receipt.status, receipt.drive_q24, receipt.prediction_q24),
        (
            NeuronFeatureTerminalStatusV1::Failed,
            Vec::new(),
            Vec::new()
        ),
    );
    assert!(worker.active_requests.is_empty());
    checked(worker.unload_model(100, "model.1"));
    assert_eq!(worker.driver.loaded, 0);
}

#[test]
fn indeterminate_neuron_feature_receipt_discards_partial_outputs() {
    let driver = Driver {
        indeterminate: true,
        partial_neuron_output: true,
        ..Driver::default()
    };
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.partial".to_string(),
        3,
        grant(),
        driver,
    ));
    checked(worker.load_model(100, manifest()));
    let receipt =
        checked(worker.run_neuron_features_receipt(100, "model.1", neuron_feature_request()));
    assert_eq!(
        (
            receipt.observed_memory_bytes,
            receipt.transient_allocation_bytes,
            receipt.queue_age_micros,
            receipt.latency_micros
        ),
        (1_024, 2_048, 11, 17),
    );
    assert_eq!(
        (receipt.status, receipt.drive_q24, receipt.prediction_q24),
        (
            NeuronFeatureTerminalStatusV1::Indeterminate,
            Vec::new(),
            Vec::new()
        ),
    );
    assert_eq!(
        worker.active_requests.get("request.1").map(String::as_str),
        Some("model.1")
    );
    assert_eq!(
        worker.run_neuron_features_receipt(100, "model.1", neuron_feature_request()),
        Err(Error::DriverStateUncertain),
    );
    assert_eq!(worker.driver.run_calls, 1);
}

#[test]
fn cancelled_neuron_feature_receipt_preserves_empty_outputs() {
    let mut worker = checked(InferenceWorker::new(
        100,
        "worker.cancelled".to_string(),
        3,
        grant(),
        Driver::default(),
    ));
    checked(worker.load_model(100, manifest()));
    let mut request = neuron_feature_request();
    request.authorization.cancelled = true;
    let receipt = checked(worker.run_neuron_features_receipt(100, "model.1", request));
    assert_eq!(
        (
            receipt.observed_memory_bytes,
            receipt.transient_allocation_bytes,
            receipt.queue_age_micros,
            receipt.latency_micros
        ),
        (1_024, 0, 0, 0),
    );
    assert_eq!(
        (receipt.status, receipt.drive_q24, receipt.prediction_q24),
        (
            NeuronFeatureTerminalStatusV1::Cancelled,
            Vec::new(),
            Vec::new()
        ),
    );
}
