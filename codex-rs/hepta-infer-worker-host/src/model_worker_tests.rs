use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    fail_load: bool,
    fail_unload: bool,
    invalid_handle: bool,
    unknown_usage: bool,
    loaded: usize,
    run_calls: usize,
    unload_calls: usize,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if self.fail_load {
            return Err(Error::DriverFailure(
                "load acknowledgement lost".to_string(),
            ));
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
        self.run_calls += 1;
        if self.indeterminate {
            return Ok(DriverRunObservation {
                terminal_observed: false,
                succeeded: false,
                output_digest: None,
                consumed_tokens: None,
                observed_memory_bytes: 1_024,
            });
        }
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            output_digest: Some("9".repeat(64)),
            consumed_tokens: if self.unknown_usage { None } else { Some(16) },
            observed_memory_bytes: 1_024,
        })
    }

    fn unload(&mut self, _handle: &DriverModelHandle) -> Result<(), Error> {
        self.unload_calls += 1;
        if self.fail_unload {
            return Err(Error::DriverFailure(
                "device did not confirm unload".to_string(),
            ));
        }
        self.loaded = self
            .loaded
            .checked_sub(1)
            .ok_or(Error::ResourceAccounting)?;
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
        maximum_resident_bytes: 1_024,
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
        maximum_kv_bytes: 256,
        maximum_transient_bytes: 2_048,
    }
}

fn worker(driver: Driver) -> InferenceWorker<Driver> {
    InferenceWorker::new(
        /*now_ms*/ 100,
        "worker.1".to_string(),
        /*generation*/ 3,
        grant(),
        driver,
    )
    .unwrap()
}

#[test]
fn loads_runs_and_unloads_exact_model_tuple() {
    let mut worker = worker(Driver::default());
    assert!(
        worker
            .load_model(/*now_ms*/ 100, manifest())
            .unwrap()
            .terminal_observed
    );
    let observed = worker.run(/*now_ms*/ 100, "model.1", request()).unwrap();
    assert_eq!(observed.status, ExecutionStatus::Succeeded);
    assert!(observed.terminal_observed);
    assert!(
        worker
            .unload_model(/*_now_ms*/ 100, "model.1")
            .unwrap()
            .terminal_observed
    );
    assert_eq!(worker.resource_snapshot().unwrap().reserved_bytes, 0);
}

#[test]
fn rejects_changed_tokenizer_model_or_payload_tuple() {
    let mut worker = worker(Driver::default());
    worker.load_model(/*now_ms*/ 100, manifest()).unwrap();
    let mut changed = request();
    changed.lease_payload_digest = "4".repeat(64);
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );
    let mut changed = request();
    changed.reservation_model_digest = "5".repeat(64);
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", changed),
        Err(Error::ModelMismatch)
    );
}

#[test]
fn lost_driver_terminality_is_indeterminate() {
    let mut worker = worker(Driver {
        indeterminate: true,
        ..Driver::default()
    });
    worker.load_model(/*now_ms*/ 100, manifest()).unwrap();
    let observed = worker.run(/*now_ms*/ 100, "model.1", request()).unwrap();
    assert_eq!(observed.status, ExecutionStatus::Indeterminate);
    assert!(!observed.terminal_observed);
    assert_eq!(observed.output_digest, None);
    assert_eq!(observed.consumed_tokens, None);
    assert_eq!(worker.resource_snapshot().unwrap().reserved_bytes, 3_328);
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request()),
        Err(Error::GenerationFenced)
    );
    assert_eq!(worker.driver.run_calls, 1);
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
    let mut worker = worker(Driver::default());
    let expected_manifest = manifest();
    worker
        .load_model(/*now_ms*/ 100, expected_manifest.clone())
        .unwrap();
    let observed = worker
        .run_neuron_features(/*now_ms*/ 100, "model.1", neuron_feature_request())
        .unwrap();
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
    let mut first = worker(Driver::default());
    first.load_model(/*now_ms*/ 100, manifest()).unwrap();
    let mut changed = neuron_feature_request();
    changed.feature_vector_q24[0] += 1;
    assert_eq!(
        first.run_neuron_features(/*now_ms*/ 100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );
    let mut second = worker(Driver {
        corrupt_neuron_head: true,
        ..Driver::default()
    });
    second.load_model(/*now_ms*/ 100, manifest()).unwrap();
    assert_eq!(
        second.run_neuron_features(/*now_ms*/ 100, "model.1", neuron_feature_request()),
        Err(Error::FeatureOutputMismatch)
    );
}

