//! Trusted compiler input over the same inherited Notes recovery lane.
use std::io::Read;

use codex_hepta_memory::NotesDocumentState;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_memory::ProductionNotesObserver;

use crate::AgentdError;

/// Read-only handle returned by the successful Session target registration.
/// It exposes no transport, issuer, effect dispatch or receipt retirement API.
#[derive(Clone)]
pub struct AgentdNotesDocumentObserver {
    inner: ProductionNotesObserver,
}

impl AgentdNotesDocumentObserver {
    pub(crate) fn new(inner: ProductionNotesObserver) -> Self {
        Self { inner }
    }

    pub fn target(&self) -> &NotesTargetIdentity {
        self.inner.target()
    }

    /// Call on the trusted blocking worker immediately before compiling a new
    /// Notes operation. A pending receipt, failed query or stale observation is
    /// never permission to overwrite the document or guess its revision.
    pub fn observe_document(&self) -> Result<NotesDocumentState, AgentdError> {
        let request_id = fresh_nonce()?;
        self.inner
            .observe_document(&request_id)
            .map_err(AgentdError::Protocol)
    }

    pub(crate) async fn previous_recovery_target(
        &self,
        writer: &codex_hepta_memory::ProductionDurableWriter,
    ) -> Result<Option<codex_hepta_memory::ProductionNotesRecoveryTarget>, AgentdError> {
        Ok(writer
            .previous_notes_recovery_target(&self.inner, &fresh_nonce()?)
            .await?)
    }
}

fn fresh_nonce() -> Result<String, AgentdError> {
    let mut nonce = [0_u8; 16];
    std::fs::File::open("/dev/urandom")?.read_exact(&mut nonce)?;
    Ok(nonce.iter().map(|byte| format!("{byte:02x}")).collect())
}

#[cfg(test)]
#[path = "notes_document_observer_tests.rs"]
mod tests;
