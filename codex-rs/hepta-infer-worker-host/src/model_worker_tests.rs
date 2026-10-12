use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    neuron_calls: usize,
    loaded: usize,
    unload_attempts: usize,
    fail_load: bool,
    fail_unload: bool,
    fail_run: bool,
    panic_run: bool,
    missing_run_output: bool,
    malformed_run_output: bool,
    run_consumed_tokens: Option<u32>,
    run_memory_bytes: Option<u64>,
    invalid_handle: bool,
    shared_handle: bool,
    memory_bytes: Option<u64>,
    neuron_consumed_tokens: Option<u32>,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if self.fail_load {
            return Err(Error::DriverFailure("ambiguous physical load".into()));
        }
        self.loaded += 1;
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                "invalid handle".to_owned()
            } else if self.shared_handle {
                "shared.handle".to_owned()
            } else {
                format!("handle.{}", manifest.model_id)
            },
            observed_memory_bytes: self.memory_bytes.unwrap_or(1_024),
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        if self.panic_run {
            panic!("physical driver panic after invocation started");
        }
        if self.fail_run {
            return Err(Error::DriverFailure("uncertain model execution".into()));
        }
        if self.indeterminate {
            return Ok(DriverRunObservation {
                terminal_observed: false,
                succeeded: false,
                output_digest: None,
                consumed_tokens: self.run_consumed_tokens.unwrap_or(4),
                observed_memory_bytes: self.run_memory_bytes.unwrap_or(1_024),
            });
        }
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            output_digest: if self.missing_run_output {
                None
            } else if self.malformed_run_output {
                Some("invalid-output".into())
            } else {
                Some("9".repeat(64))
            },
            consumed_tokens: self.run_consumed_tokens.unwrap_or(16),
            observed_memory_bytes: self.run_memory_bytes.unwrap_or(1_024),
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.unload_attempts += 1;
        if self.fail_unload {
            return Err(Error::DriverFailure("unknown physical unload".into()));
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
        self.neuron_calls += 1;
        if self.indeterminate {
            return Ok(DriverNeuronFeatureObservation {
                terminal_observed: false,
                succeeded: false,
                consumed_tokens: self.neuron_consumed_tokens.unwrap_or(4),
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
            consumed_tokens: self.neuron_consumed_tokens.unwrap_or(4),
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
    assert!(worker.is_quarantined());
    let mut fresh = request();
    fresh.request_id = "request.after-unknown".into();
    assert_eq!(
        worker.run(100, "model.1", fresh),
        Err(Error::WorkerQuarantined)
    );
}

#[test]
fn generic_driver_error_quarantines_worker_across_new_reservations() {
    let driver = Driver {
        fail_run: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.driver-unknown".into(), 3, grant(), driver).unwrap();
    worker.load_model(100, manifest()).unwrap();
    assert!(matches!(
        worker.run(100, "model.1", request()),
        Err(Error::DriverFailure(_))
    ));
    assert!(worker.is_quarantined());
    worker.driver.fail_run = false;
    let mut fresh = request();
    fresh.request_id = "request.fresh-after-driver-error".into();
    assert_eq!(
        worker.run(100, "model.1", fresh),
        Err(Error::WorkerQuarantined)
    );
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::WorkerQuarantined)
    );
}

#[test]
fn generic_driver_panic_cannot_reopen_a_partially_executed_worker() {
    let driver = Driver {
        panic_run: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.driver-panic".into(), 3, grant(), driver).unwrap();
    worker.load_model(100, manifest()).unwrap();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        worker.run(100, "model.1", request())
    }));
    assert!(result.is_err());
    assert!(worker.is_quarantined());
    worker.driver.panic_run = false;
    let mut fresh = request();
    fresh.request_id = "request.new-after-panic".into();
    assert_eq!(
        worker.run(100, "model.1", fresh),
        Err(Error::WorkerQuarantined)
    );
}

#[test]
fn generic_post_driver_resource_overruns_quarantine_worker() {
    for (worker_id, consumed, memory) in [
        ("worker.token-overrun", Some(65), None),
        ("worker.memory-overrun", None, Some(8_192)),
    ] {
        let driver = Driver {
            run_consumed_tokens: consumed,
            run_memory_bytes: memory,
            ..Driver::default()
        };
        let mut worker = InferenceWorker::new(100, worker_id.into(), 3, grant(), driver).unwrap();
        worker.load_model(100, manifest()).unwrap();
        assert!(worker.run(100, "model.1", request()).is_err());
        assert!(worker.is_quarantined());
        let mut fresh = request();
        fresh.request_id = format!("request.fresh.{worker_id}");
        assert_eq!(
            worker.run(100, "model.1", fresh),
            Err(Error::WorkerQuarantined)
        );
    }
}

