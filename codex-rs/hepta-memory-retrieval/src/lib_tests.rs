use super::*;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn revision() -> Revision {
    let Ok(value) = Revision::new(1) else {
        panic!("test revision must be valid");
    };
    value
}

fn candidate(name: &str, snapshot: Digest32, score: i64) -> RetrievalCandidate {
    RetrievalCandidate {
        record: MemoryRecord {
            record_id: id(name),
            revision: revision(),
            kind: MemoryKind::Fact,
            content_digest: Digest32::of_bytes(name.as_bytes()),
            predecessor_digest: None,
            citations: Vec::new(),
            state: RecordState::Live,
        },
        snapshot_digest: snapshot,
        lexical_score: FixedQ32::from_raw(score),
        graph_score: FixedQ32::ZERO,
        freshness_score: FixedQ32::ZERO,
    }
}

#[test]
fn ranking_is_deterministic_and_explainable() {
    let snapshot = Digest32::of_bytes(b"snapshot");
    let request = RetrievalRequest {
        query_id: id("query:1"),
        query_digest: Digest32::of_bytes(b"query"),
        snapshot_digest: snapshot,
        maximum_results: 2,
        candidates: vec![
            candidate("memory:b", snapshot, 10),
            candidate("memory:a", snapshot, 10),
        ],
    };
    let Ok(receipt) = retrieve(request) else {
        panic!("retrieval must succeed");
    };
    assert_eq!(receipt.results[0].record_id, id("memory:a"));
    assert_eq!(receipt.results[0].lexical_score, FixedQ32::from_raw(10));
    assert!(!receipt.authority.grants_any());
}

#[test]
fn stale_candidate_snapshot_is_rejected() {
    let snapshot = Digest32::of_bytes(b"snapshot");
    let request = RetrievalRequest {
        query_id: id("query:1"),
        query_digest: Digest32::of_bytes(b"query"),
        snapshot_digest: snapshot,
        maximum_results: 1,
        candidates: vec![candidate("memory:a", Digest32::of_bytes(b"stale"), 10)],
    };
    assert_eq!(
        retrieve(request),
        Err(Error::SnapshotMismatch("memory:a".to_string()))
    );
}

#[test]
fn result_count_is_bounded() {
    let snapshot = Digest32::of_bytes(b"snapshot");
    let request = RetrievalRequest {
        query_id: id("query:1"),
        query_digest: Digest32::of_bytes(b"query"),
        snapshot_digest: snapshot,
        maximum_results: 1,
        candidates: vec![
            candidate("memory:a", snapshot, 20),
            candidate("memory:b", snapshot, 10),
        ],
    };
    let Ok(receipt) = retrieve(request) else {
        panic!("retrieval must succeed");
    };
    assert_eq!(receipt.results.len(), 1);
    assert_eq!(receipt.omitted_count, 1);
}

#[test]
fn tombstone_candidates_are_rejected_before_result_truncation() {
    let snapshot = Digest32::of_bytes(b"snapshot");
    let mut tombstone = candidate("memory:deleted", snapshot, /*score*/ 10);
    tombstone.record.state = RecordState::Tombstone;
    let live = candidate("memory:live", snapshot, /*score*/ 20);

    // A low-ranked deletion must still invalidate the input when it would
    // fall outside the requested top-k. No partial receipt may hide it.
    for candidates in [
        vec![tombstone.clone()],
        vec![tombstone.clone(), live.clone()],
        vec![live, tombstone],
    ] {
        let request = RetrievalRequest {
            query_id: id("query:1"),
            query_digest: Digest32::of_bytes(b"query"),
            snapshot_digest: snapshot,
            maximum_results: 1,
            candidates,
        };
        assert_eq!(
            retrieve(request),
            Err(Error::TombstoneRecord("memory:deleted".to_string()))
        );
    }
}
