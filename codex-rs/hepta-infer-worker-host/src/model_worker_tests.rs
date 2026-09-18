use super::*;

#[derive(Debug, Default)]
struct Driver {
    fail_terminal: bool,
    indeterminate: bool,
    loaded: usize,
    observed_grant: Option<ResourceGrant>,
}

impl ModelDriver for Driver {
    fn load(
        &mut self,
        manifest: &ModelManifest,
        grant: &ResourceGrant,
    ) -> Result<DriverModelHandle, Error> {
        self.loaded += 1;
        self.observed_grant = Some(grant.clone());
        Ok(DriverModelHandle {
            opaque_id: format!("handle.{}", manifest.model_id),
            observed_memory_bytes: 1_024,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
        grant: &ResourceGrant,
    ) -> Result<DriverRunObservation, Error> {
        self.observed_grant = Some(grant.clone());
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
        semantic_digest: "1".repeat(64),
    }
}

fn verified_grant(now_ms: u64) -> VerifiedResourceGrant {
    VerifiedResourceGrant::test_only(now_ms, grant()).expect("verified test grant")
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
        isolation_digest: "a".repeat(64),
        maximum_tokens: 128,
    }
}

fn request() -> WorkerRequest {
    let prompt = "exact local input".to_string();
    let payload_digest = sha256_hex(prompt.as_bytes());
    WorkerRequest {
        request_id: "request.1".to_string(),
        reservation_id: "reservation.1".to_string(),
        model_digest: "2".repeat(64),
        payload_digest: payload_digest.clone(),
        prompt,
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
    let mut worker = InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        verified_grant(100),
        Driver::default(),
    )
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
fn driver_receives_exact_verified_capacity_before_load_and_run() {
    let expected = grant();
    let mut worker = InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        verified_grant(100),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert_eq!(worker.driver.observed_grant.as_ref(), Some(&expected));
    worker.run(100, "model.1", request()).expect("run");
    assert_eq!(worker.driver.observed_grant.as_ref(), Some(&expected));
}

#[test]
fn rejects_changed_model_lease_or_actual_payload() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        verified_grant(100),
        Driver::default(),
    )
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
    changed.prompt.push_str(" drift");
    assert_eq!(
        worker.run(100, "model.1", changed),
        Err(Error::PayloadMismatch)
    );
}

#[test]
fn lost_driver_terminality_is_indeterminate() {
    let driver = Driver {
        indeterminate: true,
        ..Driver::default()
    };
    let mut worker =
        InferenceWorker::new(100, "worker.1".to_string(), 3, verified_grant(100), driver)
            .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    let observed = worker.run(100, "model.1", request()).expect("run");
    assert_eq!(observed.status, ExecutionStatus::Indeterminate);
    assert!(!observed.terminal_observed);
    assert_eq!(observed.output_digest, None);
}

#[test]
fn expired_grant_blocks_new_work_but_never_blocks_cleanup() {
    let mut worker = InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        verified_grant(100),
        Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, manifest()).expect("load");
    assert_eq!(
        worker.run(10_000, "model.1", request()),
        Err(Error::GrantExpired)
    );
    assert!(
        worker
            .unload_model(10_000, "model.1")
            .expect("cleanup after expiry")
            .terminal_observed
    );
}

#[test]
fn resource_binding_changes_when_capacity_or_semantics_change() {
    let base = grant();
    let binding = resource_grant_binding("worker.1", &base).expect("binding");
    let mut changed = base.clone();
    changed.maximum_memory_bytes += 1;
    assert_ne!(
        resource_grant_binding("worker.1", &changed).unwrap(),
        binding
    );
    let mut changed = base;
    changed.semantic_digest = "2".repeat(64);
    assert_ne!(
        resource_grant_binding("worker.1", &changed).unwrap(),
        binding
    );
}
