use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    fail_unload: bool,
    fail_load_after_allocation: bool,
    fail_run_after_execution: bool,
    fail_feature_run_after_execution: bool,
    missing_run_output_digest: bool,
    overrun_run_tokens: bool,
    overrun_run_memory: bool,
    reported_run_memory_bytes: u64,
    feature_transient_bytes: u64,
    run_calls: usize,
    feature_run_calls: usize,
    invalid_handle: bool,
    reported_memory_bytes: u64,
    unload_calls: usize,
    loaded: usize,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        if self.fail_load_after_allocation {
            return Err(Error::DriverFailure("injected partial load".to_string()));
        }
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                String::new()
            } else {
                format!("handle.{}", manifest.model_id)
            },
            observed_memory_bytes: if self.reported_memory_bytes == 0 {
                1_024
            } else {
                self.reported_memory_bytes
            },
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.run_calls += 1;
        if self.fail_run_after_execution {
            return Err(Error::DriverFailure(
                "injected unknown run state".to_string(),
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
            output_digest: if self.missing_run_output_digest {
                None
            } else {
                Some("9".repeat(64))
            },
            consumed_tokens: if self.overrun_run_tokens { 65 } else { 16 },
            observed_memory_bytes: if self.overrun_run_memory {
                8_192
            } else if self.reported_run_memory_bytes != 0 {
                self.reported_run_memory_bytes
            } else {
                1_024
            },
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
        self.feature_run_calls += 1;
        if self.fail_feature_run_after_execution {
            return Err(Error::DriverFailure(
                "injected unknown feature state".to_string(),
            ));
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
                transient_allocation_bytes: if self.feature_transient_bytes == 0 {
                    2_048
                } else {
                    self.feature_transient_bytes
                },
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
            transient_allocation_bytes: if self.feature_transient_bytes == 0 {
                2_048
            } else {
                self.feature_transient_bytes
            },
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
    assert!(worker.requires_external_recovery());
    assert_eq!(worker.driver.run_calls, 1);
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ExecutionIndeterminate)
    );
    assert_eq!(
        worker.driver.run_calls, 1,
        "unknown run may not execute twice"
    );
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::ExecutionIndeterminate)
    );
}

#[test]
fn failed_driver_run_is_never_retried_without_external_recovery() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.run-error".to_string(),
        3,
        grant(),
        Driver {
            fail_run_after_execution: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ExecutionIndeterminate)
    );
    assert_eq!(worker.driver.run_calls, 1);
    assert!(worker.requires_external_recovery());
    worker.driver.fail_run_after_execution = false;
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ExecutionIndeterminate)
    );
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ExecutionIndeterminate)
    );
    assert_eq!(worker.driver.run_calls, 1);
    assert_eq!(worker.driver.feature_run_calls, 0);
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::ExecutionIndeterminate)
    );
    let mut other = manifest();
    other.model_id = "model.2".to_string();
    assert_eq!(
        worker.load_model(100, other),
        Err(Error::ExecutionIndeterminate)
    );
}

#[test]
fn malformed_terminal_output_and_post_driver_resource_overruns_fence_generation() {
    for (fixture, first_error) in [
        (
            Driver {
                missing_run_output_digest: true,
                ..Driver::default()
            },
            Error::MissingTerminalOutput,
        ),
        (
            Driver {
                overrun_run_tokens: true,
                ..Driver::default()
            },
            Error::TokenLimit,
        ),
        (
            Driver {
                overrun_run_memory: true,
                ..Driver::default()
            },
            Error::ModelCapacity,
        ),
    ] {
        let mut worker = InferenceWorker::new(
            100,
            "worker.invalid-terminal".to_string(),
            3,
            grant(),
            fixture,
        )
        .expect("worker");
        worker.load_model(100, manifest()).expect("load");
        assert_eq!(worker.run(100, "model.1", request()), Err(first_error));
        assert!(worker.requires_external_recovery());
        assert_eq!(worker.driver.run_calls, 1);
        assert_eq!(
            worker.run(100, "model.1", request()),
            Err(Error::ExecutionIndeterminate)
        );
        assert_eq!(worker.driver.run_calls, 1);
        assert_eq!(
            worker.unload_model(100, "model.1"),
            Err(Error::ExecutionIndeterminate)
        );
    }
}

