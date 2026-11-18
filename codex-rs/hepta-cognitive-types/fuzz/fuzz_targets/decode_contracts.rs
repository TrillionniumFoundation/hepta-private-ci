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
use codex_hepta_cognitive_types::wire::CognitiveWireError;
use codex_hepta_cognitive_types::wire::decode_wire_v1;
use codex_hepta_cognitive_types::wire::encode_wire_v1;
use codex_hepta_cognitive_types::write_receipt::MemoryWriteReceiptV1;
use libfuzzer_sys::fuzz_target;

fn assert_canonical_round_trip<T: CognitiveContractV1>(
    data: &[u8],
    decoded: Result<T, CognitiveWireError>,
) {
    if let Ok(value) = decoded {
        let encoded = encode_wire_v1(&value).expect("decoded contract must re-encode");
        assert_eq!(encoded.as_slice(), data);
    }
}

fuzz_target!(|data: &[u8]| {
    let _ = inspect_registered_envelope_v1(data);
    assert_canonical_round_trip(data, decode_wire_v1::<ModalitySpanRefV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<MemoryEventV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<CrossModalBindingV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<EngramNodeV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<SynapseV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<MemoryCueV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<RecallPacketV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<OutcomeSignalV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<ReplaySelectionReceiptV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<PlasticityBatchV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<TopologyProposalV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<ForgetPropagationReceiptV1>(data));
    assert_canonical_round_trip(data, decode_wire_v1::<MemoryWriteReceiptV1>(data));
});
