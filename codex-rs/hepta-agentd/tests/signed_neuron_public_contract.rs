//! External non-cfg(test) Agentd API contract. No issuer/Control/Effect
//! authority is constructed, and no model or signed nonce can be invoked.
//! This checks that future independently provisioned callers can actually
//! name the exact signed NDU read, frontier and non-authorizing verifier.

use codex_hepta_agentd::AgentdNeuronOwner;
use codex_hepta_agentd::NduReadFrontierPortV1;
use codex_hepta_agentd::NduReadVerificationErrorV1;
use codex_hepta_agentd::NduReadVerifierV1;
use codex_hepta_agentd::SignedNduSnapshotReadV1;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::WitnessStoreError;

struct ExternalWitness;

impl AnchorWitnessStore for ExternalWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        Ok(None)
    }

    fn compare_and_swap(
        &mut self,
        _expected: Option<JournalAnchor>,
        _next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        Err(WitnessStoreError::Unavailable)
    }
}

struct ExternalNeverExecute;

impl NeuronInferenceControlPort for ExternalNeverExecute {
    fn execute_feature(
        &mut self,
        _request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        Err(NeuronModelError::Rejected)
    }
}

#[test]
fn external_signed_neuron_contract_is_typeable_without_granting_effects() {
    type Owner = AgentdNeuronOwner<ExternalWitness, ExternalNeverExecute>;
    let method: fn(
        &mut Owner,
        NeuronTickInputV1,
        &SignedNduSnapshotReadV1,
        &SignedFinalUseGrant,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> = Owner::tick_bound;
    let _ = method;
    let name = std::any::type_name::<NduReadVerifierV1>();
    assert!(name.contains("NduReadVerifierV1"));
    assert!(
        std::any::type_name::<NduReadVerificationErrorV1>()
            .contains("NduReadVerificationErrorV1")
    );
    assert!(
        std::any::type_name::<dyn NduReadFrontierPortV1>()
            .contains("NduReadFrontierPortV1")
    );
    // No original Control signer or model effect is constructed in this test.
}
