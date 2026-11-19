//! Trusted compiler input over the same inherited Notes recovery lane.
use std::io::Read;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_memory::NotesDocumentState;
use codex_hepta_memory::NotesTargetIdentity;
use codex_hepta_memory::ProductionNotesObserver;

use crate::AgentdError;

/// Read-only handle returned by the successful Session target registration.
/// It exposes no transport, issuer, effect dispatch or receipt retirement API.
/// Clones share one bounded in-memory observation fence for this attachment.
/// It orders accepted channel reads, not later asynchronous report delivery.
/// A new attachment starts a new fence; this is not durable rollback protection.
#[derive(Clone)]
pub struct AgentdNotesDocumentObserver {
    inner: ProductionNotesObserver,
    last_document: Arc<Mutex<Option<NotesDocumentState>>>,
}

impl AgentdNotesDocumentObserver {
    pub(crate) fn new(inner: ProductionNotesObserver) -> Self {
        Self {
            inner,
            last_document: Arc::new(Mutex::new(None)),
        }
    }

    pub fn target(&self) -> &NotesTargetIdentity {
        self.inner.target()
    }

    /// Call on the trusted blocking worker immediately before compiling a new
    /// Notes operation. A pending receipt, failed query or stale observation is
    /// never permission to overwrite the document or guess its revision.
    pub fn observe_document(&self) -> Result<NotesDocumentState, AgentdError> {
        // Keep the exchange and fence update in one order across clones. Do not
        // queue another blocking read behind an occupied or poisoned observer.
        let mut last = self.last_document.try_lock().map_err(|_| {
            AgentdError::Protocol("Notes document observation is busy or poisoned".into())
        })?;
        let request_id = fresh_nonce()?;
        let observed = self
            .inner
            .observe_document(&request_id)
            .map_err(AgentdError::Protocol)?;
        if last.as_ref().is_some_and(|previous| {
            observed.revision < previous.revision
                || (observed.revision == previous.revision
                    && observed.text_sha256 != previous.text_sha256)
        }) {
            return Err(AgentdError::Protocol(
                "Notes document observation regressed or changed content at the same revision"
                    .into(),
            ));
        }
        // Receipt retirement changes independently of document content. It does
        // not advance the revision and must not be mistaken for a regression.
        *last = Some(observed.clone());
        Ok(observed)
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
