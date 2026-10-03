use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::VectorEmbeddingV1;
use crate::VectorIndexRecordV1;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation() -> Digest32 {
    digest("vector-generation")
}

fn model() -> Digest32 {
    digest("model")
}

fn preprocessor() -> Digest32 {
    digest("preprocessor")
}

fn record(number: u64) -> MemoryRecord {
    MemoryRecord {
        record_id: StableId::new(format!("memory:{number}")).expect("record id"),
        revision: Revision::new(1).expect("revision"),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("content:{number}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn embedding(subject: Digest32, first: i64, second: i64) -> VectorEmbeddingV1 {
    VectorEmbeddingV1::new(
        subject,
        generation(),
        model(),
        preprocessor(),
        vec![FixedQ32::from_raw(first), FixedQ32::from_raw(second)],
    )
    .expect("embedding")
}

fn snapshot(numbers: &[u64], owner_generation: &str) -> VectorIndexSnapshotV1 {
    let records = numbers
        .iter()
        .map(|number| {
            let record = record(*number);
            VectorIndexRecordV1 {
                embedding: embedding(record.content_digest, 0, 0),
                record,
                ood: ProbabilityQ32::ZERO,
            }
        })
        .collect();
    VectorIndexSnapshotV1::new(
        generation(),
        digest(owner_generation),
        model(),
        preprocessor(),
        2,
        records,
    )
    .expect("snapshot")
}

fn encoder() -> EncoderReleaseIdentityV1 {
    EncoderReleaseIdentityV1::new(
        model(),
        digest("weights"),
        digest("runtime"),
        preprocessor(),
        2,
    )
    .expect("encoder release")
}

fn genesis() -> VectorIndexPublicationV1 {
    VectorIndexPublicationV1::new(
        digest("tenant-a"),
        7,
        1,
        1,
        None,
        encoder(),
        snapshot(&[1, 2], "owner-generation-1"),
        3,
        5,
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("genesis publication")
}

fn query() -> VectorQueryV1 {
    let query_digest = digest("query");
    VectorQueryV1 {
        query_digest,
        embedding: embedding(query_digest, 0, 0),
        maximum_candidates: 2,
        maximum_ood: ProbabilityQ32::ONE,
    }
}

#[test]
fn published_owner_requires_exact_tenant_and_current_frontiers() {
    let owner = PublishedVectorOwnerV1::new(genesis()).expect("published owner");
    let request = PublishedVectorQueryV1 {
        tenant_digest: digest("tenant-a"),
        minimum_withdrawal_frontier: 3,
        minimum_revocation_frontier: 5,
        query: query(),
    };
    let batch = owner.generate(&request).expect("batch");
    assert_eq!(batch.receipt.candidate_count, 2);

    let mut wrong_tenant = request.clone();
    wrong_tenant.tenant_digest = digest("tenant-b");
    assert_eq!(
        owner.generate(&wrong_tenant),
        Err(VectorPublicationErrorV1::TenantMismatch)
    );

    let mut stale = request;
    stale.minimum_revocation_frontier = 6;
    assert_eq!(
        owner.generate(&stale),
        Err(VectorPublicationErrorV1::FrontierTooOld)
    );
}

#[test]
fn changed_index_requires_generation_advance_and_exact_parent() {
    let current = genesis();
    let same_generation = VectorIndexPublicationV1::new(
        current.tenant_digest(),
        current.writer_fence(),
        2,
        1,
        Some(current.publication_digest()),
        encoder(),
        snapshot(&[1, 3], "owner-generation-2"),
        3,
        5,
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("structurally valid publication");
    assert_eq!(
        current.validate_successor(&same_generation),
        Err(VectorPublicationErrorV1::GenerationNotAdvanced)
    );

    let advanced = VectorIndexPublicationV1::new(
        current.tenant_digest(),
        current.writer_fence(),
        2,
        2,
        Some(current.publication_digest()),
        encoder(),
        snapshot(&[1, 3], "owner-generation-2"),
        3,
        5,
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("advanced publication");
    current
        .validate_successor(&advanced)
        .expect("valid generation switch");
}

#[test]
fn stale_writer_fence_cannot_publish_with_an_exact_parent() {
    let current = genesis();
    let stale = VectorIndexPublicationV1::new(
        current.tenant_digest(),
        current.writer_fence() - 1,
        current.sequence() + 1,
        current.generation(),
        Some(current.publication_digest()),
        encoder(),
        current.snapshot().clone(),
        current.withdrawal_frontier(),
        current.revocation_frontier(),
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("standalone stale-fence publication");
    assert_eq!(
        current.validate_successor(&stale),
        Err(VectorPublicationErrorV1::StaleWriterFence)
    );
}

#[test]
fn newer_writer_fence_can_take_over_at_the_same_object() {
    let current = genesis();
    let takeover = VectorIndexPublicationV1::new(
        current.tenant_digest(),
        current.writer_fence() + 1,
        current.sequence() + 1,
        current.generation(),
        Some(current.publication_digest()),
        encoder(),
        current.snapshot().clone(),
        current.withdrawal_frontier(),
        current.revocation_frontier(),
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("takeover publication");
    current
        .validate_successor(&takeover)
        .expect("new fenced writer may take over");
}

#[test]
fn withdrawal_is_monotonic_and_removed_content_cannot_reappear() {
    let current = genesis();
    let removed = record(2).record_digest();
    let withdrawn = VectorIndexPublicationV1::new(
        current.tenant_digest(),
        current.writer_fence(),
        2,
        2,
        Some(current.publication_digest()),
        encoder(),
        snapshot(&[1], "owner-generation-2"),
        4,
        5,
        vec![removed],
        VectorPublicationStateV1::Active,
    )
    .expect("withdrawal publication");
    current
        .validate_successor(&withdrawn)
        .expect("monotonic withdrawal");

    let reintroduced = VectorIndexPublicationV1::new(
        current.tenant_digest(),
        current.writer_fence(),
        3,
        3,
        Some(withdrawn.publication_digest()),
        encoder(),
        snapshot(&[1, 2], "owner-generation-3"),
        5,
        5,
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("standalone publication");
    assert_eq!(
        withdrawn.validate_successor(&reintroduced),
        Err(VectorPublicationErrorV1::WithdrawalRollback)
    );
}

#[test]
fn terminally_withdrawn_publication_cannot_serve_or_reactivate() {
    let current = genesis();
    let terminal = VectorIndexPublicationV1::new(
        current.tenant_digest(),
        current.writer_fence(),
        2,
        1,
        Some(current.publication_digest()),
        encoder(),
        current.snapshot().clone(),
        current.withdrawal_frontier(),
        current.revocation_frontier() + 1,
        Vec::new(),
        VectorPublicationStateV1::Withdrawn,
    )
    .expect("terminal publication");
    current
        .validate_successor(&terminal)
        .expect("terminal transition");
    assert_eq!(
        PublishedVectorOwnerV1::new(terminal.clone()),
        Err(VectorPublicationErrorV1::PublicationNotActive)
    );

    let reactivated = VectorIndexPublicationV1::new(
        terminal.tenant_digest(),
        terminal.writer_fence() + 1,
        3,
        2,
        Some(terminal.publication_digest()),
        encoder(),
        terminal.snapshot().clone(),
        terminal.withdrawal_frontier(),
        terminal.revocation_frontier(),
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("standalone active publication");
    assert_eq!(
        terminal.validate_successor(&reactivated),
        Err(VectorPublicationErrorV1::WithdrawnPublicationReactivated)
    );
}
