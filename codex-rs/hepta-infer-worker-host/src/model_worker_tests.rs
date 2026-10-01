use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    loaded: usize,
    fail_load: bool,
    fail_run: bool,
    fail_unload: bool,
    invalid_handle: bool,
    feature_calls: usize,
    unload_calls: usize,
    run_memory_bytes: Option<u64>,
    feature_transient_bytes: Option<u64>,
    nonterminal_feature_output: bool,
    invalid_feature_encoder: bool,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if self.fail_load {
            return Err(Error::DriverFailure("unknown load outcome".to_string()));
        }
        self.loaded += 1;
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                String::new()
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
        if self.fail_run {
            return Err(Error::DriverFailure("unknown run outcome".to_string()));
        }
        if self.indeterminate {
            return Ok(DriverRunObservation {
                terminal_observed: false,
                succeeded: false,
                output_digest: None,
                consumed_tokens: 4,
                observed_memory_bytes: self.run_memory_bytes.unwrap_or(1_024),
            });
        }
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            output_digest: Some("9".repeat(64)),
            consumed_tokens: 16,
            observed_memory_bytes: self.run_memory_bytes.unwrap_or(1_024),
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.unload_calls += 1;
        if self.fail_unload {
            return Err(Error::DriverFailure("unknown unload outcome".to_string()));
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
        self.feature_calls += 1;
        if self.fail_run {
            return Err(Error::DriverFailure("unknown feature outcome".to_string()));
        }
        if self.indeterminate {
            return Ok(DriverNeuronFeatureObservation {
                terminal_observed: false,
                succeeded: false,
                encoder_digest: request.encoder_digest.clone(),
                head_digest: request.head_digest.clone(),
                drive_q24: if self.nonterminal_feature_output {
                    vec![i64::MAX; MAX_NEURON_FEATURES + 1]
                } else {
                    Vec::new()
                },
                prediction_q24: Vec::new(),
                observed_memory_bytes: self.run_memory_bytes.unwrap_or(1_024),
                transient_allocation_bytes: self.feature_transient_bytes.unwrap_or(2_048),
                queue_age_micros: 11,
                latency_micros: 17,
            });
        }
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            encoder_digest: if self.invalid_feature_encoder {
                String::new()
            } else {
                request.encoder_digest.clone()
            },
            head_digest: if self.corrupt_neuron_head {
                "f".repeat(64)
            } else {
                request.head_digest.clone()
            },
            drive_q24: vec![1 << 24; request.expected_output_width],
            prediction_q24: vec![0; request.expected_output_width],
            observed_memory_bytes: self.run_memory_bytes.unwrap_or(1_024),
            transient_allocation_bytes: self.feature_transient_bytes.unwrap_or(2_048),
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
fn aggregate_model_memory_is_bounded_and_rejected_handle_is_unloaded() {
    let mut resource_grant = grant();
    resource_grant.maximum_memory_bytes = 1_024;
    let mut worker = InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        resource_grant,
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first load");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    assert_eq!(worker.load_model(100, second), Err(Error::ModelCapacity));
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.models.len(), 1);
}

#[test]
fn invalid_loaded_handle_is_cleaned_up_before_rejection() {
    let driver = Driver {
        invalid_handle: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::InvalidIdentity("model handle"))
    );
    assert_eq!(worker.driver.loaded, 0);
    assert!(worker.models.is_empty());
}

#[test]
fn failed_cleanup_fences_further_driver_admission() {
    let driver = Driver {
        invalid_handle: true,
        fail_unload: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
    assert!(matches!(
        worker.load_model(100, manifest()),
        Err(Error::DriverFailure(_))
    ));
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::DriverUnavailable)
    );
    assert_eq!(worker.driver.loaded, 1);
}

#[test]
fn failed_unload_preserves_model_and_fences_worker() {
    let driver = Driver {
        fail_unload: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert!(matches!(
        worker.unload_model(100, "model.1"),
        Err(Error::DriverFailure(_))
    ));
    assert_eq!(worker.models.len(), 1);
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::DriverUnavailable)
    );
}

#[test]
fn unknown_run_outcomes_hold_capacity_and_prevent_replay_or_unload() {
    for driver in [
        Driver {
            indeterminate: true,
            ..Driver::default()
        },
        Driver {
            fail_run: true,
            ..Driver::default()
        },
    ] {
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
        worker.load_model(100, manifest()).expect("load");
        let _ = worker.run(100, "model.1", request());
        assert_eq!(
            worker.run(100, "model.1", request()),
            Err(Error::RequestCapacity)
        );
        assert_eq!(
            worker.unload_model(100, "model.1"),
            Err(Error::ActiveRequests)
        );
    }
}

