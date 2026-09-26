use super::*;

#[derive(Debug)]
struct LifecycleDriver {
    bytes: u64,
    invalid_handle: bool,
    fail_unload: bool,
    loaded: usize,
    load_attempts: usize,
    unload_attempts: usize,
    run_attempts: usize,
}

impl Default for LifecycleDriver {
    fn default() -> Self {
        Self {
            bytes: 1_024,
            invalid_handle: false,
            fail_unload: false,
            loaded: 0,
            load_attempts: 0,
            unload_attempts: 0,
            run_attempts: 0,
        }
    }
}

impl ModelDriver for LifecycleDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        self.load_attempts += 1;
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                String::new()
            } else {
                format!("handle.{}", manifest.model_id)
            },
            observed_memory_bytes: self.bytes,
        })
    }

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.run_attempts += 1;
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: true,
            output_digest: Some("a".repeat(64)),
            consumed_tokens: 1,
            observed_memory_bytes: handle.observed_memory_bytes,
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.unload_attempts += 1;
        if self.fail_unload {
            return Err(Error::DriverFailure("release unconfirmed".to_string()));
        }
        self.loaded -= 1;
        Ok(())
    }
}

impl NeuronFeatureDriver for LifecycleDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        self.run_attempts += 1;
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: true,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: request.head_digest.clone(),
            drive_q24: vec![0; request.expected_output_width],
            prediction_q24: vec![0; request.expected_output_width],
            observed_memory_bytes: handle.observed_memory_bytes,
            transient_allocation_bytes: 0,
            queue_age_micros: 0,
            latency_micros: 1,
        })
    }
}

fn grant(bytes: u64) -> ResourceGrant {
    ResourceGrant {
        grant_id: "grant.lifecycle".to_string(),
        authority_epoch: 1,
        generation: 1,
        expires_at_ms: 1_000,
        revoked: false,
        maximum_models: MAX_MODELS,
        maximum_active_requests: 4,
        maximum_memory_bytes: bytes,
        semantic_digest: "1".repeat(64),
    }
}

fn manifest(id: &str) -> ModelManifest {
    ModelManifest {
        model_id: id.to_string(),
        model_digest: "1".repeat(64),
        weights_digest: "2".repeat(64),
        tokenizer_digest: "3".repeat(64),
        preprocessor_digest: "4".repeat(64),
        quantization_digest: "5".repeat(64),
        runtime_digest: "6".repeat(64),
        device_digest: "7".repeat(64),
        maximum_tokens: 16,
    }
}

fn request() -> WorkerRequest {
    WorkerRequest {
        request_id: "request.lifecycle".to_string(),
        reservation_id: "reservation.lifecycle".to_string(),
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        maximum_tokens: 8,
        deadline_ms: 900,
        lease_payload_digest: "2".repeat(64),
        reservation_model_digest: "1".repeat(64),
        reservation_maximum_tokens: 8,
        cancelled: false,
    }
}

fn feature_request() -> NeuronFeatureRequest {
    let mut result = NeuronFeatureRequest {
        authorization: request(),
        encoder_digest: "3".repeat(64),
        head_digest: "4".repeat(64),
        weights_digest: "2".repeat(64),
        input_digest: "5".repeat(64),
        feature_vector_q24: vec![1],
        expected_output_width: 1,
    };
    let digest = canonical_neuron_feature_payload_digest(&result);
    result.authorization.payload_digest = digest.clone();
    result.authorization.lease_payload_digest = digest;
    result
}

fn worker(bytes: u64, driver: LifecycleDriver) -> InferenceWorker<LifecycleDriver> {
    InferenceWorker::new(100, "worker.lifecycle".to_string(), 1, grant(bytes), driver)
        .expect("valid lifecycle fixture")
}

#[test]
fn aggregate_resident_memory_rejects_second_model_and_releases_its_handle() {
    let mut worker = worker(1_500, LifecycleDriver::default());
    worker.load_model(100, manifest("model.1")).expect("first");
    assert_eq!(
        worker.load_model(100, manifest("model.2")),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.resident_memory_bytes(), 1_024);
    assert_eq!(worker.models.len(), 1);
    assert_eq!(worker.driver.loaded, 1);
    assert_eq!(worker.driver.unload_attempts, 1);
}

