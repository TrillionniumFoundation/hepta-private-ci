//! Named product composition caller for neuron.runtime.
//!
//! The caller accepts a model port that is already bound to inference.control.
//! It does not depend on worker-private APIs, mint grants or bypass the runtime's
//! journal/witness/calibration checks. Legacy unsigned dispatch is denied.

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;

pub fn run_neuron_tick_v1<W, M>(
    runtime: &mut NeuronRuntime<W>,
    model: &mut M,
    tick: NeuronTickInputV1,
) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError>
where
    W: AnchorWitnessStore,
    M: NeuronModelPort,
{
    // This legacy entry has no independently verified NDU read or signed
    // one-shot final-use grant. Never execute a model through this path.
    let _ = (runtime, model, tick);
    Err(NeuronRuntimeError::InvalidInput)
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
