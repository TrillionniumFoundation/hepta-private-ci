use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    corrupt_neuron_head: bool,
    loaded: usize,
    runs: usize,
    unloads: usize,
    failed_unloads: usize,
    invalid_handle: bool,
    fail_run: bool,
    panic_run: bool,
    panic_load: bool,
    panic_unload: bool,
    load_memory_bytes: Option<u64>,
    run_memory_bytes: Option<u64>,
    transient_allocation_bytes: Option<u64>,
    feature_output_width: Option<usize>,
}

impl ModelDriver for Driver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        assert!(!self.panic_load, "driver load panicked");
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                "invalid/handle".to_string()
            } else {
                format!("handle.{}", manifest.model_id)
            },
            observed_memory_bytes: self.load_memory_bytes.unwrap_or(1_024),
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.runs += 1;
        assert!(!self.panic_run, "driver invocation panicked");
        if self.fail_run {
            return Err(Error::DriverFailure("transport lost".to_string()));
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
            observed_memory_bytes: self.run_memory_bytes.unwrap_or(1_024),
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.unloads += 1;
        assert!(!self.panic_unload, "driver unload panicked");
        if self.failed_unloads > 0 {
            self.failed_unloads -= 1;
            return Err(Error::DriverFailure("cleanup uncertain".to_string()));
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
        self.runs += 1;
        assert!(!self.panic_run, "driver invocation panicked");
        if self.fail_run {
            return Err(Error::DriverFailure("transport lost".to_string()));
        }
        let head_digest = if self.corrupt_neuron_head {
            "f".repeat(64)
        } else {
            request.head_digest.clone()
        };
        let output_width = self
            .feature_output_width
            .unwrap_or(request.expected_output_width);
        if self.indeterminate {
            return Ok(DriverNeuronFeatureObservation {
                terminal_observed: false,
                succeeded: false,
                encoder_digest: request.encoder_digest.clone(),
                head_digest,
                drive_q24: vec![1 << 24; output_width],
                prediction_q24: vec![0; output_width],
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
            head_digest,
            drive_q24: vec![1 << 24; output_width],
            prediction_q24: vec![0; output_width],
            observed_memory_bytes: self.run_memory_bytes.unwrap_or(1_024),
            transient_allocation_bytes: self.transient_allocation_bytes.unwrap_or(2_048),
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
fn neuron_feature_payload_preserves_published_v1_digest() {
    // Independently computed with Python hashlib over the original V1 byte
    // layout, including signed big-endian Q24 values and 64-bit widths.
    assert_eq!(
        canonical_neuron_feature_payload_digest(&neuron_feature_request()),
        "55546b4b54085cf7497be38cd38ceb97b446a1987d4bfa71d2ac7629ba09e117"
    );
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
fn aggregate_model_memory_denies_load_and_releases_only_new_handle() {
    let mut budget = grant();
    budget.maximum_memory_bytes = 1_500;
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, budget, Driver::default())
            .expect("worker");
    worker.load_model(100, manifest()).expect("first load");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    assert_eq!(worker.load_model(100, second), Err(Error::ModelCapacity));
    assert_eq!(
        (
            worker.driver.loaded,
            worker.driver.unloads,
            worker.models.len()
        ),
        (1, 1, 1)
    );
    worker
        .run(100, "model.1", request())
        .expect("original model");
}

#[test]
fn invalid_loaded_handle_is_released_and_failed_cleanup_can_retry_after_expiry() {
    for failed_unloads in [0, 1] {
        let driver = Driver {
            invalid_handle: true,
            failed_unloads,
            ..Driver::default()
        };
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
        assert!(worker.load_model(100, manifest()).is_err());
        if failed_unloads == 0 {
            assert_eq!(
                (
                    worker.driver.loaded,
                    worker.driver.unloads,
                    worker.models.len()
                ),
                (0, 1, 0)
            );
        } else {
            assert_eq!(
                worker.run(100, "model.1", request()),
                Err(Error::ModelUnavailable)
            );
            assert_eq!(worker.driver.loaded, 1);
            worker
                .unload_model(10_000, "model.1")
                .expect("expired grant cleanup");
            assert_eq!(
                (
                    worker.driver.loaded,
                    worker.driver.unloads,
                    worker.models.len()
                ),
                (0, 2, 0)
            );
        }
    }
}

#[test]
fn failed_unload_retains_handle_and_fences_execution_until_confirmed_cleanup() {
    let driver = Driver {
        failed_unloads: 1,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert!(worker.unload_model(100, "model.1").is_err());
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelUnavailable)
    );
    assert_eq!((worker.driver.loaded, worker.driver.runs), (1, 0));
    worker.unload_model(100, "model.1").expect("cleanup retry");
    worker.load_model(100, manifest()).expect("reload");
    worker
        .run(100, "model.1", request())
        .expect("run after cleanup");
}

#[test]
fn driver_uncertainty_fences_all_models_and_new_loads_until_cleanup() {
    for fail_run in [false, true] {
        let driver = Driver {
            fail_run,
            indeterminate: !fail_run,
            ..Driver::default()
        };
        let mut budget = grant();
        budget.maximum_models = 3;
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_string(), 3, budget, driver).expect("worker");
        worker.load_model(100, manifest()).expect("load");
        let mut second = manifest();
        second.model_id = "model.2".to_string();
        worker.load_model(100, second).expect("second load");
        let observed = worker.run(100, "model.1", request());
        if fail_run {
            assert!(observed.is_err());
        } else {
            assert_eq!(
                observed.expect("observed result").status,
                ExecutionStatus::Indeterminate
            );
        }
        assert_eq!(
            worker.run(100, "model.2", request()),
            Err(Error::ModelUnavailable)
        );
        let mut third = manifest();
        third.model_id = "model.3".to_string();
        assert_eq!(worker.load_model(100, third), Err(Error::ModelUnavailable));
        assert_eq!((worker.driver.loaded, worker.driver.runs), (2, 1));
        worker
            .unload_model(100, "model.1")
            .expect("drained cleanup");
        worker.driver.fail_run = false;
        worker.driver.indeterminate = false;
        worker
            .run(100, "model.2", request())
            .expect("unfenced worker");
    }
}

#[test]
fn run_memory_growth_includes_other_models_and_fences_invalid_observation() {
    let mut budget = grant();
    budget.maximum_memory_bytes = 2_200;
    let driver = Driver {
        run_memory_bytes: Some(1_536),
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, budget, driver).expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    worker.load_model(100, second).expect("second load");
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelCapacity)
    );
    assert_eq!(
        worker.run(100, "model.2", request()),
        Err(Error::ModelUnavailable)
    );
    worker
        .unload_model(100, "model.1")
        .expect("release over-budget model");
    worker
        .run(100, "model.2", request())
        .expect("remaining model");
}

#[test]
fn neuron_feature_token_ceilings_are_checked_before_driver_invocation() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    for (maximum_tokens, reservation_maximum_tokens) in [(129, 129), (64, 63)] {
        let mut value = neuron_feature_request();
        value.authorization.maximum_tokens = maximum_tokens;
        value.authorization.reservation_maximum_tokens = reservation_maximum_tokens;
        assert_eq!(
            worker.run_neuron_features(100, "model.1", value),
            Err(Error::TokenLimit)
        );
    }
    assert_eq!(worker.driver.runs, 0);
}

