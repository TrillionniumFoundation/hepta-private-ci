use std::fmt;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ErrorCode {
    InvalidInput,
    NotConnected,
    AlreadyConnected,
    SessionExpired,
    SessionRevoked,
    SessionIdentityChanged,
    PermissionDenied,
    StalePermissionRevision,
    ProtocolMismatch,
    StaleGeneration,
    StaleRevision,
    SnapshotDrift,
    PendingLimit,
    OperationConflict,
    BackendRejected,
    AckMismatch,
    AmbiguousSubmission,
    Aborted,
    Storage,
    Transport,
}

impl ErrorCode {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InvalidInput => "UI_CONTROL_INVALID_INPUT",
            Self::NotConnected => "UI_CONTROL_NOT_CONNECTED",
            Self::AlreadyConnected => "UI_CONTROL_ALREADY_CONNECTED",
            Self::SessionExpired => "UI_CONTROL_SESSION_EXPIRED",
            Self::SessionRevoked => "UI_CONTROL_SESSION_REVOKED",
            Self::SessionIdentityChanged => "UI_CONTROL_SESSION_IDENTITY_CHANGED",
            Self::PermissionDenied => "UI_CONTROL_PERMISSION_DENIED",
            Self::StalePermissionRevision => "UI_CONTROL_STALE_PERMISSION_REVISION",
            Self::ProtocolMismatch => "UI_CONTROL_PROTOCOL_MISMATCH",
            Self::StaleGeneration => "UI_CONTROL_STALE_GENERATION",
            Self::StaleRevision => "UI_CONTROL_STALE_REVISION",
            Self::SnapshotDrift => "UI_CONTROL_SNAPSHOT_DRIFT",
            Self::PendingLimit => "UI_CONTROL_PENDING_LIMIT",
            Self::OperationConflict => "UI_CONTROL_OPERATION_CONFLICT",
            Self::BackendRejected => "UI_CONTROL_BACKEND_REJECTED",
            Self::AckMismatch => "UI_CONTROL_ACK_MISMATCH",
            Self::AmbiguousSubmission => "UI_CONTROL_AMBIGUOUS_SUBMISSION",
            Self::Aborted => "UI_CONTROL_ABORTED",
            Self::Storage => "UI_CONTROL_STORAGE",
            Self::Transport => "UI_CONTROL_TRANSPORT",
        }
    }
}

impl fmt::Display for ErrorCode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

/// A safe error: untrusted server text and operation reasons are never displayed.
#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
#[error("{code}")]
pub struct ControlError {
    pub code: ErrorCode,
    pub request_dispatched: Option<bool>,
}

impl ControlError {
    pub const fn new(code: ErrorCode) -> Self {
        Self {
            code,
            request_dispatched: None,
        }
    }

    pub const fn not_dispatched(mut self) -> Self {
        self.request_dispatched = Some(false);
        self
    }
}

pub type Result<T> = std::result::Result<T, ControlError>;

pub(crate) fn invalid() -> ControlError {
    ControlError::new(ErrorCode::InvalidInput)
}
