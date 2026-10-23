//! Real held test allocations; no neural behavior or physical RSS acceptance.
use super::*;

struct MemoryDriver {
    inner: ResourceDriver,
    observed: DriverRunObservation,
}

impl MemoryDriver {
    fn observe(&mut self, handle: &DriverModelHandle) -> DriverRunObservation {
        self.inner.dispatched += 1;
        let sequence = self
            .inner
            .loads
            .iter()
            .find(|a| format!("handle.{}", a.sequence) == handle.opaque_id)
            .expect("original handle")
            .sequence;
        self.inner
            .live
            .get_mut(&sequence)
            .expect("live allocation")
            .resize(self.observed.observed_memory_bytes as usize, 42);
        self.observed.clone()
    }
}

impl ModelDriver for MemoryDriver {
    fn load(&mut self, a: &DriverLoadAttempt) -> Result<DriverLoadObservation, Error> {
        self.inner.load(a)
    }
    fn reconcile_load(&mut self, a: &DriverLoadAttempt) -> Result<DriverLoadObservation, Error> {
        self.inner.reconcile_load(a)
    }
    fn run(
        &mut self,
        h: &DriverModelHandle,
        _: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Ok(self.observe(h))
    }
    fn unload(&mut self, a: &DriverLoadAttempt) -> Result<DriverLoadObservation, Error> {
        if let Some(DriverLoadState::Owned(handle)) = &self.inner.reply {
            self.inner
                .live
                .get_mut(&a.sequence)
                .expect("live allocation")
                .resize(handle.observed_memory_bytes as usize, 42);
        }
        self.inner.unload(a)
    }
}

impl NeuronFeatureDriver for MemoryDriver {
    fn run_neuron_features(
        &mut self,
        h: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        let observed = self.observe(h);
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: observed.terminal_observed,
            succeeded: observed.succeeded,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: request.head_digest.clone(),
            drive_q24: vec![0; request.expected_output_width],
            prediction_q24: vec![0; request.expected_output_width],
            observed_memory_bytes: observed.observed_memory_bytes,
            transient_allocation_bytes: 0,
            queue_age_micros: 0,
            latency_micros: 0,
        })
    }
}

fn observed_memory(bytes: u64) -> DriverRunObservation {
    DriverRunObservation {
        terminal_observed: true,
        succeeded: true,
        output_digest: Some("9".repeat(64)),
        consumed_tokens: 1,
        observed_memory_bytes: bytes,
    }
}

fn memory_worker(observed: DriverRunObservation) -> InferenceWorker<MemoryDriver> {
    let mut limits = grant();
    limits.maximum_memory_bytes = 2 * KIB;
    InferenceWorker::new(
        NOW_MS,
        "worker.1".to_string(),
        /*generation*/ 3,
        limits,
        MemoryDriver {
            inner: ResourceDriver::default(),
            observed,
        },
    )
    .expect("worker")
}