#[test]
fn neuron_feature_peak_memory_counts_transient_bytes_with_checked_arithmetic() {
    for transient_allocation_bytes in [3_073, u64::MAX] {
        let driver = Driver {
            transient_allocation_bytes: Some(transient_allocation_bytes),
            ..Driver::default()
        };
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
        worker.load_model(100, manifest()).expect("load");
        let expected = if transient_allocation_bytes == u64::MAX {
            Error::ArithmeticOverflow
        } else {
            Error::ModelCapacity
        };
        assert_eq!(
            worker.run_neuron_features(100, "model.1", neuron_feature_request()),
            Err(expected)
        );
        assert_eq!(
            worker.run(100, "model.1", request()),
            Err(Error::ModelUnavailable)
        );
        worker
            .unload_model(100, "model.1")
            .expect("release fenced model");
    }
}

#[test]
fn neuron_feature_nonsuccess_drops_outputs_and_preserves_typed_receipt_status() {
    for indeterminate in [false, true] {
        let driver = Driver {
            fail_terminal: !indeterminate,
            indeterminate,
            ..Driver::default()
        };
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
        worker.load_model(100, manifest()).expect("load");
        let receipt = worker
            .run_neuron_features_receipt(100, "model.1", neuron_feature_request())
            .expect("nonsuccess receipt");
        assert_eq!(
            (receipt.drive_q24, receipt.prediction_q24, receipt.status),
            (
                Vec::<i64>::new(),
                Vec::<i64>::new(),
                if indeterminate {
                    NeuronFeatureTerminalStatusV1::Indeterminate
                } else {
                    NeuronFeatureTerminalStatusV1::Failed
                },
            )
        );
        if indeterminate {
            assert_eq!(
                worker.run(100, "model.1", request()),
                Err(Error::ModelUnavailable)
            );
        }
    }
}

