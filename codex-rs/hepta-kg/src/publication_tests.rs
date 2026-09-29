use super::*;
use crate::KnowledgeProjectionInputV2;
use crate::build_complete_generation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

#[derive(Default)]
struct MockStorage {
    staged: bool,
    rollback_fails: bool,
    commit: Option<KnowledgeCommitOutcomeV2>,
    reconciliation: Option<KnowledgeReconciliationStateV2>,
}

impl KnowledgeTransactionalStorageV2 for MockStorage {
    type Transaction = ();

    fn begin_publication(
        &mut self,
        _expected_predecessor_digest: Option<Digest32>,
        _candidate: &KnowledgeGenerationV2,
    ) -> Result<Self::Transaction, KnowledgePublicationErrorV2> {
        Ok(())
    }

    fn stage_publication(
        &mut self,
        _transaction: &mut Self::Transaction,
        _candidate: &KnowledgeGenerationV2,
        _receipt: &KnowledgePublicationReceiptV2,
    ) -> Result<(), KnowledgePublicationErrorV2> {
        self.staged = true;
        Ok(())
    }

    fn commit_publication(
        &mut self,
        _transaction: Self::Transaction,
    ) -> KnowledgeCommitOutcomeV2 {
        self.commit
            .take()
            .unwrap_or(KnowledgeCommitOutcomeV2::Committed)
    }

    fn rollback_publication(
        &mut self,
        _transaction: Self::Transaction,
    ) -> Result<(), KnowledgePublicationErrorV2> {
        if self.rollback_fails {
            Err(KnowledgePublicationErrorV2::storage_unavailable(
                "rollback failed",
            ))
        } else {
            Ok(())
        }
    }

    fn reconcile_publication(
        &mut self,
        _generation: Generation,
        _generation_digest: Digest32,
    ) -> Result<KnowledgeReconciliationStateV2, KnowledgePublicationErrorV2> {
        Ok(self
            .reconciliation
            .unwrap_or(KnowledgeReconciliationStateV2::Unknown))
    }
}

fn generation(number: u64) -> KnowledgeGenerationV2 {
    let Ok(generation) = Generation::new(number) else {
        panic!("test generation must be valid");
    };
    let result = build_complete_generation(
        generation,
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: Digest32::of_bytes(format!("snapshot:{number}").as_bytes()),
            generation_vector_digest: Digest32::of_bytes(format!("vector:{number}").as_bytes()),
            graph_profile_digest: Digest32::of_bytes(b"profile"),
            complete_source_cut: true,
            nodes: Vec::new(),
            edges: Vec::new(),
        },
    );
    let Ok(value) = result else {
        panic!("test generation must build");
    };
    value
}

#[test]
fn unknown_commit_is_reconciled_before_success() {
    let mut storage = MockStorage {
        commit: Some(KnowledgeCommitOutcomeV2::Unknown {
            detail: "transport ended after commit request".to_string(),
        }),
        reconciliation: Some(KnowledgeReconciliationStateV2::Committed),
        ..MockStorage::default()
    };
    let candidate = generation(1);
    let result = publish_transactionally(&mut storage, None, &candidate);
    let Ok(published) = result else {
        panic!("reconciled commit must succeed");
    };
    assert!(storage.staged);
    assert!(published.reconciled_after_unknown_commit);
    assert_eq!(published.receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn unknown_commit_never_becomes_retryable_without_abort_proof() {
    let mut storage = MockStorage {
        commit: Some(KnowledgeCommitOutcomeV2::Unknown {
            detail: "lost acknowledgement".to_string(),
        }),
        reconciliation: Some(KnowledgeReconciliationStateV2::Unknown),
        ..MockStorage::default()
    };
    let result = publish_transactionally(&mut storage, None, &generation(1));
    let Err(error) = result else {
        panic!("unknown outcome must fail closed");
    };
    assert_eq!(
        error.code,
        KnowledgePublicationErrorCodeV2::CommitOutcomeUnknown
    );
}

#[test]
fn stale_generation_is_distinct_from_predecessor_gap() {
    let predecessor = generation(2);
    let stale = generation(2);
    let result = publish_transactionally(&mut MockStorage::default(), Some(&predecessor), &stale);
    let Err(stale_error) = result else {
        panic!("stale generation must fail");
    };
    assert_eq!(
        stale_error.code,
        KnowledgePublicationErrorCodeV2::StaleGeneration
    );

    let gap = generation(4);
    let result = publish_transactionally(&mut MockStorage::default(), Some(&predecessor), &gap);
    let Err(gap_error) = result else {
        panic!("generation gap must fail");
    };
    assert_eq!(
        gap_error.code,
        KnowledgePublicationErrorCodeV2::PredecessorConflict
    );
}
