use codex_hepta_cognitive_types::wire::{
    CognitiveContractV1, canonical_contract_digest_bound_v1, canonical_contract_digest_v1,
    decode_validated_canonical_payload_v1, decode_wire_v1,
};

pub fn exercise<T: CognitiveContractV1>(data: &[u8]) {
    let _ = decode_wire_v1::<T>(data);
    if let Ok(value) = decode_validated_canonical_payload_v1::<T>(data) {
        let encoded = value.encode_wire().expect("accepted input must reencode");
        assert_eq!(encoded.as_slice(), data, "accepted bytes must be canonical");
        assert_eq!(
            value.frozen_digest().digest(),
            canonical_contract_digest_v1(value.as_inner()).expect("frozen digest parity"),
        );
        assert_eq!(
            value.schema_bound_digest().digest(),
            canonical_contract_digest_bound_v1(value.as_inner())
                .expect("schema-bound digest parity"),
        );
    }
}