#[test]
fn nonsuccess_feature_observations_release_oversized_driver_vector_allocations() {
    for indeterminate in [false, true] {
        let driver = Driver {
            fail_terminal: !indeterminate,
            indeterminate,
            feature_output_width: Some(4_096),
            ..Driver::default()
        };
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
        worker.load_model(100, manifest()).expect("load");
        let observed = worker
            .run_neuron_features(100, "model.1", neuron_feature_request())
            .expect("nonsuccess observation");
        assert_eq!(
            (
                observed.drive_q24.len(),
                observed.drive_q24.capacity(),
                observed.prediction_q24.len(),
                observed.prediction_q24.capacity(),
                observed.status,
            ),
            (
                0,
                0,
                0,
                0,
                if indeterminate {
                    ExecutionStatus::Indeterminate
                } else {
                    ExecutionStatus::Failed
                },
            )
        );
    }
}

#[test]
fn neuron_feature_identity_drift_is_fenced_even_when_driver_did_not_succeed() {
    for indeterminate in [false, true] {
        let driver = Driver {
            corrupt_neuron_head: true,
            fail_terminal: !indeterminate,
            indeterminate,
            ..Driver::default()
        };
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
        worker.load_model(100, manifest()).expect("load");
        assert_eq!(
            worker.run_neuron_features_receipt(100, "model.1", neuron_feature_request()),
            Err(Error::FeatureOutputMismatch)
        );
        assert_eq!(
            worker.run(100, "model.1", request()),
            Err(Error::ModelUnavailable)
        );
        worker
            .unload_model(100, "model.1")
            .expect("release drifted model");
    }
}

#[test]
fn caught_driver_panic_keeps_worker_fenced_until_confirmed_drain() {
    for feature_path in [false, true] {
        let driver = Driver {
            panic_run: true,
            failed_unloads: 1,
            ..Driver::default()
        };
        let mut budget = grant();
        budget.maximum_active_requests = 1;
        let mut worker =
            InferenceWorker::new(100, "worker.1".to_string(), 3, budget, driver).expect("worker");
        worker.load_model(100, manifest()).expect("load");
        let panicked = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            if feature_path {
                worker
                    .run_neuron_features(100, "model.1", neuron_feature_request())
                    .map(|_| ())
            } else {
                worker.run(100, "model.1", request()).map(|_| ())
            }
        }));
        assert!(panicked.is_err());
        assert!(worker.run(100, "model.1", request()).is_err());
        assert!(worker.unload_model(100, "model.1").is_err());
        assert_eq!(
            (
                worker.driver.loaded,
                worker.models.len(),
                worker.active_requests.len()
            ),
            (1, 1, 1)
        );
        worker
            .unload_model(100, "model.1")
            .expect("confirmed drain");
        assert_eq!(
            (
                worker.driver.loaded,
                worker.models.len(),
                worker.active_requests.len()
            ),
            (0, 0, 0)
        );
        worker.driver.panic_run = false;
        worker.load_model(100, manifest()).expect("reload");
        worker
            .run(100, "model.1", request())
            .expect("recovered request capacity");
    }
}

#[test]
fn caught_load_panic_without_handle_cannot_be_cleared_by_unrelated_unload() {
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), Driver::default())
            .expect("worker");
    worker.load_model(100, manifest()).expect("known load");
    worker.driver.panic_load = true;
    let mut second = manifest();
    second.model_id = "model.2".to_string();
    let panicked = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        worker.load_model(100, second.clone())
    }));
    assert!(panicked.is_err());
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelUnavailable)
    );
    assert_eq!(
        worker.run_neuron_features(100, "model.1", neuron_feature_request()),
        Err(Error::ModelUnavailable)
    );
    worker
        .unload_model(100, "model.1")
        .expect("known handle cleanup");
    worker.driver.panic_load = false;
    assert_eq!(worker.load_model(100, second), Err(Error::ModelUnavailable));
    assert_eq!(
        (
            worker.driver.loaded,
            worker.driver.unloads,
            worker.models.len()
        ),
        (1, 1, 0)
    );
}

