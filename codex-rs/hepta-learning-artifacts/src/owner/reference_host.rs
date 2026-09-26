use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerDurabilityV1;
use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactPublicationError;
use crate::ArtifactStorageError;
use crate::DatasetWithdrawalSnapshotReceiptV1;
use crate::DirectoryDurabilityError;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::LearningArtifactOwnerServiceError;

use super::capability_validation::LearningArtifactHostAccessError;
use super::capability_validation::LearningArtifactHostAccessPolicyV1;
use super::capability_validation::LearningArtifactHostAccessVerifierV1;
use super::capability_validation::LearningArtifactHostActionV1;
use super::capability_validation::SignedLearningArtifactHostCommandV1;
use super::capability_validation::VerifiedLearningArtifactHostCommandV1;
use super::reconciliation::LearningArtifactAuditError;
use super::reconciliation::LearningArtifactAuditJournalV1;
use super::reconciliation::LearningArtifactAuditOutcomeV1;
use super::reconciliation::LearningArtifactHostHealthV1;
use super::reconciliation::LearningArtifactHostLifecycleV1;
use super::reconciliation::LearningArtifactHostMetricsV1;

#[derive(Clone, Debug)]
pub struct LearningArtifactReferenceHostConfigV1 {
    pub service: LearningArtifactOwnerServiceConfigV1,
    pub access_policy: LearningArtifactHostAccessPolicyV1,
    pub maximum_supported_control_schema_version: u32,
}

pub struct LearningArtifactReferenceHostV1 {
    pub(super) root: PathBuf,
    pub(super) control_root: PathBuf,
    pub(super) storage_binding: Digest32,
    pub(super) owner_trust: ArtifactOwnerTrustV1,
    pub(super) service: LearningArtifactOwnerService,
    pub(super) access: LearningArtifactHostAccessVerifierV1,
    pub(super) durability: Arc<dyn ArtifactOwnerDurabilityV1>,
    pub(super) audit: LearningArtifactAuditJournalV1,
    pub(super) lifecycle: LearningArtifactHostLifecycleV1,
    pub(super) metrics: LearningArtifactHostMetricsV1,
    pub(super) schema_version: u32,
    pub(super) maximum_supported_control_schema_version: u32,
    pub(super) withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1,
}

impl fmt::Debug for LearningArtifactReferenceHostV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LearningArtifactReferenceHostV1")
            .field("root", &self.root)
            .field("control_root", &self.control_root)
            .field("storage_binding", &self.storage_binding)
            .field("service", &self.service)
            .field("access_policy_digest", &self.access.policy_digest())
            .field("audit", &self.audit)
            .field("lifecycle", &self.lifecycle)
            .field("metrics", &self.metrics)
            .field("schema_version", &self.schema_version)
            .field("withdrawal_receipt", &self.withdrawal_receipt)
            .finish_non_exhaustive()
    }
}

