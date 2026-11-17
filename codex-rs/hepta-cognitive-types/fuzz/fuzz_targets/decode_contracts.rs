#![no_main]

use codex_hepta_cognitive_types::hnmf::CrossModalBindingV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::hnmf::ModalitySpanRefV1;
use codex_hepta_cognitive_types::hnmf_learning::EngramNodeV1;
use codex_hepta_cognitive_types::hnmf_learning::ForgetPropagationReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::MemoryCueV1;
use codex_hepta_cognitive_types::hnmf_learning::OutcomeSignalV1;
use codex_hepta_cognitive_types::hnmf_learning::PlasticityBatchV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallPacketV1;
use codex_hepta_cognitive_types::hnmf_learning::ReplaySelectionReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::SynapseV1;
use codex_hepta_cognitive_types::hnmf_learning::TopologyProposalV1;
use codex_hepta_cognitive_types::registry::inspect_registered_envelope_v1;
use codex_hepta_cognitive_types::wire::CognitiveContractV1;
use codex_hepta_cognitive_types::wire::decode_wire_v1;
use codex_hepta_cognitive_types::wire::encode_wire_v1;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteReceiptV1;
use libfuzzer_sys::fuzz_target;

fn assert_canonical_round_trip<T: CognitiveContractV1>(data: &[u8]) {
    if let Ok(value) = decode_wire_v1::<T>(data) {
        let encoded = encode_wire_v1(&value).expect("decoded contract must re-encode");
        assert_eq!(encoded.as_slice(), data);
    }
}

fuzz_target!(|data: &[u8]| {
    let _ = inspect_registered_envelope_v1(data);
    assert_canonical_round_trip::<ModalitySpanRefV1>(data);
    assert_canonical_round_trip::<MemoryEventV1>(data);
    assert_canonical_round_trip::<CrossModalBindingV1>(data);
    assert_canonical_round_trip::<EngramNodeV1>(data);
    assert_canonical_round_trip::<SynapseV1>(data);
    assert_canonical_round_trip::<MemoryCueV1>(data);
    assert_canonical_round_trip::<RecallPacketV1>(data);
    assert_canonical_round_trip::<OutcomeSignalV1>(data);
    assert_canonical_round_trip::<ReplaySelectionReceiptV1>(data);
    assert_canonical_round_trip::<PlasticityBatchV1>(data);
    assert_canonical_round_trip::<TopologyProposalV1>(data);
    assert_canonical_round_trip::<ForgetPropagationReceiptV1>(data);
    assert_canonical_round_trip::<MemoryWriteReceiptV1>(data);
});
