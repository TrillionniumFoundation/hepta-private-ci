use std::error::Error as StdError;
use std::fmt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_automation::AutomationError;
use codex_hepta_cognitive_store::DurableCognitiveStoreError;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_memory::ProductionCognitiveMutationError;
use codex_hepta_memory::ProductionWriterError;

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
    /// Keep indeterminate append receipts available to the in-process recovery
    /// owner instead of erasing them into a protocol/debug string. Display uses
    /// the service's stable code and does not disclose signed evidence payloads.
    #[error(transparent)]
    IntuitionPolicy(Box<crate::AgentdIntuitionServiceErrorV1>),
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

impl From<crate::AgentdIntuitionServiceErrorV1> for AgentdError {
    fn from(source: crate::AgentdIntuitionServiceErrorV1) -> Self {
        Self::IntuitionPolicy(Box::new(source))
    }
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

#[cfg(test)]
mod tests {
    use super::AgentdError;
    use crate::AgentdIntuitionPolicyError;
    use crate::AgentdIntuitionServiceErrorV1;

    #[test]
    fn intuition_policy_service_error_keeps_its_type_and_stable_code() {
        let error = AgentdError::from(AgentdIntuitionServiceErrorV1::Policy(
            AgentdIntuitionPolicyError::PreparedEvidenceExpired,
        ));
        assert_eq!(
            error.to_string(),
            "agentd.intuition.prepared_evidence_expired"
        );
        assert!(matches!(
            error,
            AgentdError::IntuitionPolicy(source)
                if matches!(*source, AgentdIntuitionServiceErrorV1::Policy(
                    AgentdIntuitionPolicyError::PreparedEvidenceExpired
                ))
        ));
    }
}
