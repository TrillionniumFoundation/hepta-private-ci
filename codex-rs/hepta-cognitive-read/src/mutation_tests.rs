use std::collections::BTreeSet;

use super::*;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn snapshot(record: MemoryRecord) -> CognitiveSnapshot {
    build_snapshot(Generation::new(1).expect("generation"), vec![record]).expect("snapshot")
}

fn read_one(snapshot: &CognitiveSnapshot) -> ReadIdsResultV1 {
    read_ids_v1(
        snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:mutation")],
            fields: vec![
                ReadFieldV1::ContentDigest,
                ReadFieldV1::PredecessorDigest,
                ReadFieldV1::Citations,
            ],
            maximum_encoded_bytes: 4096,
        },
    )
    .expect("projection")
}

fn base_record() -> MemoryRecord {
    MemoryRecord {
        record_id: id("memory:mutation"),
        revision: Revision::new(1).expect("revision"),
        kind: MemoryKind::Fact,
        content_digest: Digest32::of_bytes(b"content:base"),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

#[test]
fn every_payload_byte_is_covered_by_the_receipt_digest() {
    let result = read_one(&snapshot(base_record()));
    let payload = &result.canonical_bytes()[..result.payload_encoded_bytes()];
    for index in 0..payload.len() {
        let mut mutated = payload.to_vec();
        mutated[index] ^= 0x01;
        assert_ne!(
            Digest32::of_bytes(&mutated),
            result.receipt_digest(),
            "payload byte {index} was not bound"
        );
    }
}

#[test]
fn semantic_record_mutations_change_the_canonical_receipt() {
    let mut variants = Vec::new();
    variants.push(base_record());

    let mut content = base_record();
    content.content_digest = Digest32::of_bytes(b"content:changed");
    variants.push(content);

    let mut kind = base_record();
    kind.kind = MemoryKind::Procedure;
    variants.push(kind);

    let mut state = base_record();
    state.state = RecordState::Tombstone;
    variants.push(state);

    let mut citation = base_record();
    citation.citations = vec![Citation {
        source_id: id("source:mutation"),
        source_digest: Digest32::of_bytes(b"source:mutation"),
    }];
    variants.push(citation);

    let mut receipts = BTreeSet::new();
    for variant in variants {
        let result = read_one(&snapshot(variant));
        assert!(
            receipts.insert(result.receipt_digest()),
            "semantic mutation reused an existing receipt"
        );
    }
}

#[test]
fn request_binding_mutations_change_the_binding_and_receipt() {
    let snapshot = snapshot(base_record());
    let requests = [
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:mutation")],
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: 4096,
        },
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:mutation"), id("memory:missing")],
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: 4096,
        },
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:mutation")],
            fields: vec![ReadFieldV1::Citations],
            maximum_encoded_bytes: 4096,
        },
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:mutation")],
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: 4095,
        },
    ];

    let mut bindings = BTreeSet::new();
    let mut receipts = BTreeSet::new();
    for request in requests {
        let result = read_ids_v1(&snapshot, request).expect("bounded request");
        assert!(bindings.insert(result.request_binding_digest()));
        assert!(receipts.insert(result.receipt_digest()));
    }
}