#[test]
fn generic_post_driver_corrupt_output_quarantines_worker() {
    for (worker_id, missing, malformed) in [
        ("worker.missing-output", true, false),
        ("worker.invalid-output", false, true),
    ] {
        let driver = Driver {
            missing_run_output: missing,
            malformed_run_output: malformed,
            ..Driver::default()
        };
        let mut worker = InferenceWorker::new(100, worker_id.into(), 3, grant(), driver).unwrap();
        worker.load_model(100, manifest()).unwrap();
        assert!(worker.run(100, "model.1", request()).is_err());
        assert!(worker.is_quarantined());
    }
}

#[test]
fn explicit_terminal_failure_does_not_poison_healthy_generic_driver() {
    let driver = Driver {
        fail_terminal: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.terminal-failed".into(), 3, grant(), driver).unwrap();
    worker.load_model(100, manifest()).unwrap();
    let observed = worker.run(100, "model.1", request()).unwrap();
    assert_eq!(observed.status, ExecutionStatus::Failed);
    assert!(observed.terminal_observed);
    assert!(!worker.is_quarantined());
    worker.driver.fail_terminal = false;
    let mut fresh = request();
    fresh.request_id = "request.terminal-followup".into();
    let observed = worker.run(100, "model.1", fresh).unwrap();
    assert_eq!(observed.status, ExecutionStatus::Succeeded);
    assert!(!worker.is_quarantined());
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
    assert!(
        worker.is_quarantined(),
        "post-driver identity corruption quarantines the Worker"
    );
}

#[test]
fn typed_neuron_worker_enforces_model_and_reservation_token_limits_before_driver() {
    let mut constrained = manifest();
    constrained.maximum_tokens = 16;
    let mut worker = InferenceWorker::new(
        100,
        "worker.typed-token-ceiling".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .unwrap();
    worker.load_model(100, constrained).unwrap();

    // Worker model is frozen at 16, but the typed request asks for 64.
    let too_large = neuron_feature_request();
    assert_eq!(
        worker.run_neuron_features(100, "model.1", too_large.clone()),
        Err(Error::TokenLimit)
    );
    assert_eq!(worker.driver.neuron_calls, 0);
    // A failed pre-driver attempt still consumed this identity; never replay.
    assert_eq!(
        worker.run_neuron_features(100, "model.1", too_large),
        Err(Error::NeuronReservationReplay)
    );

    // Even within the model's budget, do not exceed the reservation quota.
    let mut unreserved = neuron_feature_request();
    unreserved.authorization.request_id = "request.token2".to_string();
    unreserved.authorization.reservation_id = "reservation.token2".to_string();
    unreserved.authorization.maximum_tokens = 16;
    unreserved.authorization.reservation_maximum_tokens = 8;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", unreserved),
        Err(Error::TokenLimit)
    );
    assert_eq!(worker.driver.neuron_calls, 0);

    // A distinct, legitimately bounded identity reaches the actual driver.
    let mut valid = neuron_feature_request();
    valid.authorization.request_id = "request.token3".to_string();
    valid.authorization.reservation_id = "reservation.token3".to_string();
    valid.authorization.maximum_tokens = 16;
    valid.authorization.reservation_maximum_tokens = 16;
    let observation = worker.run_neuron_features(100, "model.1", valid).unwrap();
    assert_eq!(observation.status, ExecutionStatus::Succeeded);
    assert_eq!(worker.driver.neuron_calls, 1);
}

#[test]
fn typed_neuron_driver_actual_token_overrun_is_rejected_and_cannot_replay() {
    let driver = Driver {
        neuron_consumed_tokens: Some(17),
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.typed-usage".to_owned(), 3, grant(), driver).unwrap();
    let mut constrained = manifest();
    constrained.maximum_tokens = 16;
    worker.load_model(100, constrained).unwrap();
    let mut request = neuron_feature_request();
    request.authorization.maximum_tokens = 16;
    request.authorization.reservation_maximum_tokens = 16;
    // The request passed both pre-driver token caps. The backend then
    // actually consumed 17 and must never become a successful typed receipt.
    assert_eq!(
        worker.run_neuron_features(100, "model.1", request.clone()),
        Err(Error::TokenLimit)
    );
    assert_eq!(worker.driver.neuron_calls, 1);
    assert!(worker.is_quarantined());
    assert_eq!(
        worker.run_neuron_features(100, "model.1", request),
        Err(Error::NeuronReservationReplay)
    );

    let mut fresh = neuron_feature_request();
    fresh.authorization.request_id = "request.usage2".to_owned();
    fresh.authorization.reservation_id = "reservation.usage2".to_owned();
    fresh.authorization.maximum_tokens = 16;
    fresh.authorization.reservation_maximum_tokens = 16;
    worker.driver.neuron_consumed_tokens = Some(16);
    assert_eq!(
        worker.run_neuron_features(100, "model.1", fresh),
        Err(Error::WorkerQuarantined),
        "a fresh reservation must not rehabilitate an overrun backend"
    );
    assert_eq!(worker.driver.neuron_calls, 1);
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

#[test]
fn worker_owned_neuron_attempt_log_blocks_direct_feature_replay() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.replay".to_owned(),
        3,
        grant(),
        Driver::default(),
    )
    .unwrap();
    worker.load_model(100, manifest()).unwrap();
    let request = neuron_feature_request();
    assert!(
        worker
            .run_neuron_features(100, "model.1", request.clone())
            .is_ok()
    );
    assert_eq!(
        worker.run_neuron_features(100, "model.1", request),
        Err(Error::NeuronReservationReplay)
    );
}

#[test]
fn neuron_attempt_capacity_fails_closed_without_eviction() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.capacity".to_owned(),
        3,
        grant(),
        Driver::default(),
    )
    .unwrap();
    let mut authorization = request();
    for index in 0..MAX_NEURON_ATTEMPTS {
        authorization.request_id = format!("request.{index}");
        authorization.reservation_id = format!("reservation.{index}");
        worker.consume_neuron_attempt(&authorization).unwrap();
    }
    authorization.request_id = "request.overflow".to_owned();
    authorization.reservation_id = "reservation.overflow".to_owned();
    assert_eq!(
        worker.consume_neuron_attempt(&authorization),
        Err(Error::NeuronReservationCapacity)
    );
    // A later attempt cannot evict an older tombstone to make room.
    authorization.request_id = "request.0".to_owned();
    authorization.reservation_id = "reservation.overflow".to_owned();
    assert_eq!(
        worker.consume_neuron_attempt(&authorization),
        Err(Error::NeuronReservationReplay)
    );
}

