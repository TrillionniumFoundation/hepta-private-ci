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

#[derive(Clone)]
pub struct AgentdNeuronHandleV2 {
    owner: Arc<dyn ProductNeuronOwnerV2>,
    config_digest: Digest32,
}

#[derive(Clone)]
pub struct AgentdNeuronInvocationV2 {
    handle: AgentdNeuronHandleV2,
    run_id: StableId,
    runtime_body_digest: Digest32,
    input: NeuronTickInputV1,
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
    entry_rejections_before_runtime: AtomicU64,
    runtime_admission_denials: AtomicU64,
    recovery_attempts: AtomicU64,
    recovery_converged: AtomicU64,
    recovery_pending: AtomicU64,
    recovery_errors: AtomicU64,
}

impl AgentdNeuronCounterStoreV2 {
    fn snapshot(&self) -> AgentdNeuronOperationalCountersV2 {
        AgentdNeuronOperationalCountersV2 {
            owner_busy_rejections: self.owner_busy_rejections.load(Ordering::Relaxed),
            owner_poisoned_failures: self.owner_poisoned_failures.load(Ordering::Relaxed),
            entry_rejections_before_runtime: self
                .entry_rejections_before_runtime
                .load(Ordering::Relaxed),
            runtime_admission_denials: self.runtime_admission_denials.load(Ordering::Relaxed),
            recovery_attempts: self.recovery_attempts.load(Ordering::Relaxed),
            recovery_converged: self.recovery_converged.load(Ordering::Relaxed),
            recovery_pending: self.recovery_pending.load(Ordering::Relaxed),
            recovery_errors: self.recovery_errors.load(Ordering::Relaxed),
        }
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

    fn recover_operation_control(
        &self,
        _input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        Err(AgentdNeuronControlErrorV2::Runtime(
            NeuronRuntimeV2Error::PendingOperation,
        ))
    }

    fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error>;

    fn reconcile_control(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        self.reconcile().map_err(AgentdNeuronControlErrorV2::Runtime)
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
        AgentdNeuronControlErrorV2::OwnerBusy
        | AgentdNeuronControlErrorV2::ControllerBusy => {
            NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Unavailable)
        }
        AgentdNeuronControlErrorV2::OwnerPoisoned
        | AgentdNeuronControlErrorV2::ControllerPoisoned => {
            NeuronRuntimeV2Error::Index(NeuronRuntimeIndexError::Poisoned)
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
