//! The original daemon owns the Notes UI receiver and sole finite adapter.
//! No external worker runtime, second writer or unmanaged service is started.

use super::*;
use std::os::fd::OwnedFd;
use tokio_util::sync::CancellationToken;
use crate::AgentdNotesUiPeer;
use crate::notes_ui_endpoint::NotesUiEndpoint;
use crate::notes_ui_queue::NotesUiQueue;

pub struct AgentdNotesUiRuntime {
    endpoint: NotesUiEndpoint,
    adapter: AgentdNotesLiteralAdapter,
}

impl AgentdNotesUiRuntime {
    /// Call inside the original I/O-enabled runtime after the actual Agentd UID
    /// has listened on Root's inherited bind-only socket. Session identities
    /// must come from the trusted sealed deployment, never UI messages.
    pub fn from_inherited(
        listener: OwnedFd,
        session_pidfd: OwnedFd,
        peer: AgentdNotesUiPeer,
        adapter: AgentdNotesLiteralAdapter,
    ) -> Result<Self, AgentdError> {
        adapter.check_available()?;
        let endpoint = NotesUiEndpoint::from_inherited(listener, session_pidfd, peer)?;
        Ok(Self { endpoint, adapter })
    }

    pub(crate) fn validate_for(&self, config: &AgentdConfig) -> Result<(), AgentdError> {
        let host = config.production_writer_host()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        if self.adapter.identity != *config.identity()
            || !Arc::ptr_eq(&self.adapter.writer, &host.writer())
            || config.notes_objective().as_ref().map(|notes| &notes.target) != Some(self.adapter.observer.target())
        { return Err(invalid("Notes UI adapter differs from this original runtime writer/target")); }
        self.endpoint.check_alive()?;
        self.adapter.check_available()
    }

    pub(crate) async fn run(mut self, cancellation: CancellationToken) -> Result<(), AgentdError> {
        let queue = NotesUiQueue::new();
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => Ok(()),
            _ = self.endpoint.lifetime.readable() => Err(invalid("original Notes Session lifetime ended")),
            result = self.endpoint.receive(&queue) => result,
            result = self.adapter.run_ui(&queue) => result,
        }
        // Dropping this future drops both bounded loops and all queued work.
        // Started original calls retain their own uncertainty and durable fence.
    }
}
