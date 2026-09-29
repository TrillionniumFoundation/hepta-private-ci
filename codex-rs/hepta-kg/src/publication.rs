//! Explicit transactional publication capability and terminal-outcome model.
//!
//! The knowledge kernel does not own durable storage. Production owners must
//! implement every transition below; there are deliberately no no-op defaults.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::KnowledgeGenerationErrorV2;
use crate::KnowledgeGenerationV2;
use crate::KnowledgePublicationReceiptV2;
use crate::publish_generation;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum KnowledgePublicationErrorCodeV2 {
    ValidationFailed,
    PredecessorConflict,
    StaleGeneration,
    StorageUnavailable,
    CapacityExhausted,
    KnownAborted,
    CommitOutcomeUnknown,
    RollbackFailed,
    ReconciliationFailed,
}

impl KnowledgePublicationErrorCodeV2 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ValidationFailed => "kg_validation_failed",
            Self::PredecessorConflict => "kg_predecessor_conflict",
            Self::StaleGeneration => "kg_stale_generation",
            Self::StorageUnavailable => "kg_storage_unavailable",
            Self::CapacityExhausted => "kg_capacity_exhausted",
            Self::KnownAborted => "kg_known_aborted",
            Self::CommitOutcomeUnknown => "kg_commit_outcome_unknown",
            Self::RollbackFailed => "kg_rollback_failed",
            Self::ReconciliationFailed => "kg_reconciliation_failed",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgePublicationErrorV2 {
    pub code: KnowledgePublicationErrorCodeV2,
    pub detail: String,
    pub primary_code: Option<KnowledgePublicationErrorCodeV2>,
    pub primary_detail: Option<String>,
}

impl KnowledgePublicationErrorV2 {
    pub fn new(code: KnowledgePublicationErrorCodeV2, detail: impl Into<String>) -> Self {
        Self {
            code,
            detail: detail.into(),
            primary_code: None,
            primary_detail: None,
        }
    }

    pub fn storage_unavailable(detail: impl Into<String>) -> Self {
        Self::new(
            KnowledgePublicationErrorCodeV2::StorageUnavailable,
            detail,
        )
    }

    pub fn capacity_exhausted(detail: impl Into<String>) -> Self {
        Self::new(
            KnowledgePublicationErrorCodeV2::CapacityExhausted,
            detail,
        )
    }

    fn rollback_failed(primary: Self, rollback: Self) -> Self {
        Self {
            code: KnowledgePublicationErrorCodeV2::RollbackFailed,
            detail: rollback.detail,
            primary_code: Some(primary.code),
            primary_detail: Some(primary.detail),
        }
    }
}

impl fmt::Display for KnowledgePublicationErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code.as_str(), self.detail)?;
        if let (Some(code), Some(detail)) = (self.primary_code, self.primary_detail.as_deref()) {
            write!(
                formatter,
                "; primary failure {}: {}",
                code.as_str(),
                detail
            )?;
        }
        Ok(())
    }
}

impl StdError for KnowledgePublicationErrorV2 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum KnowledgeCommitOutcomeV2 {
    Committed,
    KnownAborted { detail: String },
    Unknown { detail: String },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum KnowledgeReconciliationStateV2 {
    Committed,
    Aborted,
    Unknown,
}

/// Durable storage capability required by production publication.
///
/// The absence of default methods is intentional: implementing this trait is a
/// proof obligation that begin, stage, commit, rollback and reconciliation all
/// have explicit owner semantics.
pub trait KnowledgeTransactionalStorageV2 {
    type Transaction;

    fn begin_publication(
        &mut self,
        expected_predecessor_digest: Option<Digest32>,
        candidate: &KnowledgeGenerationV2,
    ) -> Result<Self::Transaction, KnowledgePublicationErrorV2>;

    fn stage_publication(
        &mut self,
        transaction: &mut Self::Transaction,
        candidate: &KnowledgeGenerationV2,
        receipt: &KnowledgePublicationReceiptV2,
    ) -> Result<(), KnowledgePublicationErrorV2>;

    fn commit_publication(
        &mut self,
        transaction: Self::Transaction,
    ) -> KnowledgeCommitOutcomeV2;

    fn rollback_publication(
        &mut self,
        transaction: Self::Transaction,
    ) -> Result<(), KnowledgePublicationErrorV2>;

