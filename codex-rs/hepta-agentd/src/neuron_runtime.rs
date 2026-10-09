//! Agentd-owned Neuron runtime composition.
//!
//! This is the named product-host ownership boundary for neuron.runtime source
//! composition.  It owns the long-lived runtime and the inference.control port
//! together so callers cannot bypass the exact feature-receipt adapter by
//! supplying drive/prediction vectors directly.  Constructing this owner does
//! not itself activate it in the daemon startup path.

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;

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

    /// Digest-only read receipt bound to the NDU owner. The caller must have
    /// independently validated the receipt before calling this method.
    pub fn tick_bound(
        &mut self,
        input: NeuronTickInputV1,
        snapshot: &codex_hepta_ndu::NduSnapshotRefV1,
        admitted_read_receipt_digest: codex_hepta_types::Digest32,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let mut model = InferenceControlModelPort::new(&mut self.inference_control);
        self.runtime.tick_with_ndu_snapshot(&mut model, input, snapshot, admitted_read_receipt_digest)
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

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