#[test]
fn model_load_enforces_aggregate_resident_budget_and_reclaims_rejected_handle() {
    let mut budget = grant();
    budget.maximum_memory_bytes = 2_000;
    let mut worker =
        InferenceWorker::new(100, "worker.total-rss".into(), 3, budget, Driver::default()).unwrap();
    worker.load_model(100, manifest()).unwrap();
    let mut second = manifest();
    second.model_id = "model.2".into();
    assert_eq!(worker.load_model(100, second), Err(Error::ModelCapacity));
    assert!(!worker.is_quarantined());
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.driver.unload_attempts, 1);
    assert_eq!(worker.models.len(), 1);
    assert!(worker.run(100, "model.1", request()).is_ok());
}

#[test]
fn invalid_or_zero_resource_model_handle_is_unloaded_before_returning_error() {
    let driver = Driver {
        invalid_handle: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.bad-handle".into(), 3, grant(), driver).unwrap();
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::InvalidIdentity("model handle"))
    );
    assert_eq!(worker.driver.loaded, 0);
    assert_eq!(worker.driver.unload_attempts, 1);
    assert!(!worker.is_quarantined());
    worker.driver.invalid_handle = false;
    worker.driver.memory_bytes = Some(0);
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.loaded, 0);
    assert_eq!(worker.driver.unload_attempts, 2);
    assert!(!worker.is_quarantined());
    worker.driver.memory_bytes = None;
    worker.load_model(100, manifest()).unwrap();
}

#[test]
fn unknown_load_or_cleanup_failure_quarantines_worker_for_entire_generation() {
    let driver = Driver {
        fail_load: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.load-fail".into(), 3, grant(), driver).unwrap();
    assert!(matches!(
        worker.load_model(100, manifest()),
        Err(Error::DriverFailure(_))
    ));
    worker.driver.fail_load = false;
    assert!(worker.is_quarantined());
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::WorkerQuarantined)
    );

    let driver = Driver {
        fail_unload: true,
        memory_bytes: Some(10_000),
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.cleanup-fail".into(), 3, grant(), driver).unwrap();
    assert!(matches!(
        worker.load_model(100, manifest()),
        Err(Error::DriverFailure(_))
    ));
    assert!(worker.is_quarantined());
    assert_eq!(worker.driver.loaded, 1);
    worker.driver.fail_unload = false;
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::WorkerQuarantined)
    );
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::WorkerQuarantined)
    );
}

