use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:product-retrieval"),
        purpose_id: id("purpose:product-recall"),
        memory_ledger_frontier: 3,
        knowledge_fact_frontier: 2,
        tombstone_frontier: 1,
        source_ledger_frontier: 4,
        knowledge_graph_generation: generation(2),
        compact_checkpoint_generation: generation(1),
        prompt_registry_revision: revision(1),
        retrieval_profile_digest: digest("retrieval-profile"),
        encoder_preprocessor_digest: digest("encoder-profile"),
        authority_epoch: 1,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .unwrap_or_else(|error| panic!("valid snapshot key: {error}"))
}

fn record(number: usize) -> MemoryRecord {
    MemoryRecord {
        record_id: id(&format!("memory:{number}")),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("content:{number}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn candidate(number: usize, score: i64) -> RetrievalCandidate {
    RetrievalCandidate {
        record: record(number),
        snapshot_digest: digest("snapshot"),
        lexical_score: FixedQ32::from_raw(score),
        graph_score: FixedQ32::ZERO,
        freshness_score: FixedQ32::ZERO,
    }
}

fn request() -> ProductRetrievalRequestV1 {
    ProductRetrievalRequestV1 {
        query_id: id("query:product"),
        query_digest: digest("query"),
        snapshot_digest: digest("snapshot"),
        owner_observation_digest: digest("owner-observation"),
        maximum_results: 2,
        candidates: vec![candidate(2, 10), candidate(1, 20), candidate(3, 5)],
    }
}

fn relation(
    candidate_number: usize,
    support_number: usize,
    kind: ProductRelationKindV1,
) -> ProductRelationEvidenceV1 {
    ProductRelationEvidenceV1 {
        candidate_record_id: id(&format!("memory:{candidate_number}")),
        candidate_revision: revision(1),
        support_record_id: id(&format!("memory:{support_number}")),
        support_revision: revision(1),
        relation: kind,
        support_digest: digest(&format!("support:{candidate_number}:{support_number}:{kind:?}")),
        relation_group_digest: digest(&format!("group:{support_number}:{kind:?}")),
    }
}

#[test]
fn compile_cue_validates_the_generation_bound_input() {
    let cue = compile_cue(CueCompileRequestV1 {
        cue_id: id("cue:product"),
        objective_digest: digest("objective"),
        approved_context_digest: digest("context"),
        snapshot_key: snapshot_key(),
        cue_profile_digest: digest("cue-profile"),
    })
    .unwrap_or_else(|error| panic!("valid cue: {error}"));
    assert_eq!(cue.cue_id, id("cue:product"));
    assert!(!cue.digest().is_zero());
}

#[test]
fn product_receipt_binds_owner_observation_and_complete_candidate_set() {
    let baseline = retrieve_product_v1(request()).expect("product retrieval succeeds");
    assert_eq!(baseline.retrieval.retrieval.results.len(), 2);
    assert_eq!(
        baseline.retrieval.retrieval.results[0].record_id,
        id("memory:1")
    );
    assert_eq!(baseline.retrieval.retrieval.omitted_count, 1);
    assert_eq!(baseline.authority, AuthorityPosture::DENY_ALL);

    let mut changed_owner = request();
    changed_owner.owner_observation_digest = digest("other-owner-observation");
    let changed_owner =
        retrieve_product_v1(changed_owner).expect("changed owner observation still ranks");
    assert_eq!(
        baseline.retrieval.retrieval,
        changed_owner.retrieval.retrieval
    );
    assert_ne!(baseline.receipt_digest, changed_owner.receipt_digest);

    let mut changed_omitted = request();
    changed_omitted.candidates[2].lexical_score = FixedQ32::from_raw(6);
    let changed_omitted =
        retrieve_product_v1(changed_omitted).expect("changed omitted candidate still ranks");
    assert_eq!(
        baseline.retrieval.retrieval.results,
        changed_omitted.retrieval.retrieval.results
    );
    assert_ne!(
        baseline.retrieval.request_binding_digest,
        changed_omitted.retrieval.request_binding_digest
    );
    assert_ne!(baseline.receipt_digest, changed_omitted.receipt_digest);
}

#[test]
fn product_v2_binds_typed_relation_evidence_without_changing_rrf_order() {
    let evidence = vec![
        relation(1, 2, ProductRelationKindV1::Causes),
        relation(3, 2, ProductRelationKindV1::Contradicts),
    ];
    let baseline = retrieve_product_v2(ProductRetrievalRequestV2 {
        retrieval: request(),
        owner_relation_evidence_count: 3,
        owner_relation_limit_reached: false,
        relation_evidence: evidence.clone(),
    })
    .expect("product v2 succeeds");
    assert_eq!(
        baseline.retrieval.retrieval.retrieval.results[0].record_id,
        id("memory:1")
    );
    assert_eq!(baseline.relation_evidence, evidence);
    assert_eq!(baseline.owner_relation_evidence_count, 3);
    assert_eq!(baseline.omitted_relation_evidence_count, 1);
    assert!(!baseline.owner_relation_limit_reached);
    assert_eq!(
        baseline.relation_evidence[0].retrieval_channel(),
        RetrievalChannelV1::Causal
    );
    assert_eq!(
        baseline.relation_evidence[1].retrieval_channel(),
        RetrievalChannelV1::ContradictionSupport
    );
    assert_eq!(
        baseline.relation_evidence[1].contradiction_group_digest(),
        Some(evidence[1].relation_group_digest)
    );
    assert_eq!(baseline.authority, AuthorityPosture::DENY_ALL);

    let changed = retrieve_product_v2(ProductRetrievalRequestV2 {
        retrieval: request(),
        owner_relation_evidence_count: 3,
        owner_relation_limit_reached: false,
        relation_evidence: vec![
            relation(1, 2, ProductRelationKindV1::TemporalBefore),
            evidence[1].clone(),
        ],
    })
    .expect("changed semantics still form a receipt");
    assert_eq!(
        baseline.retrieval.retrieval.retrieval.results,
        changed.retrieval.retrieval.retrieval.results
    );
    assert_ne!(baseline.receipt_digest, changed.receipt_digest);

    let changed_coverage = retrieve_product_v2(ProductRetrievalRequestV2 {
        retrieval: request(),
        owner_relation_evidence_count: 2,
        owner_relation_limit_reached: true,
        relation_evidence: evidence,
    })
    .expect("coverage change is explicit");
    assert_ne!(baseline.receipt_digest, changed_coverage.receipt_digest);
    assert!(changed_coverage.owner_relation_limit_reached);
    assert_eq!(changed_coverage.omitted_relation_evidence_count, 0);
}

#[test]
fn product_v2_relation_evidence_cannot_widen_the_admitted_set() {
    let missing_candidate = retrieve_product_v2(ProductRetrievalRequestV2 {
        retrieval: request(),
        owner_relation_evidence_count: 1,
        owner_relation_limit_reached: false,
        relation_evidence: vec![relation(99, 2, ProductRelationKindV1::Causes)],
    });
    assert_eq!(
        missing_candidate,
        Err(ProductRetrievalError::RelationCandidateNotAdmitted(
            "memory:99".to_string()
        ))
    );

    let missing_support = retrieve_product_v2(ProductRetrievalRequestV2 {
        retrieval: request(),
        owner_relation_evidence_count: 1,
        owner_relation_limit_reached: false,
        relation_evidence: vec![relation(1, 99, ProductRelationKindV1::Causes)],
    });
    assert_eq!(
        missing_support,
        Err(ProductRetrievalError::RelationSupportNotAdmitted(
            "memory:99".to_string()
        ))
    );
}

#[test]
fn product_v2_relation_count_cannot_understate_included_evidence() {
    assert_eq!(
        retrieve_product_v2(ProductRetrievalRequestV2 {
            retrieval: request(),
            owner_relation_evidence_count: 0,
            owner_relation_limit_reached: false,
            relation_evidence: vec![relation(1, 2, ProductRelationKindV1::Causes)],
        }),
        Err(ProductRetrievalError::RelationEvidenceCountMismatch)
    );
}

#[test]
fn product_limits_are_stricter_than_legacy_compatibility_limits() {
    let mut too_many_results = request();
    too_many_results.maximum_results = MAX_PRODUCT_RETRIEVAL_RESULTS + 1;
    assert_eq!(
        retrieve_product_v1(too_many_results),
        Err(ProductRetrievalError::InvalidMaximumResults)
    );

    let too_many_candidates = ProductRetrievalRequestV1 {
        candidates: (0..=MAX_PRODUCT_RETRIEVAL_CANDIDATES)
            .map(|index| candidate(index, i64::try_from(index).unwrap_or(i64::MAX)))
            .collect(),
        ..request()
    };
    assert_eq!(
        retrieve_product_v1(too_many_candidates),
        Err(ProductRetrievalError::CandidateLimitExceeded)
    );
}

#[test]
fn owner_observation_is_required() {
    let mut missing = request();
    missing.owner_observation_digest = Digest32::ZERO;
    assert_eq!(
        retrieve_product_v1(missing),
        Err(ProductRetrievalError::EmptyOwnerObservationDigest)
    );
}

#[test]
fn generation_bound_probability_type_remains_available_for_product_callers() {
    // Keep this compile-time regression close to the product surface: callers
    // can compose the stricter owner-bound retrieval with generation-bound
    // recall without introducing a second probability representation.
    assert_eq!(ProbabilityQ32::ZERO.raw(), 0);
}
