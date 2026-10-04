use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_memory_retrieval::VectorEmbeddingV1;
use codex_hepta_memory_retrieval::VectorIndexRecordV1;
use codex_hepta_memory_retrieval::VectorIndexSnapshotV1;
use codex_hepta_memory_retrieval::vector_publication::EncoderReleaseIdentityV1;
use codex_hepta_memory_retrieval::vector_publication::VectorIndexPublicationV1;
use codex_hepta_memory_retrieval::vector_publication::VectorPublicationErrorV1;
use codex_hepta_memory_retrieval::vector_publication::VectorPublicationStateV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn encoder() -> Result<
    EncoderReleaseIdentityV1,
    codex_hepta_memory_retrieval::vector_publication::VectorPublicationErrorV1,
> {
    EncoderReleaseIdentityV1::new(
        digest("model"),
        digest("weights"),
        digest("runtime"),
        digest("preprocessor"),
        2,
    )
}

fn snapshot(owner_generation: &str) -> Result<VectorIndexSnapshotV1, Box<dyn std::error::Error>> {
    let record = MemoryRecord {
        record_id: StableId::new("memory:sequence-boundary")?,
        revision: Revision::new(1)?,
        kind: MemoryKind::Fact,
        content_digest: digest("content"),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    };
    let embedding = VectorEmbeddingV1::new(
        record.content_digest,
        digest("generation"),
        digest("model"),
        digest("preprocessor"),
        vec![FixedQ32::ZERO, FixedQ32::ZERO],
    )?;
    Ok(VectorIndexSnapshotV1::new(
        digest("generation"),
        digest(owner_generation),
        digest("model"),
        digest("preprocessor"),
        2,
        vec![VectorIndexRecordV1 {
            record,
            embedding,
            ood: ProbabilityQ32::ZERO,
        }],
    )?)
}

#[test]
fn exhausted_sequence_has_no_valid_successor() {
    let current = VectorIndexPublicationV1::new(
        digest("tenant"),
        7,
        u64::MAX,
        9,
        Some(digest("previous")),
        encoder().expect("valid encoder fixture"),
        snapshot("owner-generation-9").expect("valid snapshot fixture"),
        4,
        7,
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("current publication");
    let candidate = VectorIndexPublicationV1::new(
        digest("tenant"),
        current.writer_fence(),
        2,
        9,
        Some(current.publication_digest()),
        encoder().expect("valid encoder fixture"),
        current.snapshot().clone(),
        4,
        7,
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("standalone candidate");

    assert_eq!(
        current.validate_successor(&candidate),
        Err(VectorPublicationErrorV1::SequenceExhausted)
    );
}