#[test]
fn unknown_feature_outcomes_hold_capacity_and_prevent_replay_or_unload() {
    for driver in [
        Driver {
            indeterminate: true,
            ..Driver::default()
        },
        Driver {
            fail_run: true,
            ..Driver::default()
        },
    ] {
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
        worker.load_model(100, manifest()).expect("load");
        let _ = worker.run_neuron_features(100, "model.1", neuron_feature_request());
        assert_eq!(
            worker.run_neuron_features(100, "model.1", neuron_feature_request()),
            Err(Error::RequestCapacity)
        );
        assert_eq!(
            worker.unload_model(100, "model.1"),
            Err(Error::ActiveRequests)
        );
    }
}

#[test]
fn unknown_load_outcome_fences_the_worker() {
    let driver = Driver {
        fail_load: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
    assert!(matches!(
        worker.load_model(100, manifest()),
        Err(Error::DriverFailure(_))
    ));
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::DriverUnavailable)
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
fn feature_authorization_rejects_model_and_reservation_token_overruns_before_driver() {
    let mut worker = InferenceWorker::new(
        /*now_ms*/ 100,
        "worker.1".to_string(),
        /*generation*/ 3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    for reservation_overrun in [false, true] {
        let mut changed = neuron_feature_request();
        if reservation_overrun {
            changed.authorization.reservation_maximum_tokens = 1;
        } else {
            changed.authorization.maximum_tokens = manifest().maximum_tokens + 1;
            changed.authorization.reservation_maximum_tokens = changed.authorization.maximum_tokens;
        }
        let payload = canonical_neuron_feature_payload_digest(&changed);
        changed.authorization.payload_digest = payload.clone();
        changed.authorization.lease_payload_digest = payload;
        assert_eq!(
            worker.run_neuron_features(/*now_ms*/ 100, "model.1", changed),
            Err(Error::TokenLimit)
        );
        assert!(worker.active_requests.is_empty());
        assert_eq!(worker.driver.feature_calls, 0);
        assert_eq!(
            worker.models.get("model.1").expect("model").active_requests,
            0
        );
    }
    assert_eq!(
        worker
            .run_neuron_features(/*now_ms*/ 100, "model.1", neuron_feature_request())
            .expect("valid request")
            .status,
        ExecutionStatus::Succeeded
    );
    assert_eq!(worker.driver.feature_calls, 1);
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

#[test]
fn expired_or_revoked_grant_denies_admission_but_allows_idle_cleanup() {
    for revoked in [false, true] {
        let mut worker = InferenceWorker::new(
            /*now_ms*/ 100,
            "worker.cleanup".to_string(),
            /*generation*/ 3,
            grant(),
            Driver::default(),
        )
        .expect("worker");
        worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
        worker.grant.revoked = revoked;
        let now_ms = if revoked { 100 } else { grant().expires_at_ms };
        let denial = if revoked {
            Error::GrantRevoked
        } else {
            Error::GrantExpired
        };
        assert_eq!(worker.run(now_ms, "model.1", request()), Err(denial));
        assert!(
            worker
                .unload_model(now_ms, "model.1")
                .expect("cleanup remains permitted")
                .terminal_observed
        );
        assert_eq!(worker.driver.loaded, 0);
        assert_eq!(worker.driver.unload_calls, 1);
    }
}

#[test]
fn expiration_never_retries_unknown_unload_or_releases_unknown_execution() {
    for unknown_unload in [false, true] {
        let driver = Driver {
            fail_unload: unknown_unload,
            indeterminate: !unknown_unload,
            ..Driver::default()
        };
        let mut worker = InferenceWorker::new(
            /*now_ms*/ 100,
            "worker.unknown".to_string(),
            /*generation*/ 3,
            grant(),
            driver,
        )
        .expect("worker");
        worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
        if unknown_unload {
            assert!(matches!(
                worker.unload_model(/*_now_ms*/ 100, "model.1"),
                Err(Error::DriverFailure(_))
            ));
        } else {
            worker
                .run(/*now_ms*/ 100, "model.1", request())
                .expect("unknown run");
        }
        let expected = if unknown_unload {
            Error::DriverUnavailable
        } else {
            Error::ActiveRequests
        };
        assert_eq!(
            worker.unload_model(grant().expires_at_ms, "model.1"),
            Err(expected)
        );
        assert_eq!(worker.driver.unload_calls, usize::from(unknown_unload));
        assert_eq!(worker.driver.loaded, 1);
    }
}

#[test]
fn runtime_growth_and_smaller_later_observations_preserve_aggregate_load_budget() {
    let mut resource_grant = grant();
    resource_grant.maximum_models = 3;
    resource_grant.maximum_memory_bytes = 3_072;
    let driver = Driver {
        run_memory_bytes: Some(2_048),
        ..Driver::default()
    };
    let mut worker = InferenceWorker::new(
        /*now_ms*/ 100,
        "worker.memory".to_string(),
        /*generation*/ 3,
        resource_grant,
        driver,
    )
    .expect("worker");
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    worker
        .run(/*now_ms*/ 100, "model.1", request())
        .expect("growth");
    worker.driver.run_memory_bytes = Some(1_024);
    worker
        .run(/*now_ms*/ 100, "model.1", request())
        .expect("smaller observation");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    worker
        .load_model(/*now_ms*/ 100, second)
        .expect("exact aggregate limit");
    let mut third = manifest();
    third.model_id = "model.3".to_string();
    assert_eq!(
        worker.load_model(/*now_ms*/ 100, third),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.loaded, 2);
    assert_eq!(worker.driver.unload_calls, 1);
}

#[test]
fn runtime_aggregate_overflow_fences_admission_until_actual_idle_drain() {
    let driver = Driver {
        run_memory_bytes: Some(4_096),
        ..Driver::default()
    };
    let mut worker = InferenceWorker::new(
        /*now_ms*/ 100,
        "worker.memory".to_string(),
        /*generation*/ 3,
        grant(),
        driver,
    )
    .expect("worker");
    worker
        .load_model(/*now_ms*/ 100, manifest())
        .expect("first load");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    worker
        .load_model(/*now_ms*/ 100, second)
        .expect("second load");
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request()),
        Err(Error::ModelCapacity)
    );
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request()),
        Err(Error::ModelCapacity)
    );
    worker
        .unload_model(/*_now_ms*/ 100, "model.1")
        .expect("known idle cleanup");
    assert_eq!(
        worker.load_model(/*now_ms*/ 100, manifest()),
        Err(Error::ModelCapacity)
    );
    worker
        .unload_model(/*_now_ms*/ 100, "model.2")
        .expect("complete drain");
    worker
        .load_model(/*now_ms*/ 100, manifest())
        .expect("admission after actual drain");
    assert_eq!(worker.driver.unload_calls, 2);
}

