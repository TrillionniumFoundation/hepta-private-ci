//! The original daemon owns the Notes UI receiver and sole finite adapter.
//! No external worker runtime, second writer or unmanaged service is started.

use super::*;
use crate::AgentdNotesUiPeer;
use crate::notes_ui_endpoint::NotesUiEndpoint;
use crate::notes_ui_queue::NotesUiQueue;
use std::os::fd::OwnedFd;
use tokio_util::sync::CancellationToken;

pub struct AgentdNotesUiRuntime {
    endpoint: NotesUiEndpoint,
    adapter: AgentdNotesLiteralAdapter,
    model_route: Option<crate::AgentdNotesModelRoute>,
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
        Ok(Self {
            endpoint,
            adapter,
            model_route: None,
        })
    }

    /// Install only Root's sealed declaration of an already registered tool
    /// on the original thread. Attachment occurs inside the managed runtime.
    pub fn with_model_route(
        mut self,
        route: crate::AgentdNotesModelRoute,
    ) -> Result<Self, AgentdError> {
        route.validate_for(self.adapter.bindings.principal_scope_digest)?;
        if self.model_route.is_some() {
            return Err(invalid("original Notes model route is already installed"));
        }
        self.model_route = Some(route);
        Ok(self)
    }

    pub(crate) fn validate_for(&self, config: &AgentdConfig) -> Result<(), AgentdError> {
        let host = config
            .production_writer_host()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        if self.adapter.identity != *config.identity()
            || !Arc::ptr_eq(&self.adapter.writer, &host.writer())
            || config.notes_objective().as_ref().map(|notes| &notes.target)
                != Some(self.adapter.observer.target())
        {
            return Err(invalid(
                "Notes UI adapter differs from this original runtime writer/target",
            ));
        }
        self.endpoint.check_alive()?;
        if let Some(route) = &self.model_route {
            route.validate_for(self.adapter.bindings.principal_scope_digest)?;
        }
        self.adapter.check_available()
    }

    pub(crate) async fn run(mut self, cancellation: CancellationToken) -> Result<(), AgentdError> {
        let queue = NotesUiQueue::new();
        let model_route = self.model_route.take();
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => Ok(()),
            _ = self.endpoint.lifetime.readable() => Err(invalid("original Notes Session lifetime ended")),
            result = self.endpoint.receive(&queue) => result,
            result = self.adapter.run_ui(&queue, model_route) => result,
        }
        // Dropping this future drops both bounded loops and all queued work.
        // Started original calls retain their own uncertainty and durable fence.
    }
}
