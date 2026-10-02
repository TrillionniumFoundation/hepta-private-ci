use super::*;
use crate::inspect_legacy_container_v1;

const INTEGRATION_EVENT: &[u8] =
    include_bytes!("../tests/fixtures/legacy-format/integration-event.bin");
const OPERATOR_EVENT: &[u8] = include_bytes!("../tests/fixtures/legacy-format/operator-event.bin");
const INTEGRATION_JOURNAL: &[u8] =
    include_bytes!("../tests/fixtures/legacy-format/integration-journal.bin");
const OPERATOR_JOURNAL: &[u8] =
    include_bytes!("../tests/fixtures/legacy-format/operator-journal.bin");
const INTEGRATION_SEGMENT: &[u8] =
    include_bytes!("../tests/fixtures/legacy-format/integration-segment.bin");
const OPERATOR_SEGMENT: &[u8] =
    include_bytes!("../tests/fixtures/legacy-format/operator-segment.bin");

#[test]
fn actual_legacy_writers_have_distinct_tag_ten_meanings_and_preserved_bytes() {
    for (bytes, profile, kind) in [
        (
            INTEGRATION_EVENT,
            LegacyLedgerProfileV1::IntegrationPreparation,
            LegacyLedgerEventKindV1::RetrievalPrepared,
        ),
        (
            OPERATOR_EVENT,
            LegacyLedgerProfileV1::OperatorPublication,
            LegacyLedgerEventKindV1::RetrievalAssignmentIntent,
        ),
    ] {
        assert_eq!(bytes[LEGACY_EVENT_DOMAIN.len()], 10);
        let observation = InspectedLegacyEventV1::inspect(bytes, Some(profile))
            .expect("correct explicit profile");
        assert_eq!(observation.kind(), kind);
        assert_eq!(observation.caller_selected_profile(), profile);
        assert_eq!(observation.original_bytes(), bytes);
        assert_eq!(observation.original_digest(), Digest32::of_bytes(bytes));
        assert_eq!(
            InspectedLegacyEventV1::inspect(bytes, None),
            Err(LegacyInspectionError::ProfileRequired)
        );
        let wrong = if profile == LegacyLedgerProfileV1::IntegrationPreparation {
            LegacyLedgerProfileV1::OperatorPublication
        } else {
            LegacyLedgerProfileV1::IntegrationPreparation
        };
        assert!(InspectedLegacyEventV1::inspect(bytes, Some(wrong)).is_err());
    }
}

#[test]
fn real_journals_and_sealed_segments_inspect_without_history_conversion() {
    let binding = Digest32::of_bytes(b"fixture-store");
    for (journal, segment, profile) in [
        (
            INTEGRATION_JOURNAL,
            INTEGRATION_SEGMENT,
            LegacyLedgerProfileV1::IntegrationPreparation,
        ),
        (
            OPERATOR_JOURNAL,
            OPERATOR_SEGMENT,
            LegacyLedgerProfileV1::OperatorPublication,
        ),
    ] {
        let j = inspect_legacy_container_v1(journal, Some(profile), binding).expect("journal");
        let s = inspect_legacy_container_v1(segment, Some(profile), binding).expect("segment");
        assert_eq!(j.last, s.last);
        assert_eq!(j.records, 1);
        assert_eq!(s.records, 1);
        assert!(!j.sealed);
        assert!(s.sealed);
        let unsealed =
            inspect_legacy_container_v1(&segment[..segment.len() - 80], Some(profile), binding)
                .expect("complete unsealed frames");
        assert!(!unsealed.sealed);
        assert_eq!(unsealed.last, s.last);
        assert!(
            inspect_legacy_container_v1(&segment[..segment.len() - 1], Some(profile), binding)
                .is_err()
        );
        assert_eq!(s.segment_index, Some(0));
        assert_eq!(j.original_bytes_digest, Digest32::of_bytes(journal));
        assert_eq!(s.original_bytes_digest, Digest32::of_bytes(segment));
        assert_eq!(
            inspect_legacy_container_v1(journal, None, binding),
            Err(LegacyInspectionError::ProfileRequired)
        );
        assert_eq!(
            inspect_legacy_container_v1(journal, Some(profile), Digest32::ZERO),
            Err(LegacyInspectionError::Binding)
        );
    }
}

#[test]
fn no_tail_repair_or_checksum_only_acceptance_in_read_only_inspection() {
    let profile = Some(LegacyLedgerProfileV1::OperatorPublication);
    let binding = Digest32::of_bytes(b"fixture-store");
    for end in 0..OPERATOR_JOURNAL.len() {
        // A complete empty journal is a separate structurally valid prefix,
        // never a witnessed recovery result; all partial headers/frames reject.
        if end == 72 {
            continue;
        }
        assert!(
            inspect_legacy_container_v1(&OPERATOR_JOURNAL[..end], profile, binding).is_err(),
            "cut {end}"
        );
    }
    let mut tampered = OPERATOR_JOURNAL.to_vec();
    tampered[72 + 16] ^= 1;
    let footer = tampered.len() - 32;
    let checksum = Digest32::of_bytes(&tampered[72..footer]);
    tampered[footer..].copy_from_slice(checksum.as_array());
    assert_eq!(
        inspect_legacy_container_v1(&tampered, profile, binding),
        Err(LegacyInspectionError::Sequence)
    );
    let mut extra = OPERATOR_SEGMENT.to_vec();
    extra.push(0);
    assert!(inspect_legacy_container_v1(&extra, profile, binding).is_err());
}

#[test]
fn legacy_event_bounds_unknown_tags_and_trailing_bytes_reject() {
    let profile = Some(LegacyLedgerProfileV1::OperatorPublication);
    let mut trailing = OPERATOR_EVENT.to_vec();
    trailing.push(0);
    assert!(InspectedLegacyEventV1::inspect(&trailing, profile).is_err());
    let mut unknown = OPERATOR_EVENT.to_vec();
    unknown[LEGACY_EVENT_DOMAIN.len()] = 255;
    assert_eq!(
        InspectedLegacyEventV1::inspect(&unknown, profile),
        Err(LegacyInspectionError::ProfileMismatch)
    );
    assert_eq!(
        InspectedLegacyEventV1::inspect(&vec![0; MAX_EVENT + 1], profile),
        Err(LegacyInspectionError::Size)
    );
}
