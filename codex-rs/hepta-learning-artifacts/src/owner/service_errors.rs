#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerRetryClassV1 {
    Never,
    SameOperationReconciliation,
    RefreshAuthority,
    AfterCapacityRelief,
    HostPolicy,
}

#[derive(Debug)]
pub enum LearningArtifactOwnerServiceError {
    Host(ArtifactOwnerHostError),
    Publication(ArtifactPublicationError),
    ControlIo(std::io::Error),
    InvalidConfiguration,
    WithdrawalScopeConflict,
    WithdrawalFrontierTooOld,
    WithdrawalFrontierConflict,
    WithdrawalDurabilityUnknown,
    RecoveryConflict,
    RecoveryRequired(StableId),
    RequestIdentityConflict,
    RequestIdentityDurabilityUnknown(StableId),
    RequestMismatch,
    StaleOwnerContext,
    CapacityExceeded,
    CheckpointShape,
    CheckpointMismatch,
    UnexpectedPhase,
    Draining,
}

impl LearningArtifactOwnerServiceError {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Host(_) => "artifact_owner_host_error",
            Self::Publication(_) => "artifact_publication_error",
            Self::ControlIo(_) => "artifact_control_io",
            Self::InvalidConfiguration => "artifact_invalid_configuration",
            Self::WithdrawalScopeConflict => "artifact_withdrawal_scope_conflict",
            Self::WithdrawalFrontierTooOld => "artifact_withdrawal_frontier_too_old",
            Self::WithdrawalFrontierConflict => "artifact_withdrawal_frontier_conflict",
            Self::WithdrawalDurabilityUnknown => "artifact_withdrawal_durability_unknown",
            Self::RecoveryConflict => "artifact_recovery_conflict",
            Self::RecoveryRequired(_) => "artifact_recovery_required",
            Self::RequestIdentityConflict => "artifact_request_identity_conflict",
            Self::RequestIdentityDurabilityUnknown(_) => {
                "artifact_request_identity_durability_unknown"
            }
            Self::RequestMismatch => "artifact_request_mismatch",
            Self::StaleOwnerContext => "artifact_stale_owner_context",
            Self::CapacityExceeded => "artifact_capacity_exceeded",
            Self::CheckpointShape => "artifact_checkpoint_shape",
            Self::CheckpointMismatch => "artifact_checkpoint_mismatch",
            Self::UnexpectedPhase => "artifact_unexpected_phase",
            Self::Draining => "artifact_draining",
        }
    }

    #[must_use]
    pub const fn retry_class(&self) -> ArtifactOwnerRetryClassV1 {
        match self {
            Self::RecoveryRequired(_)
            | Self::RequestIdentityDurabilityUnknown(_)
            | Self::WithdrawalDurabilityUnknown => {
                ArtifactOwnerRetryClassV1::SameOperationReconciliation
            }
            Self::WithdrawalScopeConflict
            | Self::WithdrawalFrontierTooOld
            | Self::WithdrawalFrontierConflict
            | Self::StaleOwnerContext => ArtifactOwnerRetryClassV1::RefreshAuthority,
            Self::CapacityExceeded => ArtifactOwnerRetryClassV1::AfterCapacityRelief,
            Self::Host(_) | Self::Publication(_) | Self::ControlIo(_) => {
                ArtifactOwnerRetryClassV1::HostPolicy
            }
            Self::InvalidConfiguration
            | Self::RecoveryConflict
            | Self::RequestIdentityConflict
            | Self::RequestMismatch
            | Self::CheckpointShape
            | Self::CheckpointMismatch
            | Self::UnexpectedPhase
            | Self::Draining => ArtifactOwnerRetryClassV1::Never,
        }
    }
}

impl fmt::Display for LearningArtifactOwnerServiceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {self:?}", self.code())
    }
}

impl StdError for LearningArtifactOwnerServiceError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Host(error) => Some(error),
            Self::Publication(error) => Some(error),
            Self::ControlIo(error) => Some(error),
            _ => None,
        }
    }
}

impl From<ArtifactOwnerHostError> for LearningArtifactOwnerServiceError {
    fn from(value: ArtifactOwnerHostError) -> Self {
        Self::Host(value)
    }
}

impl From<ArtifactPublicationError> for LearningArtifactOwnerServiceError {
    fn from(value: ArtifactPublicationError) -> Self {
        Self::Publication(value)
    }
}
