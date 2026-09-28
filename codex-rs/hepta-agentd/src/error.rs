use std::error::Error as StdError;
use std::fmt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_automation::AutomationError;
use codex_hepta_cognitive_store::DurableCognitiveStoreError;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_memory::ProductionCognitiveMutationError;
use codex_hepta_memory::ProductionWriterError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompactEngineErrorCodeV1 {
    InvalidInput,
    AdmissionRejected,
    OwnerConflict,
    CapacityExceeded,
    CorruptState,
    StorageUnavailable,
    OutcomeIndeterminate,
}

impl fmt::Display for CompactEngineErrorCodeV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let value = match self {
            Self::InvalidInput => "invalid_input",
            Self::AdmissionRejected => "admission_rejected",
            Self::OwnerConflict => "owner_conflict",
            Self::CapacityExceeded => "capacity_exceeded",
            Self::CorruptState => "corrupt_state",
            Self::StorageUnavailable => "storage_unavailable",
            Self::OutcomeIndeterminate => "outcome_indeterminate",
        };
        formatter.write_str(value)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompactEngineRecoveryActionV1 {
    CorrectRequest,
    RetrySameOperation,
    Backpressure,
    ReopenOwner,
    ReconcileSameOperation,
    StopWrites,
}

impl fmt::Display for CompactEngineRecoveryActionV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let value = match self {
            Self::CorrectRequest => "correct_request",
            Self::RetrySameOperation => "retry_same_operation",
            Self::Backpressure => "backpressure",
            Self::ReopenOwner => "reopen_owner",
            Self::ReconcileSameOperation => "reconcile_same_operation",
            Self::StopWrites => "stop_writes",
        };
        formatter.write_str(value)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompactEngineCommitStateV1 {
    NotCommitted,
    Unknown,
}

impl fmt::Display for CompactEngineCommitStateV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotCommitted => formatter.write_str("not_committed"),
            Self::Unknown => formatter.write_str("unknown"),
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum AgentdError {
    #[error("invalid agentd configuration: {0}")]
    Invalid(String),
    #[error("agentd generation fenced: {0}")]
    GenerationFenced(String),
    #[error("cognitive write runtime unavailable")]
    CognitiveWriteRuntimeUnavailable,
    #[error("agentd protocol error: {0}")]
    Protocol(String),
    #[error(
        "compact.engine {code}: {message}; action={action}; commit_state={commit_state}"
    )]
    CompactEngine {
        code: CompactEngineErrorCodeV1,
        action: CompactEngineRecoveryActionV1,
        commit_state: CompactEngineCommitStateV1,
        message: String,
    },
    #[error("agentd control overloaded; retry after {retry_after_ms} ms")]
    Overloaded { retry_after_ms: u64 },
    #[error(transparent)]
    Fleet(#[from] FleetRegistryError),
    #[error(transparent)]
    Automation(#[from] AutomationError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    ProductionWriter(#[from] ProductionWriterError),
    #[error(transparent)]
    ProductionCognitiveMutation(#[from] ProductionCognitiveMutationError),
    #[error(transparent)]
    CognitiveStore(#[from] DurableCognitiveStoreError),
}

#[derive(Debug)]
struct AgentdIoContext {
    operation: &'static str,
    path: PathBuf,
    source: std::io::Error,
}

impl fmt::Display for AgentdIoContext {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{} at {}: {}",
            self.operation,
            self.path.display(),
            self.source
        )
    }
}

impl StdError for AgentdIoContext {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        Some(&self.source)
    }
}

/// Preserve the I/O error class while recording the exact startup boundary.
///
/// Agentd paths are host-generated state paths rather than user payloads. The
/// context is intentionally attached at the point of failure so process-level
/// qualification can distinguish directory preparation, stale-socket probing,
/// bind, permission and App Server transport failures without weakening any
/// fail-closed behavior.
pub(crate) fn contextual_io_error(
    operation: &'static str,
    path: &Path,
    source: std::io::Error,
) -> std::io::Error {
    let kind = source.kind();
    std::io::Error::new(
        kind,
        AgentdIoContext {
            operation,
            path: path.to_path_buf(),
            source,
        },
    )
}

pub(crate) fn io_context(
    operation: &'static str,
    path: &Path,
    source: std::io::Error,
) -> AgentdError {
    AgentdError::Io(contextual_io_error(operation, path, source))
}
