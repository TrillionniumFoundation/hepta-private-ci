#[cfg(feature = "server")]
use std::error::Error as StdError;
#[cfg(feature = "server")]
use std::fmt;
#[cfg(feature = "server")]
use std::path::Path;
#[cfg(feature = "server")]
use std::path::PathBuf;

#[cfg(feature = "server")]
use codex_hepta_agent_components::automation::AutomationError;
#[cfg(feature = "server")]
use codex_hepta_agent_components::cognitive_store::DurableCognitiveStoreError;
#[cfg(feature = "server")]
use codex_hepta_agent_components::fleet::FleetRegistryError;
#[cfg(feature = "server")]
use codex_hepta_agent_components::memory::ProductionCognitiveMutationError;
#[cfg(feature = "server")]
use codex_hepta_agent_components::memory::ProductionWriterError;

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
    #[error("agentd control overloaded; retry after {retry_after_ms} ms")]
    Overloaded { retry_after_ms: u64 },
    #[cfg(feature = "server")]
    #[error(transparent)]
    Fleet(#[from] FleetRegistryError),
    #[cfg(feature = "server")]
    #[error(transparent)]
    Automation(#[from] AutomationError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[cfg(feature = "server")]
    #[error(transparent)]
    ProductionWriter(#[from] ProductionWriterError),
    #[cfg(feature = "server")]
    #[error(transparent)]
    ProductionCognitiveMutation(#[from] ProductionCognitiveMutationError),
    #[cfg(feature = "server")]
    #[error(transparent)]
    CognitiveStore(#[from] DurableCognitiveStoreError),
}

#[cfg(feature = "server")]
#[derive(Debug)]
struct AgentdIoContext {
    operation: &'static str,
    path: PathBuf,
    source: std::io::Error,
}

#[cfg(feature = "server")]
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

#[cfg(feature = "server")]
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
#[cfg(feature = "server")]
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

#[cfg(feature = "server")]
pub(crate) fn io_context(
    operation: &'static str,
    path: &Path,
    source: std::io::Error,
) -> AgentdError {
    AgentdError::Io(contextual_io_error(operation, path, source))
}