#[test]
fn unknown_feature_terminal_or_driver_error_requires_external_reconciliation() {
    for error in [false, true] {
        let mut worker = InferenceWorker::new(
            100,
            "worker.feature-unknown".to_string(),
            3,
            grant(),
            Driver {
                indeterminate: !error,
                fail_feature_run_after_execution: error,
                ..Driver::default()
            },
        )
        .expect("worker");
        worker.load_model(100, manifest()).expect("load");
        let result = worker.run_neuron_features(100, "model.1", neuron_feature_request());
        if error {
            assert_eq!(result, Err(Error::ExecutionIndeterminate));
        } else {
            let observation = result.expect("indeterminate terminal observation");
            assert_eq!(observation.status, ExecutionStatus::Indeterminate);
            assert!(!observation.terminal_observed);
        }
        assert!(worker.requires_external_recovery());
        assert_eq!(worker.driver.feature_run_calls, 1);
        assert_eq!(
            worker.run_neuron_features(100, "model.1", neuron_feature_request()),
            Err(Error::ExecutionIndeterminate)
        );
        assert_eq!(worker.driver.feature_run_calls, 1);
    }
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
    assert!(
        worker.requires_external_recovery(),
        "uncertain unload must be visible to the product recovery owner"
    );
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
fn loading_two_models_cannot_double_spend_total_worker_memory() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.aggregate-memory".to_string(),
        3,
        grant(),
        Driver {
            reported_memory_bytes: 3_072,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker
        .load_model(100, manifest())
        .expect("first 3 KiB model");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    assert_eq!(
        worker.load_model(100, second.clone()),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.models.len(), 1);
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.driver.unload_calls, 1);
    assert!(
        !worker.load_indeterminate,
        "successful cleanup permits retry"
    );
    assert!(!worker.requires_external_recovery());

    worker.driver.reported_memory_bytes = 1_024;
    assert!(
        worker.load_model(100, second).is_ok(),
        "3 KiB + 1 KiB meets the grant's exact global 4 KiB limit"
    );
    assert_eq!(worker.models.len(), 2);
}

#[test]
fn generic_run_accounts_for_other_loaded_models_before_accepting_driver_observation() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.generic-aggregate-memory".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("1 KiB model");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    worker.driver.reported_memory_bytes = 3_072;
    worker.load_model(100, second).expect("3 KiB model");
    assert_eq!(worker.models.len(), 2);

    // The selected model reports only 2 KiB, individually below 4 KiB.
    // Together with the other loaded model it exceeds the generation grant.
    worker.driver.reported_run_memory_bytes = 2_048;
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.run_calls, 1);
    assert!(worker.requires_external_recovery());
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ExecutionIndeterminate),
        "post-driver memory violation cannot be replayed in this generation"
    );
    assert_eq!(worker.driver.run_calls, 1);
}

#[test]
fn generic_run_conservatively_retains_loaded_handle_memory_at_grant_boundary() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.generic-resident-floor".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("1 KiB model");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    worker.driver.reported_memory_bytes = 3_072;
    worker.load_model(100, second).expect("3 KiB model");
    worker.driver.reported_run_memory_bytes = 1;
    assert_eq!(
        worker
            .run(100, "model.1", request())
            .expect("1 KiB + 3 KiB still fits conservatively")
            .status,
        ExecutionStatus::Succeeded
    );
    assert!(!worker.requires_external_recovery());
}

#[test]
fn invalid_load_handle_is_cleaned_up_once_before_retry() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.invalid-load-handle".to_string(),
        3,
        grant(),
        Driver {
            invalid_handle: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::InvalidIdentity("model handle"))
    );
    assert_eq!(worker.driver.unload_calls, 1);
    assert_eq!(worker.driver.loaded, 0);
    assert!(worker.models.is_empty());
    assert!(!worker.load_indeterminate);

    worker.driver.invalid_handle = false;
    worker
        .load_model(100, manifest())
        .expect("retry after proven cleanup");
}

#[test]
fn failed_load_rollback_seals_generation_without_losing_capacity_safety() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.load-rollback-failed".to_string(),
        3,
        grant(),
        Driver {
            invalid_handle: true,
            fail_unload: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::ModelLoadIndeterminate)
    );
    assert!(worker.load_indeterminate);
    assert!(worker.requires_external_recovery());
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.driver.unload_calls, 1);
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::ModelLoadIndeterminate)
    );
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelLoadIndeterminate)
    );
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::ModelLoadIndeterminate)
    );
    assert_eq!(worker.driver.unload_calls, 1);
}

