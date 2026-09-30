use std::cell::Cell;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_memory_retrieval::DurableVectorPublicationAppendErrorV1;
use codex_hepta_memory_retrieval::VectorEmbeddingV1;
use codex_hepta_memory_retrieval::VectorIndexRecordV1;
use codex_hepta_memory_retrieval::VectorIndexSnapshotV1;
use codex_hepta_memory_retrieval::append_vector_publication_checked_v1;
use codex_hepta_memory_retrieval::vector_publication::DurableVectorPublicationPortV1;
use codex_hepta_memory_retrieval::vector_publication::EncoderReleaseIdentityV1;
use codex_hepta_memory_retrieval::vector_publication::VectorIndexPublicationV1;
use codex_hepta_memory_retrieval::vector_publication::VectorPublicationStateV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn encoder() -> EncoderReleaseIdentityV1 {
    EncoderReleaseIdentityV1::new(
        digest("model"),
        digest("weights"),
        digest("runtime"),
        digest("preprocessor"),
        2,
    )
    .expect("encoder")
}

fn snapshot(owner_generation: &str) -> VectorIndexSnapshotV1 {
    let record = MemoryRecord {
        record_id: StableId::new("memory:checked-publication").expect("record id"),
        revision: Revision::new(1).expect("revision"),
        kind: MemoryKind::Fact,
        content_digest: digest("content"),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    };
    let embedding = VectorEmbeddingV1::new(
        record.content_digest,
        digest("generation-vector"),
        digest("model"),
        digest("preprocessor"),
        vec![FixedQ32::ZERO, FixedQ32::ZERO],
    )
    .expect("embedding");
    VectorIndexSnapshotV1::new(
        digest("generation-vector"),
        digest(owner_generation),
        digest("model"),
        digest("preprocessor"),
        2,
        vec![VectorIndexRecordV1 {
            record,
            embedding,
            ood: ProbabilityQ32::ZERO,
        }],
    )
    .expect("snapshot")
}