#[test]
fn expiry_and_revocation_block_execution_but_not_owned_handle_cleanup() {
    for revoked in [false, true] {
        let mut worker = worker(2_048, LifecycleDriver::default());
        worker.load_model(100, manifest("model.1")).expect("load");
        worker.grant.revoked = revoked;
        let now = if revoked { 100 } else { 1_000 };
        let expected = if revoked {
            Error::GrantRevoked
        } else {
            Error::GrantExpired
        };
        assert_eq!(worker.run(now, "model.1", request()), Err(expected));
        worker.unload_model(now, "model.1").expect("safe cleanup");
        assert_eq!(worker.resident_memory_bytes(), 0);
        assert_eq!(worker.driver.loaded, 0);
        assert_eq!(worker.driver.run_attempts, 0);
    }
}

#[test]
fn failed_unload_retains_accounting_and_fences_both_execution_paths() {
    let mut worker = worker(2_048, LifecycleDriver::default());
    worker.load_model(100, manifest("model.1")).expect("load");
    worker.driver.fail_unload = true;
    assert!(matches!(
        worker.unload_model(100, "model.1"),
        Err(Error::DriverFailure(_))
    ));
    assert_eq!(worker.resident_memory_bytes(), 1_024);
    assert_eq!(worker.models.len(), 1);
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelCleanupPending)
    );
    assert_eq!(
        worker.run_neuron_features(100, "model.1", feature_request()),
        Err(Error::ModelCleanupPending)
    );
    assert_eq!(worker.driver.run_attempts, 0);
    worker.driver.fail_unload = false;
    worker
        .unload_model(2_000, "model.1")
        .expect("retry after expiry");
    assert_eq!(worker.resident_memory_bytes(), 0);
    assert_eq!(worker.driver.unload_attempts, 2);
}

#[test]
fn invalid_post_load_handle_is_released_or_retained_until_confirmed_cleanup() {
    for fail_unload in [false, true] {
        let driver = LifecycleDriver {
            invalid_handle: true,
            fail_unload,
            ..LifecycleDriver::default()
        };
        let mut worker = worker(2_048, driver);
        let result = worker.load_model(100, manifest("model.1"));
        if fail_unload {
            assert!(matches!(result, Err(Error::CleanupPending(_))));
            assert_eq!(worker.resident_memory_bytes(), 1_024);
            assert_eq!(worker.models.len(), 1);
            assert_eq!(
                worker.load_model(100, manifest("model.1")),
                Err(Error::ModelAlreadyLoaded)
            );
            worker.driver.fail_unload = false;
            worker.unload_model(2_000, "model.1").expect("retry");
        } else {
            assert_eq!(result, Err(Error::InvalidIdentity("model handle")));
        }
        assert!(worker.models.is_empty());
        assert_eq!(worker.resident_memory_bytes(), 0);
        assert_eq!(worker.driver.loaded, 0);
    }
}

#[test]
fn cumulative_accounting_does_not_wrap_at_u64_maximum() {
    let driver = LifecycleDriver {
        bytes: u64::MAX / 2 + 1,
        ..LifecycleDriver::default()
    };
    let mut worker = worker(u64::MAX, driver);
    worker.load_model(100, manifest("model.1")).expect("first");
    worker.driver.fail_unload = true;
    assert!(matches!(
        worker.load_model(100, manifest("model.2")),
        Err(Error::CleanupPending(_))
    ));
    assert_eq!(worker.resident_memory_bytes(), u128::from(u64::MAX) + 1);
    let attempts = worker.driver.load_attempts;
    assert_eq!(
        worker.load_model(100, manifest("model.3")),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.load_attempts, attempts);
    worker.driver.fail_unload = false;
    worker
        .unload_model(2_000, "model.2")
        .expect("second cleanup");
    worker
        .unload_model(2_000, "model.1")
        .expect("first cleanup");
    assert_eq!(worker.resident_memory_bytes(), 0);
}

#[test]
fn acknowledged_cleanup_releases_capacity_without_double_release() {
    let mut worker = worker(1_024, LifecycleDriver::default());
    for _ in 0..256 {
        worker.load_model(100, manifest("model.1")).expect("load");
        worker.run(100, "model.1", request()).expect("active run");
        worker.unload_model(100, "model.1").expect("unload");
        let attempts = worker.driver.unload_attempts;
        assert_eq!(
            worker.unload_model(100, "model.1"),
            Err(Error::ModelNotLoaded)
        );
        assert_eq!(worker.driver.unload_attempts, attempts);
        assert_eq!(worker.resident_memory_bytes(), 0);
    }
    assert_eq!(worker.driver.loaded, 0);
    assert_eq!(worker.driver.run_attempts, 256);
}
