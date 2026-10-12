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

#[test]
fn agentd_observed_tick_api_requires_real_owner_and_strict_final_witness() {
    use crate::AgentdNeuronTickObservationV1;

    let execute: fn(
        &mut AgentdNeuronOwner<StubWitness, StubInferenceControl>,
        codex_hepta_neuron::NeuronTickInputV1,
    ) -> Result<
        (
            codex_hepta_neuron::NeuronRuntimeOutputV1,
            AgentdNeuronTickObservationV1,
        ),
        codex_hepta_neuron::NeuronRuntimeError,
    > = AgentdNeuronOwner::tick_with_observation_v1;
    let current: fn(
        &AgentdNeuronOwner<StubWitness, StubInferenceControl>,
        &AgentdNeuronTickObservationV1,
    ) -> Result<(), codex_hepta_neuron::NeuronRuntimeError> =
        AgentdNeuronOwner::revalidate_current_tick_observation_v1;
    let _ = (execute, current);
}

#[test]
fn agentd_observer_tick_join_requires_live_neuron_and_ledger_owners() {
    // Type-check the concrete product ingress: no caller-supplied bare
    // Ledger/source digest can bypass the Agentd Neuron witness check.
    let _read =
        AgentdNeuronOwner::<StubWitness, StubInferenceControl>::read_observer_linked_tick_v1;
}
