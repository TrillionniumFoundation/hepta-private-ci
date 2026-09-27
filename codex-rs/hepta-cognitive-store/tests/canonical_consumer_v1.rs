use codex_hepta_cognitive_store::CanonicalCognitiveStoreV1Ext;
use codex_hepta_cognitive_types::consumer::CONSUMER_CONVERGENCE_PROFILES_V1;
use codex_hepta_cognitive_types::consumer::CognitiveConsumerV1;
use codex_hepta_cognitive_types::consumer::SchemaFlowV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::wire::CognitiveContractV1;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteReceiptV1;

fn assert_binding<T: CognitiveContractV1>(flow: SchemaFlowV1) {
    let profile = CONSUMER_CONVERGENCE_PROFILES_V1
        .iter()
        .find(|profile| profile.consumer == CognitiveConsumerV1::CognitiveStore)
        .expect("cognitive.store profile");
    assert!(profile.canonical_bindings.iter().any(|binding| {
        binding.flow == flow
            && binding.schema_id == T::SCHEMA_ID
            && binding.contract_id == T::CONTRACT_ID
    }));
}

fn assert_adapter_is_exported<T: CanonicalCognitiveStoreV1Ext>() {}

#[test]
fn cognitive_store_compiles_against_canonical_event_and_receipt() {
    assert_binding::<MemoryEventV1>(SchemaFlowV1::Input);
    assert_binding::<MemoryWriteReceiptV1>(SchemaFlowV1::Output);
    assert_adapter_is_exported::<codex_hepta_cognitive_store::AdmittedCognitiveStoreV2>();
}
