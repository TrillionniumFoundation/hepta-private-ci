use super::*;

#[derive(Debug)]
struct FaultDriver {
    loads: usize,
    runs: usize,
    unloads: usize,
    budgets: Vec<u64>,
    memory: u64,
    invalid_handle: bool,
    fail_unload: bool,
    fail_run: bool,
    terminal: bool,
    presence: ModelPresence,
}

impl Default for FaultDriver {
    fn default() -> Self {
        Self {
            loads: 0,
            runs: 0,
            unloads: 0,
            budgets: Vec::new(),
            memory: 1_024,
            invalid_handle: false,
            fail_unload: false,
            fail_run: false,
            terminal: true,
            presence: ModelPresence::Unknown,
        }
    }
}

impl ModelDriver for FaultDriver {
    fn load_with_budget(
        &mut self,
        manifest: &ModelManifest,
        maximum_memory_bytes: u64,
    ) -> Result<DriverModelHandle, Error> {
        self.budgets.push(maximum_memory_bytes);
        self.load(manifest)
    }

    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.loads += 1;
        Ok(DriverModelHandle {
            opaque_id: if self.invalid_handle {
                String::new()
            } else {
                format!("handle.{}", manifest.model_id)
            },
            observed_memory_bytes: self.memory,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.runs += 1;
        if self.fail_run {
            return Err(Error::DriverFailure(
                "lost execution acknowledgement".to_string(),
            ));
        }
        Ok(DriverRunObservation {
            terminal_observed: self.terminal,
            succeeded: self.terminal,
            output_digest: self.terminal.then(|| "9".repeat(64)),
            consumed_tokens: 16,
            observed_memory_bytes: self.memory,
        })
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        self.unloads += 1;
        if self.fail_unload {
            return Err(Error::DriverFailure(
                "lost unload acknowledgement".to_string(),
            ));
        }
        Ok(())
    }

    fn inspect_model(&mut self, _handle: &DriverModelHandle) -> Result<ModelPresence, Error> {
        Ok(self.presence)
    }
}

fn worker(memory_limit: u64) -> InferenceWorker<FaultDriver> {
    let mut grant = super::tests::grant();
    grant.maximum_memory_bytes = memory_limit;
    InferenceWorker::new(100, "worker.1".to_string(), 3, grant, FaultDriver::default())
        .expect("worker")
}

fn model(id: &str) -> ModelManifest {
    let mut manifest = super::tests::manifest();
    manifest.model_id = id.to_string();
    manifest
}

#[test]
fn load_receives_remaining_aggregate_budget_and_rejects_overflow() {
    let mut worker = worker(1_536);
    worker.load_model(100, model("model.1")).expect("first load");
    assert_eq!(
        worker.load_model(100, model("model.2")),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.budgets, vec![1_536, 512]);
    assert_eq!(worker.driver.unloads, 1);
    assert_eq!(worker.resident_memory_bytes(), Ok(1_024));
    assert_eq!(worker.model_lifecycle("model.2"), None);
}

#[test]
fn zero_remaining_capacity_denies_before_driver_entry() {
    let mut worker = worker(1_024);
    worker.load_model(100, model("model.1")).expect("load");
    assert_eq!(
        worker.load_model(100, model("model.2")),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.loads, 1);
}

#[test]
fn failed_unload_retains_handle_until_exact_presence_reconciliation() {
    for presence in [ModelPresence::Present, ModelPresence::Absent] {
        let mut worker = worker(4_096);
        worker.load_model(100, model("model.1")).expect("load");
        worker.driver.fail_unload = true;
        assert!(worker.unload_model(100, "model.1").is_err());
        assert_eq!(
            worker.model_lifecycle("model.1"),
            Some(ModelLifecycle::RepairRequired)
        );
        assert_eq!(worker.resident_memory_bytes(), Ok(1_024));
        assert_eq!(
            worker.unload_model(100, "model.1"),
            Err(Error::RepairRequired)
        );
        assert_eq!(
            worker.reconcile_model_cleanup("model.1"),
            Err(Error::RepairRequired)
        );
        assert_eq!(worker.driver.unloads, 1);
        worker.driver.presence = presence;
        worker.driver.fail_unload = false;
        worker.reconcile_model_cleanup("model.1").expect("reconcile");
        assert_eq!(worker.resident_memory_bytes(), Ok(0));
        assert_eq!(
            worker.driver.unloads,
            if presence == ModelPresence::Present { 2 } else { 1 }
        );
    }
}

#[test]
fn invalid_handle_and_failed_cleanup_remain_owned() {
    let mut worker = worker(4_096);
    worker.driver.invalid_handle = true;
    worker.driver.fail_unload = true;
    assert!(worker.load_model(100, model("model.1")).is_err());
    assert_eq!(
        worker.model_lifecycle("model.1"),
        Some(ModelLifecycle::RepairRequired)
    );
    assert_eq!(worker.resident_memory_bytes(), Ok(1_024));
}

#[test]
fn overbudget_load_and_failed_cleanup_block_further_admission() {
    let mut worker = worker(512);
    worker.driver.fail_unload = true;
    assert!(worker.load_model(100, model("model.1")).is_err());
    assert_eq!(worker.resident_memory_bytes(), Ok(1_024));
    assert_eq!(
        worker.load_model(100, model("model.2")),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.loads, 1);
}

#[test]
fn cleanup_remains_available_after_expiry_revocation_and_fencing() {
    let mut worker = worker(4_096);
    worker.load_model(100, model("model.1")).expect("load");
    worker.grant.revoked = true;
    worker.fence_generation();
    assert_eq!(
        worker.load_model(20_000, model("model.2")),
        Err(Error::GenerationFenced)
    );
    worker.unload_model(20_000, "model.1").expect("safe cleanup");
    assert_eq!(worker.resident_memory_bytes(), Ok(0));
}

#[test]
fn exact_terminal_duplicate_returns_receipt_without_reentry() {
    let mut worker = worker(4_096);
    worker.load_model(100, model("model.1")).expect("load");
    let request = super::tests::request();
    let original = worker.run(100, "model.1", request.clone()).expect("run");
    worker.fence_generation();
    assert_eq!(worker.run(20_000, "model.1", request.clone()), Ok(original));
    let mut changed = request;
    changed.maximum_tokens += 1;
    assert_eq!(
        worker.run(100, "model.1", changed),
        Err(Error::RequestConflict)
    );
    assert_eq!(worker.driver.runs, 1);
}

#[test]
fn same_model_name_with_changed_artifact_tuple_is_not_a_duplicate() {
    let mut worker = worker(4_096);
    worker.load_model(100, model("model.1")).expect("load");
    worker
        .run(100, "model.1", super::tests::request())
        .expect("run");
    worker.unload_model(100, "model.1").expect("unload");
    let mut changed = model("model.1");
    changed.tokenizer_digest = "a".repeat(64);
    worker.load_model(100, changed).expect("reload");
    assert_eq!(
        worker.run(100, "model.1", super::tests::request()),
        Err(Error::RequestConflict)
    );
    assert_eq!(worker.driver.runs, 1);
}

#[test]
fn nonterminal_execution_holds_slot_and_is_never_reentered() {
    let mut worker = worker(4_096);
    worker.driver.terminal = false;
    worker.load_model(100, model("model.1")).expect("load");
    let request = super::tests::request();
    let first = worker.run(100, "model.1", request.clone()).expect("unknown");
    assert_eq!(first.status, ExecutionStatus::Indeterminate);
    assert_eq!(worker.run(100, "model.1", request), Ok(first));
    assert_eq!(worker.driver.runs, 1);
    assert_eq!(worker.active_requests.len(), 1);
    assert_eq!(
        worker.unload_model(100, "model.1"),
        Err(Error::ActiveRequests)
    );
}

#[test]
fn driver_error_does_not_refund_the_execution_slot() {
    let mut worker = worker(4_096);
    worker.driver.fail_run = true;
    worker.load_model(100, model("model.1")).expect("load");
    assert!(worker.run(100, "model.1", super::tests::request()).is_err());
    assert_eq!(
        worker.run(100, "model.1", super::tests::request()),
        Err(Error::RequestIndeterminate)
    );
    assert_eq!(worker.driver.runs, 1);
    assert_eq!(worker.active_requests.len(), 1);
}

#[test]
fn aggregate_memory_overflow_is_an_error_not_saturation() {
    let mut worker = worker(u64::MAX);
    worker.load_model(100, model("model.1")).expect("first");
    worker.load_model(100, model("model.2")).expect("second");
    worker
        .models
        .get_mut("model.1")
        .expect("model")
        .handle
        .observed_memory_bytes = u64::MAX;
    assert_eq!(
        worker.resident_memory_bytes(),
        Err(Error::ArithmeticOverflow)
    );
}

#[test]
fn feature_transient_memory_is_included_in_total() {
    let mut grant = super::tests::grant();
    grant.maximum_memory_bytes = 2_048;
    let mut worker = InferenceWorker::new(
        100,
        "worker.1".to_string(),
        3,
        grant,
        super::tests::Driver::default(),
    )
    .expect("worker");
    worker.load_model(100, model("model.1")).expect("load");
    assert_eq!(
        worker.run_neuron_features(100, "model.1", super::tests::neuron_feature_request()),
        Err(Error::ModelCapacity)
    );
    assert_eq!(
        worker.model_lifecycle("model.1"),
        Some(ModelLifecycle::RepairRequired)
    );
}
