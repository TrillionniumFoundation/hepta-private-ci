#![no_main]

use codex_hepta_cognitive_types::hnmf::{
    CrossModalBindingV1, MemoryEventV1, ModalitySpanRefV1,
};
use codex_hepta_cognitive_types::hnmf_learning::{
    EngramNodeV1, ForgetPropagationReceiptV1, MemoryCueV1, OutcomeSignalV1,
    PlasticityBatchV1, RecallPacketV1, ReplaySelectionReceiptV1, SynapseV1,
    TopologyProposalV1,
};
use codex_hepta_cognitive_types::shared_experience::{
    SharedExperiencePublicationV2, SharedExperienceRevocationReceiptV2,
    SharedExperienceSnapshotV2, SharedExperienceUseReceiptV2,
};
use codex_hepta_cognitive_types::wire::{
    CognitiveContractV1, canonical_contract_digest_bound_v1, canonical_contract_digest_v1,
    decode_validated_wire_v1, decode_wire_v1, encode_wire_v1,
};
use libfuzzer_sys::fuzz_target;

fn check<T: CognitiveContractV1>(data: &[u8]) {
    if let Ok(value) = decode_validated_wire_v1::<T>(data) {
        let encoded = encode_wire_v1(value.as_inner()).expect("accepted input must reencode");
        assert_eq!(encoded.as_slice(), data, "accepted bytes must already be canonical");
        let again = decode_validated_wire_v1::<T>(&encoded).expect("canonical roundtrip");
        assert!(again.as_inner() == value.as_inner(), "roundtrip changed semantics");
        assert_eq!(
            canonical_contract_digest_v1(value.as_inner()).expect("frozen digest"),
            canonical_contract_digest_v1(again.as_inner()).expect("roundtrip frozen digest"),
        );
        assert_eq!(
            canonical_contract_digest_bound_v1(value.as_inner()).expect("bound digest"),
            canonical_contract_digest_bound_v1(again.as_inner()).expect("roundtrip bound digest"),
        );
    }
}

fuzz_target!(|data: &[u8]| {
    // Exercise every raw decoder independently. The validated path below then
    // checks that accepted bytes are canonical and semantically stable.
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

    check::<ModalitySpanRefV1>(data);
    check::<MemoryEventV1>(data);
    check::<CrossModalBindingV1>(data);
    check::<EngramNodeV1>(data);
    check::<SynapseV1>(data);
    check::<MemoryCueV1>(data);
    check::<RecallPacketV1>(data);
    check::<OutcomeSignalV1>(data);
    check::<ReplaySelectionReceiptV1>(data);
    check::<PlasticityBatchV1>(data);
    check::<TopologyProposalV1>(data);
    check::<ForgetPropagationReceiptV1>(data);
    check::<SharedExperiencePublicationV2>(data);
    check::<SharedExperienceSnapshotV2>(data);
    check::<SharedExperienceUseReceiptV2>(data);
    check::<SharedExperienceRevocationReceiptV2>(data);
});
