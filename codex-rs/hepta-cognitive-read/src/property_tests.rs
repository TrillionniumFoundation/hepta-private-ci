use super::*;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn record(name: &str, kind: MemoryKind) -> MemoryRecord {
    MemoryRecord {
        record_id: id(name),
        revision: Revision::new(1).expect("revision"),
        kind,
        content_digest: Digest32::of_bytes(name.as_bytes()),
        predecessor_digest: None,
        citations: vec![Citation {
            source_id: id(&format!("source:{name}")),
            source_digest: Digest32::of_bytes(format!("source:{name}").as_bytes()),
        }],
        state: RecordState::Live,
    }
}

fn snapshot(records: Vec<MemoryRecord>) -> CognitiveSnapshot {
    build_snapshot(Generation::new(7).expect("generation"), records).expect("snapshot")
}

fn permutations<T: Clone>(values: &[T]) -> Vec<Vec<T>> {
    fn visit<T: Clone>(remaining: Vec<T>, prefix: Vec<T>, out: &mut Vec<Vec<T>>) {
        if remaining.is_empty() {
            out.push(prefix);
            return;
        }
        for index in 0..remaining.len() {
            let mut next_remaining = remaining.clone();
            let item = next_remaining.remove(index);
            let mut next_prefix = prefix.clone();
            next_prefix.push(item);
            visit(next_remaining, next_prefix, out);
        }
    }

    let mut out = Vec::new();
    visit(values.to_vec(), Vec::new(), &mut out);
    out
}

#[test]
fn exact_id_result_is_invariant_under_snapshot_request_and_field_permutations() {
    let records = vec![
        record("memory:a", MemoryKind::Fact),
        record("memory:b", MemoryKind::Episode),
        record("memory:c", MemoryKind::Procedure),
    ];
    let ids = vec![
        id("memory:c"),
        id("memory:missing"),
        id("memory:a"),
        id("memory:b"),
    ];
    let fields = vec![
        ReadFieldV1::Citations,
        ReadFieldV1::ContentDigest,
        ReadFieldV1::PredecessorDigest,
    ];

    let baseline_snapshot = snapshot(records.clone());
    let baseline = read_ids_v1(
        &baseline_snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: baseline_snapshot.snapshot_digest,
            record_ids: ids.clone(),
            fields: fields.clone(),
            maximum_encoded_bytes: 8192,
        },
    )
    .expect("baseline");

    for records in permutations(&records) {
        let candidate_snapshot = snapshot(records);
        assert_eq!(
            candidate_snapshot.snapshot_digest,
            baseline_snapshot.snapshot_digest
        );
        for candidate_ids in permutations(&ids) {
            for candidate_fields in permutations(&fields) {
                let result = read_ids_v1(
                    &candidate_snapshot,
                    ReadIdsRequestV1 {
                        snapshot_digest: candidate_snapshot.snapshot_digest,
                        record_ids: candidate_ids,
                        fields: candidate_fields,
                        maximum_encoded_bytes: 8192,
                    },
                )
                .expect("permutation");
                assert_eq!(result.canonical_bytes(), baseline.canonical_bytes());
                assert_eq!(result.receipt_digest(), baseline.receipt_digest());
                assert_eq!(
                    result.request_binding_digest(),
                    baseline.request_binding_digest()
                );
            }
        }
    }
}

#[test]
fn transient_projection_is_explicitly_authority_free() {
    let snapshot = snapshot(vec![record("memory:transient", MemoryKind::Preference)]);
    let projection =
        TransientSnapshotProjectionV1::try_new(&snapshot).expect("valid transient snapshot");
    let result = projection
        .read_ids(ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:transient")],
            fields: vec![ReadFieldV1::ContentDigest],
            maximum_encoded_bytes: 4096,
        })
        .expect("transient projection");
    assert_eq!(projection.snapshot(), &snapshot);
    assert_eq!(result.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(result.result().authority(), AuthorityPosture::DENY_ALL);
    assert!(!result.result().authority().grants_any());
}
