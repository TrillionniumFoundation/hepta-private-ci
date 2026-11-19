//! Agentd-owned Neuron runtime composition.
//!
//! This is the named product-host ownership boundary for neuron.runtime source
//! composition.  It owns the long-lived runtime and the inference.control port
//! together so callers cannot bypass the exact feature-receipt adapter by
//! supplying drive/prediction vectors directly. There are deliberately no
//! public mutable accessors for either port or runtime: exposing the latter
//! would let callers inject an arbitrary NeuronModelPort into tick.
//! Constructing this owner does not itself activate it in the daemon startup
//! path, authenticate P, or authorize an external model invocation.

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

    /// Read-only inspection is safe; mutation must remain mediated by tick().
    ///
    /// In particular, returning &mut NeuronRuntime here would let external
    /// callers invoke NeuronRuntime::tick with an arbitrary NeuronModelPort,
    /// bypassing this owner's InferenceControlModelPort receipt validation.
    /// Likewise, the control port must not escape this owner mutably.
    pub fn runtime(&self) -> &NeuronRuntime<W> {
        &self.runtime
    }
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
