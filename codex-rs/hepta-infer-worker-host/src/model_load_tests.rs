use super::*;

const NOW_MS: u64 = 100;
const EXPIRED_MS: u64 = 10_000;
const KIB: u64 = 1_024;

#[derive(Clone, Copy, Default)]
enum Fault {
    #[default]
    Owned,
    Error,
    Unknown,
    NoEffect,
    InvalidId,
    OverBudget,
    Foreign,
    Alias,
}

#[derive(Default)]
struct ResourceDriver {
    fault: Fault,
    live: BTreeMap<u64, Vec<u8>>,
    loads: Vec<DriverLoadAttempt>,
    releases: Vec<DriverLoadAttempt>,
    queried: usize,
    dispatched: usize,
    release_error: bool,
    binding: Option<DriverLoadAttempt>,
    reply: Option<DriverLoadState>,
}

fn owned(sequence: u64) -> DriverLoadState {
    DriverLoadState::Owned(DriverModelHandle {
        opaque_id: format!("handle.{sequence}"),
        observed_memory_bytes: 1_024,
    })
}

impl ResourceDriver {
    fn observation(
        &self,
        attempt: &DriverLoadAttempt,
        state: DriverLoadState,
    ) -> DriverLoadObservation {
        DriverLoadObservation {
            attempt: self.binding.as_ref().unwrap_or(attempt).clone(),
            state,
        }
    }
}

impl ModelDriver for ResourceDriver {
    fn load(&mut self, attempt: &DriverLoadAttempt) -> Result<DriverLoadObservation, Error> {
        self.loads.push(attempt.clone());
        if matches!(self.fault, Fault::NoEffect) {
            return Ok(self.observation(attempt, DriverLoadState::NoEffect));
        }
        // Actual held test allocations, not a physical RSS or neural-backend measurement.
        self.live.insert(attempt.sequence, vec![42; 1_024]);
        let state = match self.fault {
            Fault::Error => return Err(Error::DriverFailure("allocated before error".to_string())),
            Fault::Unknown => DriverLoadState::Unknown,
            Fault::InvalidId => DriverLoadState::Owned(DriverModelHandle {
                opaque_id: "bad handle".to_string(),
                observed_memory_bytes: 1_024,
            }),
            Fault::OverBudget => DriverLoadState::Owned(DriverModelHandle {
                opaque_id: format!("handle.{}", attempt.sequence),
                observed_memory_bytes: attempt.reserved_memory_bytes + 1,
            }),
            Fault::Alias => owned(/*sequence*/ 1),
            Fault::Owned | Fault::Foreign | Fault::NoEffect => owned(attempt.sequence),
        };
        let mut observed = self.observation(attempt, state);
        if matches!(self.fault, Fault::Foreign) {
            observed.attempt.manifest.weights_digest = "f".repeat(64);
        }
        Ok(observed)
    }
    fn reconcile_load(
        &mut self,
        attempt: &DriverLoadAttempt,
    ) -> Result<DriverLoadObservation, Error> {
        self.queried += 1;
        Ok(self.observation(
            attempt,
            self.reply.clone().unwrap_or(DriverLoadState::Unknown),
        ))
    }
    fn run(
        &mut self,
        _: &DriverModelHandle,
        _: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.dispatched += 1;
        Err(Error::DriverFailure("execution unknown".to_string()))
    }
    fn unload(&mut self, attempt: &DriverLoadAttempt) -> Result<DriverLoadObservation, Error> {
        self.releases.push(attempt.clone());
        if self.release_error {
            return Err(Error::DriverFailure("release unknown".to_string()));
        }
        let observed = self.observation(
            attempt,
            self.reply.clone().unwrap_or(DriverLoadState::Released),
        );
        if observed.attempt == *attempt && observed.state == DriverLoadState::Released {
            self.live.remove(&attempt.sequence);
        }
        Ok(observed)
    }
}

impl NeuronFeatureDriver for ResourceDriver {
    fn run_neuron_features(
        &mut self,
        _: &DriverModelHandle,
        _: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        self.dispatched += 1;
        Err(Error::DriverFailure("execution unknown".to_string()))
    }
}

fn worker(fault: Fault) -> InferenceWorker<ResourceDriver> {
    InferenceWorker::new(
        NOW_MS,
        "worker.1".to_string(),
        /*generation*/ 3,
        grant(),
        ResourceDriver {
            fault,
            ..ResourceDriver::default()
        },
    )
    .expect("worker")
}

