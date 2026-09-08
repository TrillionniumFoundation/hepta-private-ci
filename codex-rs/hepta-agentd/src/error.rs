use std::error::Error as StdError;
use std::fmt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_automation::AutomationError;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_memory::ProductionWriterError;

#[derive(Debug, thiserror::Error)]
pub enum AgentdError {
    #[error("invalid agentd configuration: {0}")]
    Invalid(String),
    #[error("agentd generation fenced: {0}")]
    GenerationFenced(String),
    #[error("qualification cognitive runtime unavailable")]
    QualificationCognitiveRuntimeUnavailable,
    #[error("agentd protocol error: {0}")]
    Protocol(String),
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
