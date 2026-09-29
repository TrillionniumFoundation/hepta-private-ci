use super::*;
use crate::KnowledgeProjectionInputV2;
use crate::build_complete_generation;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

#[derive(Default)]
struct MockStorage {
    began: bool,
    staged: bool,
    committed: bool,
    rolled_back: bool,
    reconciled: bool,
    begin_error: Option<KnowledgePublicationErrorV2>,
    stage_error: Option<KnowledgePublicationErrorV2>,
    rollback_error: Option<KnowledgePublicationErrorV2>,
    reconciliation_error: Option<KnowledgePublicationErrorV2>,
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
        self.began = true;
        match self.begin_error.take() {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }

    fn stage_publication(
        &mut self,
        _transaction: &mut Self::Transaction,
        _candidate: &KnowledgeGenerationV2,
        _receipt: &KnowledgePublicationReceiptV2,
    ) -> Result<(), KnowledgePublicationErrorV2> {
        self.staged = true;
        match self.stage_error.take() {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }

    fn commit_publication(
        &mut self,
        _transaction: Self::Transaction,
    ) -> KnowledgeCommitOutcomeV2 {
        self.committed = true;
        self.commit
            .take()
            .unwrap_or(KnowledgeCommitOutcomeV2::Committed)
    }

    fn rollback_publication(
        &mut self,
        _transaction: Self::Transaction,
    ) -> Result<(), KnowledgePublicationErrorV2> {
        self.rolled_back = true;
        match self.rollback_error.take() {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }

    fn reconcile_publication(
        &mut self,
        _generation: Generation,
        _generation_digest: Digest32,
    ) -> Result<KnowledgeReconciliationStateV2, KnowledgePublicationErrorV2> {
        self.reconciled = true;
        match self.reconciliation_error.take() {
            Some(error) => Err(error),
            None => Ok(self
                .reconciliation
                .unwrap_or(KnowledgeReconciliationStateV2::Unknown)),
        }
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
    assert!(storage.began);
    assert!(storage.staged);
    assert!(storage.committed);
    assert!(storage.reconciled);
    assert!(!storage.rolled_back);
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
    assert!(storage.reconciled);
    assert!(!storage.rolled_back);
}

#[test]
fn reconciliation_abort_proof_returns_known_aborted() {
    let mut storage = MockStorage {
        commit: Some(KnowledgeCommitOutcomeV2::Unknown {
            detail: "commit reply was lost".to_string(),
        }),
        reconciliation: Some(KnowledgeReconciliationStateV2::Aborted),
        ..MockStorage::default()
    };
    let result = publish_transactionally(&mut storage, None, &generation(1));
    let Err(error) = result else {
        panic!("reconciled abort must be terminal");
    };
    assert_eq!(error.code, KnowledgePublicationErrorCodeV2::KnownAborted);
    assert!(error.detail.contains("reconciliation proved abort"));
    assert!(storage.reconciled);
}

#[test]
fn reconciliation_failure_preserves_unknown_primary_outcome() {
    let mut storage = MockStorage {
        commit: Some(KnowledgeCommitOutcomeV2::Unknown {
            detail: "commit acknowledgement missing".to_string(),
        }),
        reconciliation_error: Some(KnowledgePublicationErrorV2::storage_unavailable(
            "reconciliation store unavailable",
        )),
        ..MockStorage::default()
    };
    let result = publish_transactionally(&mut storage, None, &generation(1));
    let Err(error) = result else {
        panic!("failed reconciliation must fail closed");
    };
    assert_eq!(
        error.code,
        KnowledgePublicationErrorCodeV2::ReconciliationFailed
    );
    assert_eq!(
        error.primary_code,
        Some(KnowledgePublicationErrorCodeV2::CommitOutcomeUnknown)
    );
    assert_eq!(
        error.primary_detail.as_deref(),
        Some("commit acknowledgement missing")
    );
    assert!(storage.reconciled);
}

#[test]
fn known_abort_is_terminal_without_reconciliation_or_rollback() {
    let mut storage = MockStorage {
        commit: Some(KnowledgeCommitOutcomeV2::KnownAborted {
            detail: "durable owner rejected commit".to_string(),
        }),
        ..MockStorage::default()
    };
    let result = publish_transactionally(&mut storage, None, &generation(1));
    let Err(error) = result else {
        panic!("known abort must be returned");
    };
    assert_eq!(error.code, KnowledgePublicationErrorCodeV2::KnownAborted);
    assert!(storage.committed);
    assert!(!storage.reconciled);
    assert!(!storage.rolled_back);
}

#[test]
fn stage_failure_rolls_back_and_preserves_primary_error() {
    let mut storage = MockStorage {
        stage_error: Some(KnowledgePublicationErrorV2::capacity_exhausted(
            "staging exceeds transaction budget",
        )),
        ..MockStorage::default()
    };
    let result = publish_transactionally(&mut storage, None, &generation(1));
    let Err(error) = result else {
        panic!("stage failure must be returned");
    };
    assert_eq!(
        error.code,
        KnowledgePublicationErrorCodeV2::CapacityExhausted
    );
    assert_eq!(error.primary_code, None);
    assert!(storage.rolled_back);
    assert!(!storage.committed);
    assert!(!storage.reconciled);
}

#[test]
fn rollback_failure_preserves_both_failures() {
    let mut storage = MockStorage {
        stage_error: Some(KnowledgePublicationErrorV2::capacity_exhausted(
            "staging exceeds transaction budget",
        )),
        rollback_error: Some(KnowledgePublicationErrorV2::storage_unavailable(
            "rollback result unavailable",
        )),
        ..MockStorage::default()
    };
    let result = publish_transactionally(&mut storage, None, &generation(1));
    let Err(error) = result else {
        panic!("rollback failure must be explicit");
    };
    assert_eq!(
        error.code,
        KnowledgePublicationErrorCodeV2::RollbackFailed
    );
    assert_eq!(
        error.primary_code,
        Some(KnowledgePublicationErrorCodeV2::CapacityExhausted)
    );
    assert_eq!(
        error.primary_detail.as_deref(),
        Some("staging exceeds transaction budget")
    );
    assert_eq!(error.detail, "rollback result unavailable");
    assert!(storage.rolled_back);
}

#[test]
fn begin_failure_does_not_enter_stage_or_rollback() {
    let mut storage = MockStorage {
        begin_error: Some(KnowledgePublicationErrorV2::capacity_exhausted(
            "publication concurrency exhausted",
        )),
        ..MockStorage::default()
    };
    let result = publish_transactionally(&mut storage, None, &generation(1));
    let Err(error) = result else {
        panic!("begin failure must be returned");
    };
    assert_eq!(
        error.code,
        KnowledgePublicationErrorCodeV2::CapacityExhausted
    );
    assert!(storage.began);
    assert!(!storage.staged);
    assert!(!storage.committed);
    assert!(!storage.rolled_back);
    assert!(!storage.reconciled);
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

#[test]
fn observable_error_codes_are_stable() {
    let cases = [
        (
            KnowledgePublicationErrorCodeV2::ValidationFailed,
            "kg_validation_failed",
        ),
        (
            KnowledgePublicationErrorCodeV2::PredecessorConflict,
            "kg_predecessor_conflict",
        ),
        (
            KnowledgePublicationErrorCodeV2::StaleGeneration,
            "kg_stale_generation",
        ),
        (
            KnowledgePublicationErrorCodeV2::StorageUnavailable,
            "kg_storage_unavailable",
        ),
        (
            KnowledgePublicationErrorCodeV2::CapacityExhausted,
            "kg_capacity_exhausted",
        ),
        (
            KnowledgePublicationErrorCodeV2::KnownAborted,
            "kg_known_aborted",
        ),
        (
            KnowledgePublicationErrorCodeV2::CommitOutcomeUnknown,
            "kg_commit_outcome_unknown",
        ),
        (
            KnowledgePublicationErrorCodeV2::RollbackFailed,
            "kg_rollback_failed",
        ),
        (
            KnowledgePublicationErrorCodeV2::ReconciliationFailed,
            "kg_reconciliation_failed",
        ),
    ];
    for (code, expected) in cases {
        assert_eq!(code.as_str(), expected);
    }
}
