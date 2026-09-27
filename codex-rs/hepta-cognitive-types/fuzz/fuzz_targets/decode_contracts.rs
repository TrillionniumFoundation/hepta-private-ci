#![no_main]

use codex_hepta_cognitive_types::hnmf::{CrossModalBindingV1, MemoryEventV1, ModalitySpanRefV1};
use codex_hepta_cognitive_types::hnmf_learning::{
    EngramNodeV1, ForgetPropagationReceiptV1, MemoryCueV1, OutcomeSignalV1,
    PlasticityBatchV1, RecallPacketV1, ReplaySelectionReceiptV1, SynapseV1,
    TopologyProposalV1,
};
use codex_hepta_cognitive_types::wire::{
    CognitiveContractV1, canonical_contract_digest_bound_v1, decode_wire_v1, encode_wire_v1,
};
use libfuzzer_sys::fuzz_target;

// A successful parse has a semantic oracle: exact bytes, typed round trip,
// stable bound digest, and rejection of a non-canonical whitespace mutation.
fn exercise<T: CognitiveContractV1 + std::fmt::Debug>(data: &[u8]) {
    if let Ok(value) = decode_wire_v1::<T>(data) {
        let encoded = encode_wire_v1(&value).unwrap_or_else(|error| panic!("encode: {error}"));
        assert_eq!(encoded.as_slice(), data);
        let round_trip = decode_wire_v1::<T>(&encoded)
            .unwrap_or_else(|error| panic!("round trip: {error}"));
        assert_eq!(value, round_trip);
        assert_eq!(
            canonical_contract_digest_bound_v1(&value).unwrap_or_else(|error| panic!("digest: {error}")),
            canonical_contract_digest_bound_v1(&round_trip).unwrap_or_else(|error| panic!("digest: {error}")),
        );
        let mut noncanonical = encoded;
        noncanonical.push(b' ');
        assert!(decode_wire_v1::<T>(&noncanonical).is_err());
    }
}

fuzz_target!(|data: &[u8]| {
    exercise::<ModalitySpanRefV1>(data);
    exercise::<MemoryEventV1>(data);
    exercise::<CrossModalBindingV1>(data);
    exercise::<EngramNodeV1>(data);
    exercise::<SynapseV1>(data);
    exercise::<MemoryCueV1>(data);
    exercise::<RecallPacketV1>(data);
    exercise::<OutcomeSignalV1>(data);
    exercise::<ReplaySelectionReceiptV1>(data);
    exercise::<PlasticityBatchV1>(data);
    exercise::<TopologyProposalV1>(data);
    exercise::<ForgetPropagationReceiptV1>(data);
});