    fn reconcile_publication(
        &mut self,
        generation: Generation,
        generation_digest: Digest32,
    ) -> Result<KnowledgeReconciliationStateV2, KnowledgePublicationErrorV2>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeTransactionalPublicationV2 {
    pub receipt: KnowledgePublicationReceiptV2,
    pub reconciled_after_unknown_commit: bool,
}

/// Validate, stage and commit one generation with explicit terminal semantics.
///
/// A commit error is never treated as an abort. Unknown outcomes enter the
/// storage owner's reconciliation path and are safe to retry only after that
/// path reports `Aborted`.
pub fn publish_transactionally<S: KnowledgeTransactionalStorageV2>(
    storage: &mut S,
    predecessor: Option<&KnowledgeGenerationV2>,
    candidate: &KnowledgeGenerationV2,
) -> Result<KnowledgeTransactionalPublicationV2, KnowledgePublicationErrorV2> {
    validate_predecessor(predecessor, candidate)?;
    let receipt = publish_generation(predecessor, candidate).map_err(map_generation_error)?;
    let expected_predecessor_digest = predecessor.map(|value| value.generation_digest);
    let mut transaction = storage.begin_publication(expected_predecessor_digest, candidate)?;
    if let Err(primary) = storage.stage_publication(&mut transaction, candidate, &receipt) {
        return match storage.rollback_publication(transaction) {
            Ok(()) => Err(primary),
            Err(rollback) => Err(KnowledgePublicationErrorV2::rollback_failed(
                primary, rollback,
            )),
        };
    }

    match storage.commit_publication(transaction) {
        KnowledgeCommitOutcomeV2::Committed => Ok(KnowledgeTransactionalPublicationV2 {
            receipt,
            reconciled_after_unknown_commit: false,
        }),
        KnowledgeCommitOutcomeV2::KnownAborted { detail } => {
            Err(KnowledgePublicationErrorV2::new(
                KnowledgePublicationErrorCodeV2::KnownAborted,
                detail,
            ))
        }
        KnowledgeCommitOutcomeV2::Unknown { detail } => match storage
            .reconcile_publication(candidate.generation, candidate.generation_digest)
        {
            Ok(KnowledgeReconciliationStateV2::Committed) => {
                Ok(KnowledgeTransactionalPublicationV2 {
                    receipt,
                    reconciled_after_unknown_commit: true,
                })
            }
            Ok(KnowledgeReconciliationStateV2::Aborted) => {
                Err(KnowledgePublicationErrorV2::new(
                    KnowledgePublicationErrorCodeV2::KnownAborted,
                    format!("commit outcome was unknown and reconciliation proved abort: {detail}"),
                ))
            }
            Ok(KnowledgeReconciliationStateV2::Unknown) => {
                Err(KnowledgePublicationErrorV2::new(
                    KnowledgePublicationErrorCodeV2::CommitOutcomeUnknown,
                    detail,
                ))
            }
            Err(error) => Err(KnowledgePublicationErrorV2 {
                code: KnowledgePublicationErrorCodeV2::ReconciliationFailed,
                detail: error.detail,
                primary_code: Some(KnowledgePublicationErrorCodeV2::CommitOutcomeUnknown),
                primary_detail: Some(detail),
            }),
        },
    }
}

fn validate_predecessor(
    predecessor: Option<&KnowledgeGenerationV2>,
    candidate: &KnowledgeGenerationV2,
) -> Result<(), KnowledgePublicationErrorV2> {
    candidate.validate().map_err(map_generation_error)?;
    let Some(predecessor) = predecessor else {
        if candidate.generation.get() != 1 {
            return Err(KnowledgePublicationErrorV2::new(
                KnowledgePublicationErrorCodeV2::PredecessorConflict,
                "the first publication must use generation 1",
            ));
        }
        return Ok(());
    };
    predecessor.validate().map_err(map_generation_error)?;
    if candidate.generation.get() <= predecessor.generation.get() {
        return Err(KnowledgePublicationErrorV2::new(
            KnowledgePublicationErrorCodeV2::StaleGeneration,
            format!(
                "candidate generation {} is not newer than predecessor {}",
                candidate.generation.get(),
                predecessor.generation.get()
            ),
        ));
    }
    if predecessor.generation.next().ok() != Some(candidate.generation) {
        return Err(KnowledgePublicationErrorV2::new(
            KnowledgePublicationErrorCodeV2::PredecessorConflict,
            format!(
                "candidate generation {} does not immediately follow predecessor {}",
                candidate.generation.get(),
                predecessor.generation.get()
            ),
        ));
    }
    Ok(())
}

fn map_generation_error(error: KnowledgeGenerationErrorV2) -> KnowledgePublicationErrorV2 {
    let code = match error {
        KnowledgeGenerationErrorV2::InvalidPredecessor => {
            KnowledgePublicationErrorCodeV2::PredecessorConflict
        }
        KnowledgeGenerationErrorV2::NodeLimitExceeded
        | KnowledgeGenerationErrorV2::EdgeLimitExceeded
        | KnowledgeGenerationErrorV2::SupportLimitExceeded => {
            KnowledgePublicationErrorCodeV2::CapacityExhausted
        }
        _ => KnowledgePublicationErrorCodeV2::ValidationFailed,
    };
    KnowledgePublicationErrorV2::new(code, error.to_string())
}

#[cfg(test)]
#[path = "publication_tests.rs"]
mod tests;
