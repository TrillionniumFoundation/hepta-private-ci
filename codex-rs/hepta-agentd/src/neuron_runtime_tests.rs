use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::PreparedNeuronInferenceControlPort;
use codex_hepta_neuron::WitnessStoreError;

use super::AgentdDurableNeuronOwner;
use super::AgentdNeuronOwner;
use super::AgentdPreparedDurableNeuronOwner;

struct StubWitness;

impl AnchorWitnessStore for StubWitness {
    fn admit_new_anchor(&self, expected: Option<JournalAnchor>) -> Result<(), WitnessStoreError> {
        if self.current()? != expected {
            return Err(WitnessStoreError::Conflict);
        }
        Ok(())
    }

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

struct StubPreparedInferenceControl;

impl PreparedNeuronInferenceControlPort for StubPreparedInferenceControl {
    type Prepared = ();

    fn prepare_feature(
        &mut self,
        _request: &NeuronFeatureRequestV1,
    ) -> Result<Self::Prepared, NeuronModelError> {
        Ok(())
    }

    fn dispatch_prepared(
        &mut self,
        _request: &NeuronFeatureRequestV1,
        _prepared: Self::Prepared,
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
fn agentd_durable_neuron_owner_is_the_existing_product_owner_shape() {
    let name = std::any::type_name::<AgentdDurableNeuronOwner<StubWitness, StubInferenceControl>>();
    assert!(name.contains("AgentdNeuronOwner"));
    assert!(name.contains("DurableNeuronInferenceControlPortV1"));
}

#[test]
fn agentd_prepared_durable_owner_uses_the_same_product_owner_shape() {
    let name = std::any::type_name::<
        AgentdPreparedDurableNeuronOwner<StubWitness, StubPreparedInferenceControl>,
    >();
    assert!(name.contains("AgentdNeuronOwner"));
    assert!(name.contains("DurablePreparedNeuronInferenceControlPortV1"));
}
