use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::WitnessStoreError;

use super::AgentdNeuronOwner;

struct StubWitness;

impl AnchorWitnessStore for StubWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        Ok(None)
    }

    fn compare_and_swap(
        &mut self,
        _expected: Option<JournalAnchor>,
        _next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        Ok(())
    }
}

struct StubInferenceControl;

impl NeuronInferenceControlPort for StubInferenceControl {
    fn execute_feature(
        &mut self,
        _request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        Err(NeuronModelError::Rejected)
    }
}

#[test]
fn agentd_neuron_owner_is_a_compiled_product_surface() {
    let name = std::any::type_name::<AgentdNeuronOwner<StubWitness, StubInferenceControl>>();
    assert!(name.contains("AgentdNeuronOwner"));
}

#[test]
fn agentd_local_baseline_exposes_only_witnessed_neuron_state() {
    use codex_hepta_neuron::NeuronLocalCheckpointBindingV1;
    use codex_hepta_neuron::NeuronRuntimeError;

    // This type-checks the exact, non-mutating Agentd owner ingress against
    // the real generic NeuronRuntime. The native runtime tests separately
    // prove a committed checkpoint, witness mismatch and pending write cases.
    let read: fn(
        &AgentdNeuronOwner<StubWitness, StubInferenceControl>,
    ) -> Result<NeuronLocalCheckpointBindingV1, NeuronRuntimeError> =
        AgentdNeuronOwner::read_local_checkpoint_binding_v1;
    let _ = read;
}