#[test]
fn load_driver_error_without_terminal_cleanup_proof_seals_generation() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.ambiguous-load".to_string(),
        3,
        grant(),
        Driver {
            fail_load_after_allocation: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::ModelLoadIndeterminate),
        "an ambiguous first load must report its quarantine state immediately"
    );
    assert_eq!(worker.driver.loaded, 1);
    assert!(worker.load_indeterminate);
    assert!(worker.requires_external_recovery());
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::ModelLoadIndeterminate)
    );
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ModelLoadIndeterminate)
    );
}

#[test]
fn ambiguous_second_model_load_fences_previously_loaded_model() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.existing-model-fenced".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("original model");
    worker.driver.fail_load_after_allocation = true;
    let mut other = manifest();
    other.model_id = "model.2".to_string();
    assert_eq!(
        worker.load_model(100, other),
        Err(Error::ModelLoadIndeterminate)
    );
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelLoadIndeterminate),
        "partial load poisons the whole driver generation, not just new ID"
    );
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::ModelLoadIndeterminate)
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
    assert!(!worker.requires_external_recovery());
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
    assert!(worker.requires_external_recovery());
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ExecutionIndeterminate),
        "a forged Head identity cannot be used as a safe retry baseline"
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
    NoTerminal,
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
    fn preflight_neuron_backend_batch_bytes(
        &self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<u64, Error> {
        // Sequential fixture driver claims a 2 KiB scratch minimum. This is
        // a fabricated test bound, not real process RSS or a tensor benchmark.
        if requests.is_empty() {
            return Err(Error::FeatureBatchLimit);
        }
        handle
            .observed_memory_bytes
            .checked_add(2_048)
            .ok_or(Error::ArithmeticOverflow)
    }

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
            BatchFault::NoTerminal => {
                members[0].observation.terminal_observed = false;
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
                // The mock sequentially materializes one request at a time;
                // the peak includes its 1 KiB handle and 2 KiB scratch.
                // This is NOT a fused tensor backend performance observation.
                3_072
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
    // Distinct request IDs cannot consume the same reservation twice.
    // The reservation ID is outside the feature payload digest, so this
    // regression exercises the explicit batch admission fence.
    let mut duplicate_reservation = two_batch_requests();
    duplicate_reservation[1].authorization.reservation_id = duplicate_reservation[0]
        .authorization
        .reservation_id
        .clone();
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", duplicate_reservation),
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
        assert!(worker.requires_external_recovery());
        assert!(worker.active_requests.is_empty());
        assert_eq!(
            worker.unload_model(100, "model.1"),
            Err(Error::ExecutionIndeterminate)
        );
        assert_eq!(
            worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
            Err(Error::ExecutionIndeterminate)
        );
        assert_eq!(
            worker.driver.backend_calls, 1,
            "unverified batch is never replayed"
        );
    }
}

#[test]
fn batch_driver_error_fences_generation_without_replaying_member_effects() {
    let mut worker = batch_worker(BatchFault::DriverError);
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
        Err(Error::ExecutionIndeterminate)
    );
    assert!(worker.active_requests.is_empty());
    assert_eq!(worker.models["model.1"].active_requests, 0);
    assert!(worker.requires_external_recovery());
    worker.driver.fault = BatchFault::None;
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
        Err(Error::ExecutionIndeterminate)
    );
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ExecutionIndeterminate)
    );
    assert_eq!(worker.driver.backend_calls, 1);
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::ExecutionIndeterminate)
    );
}

#[test]
fn physically_batched_unknown_terminal_denies_all_receipts_and_replay() {
    let mut worker = batch_worker(BatchFault::NoTerminal);
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
        Err(Error::ExecutionIndeterminate)
    );
    assert!(worker.active_requests.is_empty());
    assert!(worker.requires_external_recovery());
    assert_eq!(worker.driver.backend_calls, 1);
    worker.driver.fault = BatchFault::None;
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
        Err(Error::ExecutionIndeterminate)
    );
    assert_eq!(worker.driver.backend_calls, 1);
}

#[test]
fn indeterminate_model_load_fences_native_batch_before_backend_dispatch() {
    let mut worker = batch_worker(BatchFault::None);
    worker.driver.inner.fail_load_after_allocation = true;
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    assert_eq!(
        worker.load_model(100, second),
        Err(Error::ModelLoadIndeterminate)
    );
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
        Err(Error::ModelLoadIndeterminate)
    );
    assert_eq!(
        worker.driver.backend_calls, 0,
        "no batch invocation after an ambiguous load in the same generation"
    );
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

