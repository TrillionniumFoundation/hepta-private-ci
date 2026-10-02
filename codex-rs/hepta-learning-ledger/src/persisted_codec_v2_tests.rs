use super::*;
use crate::LEDGER_CONTAINER_HEADER_V2_BYTES;
use crate::LedgerAnchor;
use crate::LedgerContainerHeaderV2;
use crate::LedgerContainerKindV2;
const CONFIRMED: &[u8] =
    include_bytes!("../tests/fixtures/legacy-format/operator-confirmation.bin");
const PREPARED: &[u8] = include_bytes!("../tests/fixtures/legacy-format/integration-event.bin");
const INTENT: &[u8] = include_bytes!("../tests/fixtures/legacy-format/operator-event.bin");

fn header() -> LedgerContainerHeaderV2 {
    LedgerContainerHeaderV2 {
        kind: LedgerContainerKindV2::Journal,
        binding: Digest32::of_bytes(b"fixture-store"),
        owner_generation: 2,
        writer_fence: 3,
        segment_index: 0,
        predecessor: LedgerAnchor {
            sequence: 0,
            chain_digest: Digest32::ZERO,
        },
        legacy_manifest_digest: None,
        maximum_records: 16,
        maximum_bytes: 4096,
    }
}

#[test]
fn explicit_v2_kinds_preserve_body_and_bind_semantic_discriminator() {
    for (legacy, kind) in [
        (PREPARED, PersistedLedgerEventKindV2::RetrievalPrepared),
        (
            INTENT,
            PersistedLedgerEventKindV2::RetrievalAssignmentIntent,
        ),
        (
            CONFIRMED,
            PersistedLedgerEventKindV2::RetrievalPublicationConfirmed,
        ),
    ] {
        let body = &legacy[LEGACY_EVENT_DOMAIN.len() + 1..];
        let event = DiscriminatedLedgerEventV2::from_body(kind, body).expect("body");
        assert_eq!(event.body(), body);
        assert_eq!(event.kind(), kind);
        assert_eq!(
            DiscriminatedLedgerEventV2::decode(event.encoded_bytes()).expect("decode"),
            event
        );
        assert_ne!(event.event_digest(), Digest32::of_bytes(legacy));
        assert_eq!(
            DiscriminatedLedgerEventV2::decode(legacy),
            Err(PersistedCodecErrorV2::Version)
        );
    }
    // The old assignment and preparation share a body grammar but are never
    // the same meaning. Explicit kinds remain cryptographically different.
    let body = &PREPARED[LEGACY_EVENT_DOMAIN.len() + 1..];
    let prepared =
        DiscriminatedLedgerEventV2::from_body(PersistedLedgerEventKindV2::RetrievalPrepared, body)
            .expect("prepared");
    let legacy = DiscriminatedLedgerEventV2::from_body(
        PersistedLedgerEventKindV2::LegacyRetrievalAssignment,
        body,
    )
    .expect("legacy assertion");
    assert_ne!(prepared.event_digest(), legacy.event_digest());
}

#[test]
fn event_kind_version_length_and_bounded_body_cannot_be_substituted() {
    let event = DiscriminatedLedgerEventV2::from_body(
        PersistedLedgerEventKindV2::RetrievalAssignmentIntent,
        &INTENT[LEGACY_EVENT_DOMAIN.len() + 1..],
    )
    .expect("intent");
    for cut in 0..event.encoded_bytes().len() {
        assert!(DiscriminatedLedgerEventV2::decode(&event.encoded_bytes()[..cut]).is_err());
    }
    let mut unknown = event.encoded_bytes().to_vec();
    unknown[LEDGER_EVENT_DOMAIN_V2.len()..LEDGER_EVENT_DOMAIN_V2.len() + 2]
        .copy_from_slice(&0x999_u16.to_be_bytes());
    assert_eq!(
        DiscriminatedLedgerEventV2::decode(&unknown),
        Err(PersistedCodecErrorV2::Kind)
    );
    let mut wrong = event.encoded_bytes().to_vec();
    wrong[LEDGER_EVENT_DOMAIN_V2.len()..LEDGER_EVENT_DOMAIN_V2.len() + 2]
        .copy_from_slice(&0x100_u16.to_be_bytes());
    assert_eq!(
        DiscriminatedLedgerEventV2::decode(&wrong),
        Err(PersistedCodecErrorV2::Body)
    );
    assert_eq!(
        DiscriminatedLedgerEventV2::from_body(PersistedLedgerEventKindV2::Common(10), b""),
        Err(PersistedCodecErrorV2::Kind)
    );
    assert_eq!(
        DiscriminatedLedgerEventV2::from_body(
            PersistedLedgerEventKindV2::RetrievalPrepared,
            &vec![0; MAX_LEDGER_EVENT_V2_BYTES]
        ),
        Err(PersistedCodecErrorV2::Size)
    );
    let mut extra = event.encoded_bytes().to_vec();
    extra.push(0);
    assert_eq!(
        DiscriminatedLedgerEventV2::decode(&extra),
        Err(PersistedCodecErrorV2::Size)
    );
}

