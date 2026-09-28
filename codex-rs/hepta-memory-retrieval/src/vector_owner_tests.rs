use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn probability(raw: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(raw).expect("valid probability")
}

fn generation() -> Digest32 {
    digest("vector-generation")
}

fn model() -> Digest32 {
    digest("vector-model")
}

fn encoder() -> Digest32 {
    digest("vector-encoder-preprocessor")
}

fn record(number: u64) -> MemoryRecord {
    MemoryRecord {
        record_id: id(&format!("memory:{number}")),
        revision: Revision::new(1).expect("revision"),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("content:{number}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn components(first: i64, second: i64) -> Vec<FixedQ32> {
    vec![FixedQ32::from_raw(first), FixedQ32::from_raw(second)]
}

fn embedding(subject: Digest32, values: Vec<FixedQ32>) -> VectorEmbeddingV1 {
    VectorEmbeddingV1::new(subject, generation(), model(), encoder(), values).expect("embedding")
}

fn row(number: u64, values: Vec<FixedQ32>, ood: ProbabilityQ32) -> VectorIndexRecordV1 {
    let record = record(number);
    VectorIndexRecordV1 {
        embedding: embedding(record.content_digest, values),
        record,
        ood,
    }
}

fn snapshot(rows: Vec<VectorIndexRecordV1>) -> VectorIndexSnapshotV1 {
    VectorIndexSnapshotV1::new(
        generation(),
        digest("vector-owner-generation"),
        model(),
        encoder(),
        2,
        rows,
    )
    .expect("snapshot")
}

fn query(values: Vec<FixedQ32>, maximum_candidates: u32) -> VectorQueryV1 {
    let query_digest = digest("query");
    VectorQueryV1 {
        query_digest,
        embedding: embedding(query_digest, values),
        maximum_candidates,
        maximum_ood: ProbabilityQ32::ONE,
    }
}

#[test]
fn vector_owner_ranks_exact_embeddings_and_emits_encoder_batch() {
    let owner = GenerationBoundVectorOwnerV1::new(snapshot(vec![
        row(2, components(0, 0), ProbabilityQ32::ZERO),
        row(
            1,
            components(FixedQ32::ONE.raw(), FixedQ32::ONE.raw()),
            ProbabilityQ32::ZERO,
        ),
    ]))
    .expect("owner");
    let batch = owner
        .generate(&query(
            components(FixedQ32::ONE.raw(), FixedQ32::ONE.raw()),
            2,
        ))
        .expect("batch");
    assert_eq!(
        batch.receipt.generator,
        RetrievalGeneratorOwnerV1::EncoderVector
    );
    assert_eq!(batch.receipt.generation_vector_digest, generation());
    assert_eq!(batch.receipt.candidate_count, 2);
    assert_eq!(
        batch.receipt.completeness,
        RetrievalSourceCompletenessV1::Exhausted
    );
    assert_eq!(batch.candidates[0].record.record_id, id("memory:1"));
    assert_eq!(batch.candidates[0].normalized_score, FixedQ32::ONE);
    assert_eq!(batch.candidates[0].channel, RetrievalChannelV1::Vector);
    assert_ne!(batch.candidates[0].support_digest, Digest32::ZERO);
}

#[test]
fn equal_scores_have_stable_identity_order_and_input_order_is_irrelevant() {
    let left = snapshot(vec![
        row(2, components(0, 0), ProbabilityQ32::ZERO),
        row(1, components(0, 0), ProbabilityQ32::ZERO),
    ]);
    let right = snapshot(vec![
        row(1, components(0, 0), ProbabilityQ32::ZERO),
        row(2, components(0, 0), ProbabilityQ32::ZERO),
    ]);
    assert_eq!(left, right);
    let query = query(components(0, 0), 2);
    let left = generate_vector_batch_v1(&left, &query).expect("left");
    let right = generate_vector_batch_v1(&right, &query).expect("right");
    assert_eq!(left, right);
    assert_eq!(left.candidates[0].record.record_id, id("memory:1"));
    assert_eq!(left.candidates[1].record.record_id, id("memory:2"));
}

#[test]
fn candidate_bound_reports_limit_reached_without_hiding_count() {
    let snapshot = snapshot(vec![
        row(1, components(0, 0), ProbabilityQ32::ZERO),
        row(2, components(0, 0), ProbabilityQ32::ZERO),
        row(3, components(0, 0), ProbabilityQ32::ZERO),
    ]);
    let batch =
        generate_vector_batch_v1(&snapshot, &query(components(0, 0), 2)).expect("bounded batch");
    assert_eq!(batch.candidates.len(), 2);
    assert_eq!(batch.receipt.candidate_count, 2);
    assert_eq!(
        batch.receipt.completeness,
        RetrievalSourceCompletenessV1::LimitReached
    );
    batch.validate().expect("valid count receipt");
}

#[test]
fn calibrated_ood_filter_applies_before_capacity_completeness() {
    let snapshot = snapshot(vec![
        row(1, components(0, 0), probability(1_u64 << 30)),
        row(2, components(0, 0), probability(3_u64 << 30)),
    ]);
    let mut query = query(components(0, 0), 2);
    query.maximum_ood = probability(1_u64 << 30);
    let batch = generate_vector_batch_v1(&snapshot, &query).expect("filtered batch");
    assert_eq!(batch.candidates.len(), 1);
    assert_eq!(batch.candidates[0].record.record_id, id("memory:1"));
    assert_eq!(
        batch.receipt.completeness,
        RetrievalSourceCompletenessV1::Exhausted
    );
}

#[test]
fn query_generation_model_and_encoder_must_match_index() {
    let snapshot = snapshot(vec![row(1, components(0, 0), ProbabilityQ32::ZERO)]);
    let base = query(components(0, 0), 1);

    let mut stale = base.clone();
    stale.embedding = VectorEmbeddingV1::new(
        stale.query_digest,
        digest("stale-generation"),
        model(),
        encoder(),
        components(0, 0),
    )
    .expect("stale embedding");
    assert_eq!(
        generate_vector_batch_v1(&snapshot, &stale),
        Err(VectorOwnerErrorV1::GenerationVectorMismatch)
    );

    let mut wrong_model = base.clone();
    wrong_model.embedding = VectorEmbeddingV1::new(
        wrong_model.query_digest,
        generation(),
        digest("other-model"),
        encoder(),
        components(0, 0),
    )
    .expect("model embedding");
    assert_eq!(
        generate_vector_batch_v1(&snapshot, &wrong_model),
        Err(VectorOwnerErrorV1::ModelMismatch)
    );

    let mut wrong_encoder = base;
    wrong_encoder.embedding = VectorEmbeddingV1::new(
        wrong_encoder.query_digest,
        generation(),
        model(),
        digest("other-encoder"),
        components(0, 0),
    )
    .expect("encoder embedding");
    assert_eq!(
        generate_vector_batch_v1(&snapshot, &wrong_encoder),
        Err(VectorOwnerErrorV1::EncoderPreprocessorMismatch)
    );
}

#[test]
fn embeddings_bind_exact_query_and_record_content() {
    let mut mismatched_query = query(components(0, 0), 1);
    mismatched_query.embedding = embedding(digest("other-query"), components(0, 0));
    assert_eq!(
        mismatched_query.validate(),
        Err(VectorOwnerErrorV1::QuerySubjectMismatch)
    );

    let record = record(1);
    let row = VectorIndexRecordV1 {
        embedding: embedding(digest("other-content"), components(0, 0)),
        record,
        ood: ProbabilityQ32::ZERO,
    };
    assert_eq!(
        VectorIndexSnapshotV1::new(
            generation(),
            digest("owner-generation"),
            model(),
            encoder(),
            2,
            vec![row],
        ),
        Err(VectorOwnerErrorV1::EmbeddingSubjectMismatch(
            "memory:1".to_string()
        ))
    );
}

#[test]
fn tombstones_duplicates_and_invalid_components_fail_closed() {
    let mut deleted = record(1);
    deleted.state = RecordState::Tombstone;
    let deleted = VectorIndexRecordV1 {
        embedding: embedding(deleted.content_digest, components(0, 0)),
        record: deleted,
        ood: ProbabilityQ32::ZERO,
    };
    assert_eq!(
        VectorIndexSnapshotV1::new(
            generation(),
            digest("owner-generation"),
            model(),
            encoder(),
            2,
            vec![deleted],
        ),
        Err(VectorOwnerErrorV1::TombstoneRecord("memory:1".to_string()))
    );

    let duplicate = row(2, components(0, 0), ProbabilityQ32::ZERO);
    assert_eq!(
        VectorIndexSnapshotV1::new(
            generation(),
            digest("owner-generation"),
            model(),
            encoder(),
            2,
            vec![duplicate.clone(), duplicate],
        ),
        Err(VectorOwnerErrorV1::DuplicateRecord("memory:2".to_string()))
    );

    assert_eq!(
        VectorEmbeddingV1::new(
            digest("subject"),
            generation(),
            model(),
            encoder(),
            vec![FixedQ32::from_raw(FixedQ32::ONE.raw() + 1)],
        ),
        Err(VectorOwnerErrorV1::ComponentOutOfRange)
    );
}

#[test]
fn rehashed_or_structurally_tampered_embeddings_and_indexes_are_rejected() {
    let mut embedding = embedding(digest("subject"), components(0, 0));
    embedding.components[0] = FixedQ32::ONE;
    assert_eq!(
        embedding.validate(),
        Err(VectorOwnerErrorV1::DigestMismatch("vector embedding"))
    );

    let mut snapshot = snapshot(vec![row(1, components(0, 0), ProbabilityQ32::ZERO)]);
    snapshot.records[0].ood = ProbabilityQ32::ONE;
    assert_eq!(
        snapshot.validate(),
        Err(VectorOwnerErrorV1::DigestMismatch("vector index"))
    );
}
