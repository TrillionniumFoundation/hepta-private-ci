use super::*;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn revision(value: u64) -> Revision {
    Revision::new(value).expect("valid revision")
}

fn record(name: &str, state: RecordState) -> MemoryRecord {
    MemoryRecord {
        record_id: id(name),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: Digest32::of_bytes(name.as_bytes()),
        predecessor_digest: None,
        citations: Vec::new(),
        state,
    }
}

fn snapshot(records: Vec<MemoryRecord>) -> CognitiveSnapshot {
    build_snapshot(Generation::new(1).expect("generation"), records).expect("snapshot")
}

#[test]
fn exact_id_read_reaches_beyond_the_legacy_1024_prefix() {
    let records = (0..1_500)
        .map(|index| record(&format!("memory:{index:04}"), RecordState::Live))
        .collect::<Vec<_>>();
    let snapshot = snapshot(records);
    let target = id("memory:1499");
    let result = read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![target.clone()],
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: 4096,
        },
    )
    .expect("exact id read");
    assert_eq!(result.records().len(), 1);
    assert_eq!(result.records()[0].record_id, target);
    assert_eq!(result.records()[0].state, RecordState::Live);
    assert_eq!(result.missing_ids(), &[]);
    assert!(!result.authority().grants_any());
}

#[test]
fn requested_fields_are_explicit_and_missing_ids_are_not_silent_omissions() {
    let snapshot = snapshot(vec![record("memory:a", RecordState::Live)]);
    let result = read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:a"), id("memory:missing")],
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: 4096,
        },
    )
    .expect("projection");
    assert_eq!(result.included_fields(), &[ReadFieldV1::ContentDigest]);
    assert!(result.records()[0].content_digest.is_some());
    assert!(result.records()[0].predecessor_digest.is_none());
    assert!(result.records()[0].citations.is_empty());
    assert_eq!(result.missing_ids(), &[id("memory:missing")]);
}

#[test]
fn tombstone_state_is_mandatory_even_when_optional_fields_are_empty() {
    let snapshot = snapshot(vec![record("memory:gone", RecordState::Tombstone)]);
    let result = read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:gone")],
            fields: Vec::new(),
            maximum_encoded_bytes: 4096,
        },
    )
    .expect("projection");
    assert_eq!(result.records()[0].state, RecordState::Tombstone);
    assert!(result.records()[0].content_digest.is_none());
}

#[test]
fn duplicate_and_oversized_requests_fail_closed() {
    let snapshot = snapshot(vec![record("memory:a", RecordState::Live)]);
    let duplicate = ReadIdsRequestV1 {
        snapshot_digest: snapshot.snapshot_digest,
        record_ids: vec![id("memory:a"), id("memory:a")],
        fields: Vec::new(),
        maximum_encoded_bytes: 4096,
    };
    assert_eq!(
        read_ids_v1(&snapshot, duplicate),
        Err(ReadIdsError::DuplicateRecordId)
    );

    let too_many = ReadIdsRequestV1 {
        snapshot_digest: snapshot.snapshot_digest,
        record_ids: (0..=MAX_READ_IDS_V1)
            .map(|index| id(&format!("memory:{index:04}")))
            .collect(),
        fields: Vec::new(),
        maximum_encoded_bytes: 4096,
    };
    assert!(matches!(
        read_ids_v1(&snapshot, too_many),
        Err(ReadIdsError::TooManyRecordIds { .. })
    ));
}

#[test]
fn maximum_exact_id_batch_resolves_from_the_full_snapshot() {
    let records = (0..16_384)
        .map(|index| record(&format!("memory:{index:05}"), RecordState::Live))
        .collect::<Vec<_>>();
    let snapshot = snapshot(records);
    let record_ids = (16_384 - MAX_READ_IDS_V1..16_384)
        .map(|index| id(&format!("memory:{index:05}")))
        .collect::<Vec<_>>();
    let result = read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: record_ids.clone(),
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
        },
    )
    .expect("maximum exact-id batch");
    assert_eq!(result.records().len(), MAX_READ_IDS_V1);
    assert!(result.missing_ids().is_empty());
    assert_eq!(result.records().first().unwrap().record_id, record_ids[0]);
    assert_eq!(
        result.records().last().unwrap().record_id,
        record_ids[MAX_READ_IDS_V1 - 1]
    );
}

#[test]
fn payload_and_total_wire_accounting_are_explicit() {
    let mut value = record("memory:accounting", RecordState::Live);
    value.citations = vec![Citation {
        source_id: id("source:one"),
        source_digest: Digest32::of_bytes(b"source:one"),
    }];
    let snapshot = snapshot(vec![value]);
    let result = read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:accounting"), id("memory:missing")],
            fields: vec![ReadFieldV1::ContentDigest, ReadFieldV1::Citations],
            maximum_encoded_bytes: 4096,
        },
    )
    .expect("bounded result");

    assert_eq!(
        result.payload_encoded_bytes() + 32,
        result.total_encoded_bytes()
    );
    assert_eq!(result.encoded_bytes(), result.total_encoded_bytes());
    assert_eq!(result.canonical_bytes().len(), result.total_encoded_bytes());
    assert_eq!(
        Digest32::of_bytes(&result.canonical_bytes()[..result.payload_encoded_bytes()]),
        result.receipt_digest()
    );
    assert_eq!(
        &result.canonical_bytes()[result.payload_encoded_bytes()..],
        result.receipt_digest().as_array()
    );
}

#[test]
fn exact_total_canonical_boundary_is_all_or_error() {
    let snapshot = snapshot(vec![record("memory:boundary", RecordState::Live)]);
    let request = ReadIdsRequestV1 {
        snapshot_digest: snapshot.snapshot_digest,
        record_ids: vec![id("memory:boundary")],
        fields: vec![ReadFieldV1::ContentDigest],
        maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
    };
    let probe = read_ids_v1(&snapshot, request.clone()).expect("probe");
    let exact = probe.total_encoded_bytes();

    let accepted = read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            maximum_encoded_bytes: exact,
            ..request.clone()
        },
    )
    .expect("exact total boundary");
    assert_eq!(accepted.total_encoded_bytes(), exact);

    assert_eq!(
        read_ids_v1(
            &snapshot,
            ReadIdsRequestV1 {
                maximum_encoded_bytes: exact - 1,
                ..request
            }
        ),
        Err(ReadIdsError::EncodedResultTooLarge {
            actual: exact,
            maximum: exact - 1,
        })
    );
}

#[test]
fn invalid_zero_and_over_module_budget_fail_before_projection() {
    let snapshot = snapshot(vec![record("memory:a", RecordState::Live)]);
    for requested in [0, MAX_ENCODED_READ_RESULT_BYTES_V2 + 1] {
        assert_eq!(
            read_ids_v1(
                &snapshot,
                ReadIdsRequestV1 {
                    snapshot_digest: snapshot.snapshot_digest,
                    record_ids: vec![id("memory:a")],
                    fields: Vec::new(),
                    maximum_encoded_bytes: requested,
                }
            ),
            Err(ReadIdsError::InvalidMaximumEncodedBytes {
                requested,
                maximum: MAX_ENCODED_READ_RESULT_BYTES_V2,
            })
        );
    }
}