#[test]
fn lifetime_envelope_violation_freezes_dispatch_without_minting_execution_terminality() {
    for path in [DispatchPath::Tokens, DispatchPath::NeuronFeatures] {
        for terminal_observed in [false, true] {
            let mut observed = observed_memory(KIB + 1);
            observed.terminal_observed = terminal_observed;
            observed.consumed_tokens = 65; // A request error cannot hide a lifetime violation.
            let mut worker = memory_worker(observed);
            worker.load_model(NOW_MS, manifest(), KIB).expect("load");
            assert_eq!(
                dispatch(&mut worker, path, "model.1", "request.1"),
                Err(Error::ModelCapacity)
            );
            for next in [DispatchPath::Tokens, DispatchPath::NeuronFeatures] {
                assert_eq!(
                    dispatch(&mut worker, next, "model.1", "request.2"),
                    Err(Error::ActiveRequests)
                );
            }
            assert_eq!(
                worker.load_model(NOW_MS, other(), KIB),
                Err(Error::ActiveRequests)
            );
            assert_eq!(worker.reconcile_load("model.1"), Err(Error::ActiveRequests));
            assert_eq!(
                (
                    worker.driver.inner.dispatched,
                    worker.driver.inner.loads.len()
                ),
                (1, 1)
            );
            assert_eq!(worker.driver.inner.live[&1].len(), KIB as usize + 1);
            if terminal_observed {
                assert!(worker.active_requests.is_empty());
                worker.driver.inner.reply = Some(DriverLoadState::NoEffect);
                assert!(worker.unload_model(NOW_MS, "model.1").is_err());
                worker.driver.inner.reply = None;
                worker
                    .unload_model(NOW_MS, "model.1")
                    .expect("original Released");
                worker
                    .load_model(NOW_MS, other(), 2 * KIB)
                    .expect("released reservation");
            } else {
                assert_eq!(
                    worker.active_requests,
                    BTreeMap::from([("request.1".to_string(), "model.1".to_string())])
                );
                assert_eq!(worker.models["model.1"].active_requests, 1);
                assert_eq!(
                    worker.unload_model(EXPIRED_MS, "model.1"),
                    Err(Error::ActiveRequests)
                );
                assert!(worker.driver.inner.releases.is_empty());
            }
        }
    }
}

#[test]
fn exact_envelope_boundary_still_allows_both_run_paths_and_remaining_budget() {
    for path in [DispatchPath::Tokens, DispatchPath::NeuronFeatures] {
        let mut worker = memory_worker(observed_memory(KIB));
        worker.load_model(NOW_MS, manifest(), KIB).expect("load");
        assert_eq!(
            dispatch(&mut worker, path, "model.1", "request.1"),
            Ok(ExecutionStatus::Succeeded)
        );
        assert_eq!(
            dispatch(&mut worker, path, "model.1", "request.2"),
            Ok(ExecutionStatus::Succeeded)
        );
        worker
            .load_model(NOW_MS, other(), KIB)
            .expect("remaining budget");
        assert_eq!(
            worker
                .driver
                .inner
                .live
                .values()
                .map(Vec::len)
                .sum::<usize>(),
            2 * KIB as usize
        );
    }
}

#[test]
fn token_limit_error_within_envelope_does_not_freeze_the_live_model() {
    let mut observed = observed_memory(KIB);
    observed.consumed_tokens = 65;
    let mut worker = memory_worker(observed);
    worker.load_model(NOW_MS, manifest(), KIB).expect("load");
    assert_eq!(
        dispatch(&mut worker, DispatchPath::Tokens, "model.1", "request.1"),
        Err(Error::TokenLimit)
    );
    assert_eq!(worker.models["model.1"].lifecycle, ModelLifecycle::Ready);
    worker.driver.observed.consumed_tokens = 1;
    assert_eq!(
        dispatch(&mut worker, DispatchPath::Tokens, "model.1", "request.2"),
        Ok(ExecutionStatus::Succeeded)
    );
    worker
        .load_model(NOW_MS, other(), KIB)
        .expect("remaining budget");
}

#[test]
fn cleanup_owned_over_envelope_also_freezes_new_model_admission() {
    let mut worker = memory_worker(observed_memory(KIB));
    worker.load_model(NOW_MS, manifest(), KIB).expect("load");
    worker.driver.inner.reply = Some(DriverLoadState::Owned(DriverModelHandle {
        opaque_id: "handle.1".to_string(),
        observed_memory_bytes: KIB + 1,
    }));
    assert!(worker.unload_model(NOW_MS, "model.1").is_err());
    assert_eq!(worker.driver.inner.live[&1].len(), KIB as usize + 1);
    assert_eq!(
        worker.load_model(NOW_MS, other(), KIB),
        Err(Error::ActiveRequests)
    );
    worker.driver.inner.reply = None;
    worker
        .unload_model(NOW_MS, "model.1")
        .expect("original Released");
}