#[test]
fn neuron_feature_worker_projects_exact_inference_control_receipt() {
    let mut worker = worker(Driver::default());
    let selected = manifest();
    worker.load_model(/*now_ms*/ 100, selected.clone()).unwrap();
    let receipt = worker
        .run_neuron_features_receipt(/*now_ms*/ 100, "model.1", neuron_feature_request())
        .unwrap();
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
fn aggregate_memory_rejects_second_load_before_driver_entry() {
    let mut worker = worker(Driver::default());
    let mut first = manifest();
    first.maximum_resident_bytes = 3_072;
    worker.load_model(/*now_ms*/ 100, first).unwrap();
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    second.maximum_resident_bytes = 2_048;
    assert_eq!(
        worker.load_model(/*now_ms*/ 100, second),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.resource_snapshot().unwrap().reserved_bytes, 3_072);
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request()),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.run_calls, 0);
}

#[test]
fn unload_failure_preserves_handle_and_budget_for_cleanup_retry() {
    let mut worker = worker(Driver {
        fail_unload: true,
        ..Driver::default()
    });
    worker.load_model(/*now_ms*/ 100, manifest()).unwrap();
    assert!(worker.unload_model(/*_now_ms*/ 100, "model.1").is_err());
    assert_eq!(worker.models["model.1"].handle.opaque_id, "handle.model.1");
    assert_eq!(worker.resource_snapshot().unwrap().reserved_bytes, 1_024);
    assert_eq!(
        worker.run(/*now_ms*/ 100, "model.1", request()),
        Err(Error::GenerationFenced)
    );
    worker.driver.fail_unload = false;
    worker.unload_model(/*_now_ms*/ 20_000, "model.1").unwrap();
    assert_eq!(worker.driver.unload_calls, 2);
    assert_eq!(worker.driver.loaded, 0);
    assert_eq!(worker.resource_snapshot().unwrap().reserved_bytes, 0);
    assert!(worker.resource_snapshot().unwrap().fenced);
}

#[test]
fn revoked_or_expired_grant_does_not_prevent_resource_cleanup() {
    let mut worker = worker(Driver::default());
    worker.load_model(/*now_ms*/ 100, manifest()).unwrap();
    worker.grant.revoked = true;
    assert_eq!(
        worker.run(/*now_ms*/ 20_000, "model.1", request()),
        Err(Error::GrantRevoked)
    );
    worker.unload_model(/*_now_ms*/ 20_000, "model.1").unwrap();
    assert_eq!(worker.resource_snapshot().unwrap().reserved_bytes, 0);
}

#[test]
fn invalid_handle_is_cleaned_and_failed_cleanup_is_retained() {
    for fail_unload in [false, true] {
        let mut worker = worker(Driver {
            invalid_handle: true,
            fail_unload,
            ..Driver::default()
        });
        assert!(worker.load_model(/*now_ms*/ 100, manifest()).is_err());
        assert_eq!(worker.driver.unload_calls, 1);
        let snapshot = worker.resource_snapshot().unwrap();
        if fail_unload {
            assert!(worker.models.contains_key("model.1"));
            assert_eq!(snapshot.reserved_bytes, 1_024);
            assert!(snapshot.fenced);
        } else {
            assert_eq!(worker.driver.loaded, 0);
            assert_eq!(snapshot.reserved_bytes, 0);
        }
    }
}

#[test]
fn ambiguous_load_failure_retains_capacity_and_fences_generation() {
    let mut worker = worker(Driver {
        fail_load: true,
        ..Driver::default()
    });
    assert!(worker.load_model(/*now_ms*/ 100, manifest()).is_err());
    assert_eq!(worker.resource_snapshot().unwrap().reserved_bytes, 1_024);
    assert!(worker.resource_snapshot().unwrap().fenced);
}

#[test]
fn terminal_usage_can_remain_unknown_without_becoming_zero() {
    let mut worker = worker(Driver {
        unknown_usage: true,
        ..Driver::default()
    });
    worker.load_model(/*now_ms*/ 100, manifest()).unwrap();
    let observed = worker.run(/*now_ms*/ 100, "model.1", request()).unwrap();
    assert!(observed.terminal_observed);
    assert_eq!(observed.consumed_tokens, None);
    assert_eq!(worker.resource_snapshot().unwrap().reserved_bytes, 1_024);
}

#[test]
fn neuron_resource_budget_drift_is_part_of_v2_payload_identity() {
    let mut worker = worker(Driver::default());
    worker.load_model(/*now_ms*/ 100, manifest()).unwrap();
    let mut changed = neuron_feature_request();
    changed.authorization.maximum_transient_bytes += 1;
    assert_eq!(
        worker.run_neuron_features(/*now_ms*/ 100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );
}