#[test]
fn failed_unload_preserves_occupied_handle_and_never_reuses_budget() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.unknown-unload".into(),
        3,
        grant(),
        Driver::default(),
    )
    .unwrap();
    worker.load_model(100, manifest()).unwrap();
    worker.driver.fail_unload = true;
    assert!(matches!(
        worker.unload_model(100, "model.1"),
        Err(Error::DriverFailure(_))
    ));
    assert!(worker.is_quarantined());
    assert_eq!(worker.models.len(), 1);
    assert_eq!(worker.driver.loaded, 1);
    worker.driver.fail_unload = false;
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::WorkerQuarantined)
    );
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::WorkerQuarantined)
    );
}

#[test]
fn driver_reused_opaque_handle_quarantines_instead_of_unloading_live_model() {
    let driver = Driver {
        shared_handle: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.alias-handle".into(), 3, grant(), driver).unwrap();
    worker.load_model(100, manifest()).unwrap();
    let mut second = manifest();
    second.model_id = "model.2".into();
    assert_eq!(
        worker.load_model(100, second),
        Err(Error::ModelHandleConflict)
    );
    assert!(worker.is_quarantined());
    // Unloading an alias might release the *already live* first model.
    assert_eq!(worker.driver.unload_attempts, 0);
    assert_eq!(worker.models.len(), 1);
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::WorkerQuarantined)
    );
}

#[test]
fn unobserved_physical_neuron_terminality_quarantines_backend_for_new_requests() {
    let driver = Driver {
        indeterminate: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.neuron-unknown".to_owned(), 3, grant(), driver).unwrap();
    worker.load_model(100, manifest()).unwrap();
    let observed = worker
        .run_neuron_features(100, "model.1", neuron_feature_request())
        .unwrap();
    assert_eq!(observed.status, ExecutionStatus::Indeterminate);
    assert!(!observed.terminal_observed);
    assert!(worker.is_quarantined());
    let mut fresh = neuron_feature_request();
    fresh.authorization.request_id = "request.unknown2".into();
    fresh.authorization.reservation_id = "reservation.unknown2".into();
    worker.driver.indeterminate = false;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", fresh),
        Err(Error::WorkerQuarantined)
    );
    assert_eq!(worker.driver.neuron_calls, 1);
}

#[test]
fn invalid_pre_driver_neuron_request_does_not_quarantine_healthy_backend() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.neuron-preflight".to_owned(),
        3,
        grant(),
        Driver::default(),
    )
    .unwrap();
    worker.load_model(100, manifest()).unwrap();
    let mut invalid = neuron_feature_request();
    invalid.feature_vector_q24[0] += 1;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", invalid),
        Err(Error::PayloadMismatch)
    );
    assert!(!worker.is_quarantined());
    let mut healthy = neuron_feature_request();
    healthy.authorization.request_id = "request.valid2".into();
    healthy.authorization.reservation_id = "reservation.valid2".into();
    assert_eq!(
        worker
            .run_neuron_features(100, "model.1", healthy)
            .unwrap()
            .status,
        ExecutionStatus::Succeeded
    );
}

#[test]
fn malformed_post_driver_terminal_receipt_quarantines_worker_generation() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.typed-terminal-corrupt".to_owned(),
        3,
        grant(),
        Driver {
            // A failed terminal cannot attach successful output vectors.
            fail_terminal: true,
            ..Driver::default()
        },
    )
    .unwrap();
    worker.load_model(100, manifest()).unwrap();
    let result = worker.run_neuron_features_receipt(100, "model.1", neuron_feature_request());
    assert!(matches!(result, Err(Error::FeatureContract)));
    assert_eq!(worker.driver.neuron_calls, 1);
    assert!(worker.is_quarantined());

    // Even though a terminal (Failed) status was observed, the invalid typed
    // response means the Worker cannot be reused until independent recovery.
    worker.driver.fail_terminal = false;
    let mut next = neuron_feature_request();
    next.authorization.request_id = "request.terminal2".into();
    next.authorization.reservation_id = "reservation.terminal2".into();
    assert!(matches!(
        worker.run_neuron_features_receipt(100, "model.1", next),
        Err(Error::WorkerQuarantined)
    ));
    assert_eq!(worker.driver.neuron_calls, 1);
}
