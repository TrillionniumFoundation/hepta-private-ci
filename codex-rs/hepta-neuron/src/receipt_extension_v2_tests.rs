use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

#[test]
fn absent_extension_preserves_historical_bytes_exactly() {
    let checkpoint = b"legacy-canonical-checkpoint";
    let encoded = encode_full_receipt_v2(checkpoint, None).expect("encode");
    assert_eq!(encoded, checkpoint);
    assert_eq!(
        decode_full_receipt_v2(checkpoint, &encoded).expect("decode"),
        None
    );
}

#[test]
fn typed_extension_round_trips_and_binds_checkpoint() {
    let checkpoint = b"canonical-checkpoint-v2";
    let extension = NeuronReceiptExtensionV2::new(
        id("DecisionCellReceiptV1"),
        1,
        b"typed-decision-receipt".to_vec(),
    )
    .expect("extension");
    let encoded = encode_full_receipt_v2(checkpoint, Some(&extension)).expect("encode");
    assert_ne!(encoded, checkpoint);
    assert_eq!(
        decode_full_receipt_v2(checkpoint, &encoded).expect("decode"),
        Some(extension)
    );
    assert_eq!(
        decode_full_receipt_v2(b"changed-checkpoint", &encoded),
        Err(NeuronReceiptExtensionErrorV2::CheckpointMismatch)
    );
}

#[test]
fn payload_and_checksum_tampering_fail_closed() {
    let checkpoint = b"canonical-checkpoint-v2";
    let extension = NeuronReceiptExtensionV2::new(
        id("DecisionCellReceiptV1"),
        1,
        b"typed-decision-receipt".to_vec(),
    )
    .expect("extension");
    let encoded = encode_full_receipt_v2(checkpoint, Some(&extension)).expect("encode");

    let mut payload_tampered = encoded.clone();
    let index = payload_tampered.len() - CHECKSUM_BYTES - 1;
    payload_tampered[index] ^= 0x01;
    assert!(matches!(
        decode_full_receipt_v2(checkpoint, &payload_tampered),
        Err(NeuronReceiptExtensionErrorV2::PayloadMismatch)
            | Err(NeuronReceiptExtensionErrorV2::InvalidEnvelope)
    ));

    let mut checksum_tampered = encoded;
    let index = checksum_tampered.len() - 1;
    checksum_tampered[index] ^= 0x01;
    assert_eq!(
        decode_full_receipt_v2(checkpoint, &checksum_tampered),
        Err(NeuronReceiptExtensionErrorV2::InvalidEnvelope)
    );
}
