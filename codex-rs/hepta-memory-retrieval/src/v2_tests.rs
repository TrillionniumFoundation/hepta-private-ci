use super::*;
use crate::RetrievalCandidate;
use crate::retrieve;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identifier is valid")
}

fn candidate(name: &str, score: i64) -> RetrievalCandidate {
    RetrievalCandidate {
        record: MemoryRecord {
            record_id: id(name),
            revision: Revision::new(/*value*/ 1).expect("fixture revision is valid"),
            kind: MemoryKind::Fact,
            content_digest: Digest32::of_bytes(name.as_bytes()),
            predecessor_digest: None,
            citations: Vec::new(),
            state: RecordState::Live,
        },
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        lexical_score: FixedQ32::from_raw(score),
        graph_score: FixedQ32::ZERO,
        freshness_score: FixedQ32::ZERO,
    }
}

fn request() -> RetrievalRequest {
    RetrievalRequest {
        query_id: id("query:1"),
        query_digest: Digest32::of_bytes(b"query"),
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        maximum_results: 1,
        candidates: vec![
            candidate("memory:a", /*score*/ 20),
            candidate("memory:b", /*score*/ 10),
        ],
    }
}

#[test]
fn v2_preserves_the_v1_result_and_digest_bytes() {
    let request = request();
    let expected_input = request.binding_digest_v2().expect("valid input binding");
    let legacy = retrieve(request.clone()).expect("legacy retrieval succeeds");
    let bound = retrieve_v2(request).expect("V2 retrieval succeeds");

    assert_eq!(
        legacy.receipt_digest.to_string(),
        "50fe1ac087140ddec3ab9061bedc174f910c018fd91e288c442510ffb4b9df50"
    );
    // Independently framed with Python struct.pack and hashlib.sha256.
    assert_eq!(
        bound.request_binding_digest.to_string(),
        "86fb616715321f03729825d7c4b7cc1509a818ce21b047a1814584e043d5c313"
    );
    assert_eq!(
        bound.receipt_digest.to_string(),
        "1ec7251c126e56b9fc989f9e605ab77d42e0d4e81cd08fb409810bb8f087659a"
    );
    assert_eq!(bound.retrieval, legacy);
    assert_eq!(bound.request_binding_digest, expected_input);
    assert_eq!(bound.authority, AuthorityPosture::DENY_ALL);
    assert_ne!(bound.receipt_digest, bound.retrieval.receipt_digest);
}

#[test]
fn identical_top_k_with_different_omission_counts_has_distinct_v2_receipts() {
    let full = retrieve_v2(request()).expect("full retrieval succeeds");
    let mut shorter_request = request();
    shorter_request.candidates.pop();
    let shorter = retrieve_v2(shorter_request).expect("short retrieval succeeds");

    assert_eq!(full.retrieval.results, shorter.retrieval.results);
    assert_eq!(
        full.retrieval.receipt_digest,
        shorter.retrieval.receipt_digest
    );
    assert_ne!(
        full.retrieval.omitted_count,
        shorter.retrieval.omitted_count
    );
    assert_ne!(full.request_binding_digest, shorter.request_binding_digest);
    assert_ne!(full.receipt_digest, shorter.receipt_digest);
}

#[test]
fn omitted_candidate_identity_content_and_every_score_are_bound() {
    let baseline_request = request();
    let baseline = retrieve_v2(baseline_request.clone()).expect("baseline succeeds");
    let mut variants = vec![baseline_request; 5];
    variants[0].candidates[1].record.record_id = id("memory:other");
    variants[1].candidates[1].record.content_digest = Digest32::of_bytes(b"changed");
    variants[2].candidates[1].lexical_score = FixedQ32::from_raw(/*raw*/ 11);
    variants[3].candidates[1].graph_score = FixedQ32::from_raw(/*raw*/ 1);
    variants[4].candidates[1].freshness_score = FixedQ32::from_raw(/*raw*/ 1);
    for variant in variants {
        let receipt = retrieve_v2(variant).expect("variant succeeds");
        assert_eq!(baseline.retrieval, receipt.retrieval);
        assert_ne!(
            baseline.request_binding_digest,
            receipt.request_binding_digest
        );
        assert_ne!(baseline.receipt_digest, receipt.receipt_digest);
    }
}

#[test]
fn query_snapshot_and_result_limit_are_in_the_expected_input_binding() {
    let mut baseline_request = request();
    baseline_request.candidates.pop();
    let baseline = retrieve_v2(baseline_request.clone()).expect("baseline succeeds");
    let mut variants = vec![baseline_request; 4];
    variants[0].query_id = id("query:other");
    variants[1].query_digest = Digest32::of_bytes(b"other query");
    variants[2].snapshot_digest = Digest32::of_bytes(b"other snapshot");
    variants[2].candidates[0].snapshot_digest = variants[2].snapshot_digest;
    variants[3].maximum_results = 2;
    for variant in variants {
        let expected = variant.binding_digest_v2().expect("valid variant input");
        let receipt = retrieve_v2(variant).expect("variant succeeds");
        assert_eq!(baseline.retrieval.results, receipt.retrieval.results);
        assert_eq!(receipt.request_binding_digest, expected);
        assert_ne!(baseline.request_binding_digest, expected);
        assert_ne!(baseline.receipt_digest, receipt.receipt_digest);
    }
}

#[test]
fn candidate_and_citation_permutations_have_one_binding() {
    let mut first_request = request();
    first_request.candidates[1].record.citations = vec![
        Citation {
            source_id: id("source:a"),
            source_digest: Digest32::of_bytes(b"source a"),
        },
        Citation {
            source_id: id("source:b"),
            source_digest: Digest32::of_bytes(b"source b"),
        },
    ];
    let first = retrieve_v2(first_request.clone()).expect("first succeeds");
    first_request.candidates[1].record.citations.reverse();
    first_request.candidates.reverse();
    let second = retrieve_v2(first_request).expect("permutation succeeds");
    assert_eq!(first, second);
}

#[test]
fn v2_and_expected_input_binding_preserve_validation_failures() {
    let mut duplicate = request();
    duplicate.candidates[1] = duplicate.candidates[0].clone();
    let mut deleted = request();
    deleted.candidates[1].record.state = RecordState::Tombstone;
    let mut stale = request();
    stale.candidates[1].snapshot_digest = Digest32::of_bytes(b"stale");
    for request in [duplicate, deleted, stale] {
        let legacy_error = retrieve(request.clone()).expect_err("V1 rejects invalid input");
        assert_eq!(request.binding_digest_v2(), Err(legacy_error.clone()));
        assert_eq!(retrieve_v2(request), Err(legacy_error));
    }
}