#[test]
fn header_roundtrip_separates_new_history_and_legacy_manifest_continuation() {
    for kind in [
        LedgerContainerKindV2::Journal,
        LedgerContainerKindV2::Segment,
    ] {
        let mut h = header();
        h.kind = kind;
        let bytes = h.encode().expect("header");
        assert_eq!(bytes.len(), LEDGER_CONTAINER_HEADER_V2_BYTES);
        assert_eq!(LedgerContainerHeaderV2::decode(&bytes).expect("decode"), h);
        h.predecessor = LedgerAnchor {
            sequence: 12,
            chain_digest: Digest32::of_bytes(b"prior"),
        };
        assert_eq!(h.encode(), Err(PersistedCodecErrorV2::Header));
        h.legacy_manifest_digest = Some(Digest32::of_bytes(b"independently-admitted-inventory"));
        assert_eq!(
            LedgerContainerHeaderV2::decode(&h.encode().expect("continuation"))
                .expect("decode continuation"),
            h
        );
    }
}

#[test]
fn header_corruption_unknown_versions_and_invalid_context_fail_closed() {
    let valid = header().encode().expect("valid");
    for index in 0..valid.len() {
        let mut bytes = valid.clone();
        bytes[index] ^= 1;
        assert!(
            LedgerContainerHeaderV2::decode(&bytes).is_err(),
            "byte {index}"
        );
    }
    for mutation in 0..8 {
        let mut h = header();
        match mutation {
            0 => h.binding = Digest32::ZERO,
            1 => h.owner_generation = 0,
            2 => h.writer_fence = 0,
            3 => h.segment_index = 1,
            4 => h.legacy_manifest_digest = Some(Digest32::ZERO),
            5 => h.maximum_records = 8193,
            6 => h.maximum_bytes = 4095,
            _ => h.predecessor.chain_digest = Digest32::of_bytes(b"unbound"),
        };
        assert!(h.encode().is_err());
    }
    let mut flags = valid;
    flags[15] = 2;
    let hash = Digest32::of_bytes(&flags[..160]);
    flags[160..].copy_from_slice(hash.as_array());
    assert!(LedgerContainerHeaderV2::decode(&flags).is_err());
}

// Independently generated with Python struct.pack and hashlib.sha256.
#[test]
fn independent_python_header_and_event_vectors_match() {
    let expected_header = "484550544c5230320002000200000000e3e223b168741baf52e0af9630f45c140a979b5cedc1ad819d99aedcb2248e3c0000000000000002000000000000000300000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000000000000100029c80b8b7d46012c37f00b84477e6e31dd35e3ccd23fb892439fa08a87cee90a";
    let expected_event_digest = "0de4b53a343a4dd7d84354beb10b6439f7b80a28dce9e9d2097c6bc7350c1a89";
    let bytes = header().encode().expect("header");
    let actual = bytes.iter().map(|b| format!("{b:02x}")).collect::<String>();
    assert_eq!(actual, expected_header);
    let event = DiscriminatedLedgerEventV2::from_body(
        PersistedLedgerEventKindV2::RetrievalPrepared,
        &PREPARED[LEGACY_EVENT_DOMAIN.len() + 1..],
    )
    .expect("event");
    assert_eq!(event.event_digest().to_string(), expected_event_digest);
}
