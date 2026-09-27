//! Agentd-owned Neuron runtime composition.
//!
//! This is the named product-host ownership boundary for neuron.runtime source
//! composition.  It owns the long-lived runtime and the inference.control port
//! together. The canonical product invocation uses a shared handle plus live
//! admission, never request-authored drive/prediction vectors. Constructing the
//! owner does not select a model or qualify a daemon deployment.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

pub struct AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    runtime: NeuronRuntime<W>,
    inference_control: P,
}

impl<W, P> AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    pub fn new(runtime: NeuronRuntime<W>, inference_control: P) -> Self {
        Self {
            runtime,
            inference_control,
        }
    }

    pub fn tick(
        &mut self,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let mut model = InferenceControlModelPort::new(&mut self.inference_control);
        self.runtime.tick(&mut model, input)
    }

    pub fn runtime(&self) -> &NeuronRuntime<W> {
        &self.runtime
    }

    pub fn runtime_mut(&mut self) -> &mut NeuronRuntime<W> {
        &mut self.runtime
    }

    pub fn inference_control_mut(&mut self) -> &mut P {
        &mut self.inference_control
    }
}

/// Cloneable reference to one long-lived owner, not a copied runtime/state.
#[derive(Clone)]
pub struct AgentdNeuronHandleV1 {
    owner: Arc<dyn ProductNeuronOwner>,
    config_digest: Digest32,
}

/// An owner-backed pending invocation. It contains features, never caller-authored
/// drive/prediction vectors. Only `AgentdNeuronHandleV1` can construct it.
#[derive(Clone)]
pub struct AgentdNeuronInvocationV1 {
    handle: AgentdNeuronHandleV1,
    run_id: StableId,
    runtime_body_digest: Digest32,
    input: NeuronTickInputV1,
}

struct GuardedOwner<W: AnchorWitnessStore, P: NeuronInferenceControlPort, G> {
    owner: AgentdNeuronOwner<W, P>,
    admission: G,
}

/// Private type-erasure boundary; arbitrary wire/request code cannot substitute
/// an executor for the actual durable Neuron owner.
trait ProductNeuronOwner: Send + Sync {
    fn execute(
        &self,
        input: NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError>;
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

impl<W, P, G> ProductNeuronOwner for Mutex<GuardedOwner<W, P, G>>
where
    W: AnchorWitnessStore + Send,
    P: NeuronInferenceControlPort + Send,
    G: NeuronAdmissionGuard + Send,
{
    fn execute(
        &self,
        input: NeuronTickInputV1,
        stage: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        // Fail boundedly rather than waiting past the caller's deadline on a
        // mutex held by an uninterruptible backend. The existing worker owns
        // admission and physical cancellation of model execution.
        let mut locked = self.try_lock().map_err(|error| match error {
            std::sync::TryLockError::WouldBlock => {
                NeuronRuntimeError::Admission(NeuronAdmissionError::Unavailable)
            }
            // A panic in the owner is not an ordinary busy retry. Reconstruct
            // the owner from its durable stores before publishing another result.
            std::sync::TryLockError::Poisoned(_) => NeuronRuntimeError::PendingReconciliation,
        })?;
        let GuardedOwner { owner, admission } = &mut *locked;
        let AgentdNeuronOwner {
            runtime,
            inference_control,
        } = owner;
        let mut model = InferenceControlModelPort::new(inference_control);
        let mut guard = CombinedAdmission {
            selected: admission,
            stage,
        };
        runtime.tick_guarded(&mut model, input, &mut guard)
    }
}

impl<W, P> AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore + Send + 'static,
    P: NeuronInferenceControlPort + Send + 'static,
{
    /// Install the selected-artifact/calibration/source admission owner exactly
    /// once. There is deliberately no permissive production default guard.
    pub fn into_shared<G>(self, admission: G) -> Result<AgentdNeuronHandleV1, NeuronRuntimeError>
    where
        G: NeuronAdmissionGuard + Send + 'static,
    {
        let config_digest = self.runtime.configuration_digest()?;
        Ok(AgentdNeuronHandleV1 {
            owner: Arc::new(Mutex::new(GuardedOwner {
                owner: self,
                admission,
            })),
            config_digest,
        })
    }
}

impl AgentdNeuronHandleV1 {
    pub fn prepare(
        &self,
        run_id: StableId,
        runtime_body_digest: Digest32,
        input: NeuronTickInputV1,
    ) -> Result<AgentdNeuronInvocationV1, NeuronRuntimeError> {
        input.semantic_digest()?;
        if input.tick_id != run_id
            || runtime_body_digest.is_zero()
            || input
                .body_generation
                .is_none_or(|generation| generation == 0)
        {
            return Err(NeuronRuntimeError::Admission(
                NeuronAdmissionError::BindingMismatch,
            ));
        }
        Ok(AgentdNeuronInvocationV1 {
            handle: self.clone(),
            run_id,
            runtime_body_digest,
            input,
        })
    }
}

impl AgentdNeuronInvocationV1 {
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
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        if input.run_id != self.run_id
            || input.objective_digest != self.input.objective_digest
            || input.predecessor_digest != self.input.ndu_snapshot_digest
        {
            return Err(NeuronRuntimeError::Admission(
                NeuronAdmissionError::BindingMismatch,
            ));
        }
        let mut bound = BoundConfiguration {
            expected: self.handle.config_digest,
            inner: guard,
        };
        self.handle.owner.execute(self.input.clone(), &mut bound)
    }
}

struct BoundConfiguration<'a> {
    expected: Digest32,
    inner: &'a mut dyn NeuronAdmissionGuard,
}
impl NeuronAdmissionGuard for BoundConfiguration<'_> {
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        if config.semantic_digest().ok() != Some(self.expected) {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        self.inner.check(config, input)
    }
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
