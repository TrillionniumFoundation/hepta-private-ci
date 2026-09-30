//! Stable operational contracts shared by admission, durable storage, recovery
//! and the Agentd product host.
//!
//! These values are deliberately data-only. They do not mint authority and
//! cannot bypass the durable owner, trust registry, source owner or recovery
//! protocol. Product code uses them to preserve one vocabulary across every
//! layer instead of collapsing failures into strings or rebuilding fence state
//! independently in several wrappers.

use std::future::Future;
use std::pin::Pin;

use codex_hepta_types::Digest32;

use crate::coordinator::CompactionCoordinatorErrorV2;
use crate::durable::DurableCompactionError;

/// Stable externally actionable error families for compact.engine.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum CompactionErrorClassV1 {
    InvalidInput,
    TrustRejected,
    LeaseConflict,
    CapacityExceeded,
    CommitOutcomeUnknown,
    RecoveryRequired,
    StorageCorrupt,
    TerminalFailure,
}

/// The recovery action paired with a stable error family.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum CompactionRecoveryDirectiveV1 {
    DoNotRetry,
    AwaitManifestOrOperator,
    ReacquireOwner,
    ApplyBackpressureOrGenerationHandoff,
    QueryOriginalOperation,
    RunReconciler,
    StopWritesAndQuarantine,
    ReturnStoredTerminal,
}

/// Preserve machine-readable failure semantics through product adapters.
pub trait CompactionErrorSemanticsV1 {
    fn error_class(&self) -> CompactionErrorClassV1;
    fn recovery_directive(&self) -> CompactionRecoveryDirectiveV1;
}

impl CompactionErrorSemanticsV1 for DurableCompactionError {
    fn error_class(&self) -> CompactionErrorClassV1 {
        match self {
            Self::Invalid(_) => CompactionErrorClassV1::InvalidInput,
            Self::Conflict(_) => CompactionErrorClassV1::LeaseConflict,
            Self::Corrupt(_) => CompactionErrorClassV1::StorageCorrupt,
            Self::Capacity(_) => CompactionErrorClassV1::CapacityExceeded,
            // A transport/driver failure after BEGIN or COMMIT cannot safely be
            // interpreted as not-started. Recovery must query the original
            // durable operation identity before any retry.
            Self::Sql(_) => CompactionErrorClassV1::CommitOutcomeUnknown,
        }
    }

    fn recovery_directive(&self) -> CompactionRecoveryDirectiveV1 {
        match self.error_class() {
            CompactionErrorClassV1::InvalidInput => {
                CompactionRecoveryDirectiveV1::DoNotRetry
            }
            CompactionErrorClassV1::LeaseConflict => {
                CompactionRecoveryDirectiveV1::ReacquireOwner
            }
            CompactionErrorClassV1::CapacityExceeded => {
                CompactionRecoveryDirectiveV1::ApplyBackpressureOrGenerationHandoff
            }
            CompactionErrorClassV1::CommitOutcomeUnknown => {
                CompactionRecoveryDirectiveV1::QueryOriginalOperation
            }
            CompactionErrorClassV1::StorageCorrupt => {
                CompactionRecoveryDirectiveV1::StopWritesAndQuarantine
            }
            CompactionErrorClassV1::TrustRejected => {
                CompactionRecoveryDirectiveV1::AwaitManifestOrOperator
            }
            CompactionErrorClassV1::RecoveryRequired => {
                CompactionRecoveryDirectiveV1::RunReconciler
            }
            CompactionErrorClassV1::TerminalFailure => {
                CompactionRecoveryDirectiveV1::ReturnStoredTerminal
            }
        }
    }
}

impl CompactionErrorSemanticsV1 for CompactionCoordinatorErrorV2 {
    fn error_class(&self) -> CompactionErrorClassV1 {
        match self {
            Self::Durable(error) => error.error_class(),
            Self::Admission(_) => CompactionErrorClassV1::TrustRejected,
            Self::Invalid(_) => CompactionErrorClassV1::InvalidInput,
            Self::Corrupt(_) => CompactionErrorClassV1::StorageCorrupt,
        }
    }

    fn recovery_directive(&self) -> CompactionRecoveryDirectiveV1 {
        match self {
            Self::Durable(error) => error.recovery_directive(),
            Self::Admission(_) => CompactionRecoveryDirectiveV1::AwaitManifestOrOperator,
            Self::Invalid(_) => CompactionRecoveryDirectiveV1::DoNotRetry,
            Self::Corrupt(_) => CompactionRecoveryDirectiveV1::StopWritesAndQuarantine,
        }
    }
}

/// One complete fence snapshot passed to every durable mutation.
///
/// `execution_now_unix_seconds` is the current execution time. Historical
/// acceptance/event timestamps never substitute for it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MutationFenceContextV1 {
    owner_id: String,
    root_key_digest: Digest32,
    manifest_digest: Digest32,
    lease_token_digest: Digest32,
    lease_epoch: u64,
    execution_now_unix_seconds: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MutationFenceContextErrorV1 {
    #[error("mutation fence owner id must contain 1..=128 bytes")]
    InvalidOwner,
    #[error("mutation fence lease epoch must be non-zero")]
    InvalidLeaseEpoch,
}

