//! Agentd ownership boundary for the unified V2 Neuron runtime.
//!
//! Product construction requires a durable inference-control port. The shared
//! handle exposes guarded invocations plus serialized administrative query and
//! reconciliation; it does not expose the mutable runtime or an execution bypass.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::DurableInferenceControlModelPort;
use codex_hepta_neuron::DurableNeuronInferenceControlPort;
use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronOperationStatusV2;
use codex_hepta_neuron::NeuronRuntimeCapacityV2;
use codex_hepta_neuron::NeuronRuntimeCommitV2;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeV2;
use codex_hepta_neuron::NeuronRuntimeV2Error;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

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
    /// work. Provider-side dispatched inference is reconciled by the durable
    /// inference-control owner before this method is called.
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

trait ProductNeuronOwnerV2: Send + Sync {
    fn execute(
        &self,
        input: NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error>;

    fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error>;

    fn query_operation(
        &self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error>;

    fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error>;
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

fn lock_owner<T>(owner: &Mutex<T>) -> Result<MutexGuard<'_, T>, NeuronRuntimeV2Error> {
    owner.try_lock().map_err(|error| match error {
        std::sync::TryLockError::WouldBlock => {
            NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Unavailable)
        }
        std::sync::TryLockError::Poisoned(_) => NeuronRuntimeV2Error::PendingOperation,
    })
}

impl<W, P, G> ProductNeuronOwnerV2 for Mutex<GuardedOwnerV2<W, P, G>>
where
    W: AnchorWitnessStore + Send,
    P: DurableNeuronInferenceControlPort + Send,
    G: NeuronAdmissionGuard + Send,
{
    fn execute(
        &self,
        input: NeuronTickInputV1,
        stage: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        let mut locked = lock_owner(self)?;
        let GuardedOwnerV2 { owner, admission } = &mut *locked;
        let AgentdNeuronOwnerV2 {
            runtime,
            inference_control,
        } = owner;
        let mut model = DurableInferenceControlModelPort::new(inference_control);
        let mut guard = CombinedAdmission {
            selected: admission,
            stage,
        };
        runtime.tick_guarded(&mut model, input, &mut guard)
    }

    fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error> {
        let mut locked = lock_owner(self)?;
        locked.owner.reconcile()
    }

    fn query_operation(
        &self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        let mut locked = lock_owner(self)?;
        locked
            .owner
            .runtime
            .query_operation(tick_id, input_digest)
    }

    fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
        let locked = lock_owner(self)?;
        locked.owner.runtime.capacity_snapshot()
    }
}

impl<W, P> AgentdNeuronOwnerV2<W, P>
where
    W: AnchorWitnessStore + Send + 'static,
    P: DurableNeuronInferenceControlPort + Send + 'static,
{
    pub fn into_shared<G>(
        self,
        admission: G,
    ) -> Result<AgentdNeuronHandleV2, NeuronRuntimeV2Error>
    where
        G: NeuronAdmissionGuard + Send + 'static,
    {
        let config_digest = self.runtime.configuration_digest()?;
        Ok(AgentdNeuronHandleV2 {
            owner: Arc::new(Mutex::new(GuardedOwnerV2 {
                owner: self,
                admission,
            })),
            config_digest,
        })
    }
}

impl AgentdNeuronHandleV2 {
    pub fn configuration_digest(&self) -> Digest32 {
        self.config_digest
    }

    /// Administrative local reconciliation. This never dispatches model work.
    pub fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error> {
        self.owner.reconcile()
    }

    /// Query exact operation truth through the same serialized product owner.
    pub fn query_operation(
        &self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        self.owner.query_operation(tick_id, input_digest)
    }

    /// Derive the canonical input digest and query the exact operation through
    /// the same serialized owner. This is the preferred host integration path.
    pub fn query_input_operation(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        self.query_operation(&input.tick_id, input.semantic_digest()?)
    }

    /// Advisory capacity through the same serialized product owner. Admission
    /// remains authoritative and may reject payload-specific work sooner.
    pub fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
        self.owner.capacity_snapshot()
    }

    pub fn prepare(
        &self,
        run_id: StableId,
        runtime_body_digest: Digest32,
        input: NeuronTickInputV1,
    ) -> Result<AgentdNeuronInvocationV2, NeuronRuntimeV2Error> {
        input.semantic_digest()?;
        if input.tick_id != run_id
            || runtime_body_digest.is_zero()
            || input.body_generation.is_none_or(|generation| generation == 0)
        {
            return Err(NeuronRuntimeV2Error::Admission(
                NeuronAdmissionError::BindingMismatch,
            ));
        }
        Ok(AgentdNeuronInvocationV2 {
            handle: self.clone(),
            run_id,
            runtime_body_digest,
            input,
        })
    }
}

impl AgentdNeuronInvocationV2 {
    pub fn runtime_body_digest(&self) -> Digest32 {
        self.runtime_body_digest
    }

    pub(crate) fn matches_run(&self, run_id: &StableId, body_generation: u64) -> bool {
        &self.run_id == run_id && self.input.body_generation == Some(body_generation)
    }

    pub(crate) fn execute(
        &self,
        input: &codex_hepta_intelligence::CanonicalPortInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        if input.run_id != self.run_id
            || input.objective_digest != self.input.objective_digest
            || input.predecessor_digest != self.input.ndu_snapshot_digest
        {
            return Err(NeuronRuntimeV2Error::Admission(
                NeuronAdmissionError::BindingMismatch,
            ));
        }
        let mut bound = BoundConfiguration {
            expected_config: self.handle.config_digest,
            inner: guard,
        };
        self.handle.owner.execute(self.input.clone(), &mut bound)
    }
}

struct BoundConfiguration<'a> {
    expected_config: Digest32,
    inner: &'a mut dyn NeuronAdmissionGuard,
}

impl NeuronAdmissionGuard for BoundConfiguration<'_> {
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        if config.semantic_digest().ok() != Some(self.expected_config) {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        self.inner.check(config, input)
    }
}

#[path = "neuron_artifact_admission_v2.rs"]
mod artifact_admission;

#[cfg(test)]
#[path = "neuron_runtime_v2_tests.rs"]
mod tests;
