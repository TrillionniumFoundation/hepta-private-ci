use super::*;

#[derive(Debug)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    loaded: usize,
    observed_memory_bytes: u64,
}

impl Default for Driver {
    fn default() -> Self {
        Self {
            fail_terminal: false,
            indeterminate: false,
            loaded: 0,
            observed_memory_bytes: 1_024,
        }
    }
}

impl ModelDriver for Driver {
    fn load(
        &mut self,
        manifest: &ModelManifest,
        _grant: &ResourceGrant,
    ) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        Ok(DriverModelHandle {
            opaque_id: format!("handle.{}", manifest.model_id),
            observed_memory_bytes: self.observed_memory_bytes,
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
                output: None,
                consumed_tokens: 4,
                observed_memory_bytes: self.observed_memory_bytes,
            });
        }
        Ok(DriverRunObservation {
            terminal_observed: true,
            succeeded: !self.fail_terminal,
            output: Some("model output".to_string()),
            consumed_tokens: 16,
            observed_memory_bytes: self.observed_memory_bytes,
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.loaded = self.loaded.saturating_sub(1);
        Ok(())
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
        device_digest: "8".repeat(64),
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
        license_digest: "9".repeat(64),
        sbom_digest: "a".repeat(64),
        runtime_digest: "7".repeat(64),
        device_digest: "8".repeat(64),
        maximum_tokens: 128,
    }
}

fn request() -> WorkerRequest {
    let payload = "hello local model".to_string();
    let payload_digest = sha256_hex(payload.as_bytes());
    WorkerRequest {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        model_digest: "2".repeat(64),
        payload,
        payload_digest: payload_digest.clone(),
        maximum_tokens: 64,
        deadline_ms: 9_000,
        lease_payload_digest: payload_digest,
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
    assert_eq!(observed.output.as_deref(), Some("model output"));
    assert_eq!(
        observed.output_digest,
        Some(sha256_hex(b"model output"))
    );
    assert!(observed.terminal_observed);
    assert!(
        worker
            .unload_model(100, "model.1")
            .expect("unload")
            .terminal_observed
    );
}

#[test]
fn rejects_changed_model_lease_or_actual_payload_tuple() {
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

    let mut changed = request();
    changed.payload.push('!');
    assert_eq!(
        worker.run(100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );
}

#[test]
fn grant_device_binding_rejects_wrong_device() {
    let mut bad_grant = grant();
    bad_grant.device_digest = "b".repeat(64);
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, bad_grant, Driver::default())
            .expect("worker");
    assert_eq!(
        worker.load_model(100, manifest()),
        Err(Error::ResourceMismatch("device"))
    );
}

#[test]
fn aggregate_loaded_memory_cannot_exceed_grant() {
    let mut tight = grant();
    tight.maximum_memory_bytes = 1_500;
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, tight, Driver::default())
            .expect("worker");
    worker.load_model(100, manifest()).expect("first load");

    let mut second = manifest();
    second.model_id = "model.2".to_string();
    second.model_digest = "b".repeat(64);
    assert_eq!(worker.load_model(100, second), Err(Error::ModelCapacity));
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
    assert_eq!(observed.output, None);
    assert_eq!(observed.output_digest, None);
}
