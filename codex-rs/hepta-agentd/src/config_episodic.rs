//! Explicit owner configuration; a control request cannot supply admission.
use std::sync::Arc;

use codex_hepta_memory::EpisodicSnapshotVerifier;

use super::AgentdConfig;
use crate::AgentdError;
use crate::episodic_import::EpisodicImportIngress;

impl AgentdConfig {
    /// Enable bounded agent-private imports through an already recovered writer.
    /// The embedding authenticates the original live source owner and supplies
    /// stable fact observations. Hashes and request provenance are not authority.
    /// The verifier must bound blocking I/O and reject stale or revoked input.
    pub fn with_episodic_snapshot_import(
        mut self,
        namespace: String,
        verifier: Arc<dyn EpisodicSnapshotVerifier>,
    ) -> Result<Self, AgentdError> {
        self.require_no_circuit_task_profile()?;
        if self.episodic_snapshot_import.is_some()
            || self.notes_objective.is_some()
            || self.desktop_objective.is_some()
            || self.neuron_generation_bootstrap.is_some()
            || namespace.trim().is_empty()
            || namespace.len() > 128
            || namespace.contains('\0')
        {
            return Err(AgentdError::Invalid("invalid episodic import composition".into()));
        }
        let writer = self.production_writer_host.as_ref()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        if writer.production_mutation().is_none() {
            return Err(AgentdError::CognitiveWriteRuntimeUnavailable);
        }
        self.episodic_snapshot_import = Some(Arc::new(EpisodicImportIngress {
            namespace,
            writer: Arc::clone(writer),
            verifier,
        }));
        Ok(self)
    }

    pub(crate) fn take_episodic_snapshot_import(&mut self) -> Option<Arc<EpisodicImportIngress>> {
        self.episodic_snapshot_import.take()
    }
}