#[test]
fn feature_transient_exceeding_generation_memory_budget_seals_single_request() {
    for transient in [4_096, u64::MAX] {
        let driver = Driver {
            feature_transient_bytes: transient,
            ..Driver::default()
        };
        let mut worker =
            InferenceWorker::new(100, "worker.transient".to_string(), 3, grant(), driver)
                .expect("worker");
        worker.load_model(100, manifest()).expect("load");
        assert_eq!(
            worker.run_neuron_features(100, "model.1", neuron_feature_request()),
            Err(Error::ModelCapacity),
        );
        assert!(worker.requires_external_recovery());
        assert_eq!(
            worker.run_neuron_features(100, "model.1", neuron_feature_request()),
            Err(Error::ExecutionIndeterminate),
        );
        assert_eq!(worker.driver.feature_run_calls, 1);
    }
}

#[test]
fn single_feature_never_uses_driver_underreported_residency_to_hide_scratch_peak() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.feature-resident-floor".to_string(),
        3,
        grant(),
        Driver {
            reported_memory_bytes: 3_072,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker
        .load_model(100, manifest())
        .expect("3 KiB loaded model");

    // The driver's feature observation claims only 1 KiB resident but also
    // allocates 2 KiB scratch. The loader already observed 3 KiB resident,
    // so 3 + 2 KiB exceeds the generation's 4 KiB grant.
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.feature_run_calls, 1);
    assert!(worker.requires_external_recovery());
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ExecutionIndeterminate)
    );
    assert_eq!(worker.driver.feature_run_calls, 1);
}

#[test]
fn feature_transient_plus_other_loaded_model_cannot_exceed_global_grant() {
    let mut resource_grant = grant();
    resource_grant.maximum_memory_bytes = 3_600;
    let mut worker = InferenceWorker::new(
        100,
        "worker.shared-budget".to_string(),
        3,
        resource_grant,
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first model");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    worker.load_model(100, second).expect("second model");
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ModelCapacity),
    );
    assert_eq!(worker.driver.feature_run_calls, 1);
    assert!(worker.requires_external_recovery());
}

#[test]
fn batch_rejects_member_transient_peak_mismatch_and_blocks_retry() {
    for transient in [4_096, u64::MAX] {
        let mut worker = batch_worker(BatchFault::None);
        worker.driver.inner.feature_transient_bytes = transient;
        assert_eq!(
            worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
            Err(Error::FeatureBatchMismatch),
        );
        assert!(worker.requires_external_recovery());
        assert_eq!(worker.driver.backend_calls, 1);
        assert!(worker.active_requests.is_empty());
        assert_eq!(
            worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
            Err(Error::ExecutionIndeterminate),
        );
        assert_eq!(worker.driver.backend_calls, 1);
    }
}

#[test]
fn batch_peak_includes_other_models_loaded_in_worker_generation() {
    let mut worker = batch_worker(BatchFault::None);
    worker.grant.maximum_memory_bytes = 4_095;
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    worker.load_model(100, second).expect("second model load");
    // Include the second live handle in the generation-wide tracked peak
    // BEFORE physical dispatch. Preflight rejection cannot be reclassified
    // as a post-dispatch mismatch or indeterminate execution.
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests()),
        Err(Error::ModelCapacity),
    );
    assert_eq!(worker.driver.backend_calls, 0);
    assert!(!worker.requires_external_recovery());
    // This is an inclusive bound, not a permanent denial after valid
    // preflight; exactly 4096 bytes allows the same requests to execute.
    worker.grant.maximum_memory_bytes = 4_096;
    let success = worker
        .run_neuron_features_backend_batch(100, "model.1", two_batch_requests())
        .expect("same generation can execute at the exact aggregate grant");
    assert_eq!(success.receipts.len(), 2);
    assert_eq!(worker.driver.backend_calls, 1);
}

