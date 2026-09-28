//! Observation wrappers around the existing serialized durable owner protocol.
//! Errors never become successful observations, and metrics cannot clear fences.

use std::time::Instant;

use super::ArtifactOwnerDiagnosticsV1;
use super::LearningArtifactOwnerService;
use super::LearningArtifactOwnerServiceError;
use super::LearningArtifactPublishRequestV1;
use super::diagnostics::Phase;
use crate::ArtifactAdmissionError;
use crate::ArtifactClosureError;
use crate::ArtifactOwnerHostError;
use crate::ArtifactPublicationError;
use crate::ArtifactPublicationReceiptV1;
use crate::DatasetWithdrawalRegistry;

impl LearningArtifactOwnerService {
    /// Read process-local diagnostics without changing authority or durable state.
    #[must_use]
    pub fn diagnostics(&self) -> ArtifactOwnerDiagnosticsV1 {
        self.observations.snapshot(
            self.recovery_required.is_some(),
            self.withdrawal_persistence_uncertain,
            self.drain_persistence_uncertain,
            self.draining,
        )
    }

    /// Preserve exact historical replay and the existing reconciliation fence.
    /// All returned failures, including preflight refusals, are counted.
    pub fn publish(
        &mut self,
        request: LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        let started = Instant::now();
        let outcome = self.publish_recorded(request);
        self.observations.record(Phase::Publish, started, &outcome);
        if let Err(error) = &outcome {
            if matches!(error, LearningArtifactOwnerServiceError::RequestMismatch) {
                self.observations.identity_conflicts =
                    self.observations.identity_conflicts.saturating_add(1);
            }
            if error.is_withdrawal_block() {
                self.observations.withdrawal_blocked_publications =
                    self.observations.withdrawal_blocked_publications.saturating_add(1);
            }
        }
        self.observations.observe_state(
            self.recovery_required.is_some(),
            self.draining,
            self.withdrawal_persistence_uncertain,
        );
        outcome
    }

    /// Acknowledge stop only after the existing create-only control record and
    /// directory synchronizations succeed. A failed write keeps admission closed.
    pub fn begin_drain_durable(&mut self) -> Result<(), LearningArtifactOwnerServiceError> {
        let started = Instant::now();
        let outcome = self.begin_drain_recorded();
        self.observations.record(Phase::Drain, started, &outcome);
        self.observations.observe_state(
            self.recovery_required.is_some(),
            self.draining,
            self.withdrawal_persistence_uncertain,
        );
        outcome
    }

    /// Observe installation without weakening the durable floor's monotonicity
    /// or its unknown-outcome fence. The caller still authenticates the frontier.
    pub fn install_withdrawal_frontier(
        &mut self,
        next: DatasetWithdrawalRegistry,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        let started = Instant::now();
        let outcome = self.install_withdrawal_frontier_recorded(next);
        self.observations.record(Phase::Withdrawal, started, &outcome);
        if matches!(&outcome, Err(LearningArtifactOwnerServiceError::WithdrawalFrontierConflict)) {
            self.observations.withdrawal_conflicts =
                self.observations.withdrawal_conflicts.saturating_add(1);
        }
        self.observations.observe_state(
            self.recovery_required.is_some(),
            self.draining,
            self.withdrawal_persistence_uncertain,
        );
        outcome
    }
}

impl LearningArtifactOwnerServiceError {
    /// Stable coarse error codes; retain the typed underlying error for detail.
    /// No code is permission to retry an unknown effect as a new operation.
    #[must_use]
    pub fn code(&self) -> &'static str {
        match self {
            Self::Host(ArtifactOwnerHostError::WriterFenceBusy) => "artifact.owner_busy",
            Self::Host(ArtifactOwnerHostError::WriterLeaseContext) => "artifact.owner_context",
            Self::Host(_) => "artifact.owner_failure",
            Self::Publication(error) => match error {
                ArtifactPublicationError::Admission(admission) => match admission {
                    ArtifactAdmissionError::WithdrawalHeadChanged => "artifact.withdrawal_frontier",
                    ArtifactAdmissionError::WithdrawalScopeChanged
                    | ArtifactAdmissionError::WithdrawalScopeRequired => "artifact.withdrawal_scope",
                    ArtifactAdmissionError::Manifest(ArtifactClosureError::WithdrawnDataset) => {
                        "artifact.dataset_withdrawn"
                    }
                    _ => "artifact.admission_rejected",
                },
                _ => "artifact.publication_rejected",
            },
            Self::ControlIo(_) => "artifact.persistence_unknown",
            Self::InvalidConfiguration => "artifact.invalid_configuration",
            Self::WithdrawalFrontierConflict => "artifact.withdrawal_conflict",
            Self::WithdrawalDurabilityUnknown => "artifact.withdrawal_durability_unknown",
            Self::RecoveryConflict => "artifact.recovery_conflict",
            Self::RecoveryRequired(_) => "artifact.recovery_required",
            Self::RequestMismatch => "artifact.identity_conflict",
            Self::CheckpointShape => "artifact.checkpoint_shape",
            Self::CheckpointMismatch => "artifact.checkpoint_mismatch",
            Self::UnexpectedPhase => "artifact.unexpected_phase",
            Self::Draining => "artifact.draining",
        }
    }

    fn is_withdrawal_block(&self) -> bool {
        matches!(self,
            Self::WithdrawalDurabilityUnknown
            | Self::Publication(ArtifactPublicationError::Admission(
                ArtifactAdmissionError::WithdrawalHeadChanged
                | ArtifactAdmissionError::WithdrawalScopeChanged
                | ArtifactAdmissionError::WithdrawalScopeRequired
                | ArtifactAdmissionError::Manifest(ArtifactClosureError::WithdrawnDataset)
            ))
        )
    }
}
