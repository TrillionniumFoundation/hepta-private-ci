use codex_hepta_cognitive_types::consumer::CONSUMER_CONVERGENCE_PROFILES_V1;
use codex_hepta_cognitive_types::consumer::CognitiveConsumerV1;
use codex_hepta_cognitive_types::consumer::SchemaFlowV1;
use codex_hepta_cognitive_types::hnmf::CrossModalBindingV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::hnmf_learning::ForgetPropagationReceiptV1;
use codex_hepta_cognitive_types::wire::CognitiveContractV1;

fn assert_binding<T: CognitiveContractV1>(flow: SchemaFlowV1) {
    let profile = CONSUMER_CONVERGENCE_PROFILES_V1
        .iter()
        .find(|profile| profile.consumer == CognitiveConsumerV1::CognitiveRead)
        .expect("cognitive.read profile");
    assert!(profile.canonical_bindings.iter().any(|binding| {
        binding.flow == flow
            && binding.schema_id == T::SCHEMA_ID
            && binding.contract_id == T::CONTRACT_ID
    }));
}

#[test]
fn cognitive_read_compiles_against_closed_canonical_inputs() {
    assert_binding::<MemoryEventV1>(SchemaFlowV1::Input);
    assert_binding::<CrossModalBindingV1>(SchemaFlowV1::Input);
    assert_binding::<ForgetPropagationReceiptV1>(SchemaFlowV1::Input);
}