fn genesis(owner_generation: &str) -> VectorIndexPublicationV1 {
    VectorIndexPublicationV1::new(
        digest("tenant"),
        7,
        1,
        1,
        None,
        encoder(),
        snapshot(owner_generation),
        3,
        5,
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("genesis")
}

fn successor(current: &VectorIndexPublicationV1) -> VectorIndexPublicationV1 {
    VectorIndexPublicationV1::new(
        current.tenant_digest(),
        current.writer_fence(),
        current
            .sequence()
            .checked_add(1)
            .expect("sequence capacity"),
        current
            .generation()
            .checked_add(1)
            .expect("generation capacity"),
        Some(current.publication_digest()),
        encoder(),
        snapshot("owner-generation-2"),
        current.withdrawal_frontier(),
        current.revocation_frontier(),
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("successor")
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PortError {
    CompareAndPublish,
    LostAcknowledgement,
    Load,
}

impl fmt::Display for PortError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PortError {}

#[derive(Default)]
struct Port {
    current: Option<VectorIndexPublicationV1>,
    writes: usize,
    fail_before_commit_once: bool,
    fail_after_commit_once: bool,
    fail_confirmation_once: Cell<bool>,
    replacement: Option<VectorIndexPublicationV1>,
}

impl DurableVectorPublicationPortV1 for Port {
    type Error = PortError;

    fn acquire_writer_fence(
        &mut self,
        _tenant_digest: Digest32,
        _writer_identity_digest: Digest32,
    ) -> Result<u64, Self::Error> {
        Ok(7)
    }

    fn load_current(
        &self,
        tenant_digest: Digest32,
    ) -> Result<Option<VectorIndexPublicationV1>, Self::Error> {
        if self.writes > 0 && self.fail_confirmation_once.replace(false) {
            return Err(PortError::Load);
        }
        Ok(self
            .current
            .as_ref()
            .filter(|publication| publication.tenant_digest() == tenant_digest)
            .cloned())
    }

    fn compare_and_publish(
        &mut self,
        tenant_digest: Digest32,
        expected_current: Option<Digest32>,
        next: &VectorIndexPublicationV1,
    ) -> Result<(), Self::Error> {
        let actual = self
            .current
            .as_ref()
            .filter(|publication| publication.tenant_digest() == tenant_digest)
            .map(VectorIndexPublicationV1::publication_digest);
        if actual != expected_current || self.fail_before_commit_once {
            self.fail_before_commit_once = false;
            return Err(PortError::CompareAndPublish);
        }
        self.writes = self.writes.checked_add(1).expect("write count capacity");
        self.current = Some(self.replacement.take().unwrap_or_else(|| next.clone()));
        if self.fail_after_commit_once {
            self.fail_after_commit_once = false;
            return Err(PortError::LostAcknowledgement);
        }
        Ok(())
    }
}

#[test]
fn checked_api_publishes_genesis_and_exact_successor() {
    let first = genesis("owner-generation-1");
    let mut port = Port::default();
    assert_eq!(
        append_vector_publication_checked_v1(&mut port, first.tenant_digest(), None, &first,)
            .expect("publish genesis"),
        first.publication_digest()
    );

    let second = successor(&first);
    assert_eq!(
        append_vector_publication_checked_v1(
            &mut port,
            second.tenant_digest(),
            Some(first.publication_digest()),
            &second,
        )
        .expect("publish successor"),
        second.publication_digest()
    );
    assert_eq!(port.writes, 2);
}

#[test]
fn lost_acknowledgement_is_reconciled_without_a_second_write() {
    let publication = genesis("owner-generation-1");
    let mut port = Port {
        fail_after_commit_once: true,
        ..Port::default()
    };

    assert_eq!(
        append_vector_publication_checked_v1(
            &mut port,
            publication.tenant_digest(),
            None,
            &publication,
        )
        .expect("exact committed object reconciles"),
        publication.publication_digest()
    );
    assert_eq!(port.writes, 1);

    append_vector_publication_checked_v1(
        &mut port,
        publication.tenant_digest(),
        None,
        &publication,
    )
    .expect("exact replay is idempotent");
    assert_eq!(port.writes, 1);
}

#[test]
fn compare_failure_without_exact_current_is_outcome_unknown() {
    let publication = genesis("owner-generation-1");
    let mut port = Port {
        fail_before_commit_once: true,
        ..Port::default()
    };

    let error = append_vector_publication_checked_v1(
        &mut port,
        publication.tenant_digest(),
        None,
        &publication,
    )
    .expect_err("failed publish without exact reconciliation must be unknown");
    assert!(matches!(
        error,
        DurableVectorPublicationAppendErrorV1::CommitOutcomeUnknown {
            publish_error: Some(PortError::CompareAndPublish),
            reconciliation_error: None,
            observed: None,
        }
    ));
    assert_eq!(port.writes, 0);
}

#[test]
fn successful_publish_with_failed_confirmation_is_outcome_unknown() {
    let publication = genesis("owner-generation-1");
    let mut port = Port {
        fail_confirmation_once: Cell::new(true),
        ..Port::default()
    };

    let error = append_vector_publication_checked_v1(
        &mut port,
        publication.tenant_digest(),
        None,
        &publication,
    )
    .expect_err("successful publish without confirmation must be unknown");
    assert!(matches!(
        error,
        DurableVectorPublicationAppendErrorV1::CommitOutcomeUnknown {
            publish_error: None,
            reconciliation_error: Some(PortError::Load),
            observed: None,
        }
    ));
    assert_eq!(port.writes, 1);

    append_vector_publication_checked_v1(
        &mut port,
        publication.tenant_digest(),
        None,
        &publication,
    )
    .expect("later exact reload recognizes the committed object");
    assert_eq!(port.writes, 1);
}

#[test]
fn stale_expected_parent_is_rejected_before_mutation() {
    let current = genesis("owner-generation-1");
    let next = successor(&current);
    let mut port = Port {
        current: Some(current.clone()),
        ..Port::default()
    };

    let error = append_vector_publication_checked_v1(&mut port, next.tenant_digest(), None, &next)
        .expect_err("stale parent must fail");
    assert!(matches!(
        error,
        DurableVectorPublicationAppendErrorV1::CurrentPublicationMismatch {
            expected: None,
            actual: Some(actual),
        } if actual == current.publication_digest()
    ));
    assert_eq!(port.writes, 0);
}

#[test]
fn non_genesis_sequence_without_current_object_is_rejected() {
    let candidate = VectorIndexPublicationV1::new(
        digest("tenant"),
        7,
        2,
        2,
        Some(digest("missing-parent")),
        encoder(),
        snapshot("owner-generation-2"),
        3,
        5,
        Vec::new(),
        VectorPublicationStateV1::Active,
    )
    .expect("standalone candidate");
    let mut port = Port::default();

    let error = append_vector_publication_checked_v1(
        &mut port,
        candidate.tenant_digest(),
        None,
        &candidate,
    )
    .expect_err("non-genesis without current must fail");
    assert!(matches!(
        error,
        DurableVectorPublicationAppendErrorV1::InvalidGenesisSequence { actual: 2 }
    ));
    assert_eq!(port.writes, 0);
}

#[test]
fn successful_port_return_still_requires_exact_committed_object() {
    let expected = genesis("owner-generation-1");
    let replacement = genesis("owner-generation-other");
    let mut port = Port {
        replacement: Some(replacement.clone()),
        ..Port::default()
    };

    let error =
        append_vector_publication_checked_v1(&mut port, expected.tenant_digest(), None, &expected)
            .expect_err("wrong committed object must fail");
    assert!(matches!(
        error,
        DurableVectorPublicationAppendErrorV1::CommittedPublicationMismatch {
            expected: expected_digest,
            actual: Some(actual_digest),
        } if expected_digest == expected.publication_digest()
            && actual_digest == replacement.publication_digest()
    ));
    assert_eq!(port.writes, 1);
}
