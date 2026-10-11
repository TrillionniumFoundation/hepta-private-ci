use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    invalid_handle: bool,
    fail_unload: bool,
    loaded: usize,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                "invalid handle".to_string()
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
        if self.fail_unload {
            return Err(Error::DriverFailure("unload indeterminate".to_string()));
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
fn invalid_loaded_handle_is_cleaned_up_without_leaking_model_owner() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.invalid-handle".into(),
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
    assert_eq!(worker.driver.loaded, 0);
    assert!(worker.models.is_empty());
    assert!(!worker.poisoned);
}

#[test]
fn failed_unload_poison_worker_until_owner_reconciliation() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.unload-failure".into(),
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
        Err(Error::IndeterminateLifecycle)
    );
    assert!(worker.poisoned);
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::IndeterminateLifecycle)
    );
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::IndeterminateLifecycle)
    );
}

#[test]
fn failed_post_load_cleanup_poison_worker_instead_of_leaking_authority() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.cleanup-failure".into(),
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
        Err(Error::IndeterminateLifecycle)
    );
    assert!(worker.poisoned);
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::IndeterminateLifecycle)
    );
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
fn neuron_feature_rejects_token_budget_without_backend_dispatch() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.tokens".to_string(),
        3,
        grant(),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let mut oversized = neuron_feature_request();
    oversized.authorization.maximum_tokens = 129;
    oversized.authorization.reservation_maximum_tokens = 129;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", oversized),
        Err(Error::TokenLimit)
    );
    let mut over_reservation = neuron_feature_request();
    over_reservation.authorization.maximum_tokens = 65;
    assert_eq!(
        worker.run_neuron_features(100, "model.1", over_reservation),
        Err(Error::TokenLimit)
    );
}

#[test]
fn neuron_feature_never_exposes_failed_driver_logits() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.failure".to_string(),
        3,
        grant(),
        Driver {
            fail_terminal: true,
            ..Driver::default()
        },
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::FeatureOutputMismatch)
    );
}

#[test]
fn multi_model_resident_memory_cannot_exceed_total_worker_grant() {
    let mut bounded = grant();
    bounded.maximum_memory_bytes = 1024;
    let mut worker = InferenceWorker::new(
        100,
        "worker.memory".to_string(),
        3,
        bounded,
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("first load");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    second.model_digest = "9".repeat(64);
    assert_eq!(worker.load_model(100, second), Err(Error::ModelCapacity));
    assert_eq!(worker.models.len(), 1);
    assert_eq!(worker.driver.loaded, 1);
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
