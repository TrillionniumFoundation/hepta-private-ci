#![no_main]

use codex_hepta_cognitive_types::hnmf::{
    CrossModalBindingV1, MemoryEventV1, ModalitySpanRefV1,
};
use codex_hepta_cognitive_types::hnmf_learning::{
    EngramNodeV1, ForgetPropagationReceiptV1, MemoryCueV1, OutcomeSignalV1,
    PlasticityBatchV1, RecallPacketV1, ReplaySelectionReceiptV1, SynapseV1,
    TopologyProposalV1,
};
use codex_hepta_cognitive_types::wire::decode_wire_v1;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = decode_wire_v1::<ModalitySpanRefV1>(data);
    let _ = decode_wire_v1::<MemoryEventV1>(data);
    let _ = decode_wire_v1::<CrossModalBindingV1>(data);
    let _ = decode_wire_v1::<EngramNodeV1>(data);
    let _ = decode_wire_v1::<SynapseV1>(data);
    let _ = decode_wire_v1::<MemoryCueV1>(data);
    let _ = decode_wire_v1::<RecallPacketV1>(data);
    let _ = decode_wire_v1::<OutcomeSignalV1>(data);
    let _ = decode_wire_v1::<ReplaySelectionReceiptV1>(data);
    let _ = decode_wire_v1::<PlasticityBatchV1>(data);
    let _ = decode_wire_v1::<TopologyProposalV1>(data);
    let _ = decode_wire_v1::<ForgetPropagationReceiptV1>(data);
});
