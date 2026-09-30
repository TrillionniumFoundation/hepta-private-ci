pub struct AgentdNeuronOwnerV2<W, P>
where
    W: AnchorWitnessStore,
    P: DurableNeuronInferenceControlPort,
{
    runtime: NeuronRuntimeV2<W>,
    inference_control: P,
}

impl<W, P> AgentdNeuronOwnerV2<W, P>
where
    W: AnchorWitnessStore,
    P: DurableNeuronInferenceControlPort,
{
    pub fn new(runtime: NeuronRuntimeV2<W>, inference_control: P) -> Self {
        Self {
            runtime,
            inference_control,
        }
    }

    pub fn runtime(&self) -> &NeuronRuntimeV2<W> {
        &self.runtime
    }

    /// Reconcile local index and witness obligations without starting model
    /// work. Provider-side recovery is deliberately exposed separately.
    pub fn reconcile(&mut self) -> Result<(), NeuronRuntimeV2Error> {
        self.runtime.reconcile()
    }
}

struct AgentdNeuronExecutionGateV2 {
    accepting_new_work: AtomicBool,
    epoch: AtomicU64,
    in_flight: RwLock<()>,
}

impl AgentdNeuronExecutionGateV2 {
    fn standalone() -> Self {
        Self {
            accepting_new_work: AtomicBool::new(true),
            epoch: AtomicU64::new(1),
            in_flight: RwLock::new(()),
        }
    }

    fn capture(&self) -> Result<u64, NeuronRuntimeV2Error> {
        let epoch = self.epoch.load(Ordering::Acquire);
        if !self.accepting_new_work.load(Ordering::Acquire) {
            return Err(NeuronRuntimeV2Error::Admission(
                NeuronAdmissionError::Revoked,
            ));
        }
        Ok(epoch)
    }