impl MutationFenceContextV1 {
    pub fn new(
        owner_id: impl Into<String>,
        root_key_digest: Digest32,
        manifest_digest: Digest32,
        lease_token_digest: Digest32,
        lease_epoch: u64,
        execution_now_unix_seconds: u64,
    ) -> Result<Self, MutationFenceContextErrorV1> {
        let owner_id = owner_id.into();
        if owner_id.trim().is_empty() || owner_id.len() > 128 {
            return Err(MutationFenceContextErrorV1::InvalidOwner);
        }
        if lease_epoch == 0 {
            return Err(MutationFenceContextErrorV1::InvalidLeaseEpoch);
        }
        Ok(Self {
            owner_id,
            root_key_digest,
            manifest_digest,
            lease_token_digest,
            lease_epoch,
            execution_now_unix_seconds,
        })
    }

    #[must_use]
    pub fn owner_id(&self) -> &str {
        &self.owner_id
    }

    #[must_use]
    pub const fn root_key_digest(&self) -> Digest32 {
        self.root_key_digest
    }

    #[must_use]
    pub const fn manifest_digest(&self) -> Digest32 {
        self.manifest_digest
    }

    #[must_use]
    pub const fn lease_token_digest(&self) -> Digest32 {
        self.lease_token_digest
    }

    #[must_use]
    pub const fn lease_epoch(&self) -> u64 {
        self.lease_epoch
    }

    #[must_use]
    pub const fn execution_now_unix_seconds(&self) -> u64 {
        self.execution_now_unix_seconds
    }
}

pub const MAX_COMPACTION_SEMANTIC_PAYLOAD_BYTES_V2: usize = 64 * 1024 * 1024;
pub const MAX_COMPACTION_SOURCE_METADATA_BYTES_V2: usize = 128 * 1024 * 1024;
pub const MAX_COMPACTION_RECEIPTS_AND_PROOF_BYTES_V2: usize = 128 * 1024 * 1024;
pub const MAX_COMPACTION_ARCHIVE_BYTES_V2: usize = 64 * 1024 * 1024;
pub const MAX_COMPACTION_DURABLE_TRANSACTION_BYTES_V2: usize = 320 * 1024 * 1024;
pub const MAX_COMPACTION_TRANSIENT_MEMORY_BYTES_V2: usize = 448 * 1024 * 1024;

/// Separate capacity domains. Passing the pure kernel payload ceiling does not
/// imply that metadata, proof/archive encoding, one SQLite transaction or peak
/// process memory is within its own limit.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CompactionCapacityUsageV2 {
    pub semantic_payload_bytes: usize,
    pub source_metadata_bytes: usize,
    pub receipts_and_proof_bytes: usize,
    pub archive_bytes: usize,
    pub durable_transaction_bytes: usize,
    pub transient_memory_bytes: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum CompactionCapacityViolationV2 {
    #[error("semantic payload capacity exceeded")]
    SemanticPayload,
    #[error("source metadata capacity exceeded")]
    SourceMetadata,
    #[error("receipt/proof capacity exceeded")]
    ReceiptsAndProof,
    #[error("archive capacity exceeded")]
    Archive,
    #[error("durable transaction capacity exceeded")]
    DurableTransaction,
    #[error("transient memory capacity exceeded")]
    TransientMemory,
}

impl CompactionCapacityUsageV2 {
    pub fn validate(self) -> Result<(), CompactionCapacityViolationV2> {
        if self.semantic_payload_bytes > MAX_COMPACTION_SEMANTIC_PAYLOAD_BYTES_V2 {
            return Err(CompactionCapacityViolationV2::SemanticPayload);
        }
        if self.source_metadata_bytes > MAX_COMPACTION_SOURCE_METADATA_BYTES_V2 {
            return Err(CompactionCapacityViolationV2::SourceMetadata);
        }
        if self.receipts_and_proof_bytes > MAX_COMPACTION_RECEIPTS_AND_PROOF_BYTES_V2 {
            return Err(CompactionCapacityViolationV2::ReceiptsAndProof);
        }
        if self.archive_bytes > MAX_COMPACTION_ARCHIVE_BYTES_V2 {
            return Err(CompactionCapacityViolationV2::Archive);
        }
        if self.durable_transaction_bytes > MAX_COMPACTION_DURABLE_TRANSACTION_BYTES_V2 {
            return Err(CompactionCapacityViolationV2::DurableTransaction);
        }
        if self.transient_memory_bytes > MAX_COMPACTION_TRANSIENT_MEMORY_BYTES_V2 {
            return Err(CompactionCapacityViolationV2::TransientMemory);
        }
        Ok(())
    }
}

