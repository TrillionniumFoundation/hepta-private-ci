use super::*;
use crate::PersistedLedgerEventKindV2;
const OLD_JOURNAL: &[u8] =
    include_bytes!("../tests/fixtures/legacy-format/integration-journal.bin");
const OLD_EVENT: &[u8] = include_bytes!("../tests/fixtures/legacy-format/integration-event.bin");
fn event() -> DiscriminatedLedgerEventV2 {
    DiscriminatedLedgerEventV2::from_body(
        PersistedLedgerEventKindV2::RetrievalPrepared,
        &OLD_EVENT[crate::legacy_inspection::LEGACY_EVENT_DOMAIN.len() + 1..],
    )
    .expect("source fixture body")
}
#[test]
fn discriminated_frames_chain_without_reinterpreting_legacy_frames() {
    let first = DiscriminatedLedgerFrameV2::new(1, Digest32::ZERO, event()).expect("first");
    let second = DiscriminatedLedgerFrameV2::new(2, first.chain_digest(), event()).expect("second");
    assert_eq!(
        DiscriminatedLedgerFrameV2::decode(first.encoded_bytes()).expect("first decode"),
        first
    );
    assert_eq!(
        DiscriminatedLedgerFrameV2::decode(second.encoded_bytes()).expect("second decode"),
        second
    );
    assert_eq!(second.predecessor(), first.chain_digest());
    assert_eq!(second.sequence(), 2);
    assert_eq!(second.event().body(), first.event().body());
    assert_ne!(second.chain_digest(), first.chain_digest());
    assert!(DiscriminatedLedgerFrameV2::decode(&OLD_JOURNAL[72..]).is_err());
    assert!(crate::durable_codec::decode_event(first.event().encoded_bytes()).is_err());
    assert!(DiscriminatedLedgerFrameV2::new(0, Digest32::ZERO, event()).is_err());
    assert!(DiscriminatedLedgerFrameV2::new(2, Digest32::ZERO, event()).is_err());
    assert!(DiscriminatedLedgerFrameV2::new(1, first.chain_digest(), event()).is_err());
}
#[test]
fn frame_truncation_corruption_and_rehashed_chain_substitution_reject() {
    let frame = DiscriminatedLedgerFrameV2::new(1, Digest32::ZERO, event()).expect("frame");
    let bytes = frame.encoded_bytes();
    for cut in 0..bytes.len() {
        assert!(DiscriminatedLedgerFrameV2::decode(&bytes[..cut]).is_err());
    }
    for at in 0..bytes.len() {
        let mut bad = bytes.to_vec();
        bad[at] ^= 1;
        assert!(
            DiscriminatedLedgerFrameV2::decode(&bad).is_err(),
            "byte {at}"
        );
    }
    let mut bad = bytes.to_vec();
    let footer = bad.len() - 32;
    bad[footer - 1] ^= 1;
    let checksum = Digest32::of_bytes(&bad[..footer]);
    bad[footer..].copy_from_slice(checksum.as_array());
    assert_eq!(
        DiscriminatedLedgerFrameV2::decode(&bad),
        Err(PersistedCodecErrorV2::Frame)
    );
}

// Python struct.pack/hashlib oracle, independent of the Rust frame encoder.
#[test]
fn independent_python_frame_vector_matches() {
    let frame = DiscriminatedLedgerFrameV2::new(1, Digest32::ZERO, event()).expect("frame");
    assert_eq!(
        frame.chain_digest().to_string(),
        "6230b320991f31b6a9a7f650beb0cab0b3b0da02263685d4115b2bed9d8306e7"
    );
    assert_eq!(
        Digest32::of_bytes(frame.encoded_bytes()).to_string(),
        "40cc7219f4a945e629c9b6dd470cba5aeadd17f273aa9fb1d56141af11ee5920"
    );
}