#[test]
fn feature_transient_peak_and_arithmetic_overflow_are_bounded_with_idle_cleanup() {
    for transient in [3_073, u64::MAX] {
        let driver = Driver {
            feature_transient_bytes: Some(transient),
            ..Driver::default()
        };
        let mut worker = InferenceWorker::new(
            /*now_ms*/ 100,
            "worker.feature-memory".to_string(),
            /*generation*/ 3,
            grant(),
            driver,
        )
        .expect("worker");
        worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
        assert_eq!(
            worker.run_neuron_features(/*now_ms*/ 100, "model.1", neuron_feature_request()),
            Err(Error::ModelCapacity)
        );
        assert_eq!(
            worker.run(/*now_ms*/ 100, "model.1", request()),
            Err(Error::ModelCapacity)
        );
        worker
            .unload_model(/*_now_ms*/ 100, "model.1")
            .expect("cleanup");
        assert_eq!(worker.driver.loaded, 0);
    }
}

#[test]
fn failed_and_partial_feature_values_are_discarded_before_typed_receipt() {
    for indeterminate in [false, true] {
        let driver = Driver {
            fail_terminal: true,
            indeterminate,
            nonterminal_feature_output: true,
            ..Driver::default()
        };
        let mut worker = InferenceWorker::new(
            /*now_ms*/ 100,
            "worker.feature-output".to_string(),
            /*generation*/ 3,
            grant(),
            driver,
        )
        .expect("worker");
        worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
        let receipt = worker
            .run_neuron_features_receipt(/*now_ms*/ 100, "model.1", neuron_feature_request())
            .expect("non-success receipt remains representable");
        let expected = if indeterminate {
            codex_hepta_infer_core::NeuronFeatureTerminalStatusV1::Indeterminate
        } else {
            codex_hepta_infer_core::NeuronFeatureTerminalStatusV1::Failed
        };
        assert_eq!(receipt.status, expected);
        assert!(receipt.drive_q24.is_empty());
        assert!(receipt.prediction_q24.is_empty());
        if indeterminate {
            assert_eq!(
                worker.unload_model(/*_now_ms*/ 100, "model.1"),
                Err(Error::ActiveRequests)
            );
        } else {
            worker
                .unload_model(/*_now_ms*/ 100, "model.1")
                .expect("terminal cleanup");
        }
    }
}

#[test]
fn failed_feature_observation_still_validates_identity_bounds() {
    let driver = Driver {
        fail_terminal: true,
        invalid_feature_encoder: true,
        ..Driver::default()
    };
    let mut worker = InferenceWorker::new(
        /*now_ms*/ 100,
        "worker.feature-identity".to_string(),
        /*generation*/ 3,
        grant(),
        driver,
    )
    .expect("worker");
    worker.load_model(/*now_ms*/ 100, manifest()).expect("load");
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", neuron_feature_request()),
        Err(Error::InvalidDigest("encoder"))
    );
    worker
        .unload_model(/*_now_ms*/ 100, "model.1")
        .expect("known terminal cleanup");
}

#[path = "model_worker_memory_tests.rs"]
mod memory_tests;