/// End-to-end phase timings; each value is measured, never inferred from a
/// fixed hash count or from payload length.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CompactionPhaseTimingsV1 {
    pub authority_wait_micros: u64,
    pub trust_verification_micros: u64,
    pub candidate_build_micros: u64,
    pub proof_verification_micros: u64,
    pub archive_encode_micros: u64,
    pub admission_reservation_micros: u64,
    pub artifact_transaction_micros: u64,
    pub finalization_micros: u64,
    pub restart_reconciliation_micros: u64,
    pub reopen_micros: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CompactionResourceMeasurementsV1 {
    pub mutex_wait_micros: u64,
    pub database_lock_wait_micros: u64,
    pub bytes_hashed: u64,
    pub clone_copy_bytes: u64,
    pub archive_bytes: u64,
    pub database_growth_bytes: u64,
    pub wal_growth_bytes: u64,
    pub peak_resident_bytes: u64,
    pub cpu_micros: u64,
    pub retry_recovery_latency_micros: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CompactionOperationMeasurementsV1 {
    pub phases: CompactionPhaseTimingsV1,
    pub resources: CompactionResourceMeasurementsV1,
}

/// Exact current-source identity that must be re-admitted immediately before a
/// recovered checkpoint payload is returned to a product caller.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CurrentSourceUseBindingV1 {
    pub owner_id: String,
    pub owner_generation: u64,
    pub source_snapshot_digest: Digest32,
    pub source_memory_snapshot_digest: Digest32,
    pub scope_id: String,
    pub purpose_id: String,
    pub checkpoint_digest: Digest32,
    pub payload_digest: Digest32,
}

/// Source-owner response. Caches may retain this only for the exact immutable
/// owner cut and validation revision represented here; revocation is never
/// skipped by cache freshness alone.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CurrentSourceUseReceiptV1 {
    pub owner_cut_digest: Digest32,
    pub deletion_correction_frontier_digest: Digest32,
    pub retention_revocation_state_digest: Digest32,
    pub validation_revision: u64,
    pub validated_at_unix_seconds: u64,
    pub expires_at_unix_seconds: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum CurrentSourceUseErrorV1 {
    #[error("current source-use binding is invalid")]
    InvalidBinding,
    #[error("current source-use validator is unavailable")]
    Unavailable,
    #[error("current source owner rejected the checkpoint")]
    Rejected,
    #[error("current source-use receipt is stale or bound to another owner cut")]
    Stale,
}

pub type CurrentSourceUseFuture<'a> = Pin<
    Box<dyn Future<Output = Result<CurrentSourceUseReceiptV1, CurrentSourceUseErrorV1>> + Send + 'a>,
>;

/// Product-supplied source-owner verifier. compact.engine never fabricates a
/// permissive implementation.
pub trait CurrentSourceUseValidatorV1: Send + Sync {
    fn validate_current_use<'a>(
        &'a self,
        binding: &'a CurrentSourceUseBindingV1,
        now_unix_seconds: u64,
    ) -> CurrentSourceUseFuture<'a>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capacity_domains_reject_each_limit_plus_one() {
        let base = CompactionCapacityUsageV2 {
            semantic_payload_bytes: MAX_COMPACTION_SEMANTIC_PAYLOAD_BYTES_V2,
            source_metadata_bytes: MAX_COMPACTION_SOURCE_METADATA_BYTES_V2,
            receipts_and_proof_bytes: MAX_COMPACTION_RECEIPTS_AND_PROOF_BYTES_V2,
            archive_bytes: MAX_COMPACTION_ARCHIVE_BYTES_V2,
            durable_transaction_bytes: MAX_COMPACTION_DURABLE_TRANSACTION_BYTES_V2,
            transient_memory_bytes: MAX_COMPACTION_TRANSIENT_MEMORY_BYTES_V2,
        };
        assert_eq!(base.validate(), Ok(()));

        let mut over = base;
        over.semantic_payload_bytes += 1;
        assert_eq!(
            over.validate(),
            Err(CompactionCapacityViolationV2::SemanticPayload)
        );

        let mut over = base;
        over.source_metadata_bytes += 1;
        assert_eq!(
            over.validate(),
            Err(CompactionCapacityViolationV2::SourceMetadata)
        );

        let mut over = base;
        over.receipts_and_proof_bytes += 1;
        assert_eq!(
            over.validate(),
            Err(CompactionCapacityViolationV2::ReceiptsAndProof)
        );

        let mut over = base;
        over.archive_bytes += 1;
        assert_eq!(over.validate(), Err(CompactionCapacityViolationV2::Archive));

        let mut over = base;
        over.durable_transaction_bytes += 1;
        assert_eq!(
            over.validate(),
            Err(CompactionCapacityViolationV2::DurableTransaction)
        );

        let mut over = base;
        over.transient_memory_bytes += 1;
        assert_eq!(
            over.validate(),
            Err(CompactionCapacityViolationV2::TransientMemory)
        );
    }

    #[test]
    fn mutation_fence_rejects_empty_owner_and_zero_epoch() {
        let digest = Digest32::of_bytes(b"fence");
        assert_eq!(
            MutationFenceContextV1::new("", digest, digest, digest, 1, 0),
            Err(MutationFenceContextErrorV1::InvalidOwner)
        );
        assert_eq!(
            MutationFenceContextV1::new("owner", digest, digest, digest, 0, 0),
            Err(MutationFenceContextErrorV1::InvalidLeaseEpoch)
        );
    }
}
