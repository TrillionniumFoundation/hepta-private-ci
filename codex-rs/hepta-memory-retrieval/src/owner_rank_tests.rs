use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn candidate(name: &str, score: u64) -> OwnerRankCandidateV1 {
    OwnerRankCandidateV1 {
        record: MemoryRecord {
            record_id: id(name),
            revision: Revision::new(1).expect("revision"),
            kind: MemoryKind::Fact,
            content_digest: digest(&format!("content:{name}")),
            predecessor_digest: None,
            citations: Vec::new(),
            state: RecordState::Live,
        },
        snapshot_digest: digest("snapshot"),
        owner_score: score,
        support_digest: digest(&format!("support:{name}")),
    }
}

fn request() -> OwnerRankRequestV1 {
    OwnerRankRequestV1 {
        query_id: id("query:owner-rank"),
        query_digest: digest("query"),
        snapshot_digest: digest("snapshot"),
        maximum_results: 1,
        candidates: vec![candidate("memory:b", 20), candidate("memory:a", 20)],
    }
}

#[test]
fn owner_rank_is_deterministic_and_binds_complete_input() {
    let baseline = rank_owner_candidates(request()).expect("rank");
    assert_eq!(baseline.results[0].record_id, id("memory:a"));
    assert_eq!(baseline.omitted_count, 1);
    assert_eq!(baseline.authority, AuthorityPosture::DENY_ALL);

    let mut reversed = request();
    reversed.candidates.reverse();
    assert_eq!(
        baseline,
        rank_owner_candidates(reversed).expect("permutation")
    );

    let mut changed_tail = request();
    changed_tail.candidates[0].owner_score = 21;
    let changed = rank_owner_candidates(changed_tail).expect("changed");
    assert_ne!(
        baseline.request_binding_digest,
        changed.request_binding_digest
    );
    assert_ne!(baseline.receipt_digest, changed.receipt_digest);
}

#[test]
fn owner_rank_binds_support_and_rejects_tombstones() {
    let baseline = rank_owner_candidates(request()).expect("rank");
    let mut changed = request();
    changed.candidates[1].support_digest = digest("changed-support");
    let changed = rank_owner_candidates(changed).expect("changed support");
    assert_ne!(
        baseline.request_binding_digest,
        changed.request_binding_digest
    );

    let mut stale = request();
    stale.candidates[0].snapshot_digest = digest("stale-snapshot");
    assert_eq!(
        rank_owner_candidates(stale),
        Err(OwnerRankErrorV1::SnapshotMismatch("memory:b".to_string()))
    );

    let mut deleted = request();
    deleted.candidates[0].record.state = RecordState::Tombstone;
    assert_eq!(
        rank_owner_candidates(deleted),
        Err(OwnerRankErrorV1::TombstoneRecord("memory:b".to_string()))
    );
}

#[test]
fn owner_rank_enforces_product_capacity() {
    assert_eq!(MAX_OWNER_RANK_CANDIDATES, 512);
    assert_eq!(MAX_OWNER_RANK_RESULTS, 16);
    let mut oversized = request();
    oversized.maximum_results = 17;
    assert_eq!(
        rank_owner_candidates(oversized),
        Err(OwnerRankErrorV1::InvalidMaximumResults)
    );
}