impl LearningArtifactReferenceHostV1 {
    #[must_use]
    pub fn health(&self) -> LearningArtifactHostHealthV1 {
        let lifecycle = self.lifecycle.clone();
        LearningArtifactHostHealthV1 {
            ready: lifecycle == LearningArtifactHostLifecycleV1::Ready,
            live: lifecycle != LearningArtifactHostLifecycleV1::Faulted,
            lifecycle,
            schema_version: self.schema_version,
            registry_head_digest: self.service.registry().snapshot().head_digest,
            withdrawal_head_digest: self.service.withdrawal_registry().head_digest(),
            access_policy_digest: self.access.policy_digest(),
            audit_head_digest: self.audit.head_digest(),
            audit_events: self.audit.len(),
            metrics: self.metrics,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[must_use]
    pub fn access_policy(&self) -> &LearningArtifactHostAccessPolicyV1 {
        self.access.policy()
    }

    #[must_use]
    pub fn root(&self) -> &std::path::Path {
        &self.root
    }

    #[must_use]
    pub fn control_root(&self) -> &std::path::Path {
        &self.control_root
    }

    pub(super) fn authorize(
        &mut self,
        command: &SignedLearningArtifactHostCommandV1,
        action: LearningArtifactHostActionV1,
        request_digest: Digest32,
        now: u64,
    ) -> Result<VerifiedLearningArtifactHostCommandV1, LearningArtifactReferenceHostError> {
        let verified = match self.access.verify(command, action, request_digest, now) {
            Ok(verified) => verified,
            Err(error) => {
                self.metrics.authentication_rejected =
                    self.metrics.authentication_rejected.saturating_add(1);
                return Err(error.into());
            }
        };
        match self.audit.require_fresh(&verified) {
            Ok(()) => Ok(verified),
            Err(error @ (LearningArtifactAuditError::Replay
            | LearningArtifactAuditError::ReplayConflict)) => {
                self.metrics.replay_rejected = self.metrics.replay_rejected.saturating_add(1);
                Err(error.into())
            }
            Err(error) => Err(error.into()),
        }
    }

    pub(super) fn record_applied(
        &mut self,
        verified: &VerifiedLearningArtifactHostCommandV1,
        result_digest: Digest32,
        now: u64,
    ) -> Result<(), LearningArtifactReferenceHostError> {
        self.record_outcome(
            verified,
            LearningArtifactAuditOutcomeV1::Applied,
            result_digest,
            now,
        )?;
        self.metrics.commands_applied = self.metrics.commands_applied.saturating_add(1);
        Ok(())
    }

    pub(super) fn record_rejected(
        &mut self,
        verified: &VerifiedLearningArtifactHostCommandV1,
        result_digest: Digest32,
        now: u64,
    ) -> Result<(), LearningArtifactReferenceHostError> {
        self.record_outcome(
            verified,
            LearningArtifactAuditOutcomeV1::Rejected,
            result_digest,
            now,
        )?;
        self.metrics.commands_rejected = self.metrics.commands_rejected.saturating_add(1);
        Ok(())
    }

    pub(super) fn record_indeterminate(
        &mut self,
        verified: &VerifiedLearningArtifactHostCommandV1,
        result_digest: Digest32,
        now: u64,
    ) -> Result<(), LearningArtifactReferenceHostError> {
        self.record_outcome(
            verified,
            LearningArtifactAuditOutcomeV1::Indeterminate,
            result_digest,
            now,
        )?;
        self.metrics.durability_indeterminate =
            self.metrics.durability_indeterminate.saturating_add(1);
        Ok(())
    }

    fn record_outcome(
        &mut self,
        verified: &VerifiedLearningArtifactHostCommandV1,
        outcome: LearningArtifactAuditOutcomeV1,
        result_digest: Digest32,
        now: u64,
    ) -> Result<(), LearningArtifactReferenceHostError> {
        if let Err(error) = self.audit.record(
            &self.control_root,
            &self.durability,
            verified,
            outcome,
            result_digest,
            now,
        ) {
            self.lifecycle = LearningArtifactHostLifecycleV1::Faulted;
            return Err(error.into());
        }
        self.metrics.audit_events = self.metrics.audit_events.saturating_add(1);
        Ok(())
    }

    pub(super) fn require_ready(&self) -> Result<(), LearningArtifactReferenceHostError> {
        match &self.lifecycle {
            LearningArtifactHostLifecycleV1::Ready => Ok(()),
            LearningArtifactHostLifecycleV1::Recovering(operation) => Err(
                LearningArtifactReferenceHostError::RecoveryRequired(operation.clone()),
            ),
            LearningArtifactHostLifecycleV1::Draining => {
                Err(LearningArtifactReferenceHostError::Draining)
            }
            LearningArtifactHostLifecycleV1::Faulted => {
                Err(LearningArtifactReferenceHostError::Faulted)
            }
        }
    }

    pub(super) fn require_publishable(
        &self,
        operation_id: &StableId,
    ) -> Result<(), LearningArtifactReferenceHostError> {
        match &self.lifecycle {
            LearningArtifactHostLifecycleV1::Ready => Ok(()),
            LearningArtifactHostLifecycleV1::Recovering(expected) if expected == operation_id => {
                Ok(())
            }
            LearningArtifactHostLifecycleV1::Recovering(expected) => Err(
                LearningArtifactReferenceHostError::RecoveryRequired(expected.clone()),
            ),
            LearningArtifactHostLifecycleV1::Draining => {
                Err(LearningArtifactReferenceHostError::Draining)
            }
            LearningArtifactHostLifecycleV1::Faulted => {
                Err(LearningArtifactReferenceHostError::Faulted)
            }
        }
    }

    pub(super) fn refresh_recovery_state(&mut self) {
        if let Some(operation) = self.service.recovery_required() {
            self.lifecycle = LearningArtifactHostLifecycleV1::Recovering(operation.clone());
        } else if matches!(
            self.lifecycle,
            LearningArtifactHostLifecycleV1::Recovering(_)
        ) {
            self.lifecycle = LearningArtifactHostLifecycleV1::Ready;
            self.metrics.recovery_completions =
                self.metrics.recovery_completions.saturating_add(1);
        }
    }
}

#[derive(Debug)]
pub enum LearningArtifactReferenceHostError {
    Access(LearningArtifactHostAccessError),
    Audit(LearningArtifactAuditError),
    Service(LearningArtifactOwnerServiceError),
    Owner(ArtifactOwnerHostError),
    Publication(ArtifactPublicationError),
    Storage(ArtifactStorageError),
    Durability(DirectoryDurabilityError),
    Io(std::io::Error),
    InvalidRoot,
    InsecureRoot,
    UnsupportedTarget,
    PolicyAnchorConflict,
    WithdrawalAnchorConflict,
    SchemaAnchorConflict,
    RecoveryRequired(StableId),
    Draining,
    Faulted,
    PolicyGeneration,
    SchemaGeneration,
    MigrationContext,
    BackupContext,
}

impl fmt::Display for LearningArtifactReferenceHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearningArtifactReferenceHostError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Access(error) => Some(error),
            Self::Audit(error) => Some(error),
            Self::Service(error) => Some(error),
            Self::Owner(error) => Some(error),
            Self::Publication(error) => Some(error),
            Self::Storage(error) => Some(error),
            Self::Durability(error) => Some(error),
            Self::Io(error) => Some(error),
            Self::InvalidRoot
            | Self::InsecureRoot
            | Self::UnsupportedTarget
            | Self::PolicyAnchorConflict
            | Self::WithdrawalAnchorConflict
            | Self::SchemaAnchorConflict
            | Self::RecoveryRequired(_)
            | Self::Draining
            | Self::Faulted
            | Self::PolicyGeneration
            | Self::SchemaGeneration
            | Self::MigrationContext
            | Self::BackupContext => None,
        }
    }
}

