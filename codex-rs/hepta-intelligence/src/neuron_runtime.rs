//! Named product composition caller for neuron.runtime.
//!
//! The caller accepts a model port that is already bound to inference.control.
//! It does not depend on worker-private APIs, mint grants or bypass the runtime's
//! journal/witness/calibration checks.

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;

pub fn run_neuron_tick_v1<W, M>(
    runtime: &mut NeuronRuntime<W>,
    authority: &FinalUseAuthority,
    signed: &SignedFinalUseGrant,
    model: &mut M,
    tick: NeuronTickInputV1,
) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError>
where
    W: AnchorWitnessStore,
    M: NeuronModelPort,
{
    runtime.tick_authorized(authority, signed, model, tick)
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