    fn enter(&self, expected_epoch: u64) -> Result<RwLockReadGuard<'_, ()>, NeuronRuntimeV2Error> {
        let guard = self
            .in_flight
            .read()
            .map_err(|_| NeuronRuntimeV2Error::Index(NeuronRuntimeIndexError::Poisoned))?;
        if !self.accepting_new_work.load(Ordering::Acquire)
            || self.epoch.load(Ordering::Acquire) != expected_epoch
        {
            return Err(NeuronRuntimeV2Error::Admission(
                NeuronAdmissionError::Revoked,
            ));
        }
        Ok(guard)
    }

    fn close(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        self.accepting_new_work.store(false, Ordering::Release);
        self.advance_epoch().map(|_| ())
    }

    fn open(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        self.advance_epoch()?;
        self.accepting_new_work.store(true, Ordering::Release);
        Ok(())
    }

    fn try_drain(&self) -> Result<RwLockWriteGuard<'_, ()>, AgentdNeuronControlErrorV2> {
        self.in_flight.try_write().map_err(|error| match error {
            TryLockError::WouldBlock => AgentdNeuronControlErrorV2::ControllerBusy,
            TryLockError::Poisoned(_) => AgentdNeuronControlErrorV2::ControllerPoisoned,
        })
    }

    fn snapshot(&self) -> (bool, u64) {
        (
            self.accepting_new_work.load(Ordering::Acquire),
            self.epoch.load(Ordering::Acquire),
        )
    }

    fn advance_epoch(&self) -> Result<u64, AgentdNeuronControlErrorV2> {
        let mut current = self.epoch.load(Ordering::Acquire);
        loop {
            let next = current
                .checked_add(1)
                .ok_or(AgentdNeuronControlErrorV2::GenerationConflict)?;
            match self.epoch.compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => return Ok(next),
                Err(observed) => current = observed,
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum AgentdNeuronRecoveryPolicyV2 {
    PreserveUnexecuted,
    CloseUnexecuted,
}

#[derive(Clone)]
pub struct AgentdNeuronHandleV2 {
    owner: Arc<dyn ProductNeuronOwnerV2>,
    config_digest: Digest32,
    lifecycle_gate: Arc<AgentdNeuronExecutionGateV2>,
}

#[derive(Clone)]
enum AgentdNeuronInvocationContextV2 {
    Neuron,
    DecisionCell(Box<DecisionCellInvocationV2>),
}

#[derive(Clone)]
pub struct AgentdNeuronInvocationV2 {
    handle: AgentdNeuronHandleV2,
    run_id: StableId,
    runtime_body_digest: Digest32,
    input: NeuronTickInputV1,
    lifecycle_epoch: u64,
    context: AgentdNeuronInvocationContextV2,
}

struct GuardedOwnerV2<W, P, G>
where
    W: AnchorWitnessStore,
    P: DurableNeuronInferenceControlPort,
{
    owner: AgentdNeuronOwnerV2<W, P>,
    admission: G,
}

#[derive(Default)]
struct AgentdNeuronCounterStoreV2 {
    owner_busy_rejections: AtomicU64,
    owner_poisoned_failures: AtomicU64,
    owner_lock_attempts: AtomicU64,
    owner_lock_acquired: AtomicU64,
    owner_lock_wait_micros_total: AtomicU64,
    owner_lock_wait_micros_max: AtomicU64,
    owner_lock_hold_micros_total: AtomicU64,
    owner_lock_hold_micros_max: AtomicU64,
    entry_rejections_before_runtime: AtomicU64,
    stale_invocation_rejections: AtomicU64,
    runtime_admission_denials: AtomicU64,
    recovery_attempts: AtomicU64,
    recovery_preserve_requests: AtomicU64,
    recovery_close_requests: AtomicU64,
    recovery_converged: AtomicU64,
    recovery_pending: AtomicU64,
    recovery_errors: AtomicU64,
}

impl AgentdNeuronCounterStoreV2 {
    fn record_lock_wait(&self, elapsed: u64) {
        self.owner_lock_acquired.fetch_add(1, Ordering::Relaxed);
        self.owner_lock_wait_micros_total
            .fetch_add(elapsed, Ordering::Relaxed);
        self.owner_lock_wait_micros_max
            .fetch_max(elapsed, Ordering::Relaxed);
    }

    fn record_lock_hold(&self, elapsed: u64) {
        self.owner_lock_hold_micros_total
            .fetch_add(elapsed, Ordering::Relaxed);
        self.owner_lock_hold_micros_max
            .fetch_max(elapsed, Ordering::Relaxed);
    }

    fn snapshot(&self) -> AgentdNeuronOperationalCountersV2 {
        AgentdNeuronOperationalCountersV2 {
            owner_busy_rejections: self.owner_busy_rejections.load(Ordering::Relaxed),
            owner_poisoned_failures: self.owner_poisoned_failures.load(Ordering::Relaxed),
            owner_lock_attempts: self.owner_lock_attempts.load(Ordering::Relaxed),
            owner_lock_acquired: self.owner_lock_acquired.load(Ordering::Relaxed),
            owner_lock_wait_micros_total: self
                .owner_lock_wait_micros_total
                .load(Ordering::Relaxed),
            owner_lock_wait_micros_max: self.owner_lock_wait_micros_max.load(Ordering::Relaxed),
            owner_lock_hold_micros_total: self
                .owner_lock_hold_micros_total
                .load(Ordering::Relaxed),
            owner_lock_hold_micros_max: self.owner_lock_hold_micros_max.load(Ordering::Relaxed),
            entry_rejections_before_runtime: self
                .entry_rejections_before_runtime
                .load(Ordering::Relaxed),
            stale_invocation_rejections: self.stale_invocation_rejections.load(Ordering::Relaxed),
            runtime_admission_denials: self.runtime_admission_denials.load(Ordering::Relaxed),
            recovery_attempts: self.recovery_attempts.load(Ordering::Relaxed),
            recovery_preserve_requests: self.recovery_preserve_requests.load(Ordering::Relaxed),
            recovery_close_requests: self.recovery_close_requests.load(Ordering::Relaxed),
            recovery_converged: self.recovery_converged.load(Ordering::Relaxed),
            recovery_pending: self.recovery_pending.load(Ordering::Relaxed),
            recovery_errors: self.recovery_errors.load(Ordering::Relaxed),
        }
    }
}

struct AgentdNeuronOwnerLockGuardV2<'a, W, P, G>
where
    W: AnchorWitnessStore,
    P: DurableNeuronInferenceControlPort,
{
    guard: MutexGuard<'a, GuardedOwnerV2<W, P, G>>,
    counters: &'a AgentdNeuronCounterStoreV2,
    acquired_at: Instant,
}

impl<W, P, G> std::ops::Deref for AgentdNeuronOwnerLockGuardV2<'_, W, P, G>
where
    W: AnchorWitnessStore,
    P: DurableNeuronInferenceControlPort,
{
    type Target = GuardedOwnerV2<W, P, G>;

    fn deref(&self) -> &Self::Target {
        &self.guard
    }
}

impl<W, P, G> std::ops::DerefMut for AgentdNeuronOwnerLockGuardV2<'_, W, P, G>
where
    W: AnchorWitnessStore,
    P: DurableNeuronInferenceControlPort,
{
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.guard
    }
}

impl<W, P, G> Drop for AgentdNeuronOwnerLockGuardV2<'_, W, P, G>
where
    W: AnchorWitnessStore,
    P: DurableNeuronInferenceControlPort,
{
    fn drop(&mut self) {
        self.counters
            .record_lock_hold(elapsed_micros(self.acquired_at));
    }
}

#[derive(Default)]
struct AgentdNeuronTelemetryV2 {
    outcome_unknown_since: Option<Instant>,
    witness_pending_since: Option<Instant>,
    previous_capacity: Option<(Instant, NeuronRuntimeCapacityV2)>,
}

struct SharedProductNeuronOwnerV2<W, P, G>
where
    W: AnchorWitnessStore,
    P: DurableNeuronInferenceControlPort,
{
    guarded: Mutex<GuardedOwnerV2<W, P, G>>,
    counters: AgentdNeuronCounterStoreV2,
    telemetry: Mutex<AgentdNeuronTelemetryV2>,
    generation: u64,
    body_bundle_digest: Digest32,
}

trait ProductNeuronOwnerV2: Send + Sync {
    fn execute_decision_cell(
        &self,
        _invocation: &DecisionCellInvocationV2,
        _input: NeuronTickInputV1,
        _guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        Err(NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::BindingMismatch,
        ))
    }

    fn query_decision_cell_operation(
        &self,
        _invocation: &DecisionCellInvocationV2,
        _input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        Err(NeuronRuntimeV2Error::PendingOperation)
    }

    fn query_decision_cell_result_guarded(
        &self,
        _invocation: &DecisionCellInvocationV2,
        _input: &NeuronTickInputV1,
        _guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<Option<NeuronRuntimeCommitV2>, NeuronRuntimeV2Error> {
        Err(NeuronRuntimeV2Error::PendingOperation)
    }

    fn recover_decision_cell_control(
        &self,
        _invocation: &DecisionCellInvocationV2,
        _input: &NeuronTickInputV1,
        _policy: AgentdNeuronRecoveryPolicyV2,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        Err(AgentdNeuronControlErrorV2::PendingRecovery)
    }

    fn execute(
        &self,
        input: NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error>;

    fn query_result_guarded(
        &self,
        input: &NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<Option<NeuronRuntimeCommitV2>, NeuronRuntimeV2Error> {
        let _ = (input, guard);
        Err(NeuronRuntimeV2Error::PendingOperation)
    }

    fn recover_operation_control_with_policy(
        &self,
        _input: &NeuronTickInputV1,
        _policy: AgentdNeuronRecoveryPolicyV2,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        Err(AgentdNeuronControlErrorV2::Runtime(
            NeuronRuntimeV2Error::PendingOperation,
        ))
    }

    fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error>;

    fn reconcile_control(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        self.reconcile()
            .map_err(AgentdNeuronControlErrorV2::Runtime)
    }

    fn query_operation(
        &self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error>;

    fn query_operation_control(
        &self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        self.query_operation(tick_id, input_digest)
            .map_err(AgentdNeuronControlErrorV2::Runtime)
    }

    fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error>;

    fn operational_snapshot_control(
        &self,
    ) -> Result<AgentdNeuronOperationalSnapshotV2, AgentdNeuronControlErrorV2> {
        Ok(AgentdNeuronOperationalSnapshotV2 {
            generation: self.generation(),
            body_bundle_digest: self.body_bundle_digest().map(|value| value.to_string()),
            pending_tick_id: None,
            pending_input_digest: None,
            pending_operation_code: None,
            oldest_outcome_unknown_age_micros: None,
            pending_witness_count: 0,
            pending_witness_age_micros: None,
            capacity: self
                .capacity_snapshot()
                .map_err(AgentdNeuronControlErrorV2::Runtime)?,
            capacity_trend: None,
            counters: self.operational_counters(),
            last_measurement: None,
        })
    }

    fn generation(&self) -> Option<u64> {
        None
    }

    fn body_bundle_digest(&self) -> Option<Digest32> {
        None
    }

    fn operational_counters(&self) -> AgentdNeuronOperationalCountersV2 {
        AgentdNeuronOperationalCountersV2::default()
    }

    fn record_entry_rejection(&self) {}

    fn record_stale_invocation_rejection(&self) {
        self.record_entry_rejection();
    }
}

struct CombinedAdmission<'a> {
    selected: &'a mut dyn NeuronAdmissionGuard,
    stage: &'a mut dyn NeuronAdmissionGuard,
}

impl NeuronAdmissionGuard for CombinedAdmission<'_> {
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        self.stage.check(config, input)?;
        self.selected.check(config, input)
    }
}

fn compatibility_error(error: AgentdNeuronControlErrorV2) -> NeuronRuntimeV2Error {
    match error {
        AgentdNeuronControlErrorV2::Runtime(error) => error,
        AgentdNeuronControlErrorV2::ControlState(_)
        | AgentdNeuronControlErrorV2::OwnerPoisoned
        | AgentdNeuronControlErrorV2::ControllerPoisoned => {
            NeuronRuntimeV2Error::Index(NeuronRuntimeIndexError::Poisoned)
        }
        AgentdNeuronControlErrorV2::OwnerBusy | AgentdNeuronControlErrorV2::ControllerBusy => {
            NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Unavailable)
        }
        AgentdNeuronControlErrorV2::PendingRecovery => NeuronRuntimeV2Error::PendingOperation,
        AgentdNeuronControlErrorV2::NotServing
        | AgentdNeuronControlErrorV2::InvalidTransition
        | AgentdNeuronControlErrorV2::GenerationConflict
        | AgentdNeuronControlErrorV2::UnknownGeneration => {
            NeuronRuntimeV2Error::Admission(NeuronAdmissionError::BindingMismatch)
        }
    }
}