impl From<LearningArtifactHostAccessError> for LearningArtifactReferenceHostError {
    fn from(value: LearningArtifactHostAccessError) -> Self {
        Self::Access(value)
    }
}

impl From<LearningArtifactAuditError> for LearningArtifactReferenceHostError {
    fn from(value: LearningArtifactAuditError) -> Self {
        Self::Audit(value)
    }
}

impl From<LearningArtifactOwnerServiceError> for LearningArtifactReferenceHostError {
    fn from(value: LearningArtifactOwnerServiceError) -> Self {
        Self::Service(value)
    }
}

impl From<ArtifactOwnerHostError> for LearningArtifactReferenceHostError {
    fn from(value: ArtifactOwnerHostError) -> Self {
        Self::Owner(value)
    }
}

impl From<ArtifactPublicationError> for LearningArtifactReferenceHostError {
    fn from(value: ArtifactPublicationError) -> Self {
        Self::Publication(value)
    }
}

impl From<ArtifactStorageError> for LearningArtifactReferenceHostError {
    fn from(value: ArtifactStorageError) -> Self {
        Self::Storage(value)
    }
}

impl From<DirectoryDurabilityError> for LearningArtifactReferenceHostError {
    fn from(value: DirectoryDurabilityError) -> Self {
        Self::Durability(value)
    }
}

impl From<std::io::Error> for LearningArtifactReferenceHostError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value)
    }
}

pub(super) fn error_digest(error: &impl fmt::Debug) -> Digest32 {
    Digest32::of_bytes(format!("{error:?}").as_bytes())
}