fn other() -> ModelManifest {
    ModelManifest {
        model_id: "model.2".to_string(),
        ..manifest()
    }
}

#[test]
fn unknown_load_retains_budget_and_blocks_both_paths_without_redispatch() {
    for fault in [Fault::Error, Fault::Unknown] {
        let mut worker = worker(Fault::Owned);
        worker.load_model(NOW_MS, manifest(), KIB).expect("first");
        worker.driver.fault = fault;
        assert!(worker.load_model(NOW_MS, other(), 3 * KIB).is_err());
        let attempt = worker.models["model.2"].attempt.clone();
        for _ in 0..3 {
            assert_eq!(
                worker.reconcile_load("model.2"),
                Ok(DriverLoadState::Unknown)
            );
        }
        assert_eq!(
            worker.run(NOW_MS, "model.1", request()),
            Err(Error::ActiveRequests)
        );
        assert_eq!(
            worker.run_neuron_features(NOW_MS, "model.1", neuron_feature_request()),
            Err(Error::ActiveRequests)
        );
        let third = ModelManifest {
            model_id: "model.3".to_string(),
            ..manifest()
        };
        assert_eq!(
            worker.load_model(NOW_MS, third, KIB),
            Err(Error::ActiveRequests)
        );
        assert_eq!(
            (
                worker.driver.loads.len(),
                worker.driver.queried,
                worker.driver.dispatched
            ),
            (2, 3, 0)
        );
        assert_eq!(worker.models["model.2"].attempt, attempt);
        assert_eq!(worker.driver.live.len(), 2);
        worker.driver.reply = Some(owned(attempt.sequence));
        assert_eq!(
            worker.reconcile_load("model.2"),
            Ok(owned(attempt.sequence))
        );
        assert_eq!(worker.models["model.2"].attempt, attempt);
    }
}

#[test]
fn no_effect_releases_only_before_owned_and_retry_gets_a_fresh_attempt() {
    let mut worker = worker(Fault::NoEffect);
    assert!(worker.load_model(NOW_MS, manifest(), 4 * KIB).is_err());
    assert!(worker.models.is_empty() && worker.driver.live.is_empty());
    worker.driver.fault = Fault::Owned;
    worker
        .load_model(NOW_MS, manifest(), 4 * KIB)
        .expect("fresh load");
    assert_eq!(
        worker.driver.loads[1].sequence,
        worker.driver.loads[0].sequence + 1
    );
    for reply in [
        DriverLoadState::NoEffect,
        DriverLoadState::Unknown,
        owned(/*sequence*/ 2),
    ] {
        worker.driver.reply = Some(reply);
        assert!(worker.unload_model(NOW_MS, "model.1").is_err());
        assert_eq!(worker.reconcile_load("model.1"), Err(Error::ActiveRequests));
        assert_eq!(
            worker.models["model.1"].lifecycle,
            ModelLifecycle::UnloadUnresolved
        );
        assert_eq!(worker.driver.live.len(), 1);
    }
    worker.driver.reply = None;
    worker.unload_model(NOW_MS, "model.1").expect("released");
    assert!(worker.models.is_empty() && worker.driver.live.is_empty());
}

#[test]
fn rejected_load_cleanup_retains_original_attempt_and_never_releases_another_model() {
    for fault in [
        Fault::InvalidId,
        Fault::OverBudget,
        Fault::Foreign,
        Fault::Alias,
    ] {
        let mut worker = worker(Fault::Owned);
        worker
            .load_model(NOW_MS, manifest(), 2 * KIB)
            .expect("first");
        let first = worker.models["model.1"].handle.clone();
        worker.driver.fault = fault;
        worker.driver.release_error = true;
        assert!(worker.load_model(NOW_MS, other(), 2 * KIB).is_err());
        let attempt = worker.models["model.2"].attempt.clone();
        assert_eq!(worker.driver.releases, vec![attempt.clone()]);
        assert_eq!(
            worker.models["model.2"].lifecycle,
            ModelLifecycle::LoadRejected
        );
        assert_eq!(worker.reconcile_load("model.2"), Err(Error::ActiveRequests));
        assert_eq!(worker.driver.live.len(), 2);
        worker.driver.release_error = false;
        worker
            .unload_model(EXPIRED_MS, "model.2")
            .expect("original cleanup after expiry");
        assert_eq!(worker.driver.releases, vec![attempt.clone(), attempt]);
        assert_eq!(worker.models["model.1"].handle, first);
        assert_eq!(
            worker.driver.live.keys().copied().collect::<Vec<_>>(),
            vec![1]
        );
    }
}

