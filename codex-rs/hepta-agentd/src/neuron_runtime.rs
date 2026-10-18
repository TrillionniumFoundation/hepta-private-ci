//! Agentd-owned Neuron runtime composition.
//!
//! This is the named product-host ownership boundary for neuron.runtime source
//! composition.  It owns the long-lived runtime and the inference.control port
//! together so callers cannot bypass the exact feature-receipt adapter by
//! supplying drive/prediction vectors directly.  Constructing this owner does
//! not itself activate it in the daemon startup path.

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
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
    authority: FinalUseAuthority,
}

impl<W, P> AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    /// Only the trusted Agentd composition root may install the pinned,
    /// independently configured authority. Request payloads cannot swap
    /// verifying keys or supply a different authority for a single tick.
    pub fn new(
        runtime: NeuronRuntime<W>,
        inference_control: P,
        authority: FinalUseAuthority,
    ) -> Self {
        Self {
            runtime,
            inference_control,
            authority,
        }
    }

    pub fn tick_authorized(
        &mut self,
        signed: &SignedFinalUseGrant,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let mut model = InferenceControlModelPort::new(&mut self.inference_control);
        self.runtime
            .tick_authorized(&self.authority, signed, &mut model, input)
    }

    pub fn runtime(&self) -> &NeuronRuntime<W> {
        &self.runtime
    }
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