#[test]
fn neuron_single_feature_respects_loaded_model_token_limit_without_driver_dispatch() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.token-single".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    let mut pinned_manifest = manifest();
    pinned_manifest.maximum_tokens = 32;
    worker.load_model(100, pinned_manifest).expect("model");

    // The lease and reservation themselves are consistent and unexpired.
    // A wider request must still be refused by the selected model manifest.
    let oversized = neuron_feature_request();
    assert_eq!(oversized.authorization.maximum_tokens, 64);
    assert_eq!(
        worker.run_neuron_features(100, "model.1", oversized),
        Err(Error::TokenLimit)
    );
    assert!(
        !worker.requires_external_recovery(),
        "preflight rejection never dispatched"
    );

    let mut bounded = neuron_feature_request();
    bounded.authorization.maximum_tokens = 32;
    let observed = worker
        .run_neuron_features(100, "model.1", bounded)
        .expect("within immutable model token limit");
    assert_eq!(observed.status, ExecutionStatus::Succeeded);
    worker.unload_model(100, "model.1").expect("releasable");
}

#[test]
fn neuron_batch_and_single_share_manifest_token_ceiling_on_cancelled_inputs() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.token-batch".to_string(),
        3,
        grant(),
        MockBatchDriver::default(),
    )
    .expect("worker");
    let mut pinned_manifest = manifest();
    pinned_manifest.maximum_tokens = 32;
    worker.load_model(100, pinned_manifest).expect("model");

    let mut cancelled = neuron_feature_request();
    cancelled.authorization.cancelled = true;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", cancelled),
        Err(Error::TokenLimit),
        "cancellation cannot silently bypass immutable model admission"
    );

    let oversized = two_batch_requests();
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", oversized),
        Err(Error::TokenLimit)
    );
    assert_eq!(worker.driver.backend_calls, 0);
    assert!(!worker.requires_external_recovery());

    let mut bounded = two_batch_requests();
    for request in &mut bounded {
        request.authorization.maximum_tokens = 32;
    }
    let receipts = worker
        .run_neuron_features_backend_batch(100, "model.1", bounded)
        .expect("bounded batch");
    assert_eq!(receipts.receipts.len(), 2);
    assert_eq!(worker.driver.backend_calls, 1);
    worker.unload_model(100, "model.1").expect("releasable");
}

#[test]
fn reservation_token_bound_is_shared_by_generic_single_batch_and_cancelled_neuron_paths() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.reservation-bound".to_string(),
        3,
        grant(),
        MockBatchDriver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("load");

    let mut generic = request();
    generic.reservation_maximum_tokens = 32;
    assert_eq!(worker.run(100, "model.1", generic), Err(Error::TokenLimit));
    assert_eq!(worker.driver.inner.run_calls, 0);

    let mut single = neuron_feature_request();
    single.authorization.reservation_maximum_tokens = 32;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", single),
        Err(Error::TokenLimit)
    );
    assert_eq!(worker.driver.inner.feature_run_calls, 0);

    let mut cancelled = neuron_feature_request();
    cancelled.authorization.cancelled = true;
    cancelled.authorization.reservation_maximum_tokens = 32;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", cancelled),
        Err(Error::TokenLimit),
        "cancellation cannot bypass a narrower reservation"
    );

    let mut members = two_batch_requests();
    members[1].authorization.reservation_maximum_tokens = 32;
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", members),
        Err(Error::TokenLimit)
    );
    assert_eq!(worker.driver.backend_calls, 0);
    assert!(
        !worker.requires_external_recovery(),
        "all rejected before backend"
    );

    assert_eq!(
        worker
            .run_neuron_features(100, "model.1", neuron_feature_request())
            .expect("legitimate reserved request")
            .status,
        ExecutionStatus::Succeeded
    );
    assert_eq!(worker.driver.inner.feature_run_calls, 1);
}

#[test]
fn native_backend_batch_preflight_respects_other_models_generation_budget() {
    let mut worker = batch_worker(BatchFault::None);
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    worker
        .load_model(100, second)
        .expect("both models independently fit generation budget");

    // The selected batch requires 3 KiB tracked numeric memory, while another
    // loaded handle retains 1 KiB. Global grant 4,095 B must reject BEFORE
    // dispatch, even though the individual batch would fit that grant.
    worker.grant.maximum_memory_bytes = 4_095;
    assert_eq!(
        worker.run_neuron_features_backend_batch(100, "model.1", two_batch_requests(),),
        Err(Error::ModelCapacity),
    );
    assert_eq!(worker.driver.backend_calls, 0);
    assert!(!worker.requires_external_recovery());

    worker.grant.maximum_memory_bytes = 4_096;
    let receipts = worker
        .run_neuron_features_backend_batch(100, "model.1", two_batch_requests())
        .expect("exact inclusive whole-generation budget");
    assert_eq!(receipts.receipts.len(), 2);
    assert_eq!(worker.driver.backend_calls, 1);
}