#[test]
fn mismatched_original_bindings_never_release_reservations() {
    let mutations: [fn(&mut DriverLoadAttempt); 7] = [
        |a| a.worker_id.push('x'),
        |a| a.worker_generation += 1,
        |a| a.sequence += 1,
        |a| a.grant.authority_epoch += 1,
        |a| a.grant.semantic_digest = "f".repeat(64),
        |a| a.manifest.tokenizer_digest = "f".repeat(64),
        |a| a.reserved_memory_bytes -= 1,
    ];
    for mutate in mutations {
        let mut worker = worker(Fault::Unknown);
        assert!(worker.load_model(NOW_MS, manifest(), 4 * KIB).is_err());
        let attempt = worker.models["model.1"].attempt.clone();
        let mut wrong = attempt.clone();
        mutate(&mut wrong);
        worker.driver.binding = Some(wrong);
        worker.driver.reply = Some(DriverLoadState::Released);
        assert!(worker.reconcile_load("model.1").is_err());
        assert_eq!(worker.models["model.1"].attempt, attempt);
        assert_eq!(worker.driver.releases, vec![attempt.clone()]);
        assert_eq!(worker.driver.live.len(), 1);
        worker.driver.binding = None;
        worker
            .unload_model(NOW_MS, "model.1")
            .expect("correct original receipt");
        assert!(worker.driver.live.is_empty());
    }
}

#[test]
fn lifetime_budget_sum_and_overflow_are_checked_before_load() {
    let mut worker = worker(Fault::Owned);
    worker
        .load_model(NOW_MS, manifest(), 3 * KIB)
        .expect("reserve above observed low water");
    for budget in [0, 2 * KIB] {
        assert_eq!(
            worker.load_model(NOW_MS, other(), budget),
            Err(Error::ModelCapacity)
        );
    }
    worker.driver.release_error = true;
    assert!(worker.unload_model(NOW_MS, "model.1").is_err());
    assert_eq!(
        worker.load_model(NOW_MS, other(), 2 * KIB),
        Err(Error::ModelCapacity)
    );
    assert_eq!(worker.driver.loads.len(), 1);
    let mut limits = grant();
    limits.maximum_memory_bytes = u64::MAX;
    let mut overflow = InferenceWorker::new(
        NOW_MS,
        "worker.2".to_string(),
        /*generation*/ 3,
        limits,
        ResourceDriver::default(),
    )
    .expect("worker");
    overflow
        .load_model(NOW_MS, manifest(), u64::MAX)
        .expect("reserve maximum");
    assert_eq!(
        overflow.load_model(NOW_MS, other(), /*reserved_memory_bytes*/ 1),
        Err(Error::ArithmeticOverflow)
    );
    assert_eq!(overflow.driver.loads.len(), 1);
}

#[test]
fn expiry_allows_original_reconciliation_but_never_new_execution() {
    let mut worker = worker(Fault::Unknown);
    assert!(worker.load_model(NOW_MS, manifest(), 4 * KIB).is_err());
    worker.driver.reply = Some(owned(/*sequence*/ 1));
    worker
        .reconcile_load("model.1")
        .expect("observe original load");
    assert_eq!(
        worker.run(EXPIRED_MS, "model.1", request()),
        Err(Error::GrantExpired)
    );
    assert_eq!(
        worker.run_neuron_features(EXPIRED_MS, "model.1", neuron_feature_request()),
        Err(Error::GrantExpired)
    );
    assert_eq!(
        worker.load_model(EXPIRED_MS, other(), /*reserved_memory_bytes*/ 1),
        Err(Error::GrantExpired)
    );
    worker.driver.reply = None;
    worker.unload_model(EXPIRED_MS, "model.1").expect("cleanup");
    assert!(worker.driver.live.is_empty());
}

#[test]
fn load_reconciliation_cannot_wash_an_unterminated_execution() {
    let mut worker = worker(Fault::Owned);
    worker
        .load_model(NOW_MS, manifest(), 4 * KIB)
        .expect("load");
    assert!(worker.run(NOW_MS, "model.1", request()).is_err());
    assert_eq!(worker.reconcile_load("model.1"), Err(Error::ActiveRequests));
    assert_eq!(
        worker.unload_model(EXPIRED_MS, "model.1"),
        Err(Error::ActiveRequests)
    );
    assert_eq!(
        (
            worker.driver.queried,
            worker.driver.releases.len(),
            worker.driver.live.len()
        ),
        (0, 0, 1)
    );
}