#[test]
fn invalid_handle_cleanup_panic_retains_handle_until_confirmed_retry() {
    let driver = Driver {
        invalid_handle: true,
        panic_unload: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, grant(), driver).expect("worker");
    let panicked = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        worker.load_model(100, manifest())
    }));
    assert!(panicked.is_err());
    assert_eq!(
        worker.run(100, "model.1", request()),
        Err(Error::ModelUnavailable)
    );
    assert_eq!((worker.driver.loaded, worker.models.len()), (1, 1));
    worker.driver.panic_unload = false;
    worker
        .unload_model(100, "model.1")
        .expect("confirmed cleanup retry");
    assert_eq!(
        (
            worker.driver.loaded,
            worker.driver.unloads,
            worker.models.len()
        ),
        (0, 2, 0)
    );
    worker.driver.invalid_handle = false;
    worker
        .load_model(100, manifest())
        .expect("reload after confirmed cleanup");
    worker
        .run(100, "model.1", request())
        .expect("recovered execution");
}

#[derive(Debug, Default)]
struct AliasingDriver {
    physical_handles: BTreeMap<String, ModelManifest>,
    loads: usize,
    runs: usize,
    unloads: usize,
}

impl ModelDriver for AliasingDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loads += 1;
        let opaque_id = "handle.shared".to_string();
        self.physical_handles
            .insert(opaque_id.clone(), manifest.clone());
        Ok(DriverModelHandle {
            opaque_id,
            observed_memory_bytes: 1_024,
        })
    }

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.runs += 1;
        if !self.physical_handles.contains_key(&handle.opaque_id) {
            return Err(Error::DriverFailure("released handle".to_string()));
        }
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: true,
            output_digest: Some("9".repeat(64)),
            consumed_tokens: 16,
            observed_memory_bytes: 1_024,
        })
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        self.unloads += 1;
        self.physical_handles.remove(&handle.opaque_id);
        Ok(())
    }
}

impl NeuronFeatureDriver for AliasingDriver {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        self.runs += 1;
        Err(Error::DriverFailure(
            "unexpected feature execution".to_string(),
        ))
    }
}

#[test]
fn duplicate_physical_handle_fences_generation_without_automatically_releasing_alias() {
    // The smaller budget also proves alias detection precedes rejected-load cleanup.
    for maximum_memory_bytes in [4_096, 1_500] {
        let mut budget = grant();
        budget.maximum_memory_bytes = maximum_memory_bytes;
        let mut worker = InferenceWorker::new(
            100,
            "worker.1".to_string(),
            3,
            budget,
            AliasingDriver::default(),
        )
        .expect("worker");
        worker.load_model(100, manifest()).expect("known load");
        let mut second = manifest();
        second.model_id = "model.2".to_string();
        assert_eq!(
            worker.load_model(100, second.clone()),
            Err(Error::ModelUnavailable)
        );
        assert_eq!(
            &worker.driver.physical_handles,
            &BTreeMap::from([("handle.shared".to_string(), second.clone())])
        );
        assert_eq!(
            (
                worker.driver.loads,
                worker.driver.runs,
                worker.driver.unloads,
                worker.models.len()
            ),
            (2, 0, 0, 1)
        );
        for model_id in ["model.1", "model.2"] {
            assert_eq!(
                worker.run(100, model_id, request()),
                Err(Error::ModelUnavailable)
            );
            assert_eq!(
                worker.run_neuron_features(100, model_id, neuron_feature_request()),
                Err(Error::ModelUnavailable)
            );
        }
        worker
            .unload_model(100, "model.1")
            .expect("known alias cleanup");
        assert_eq!(worker.load_model(100, second), Err(Error::ModelUnavailable));
        assert_eq!(
            worker.run(100, "model.1", request()),
            Err(Error::ModelUnavailable)
        );
        assert_eq!(
            worker.run_neuron_features(100, "model.1", neuron_feature_request()),
            Err(Error::ModelUnavailable)
        );
        assert_eq!(
            (
                worker.driver.loads,
                worker.driver.runs,
                worker.driver.unloads,
                worker.models.len(),
                worker.driver.physical_handles.len()
            ),
            (2, 0, 1, 0, 0)
        );
    }
}
