use std::fmt;

/// Stable error identities; messages are fixed and never reflect backend input.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
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
    pub fn as_str(self) -> &'static str {
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

    pub fn message(self) -> &'static str {
        match self {
            Self::InvalidInput => "The request or backend response is invalid.",
            Self::NotConnected => "An authenticated connection is required.",
            Self::AlreadyConnected => "The client is already connected.",
            Self::SessionExpired => "The session expired; establish a new authenticated session.",
            Self::SessionRevoked => {
                "The session was revoked; establish a new authenticated session."
            }
            Self::SessionIdentityChanged => "The authenticated identity changed; reconnect.",
            Self::PermissionDenied => "The session does not permit this request.",
            Self::StalePermissionRevision => "Session permissions changed; reconnect.",
            Self::ProtocolMismatch => "The client and backend protocols do not match.",
            Self::StaleGeneration | Self::StaleRevision => {
                "The displayed context changed; refresh and confirm again."
            }
            Self::SnapshotDrift => "The backend view is inconsistent; preserve recovery records.",
            Self::PendingLimit => "Pending capacity is exhausted; recover existing operations.",
            Self::OperationConflict => "The operation identity conflicts with retained data.",
            Self::BackendRejected => "The backend rejected this request.",
            Self::AckMismatch => "The backend observation does not match the retained operation.",
            Self::AmbiguousSubmission => {
                "Acceptance is uncertain; recover the original operation without resubmitting."
            }
            Self::Aborted => "The attempt was cancelled; preserve unresolved operation identities.",
            Self::Storage => {
                "Local recovery storage needs attention; preserve records and recover unresolved operations."
            }
            Self::Transport => {
                "Backend communication failed; refresh or recover unresolved operations."
            }
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ControlError {
    pub code: ErrorCode,
    pub retryable: bool,
    pub request_dispatched: Option<bool>,
    pub details: serde_json::Map<String, serde_json::Value>,
}

impl ControlError {
    pub fn new(code: ErrorCode) -> Self {
        Self {
            code,
            retryable: false,
            request_dispatched: None,
            details: serde_json::Map::new(),
        }
    }

    pub fn invalid() -> Self {
        Self::new(ErrorCode::InvalidInput)
    }

    pub fn unsent(code: ErrorCode) -> Self {
        Self::new(code).with_dispatch(false)
    }

    pub fn retryable(mut self, retryable: bool) -> Self {
        self.retryable = retryable;
        self
    }

    pub fn with_dispatch(mut self, request_dispatched: bool) -> Self {
        self.request_dispatched = Some(request_dispatched);
        self
    }

    /// Diagnostic data is never rendered in operator messages or live regions.
    pub fn detail(mut self, key: impl Into<String>, value: serde_json::Value) -> Self {
        self.details.insert(key.into(), value);
        self
    }

    /// Only definite pre-dispatch failure or an explicit backend rejection retires a reservation.
    pub fn definitely_not_accepted(&self) -> bool {
        self.request_dispatched == Some(false)
            || matches!(
                self.code,
                ErrorCode::BackendRejected
                    | ErrorCode::OperationConflict
                    | ErrorCode::StaleRevision
                    | ErrorCode::PermissionDenied
                    | ErrorCode::SessionExpired
                    | ErrorCode::SessionRevoked
                    | ErrorCode::ProtocolMismatch
            )
    }
}

impl fmt::Display for ControlError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code.as_str(), self.code.message())
    }
}

impl std::error::Error for ControlError {}
