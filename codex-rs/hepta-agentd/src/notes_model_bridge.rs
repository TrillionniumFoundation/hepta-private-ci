//! One model subscription under the original Notes owner. The only mutable
//! device path remains the existing unique literal adapter and original writer.

use super::model_proposal::*;
use super::*;
use crate::AgentdNotesModelRoute;
use crate::notes_ui_queue::NotesUiQueue;
use crate::notes_ui_wire::*;
use crate::text_session::AgentdTextRequests;
use crate::text_session::AgentdTextSession;
use crate::text_session::NotesToolCall;
use crate::text_session::NotesToolPhase;
use codex_app_server_protocol::DynamicToolCallOutputContentItem;
use codex_app_server_protocol::DynamicToolCallResponse;
use std::collections::BTreeMap;

#[path = "notes_model_confirmation.rs"]
mod confirmation;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ModelAdmission {
    NotStarted,
    MayExist,
}

impl ModelAdmission {
    fn mark_may_exist(&mut self) {
        *self = Self::MayExist;
    }

    fn can_release_tracking(self, view: &NotesModelProposalObservation) -> bool {
        match self {
            Self::NotStarted => {
                view.phase == NotesModelPhase::Closed || view.can_release_tracking()
            }
            Self::MayExist => {
                matches!(
                    view.phase,
                    NotesModelPhase::ReplyObserved | NotesModelPhase::Closed
                ) && view.owner_terminal.is_some()
            }
        }
    }
}

struct ModelPending {
    call: NotesToolCall,
    view: NotesModelProposalObservation,
    reviewed: Option<NotesDocumentState>,
    reply: Option<DynamicToolCallResponse>,
    settle_by: Instant,
    snapshot_after: Instant,
    terminal_after: Instant,
    admission: ModelAdmission,
}

pub(super) struct NotesModelBridge {
    route: AgentdNotesModelRoute,
    session: AgentdTextSession,
    pending: BTreeMap<String, ModelPending>,
    available: bool,
    reconnect_after: Instant,
}

impl NotesModelBridge {
    pub(super) async fn attach(
        adapter: &AgentdNotesLiteralAdapter,
        route: AgentdNotesModelRoute,
    ) -> Result<Self, AgentdError> {
        route.validate_for(adapter.bindings.principal_scope_digest)?;
        let config = route.text_session_config(&adapter.identity)?;
        // Notes UI is spawned before App Server in the same original runtime.
        // Wait only for that fixed route; never create or register another one.
        let end = Instant::now() + Duration::from_secs(10);
        let session = loop {
            adapter.check_available()?;
            match AgentdTextSession::connect_notes_owner(config.clone()).await {
                Ok(session) => break session,
                Err(error) if Instant::now() >= end => return Err(text_error(error)),
                Err(crate::text_session::TextSessionError::Identity) => {
                    return Err(invalid("original Notes model route identity changed"));
                }
                Err(_) => tokio::time::sleep(Duration::from_millis(100)).await,
            }
        };
        Ok(Self {
            route,
            session,
            pending: BTreeMap::new(),
            available: true,
            reconnect_after: Instant::now(),
        })
    }

    pub(super) async fn wait(
        &mut self,
        adapter: &AgentdNotesLiteralAdapter,
        queue: &NotesUiQueue,
    ) -> Result<(), AgentdError> {
        let observed = tokio::select! {
            _ = queue.wake.notified() => return Ok(()),
            _ = tokio::time::sleep(Duration::from_millis(250)) => return Ok(()),
            observed = self.session.events.next_observation() => observed,
        };
        if !matches!(observed, Ok(Some(_))) {
            self.available = false;
            queue
                .publish_model(None)
                .map_err(|_| invalid("Notes model view is unavailable"))?;
            let _ = self.reconnect(adapter).await;
            adapter.check_available()?;
            // A temporary model socket failure cannot stop the original Notes
            // owner. Root/Session lifetime fencing still terminates its task.
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
        Ok(())
    }

    async fn reconnect(&mut self, adapter: &AgentdNotesLiteralAdapter) -> Result<(), AgentdError> {
        adapter.check_available()?;
        if Instant::now() < self.reconnect_after {
            return Err(invalid(
                "original Notes model reconnect is waiting for its bounded backoff",
            ));
        }
        self.reconnect_after = Instant::now() + Duration::from_secs(1);
        let config = self.route.text_session_config(&adapter.identity)?;
        let next = self.session.reattach(config).await.map_err(text_error)?;
        let old = std::mem::replace(&mut self.session, next);
        let _ = old.events.shutdown().await;
        // Private old callbacks remain read-only evidence. A new response
        // requires the App Server to replay its actual pending request.
        Ok(())
    }

    pub(super) fn view(&self, id: Option<&str>) -> Option<NotesModelProposalObservation> {
        let pending = if let Some(id) = id {
            self.pending.get(id)
        } else {
            self.pending
                .values()
                .find(|pending| pending.view.phase == NotesModelPhase::ReviewRequired)
                .or_else(|| {
                    self.pending.values().find(|pending| {
                        matches!(
                            pending.view.phase,
                            NotesModelPhase::Retained | NotesModelPhase::ReplyStarted
                        )
                    })
                })
                .or_else(|| self.pending.values().next_back())
        };
        pending
            .filter(|pending| {
                self.available || pending.view.phase != NotesModelPhase::ReviewRequired
            })
            .map(|pending| pending.view.clone())
    }

    pub(super) async fn refresh(
        &mut self,
        adapter: &mut AgentdNotesLiteralAdapter,
        queue: &NotesUiQueue,
    ) -> Result<(), AgentdError> {
        self.available = false;
        adapter.check_available()?;
        // Original receipt reads remain available when the model connection
        // is down; only callback preparation/response needs that connection.
        for pending in self.pending.values_mut() {
            Self::refresh_owner_terminal(adapter, pending).await?;
        }
        // The event pump retains each callback before display publication.
        // Drain a bounded number even while the UI has continuous requests.
        for _ in 0..32 {
            match tokio::time::timeout(Duration::ZERO, self.session.events.next_observation()).await
            {
                Ok(Ok(Some(_))) => {}
                Ok(_) => {
                    self.reconnect(adapter).await?;
                    break;
                }
                Err(_) => break,
            }
        }
        adapter.check_available()?;
        // Late original receipts must remain observable even while a new
        // callback is refused because all eight unresolved slots are retained.
        for pending in self.pending.values_mut() {
            Self::refresh_result(adapter, &self.session.requests, pending).await?;
        }
        let calls = self
            .session
            .requests
            .notes_tool_calls()
            .map_err(text_error)?;
        for call in calls {
            self.observe_call(adapter, call).await?;
        }
        for pending in self.pending.values_mut() {
            Self::refresh_result(adapter, &self.session.requests, pending).await?;
        }
        self.available = true;
        queue
            .publish_model(self.view(None))
            .map_err(|_| invalid("Notes model view is unavailable"))?;
        Ok(())
    }

    async fn observe_call(
        &mut self,
        adapter: &mut AgentdNotesLiteralAdapter,
        mut call: NotesToolCall,
    ) -> Result<(), AgentdError> {
        let id = proposal_id(
            adapter.identity.agent_id.as_str(),
            &self.route,
            &call.params,
        )?;
        if let Some(pending) = self.pending.get_mut(&id) {
            if pending.call.params != call.params
                || pending.call.app_server_session_id != call.app_server_session_id
            {
                return Err(invalid(
                    "same original Notes model call changed its arguments",
                ));
            }
            if pending.call.connection_id != call.connection_id {
                let previous = self
                    .session
                    .requests
                    .reconcile_notes_tool(&pending.call)
                    .await
                    .map_err(text_error)?;
                if pending.view.phase == NotesModelPhase::ReplyObserved
                    && previous != NotesToolPhase::Completed
                {
                    return Err(invalid("original Notes callback completion changed"));
                }
                if matches!(previous, NotesToolPhase::Completed | NotesToolPhase::Closed) {
                    pending.call.phase = previous;
                    pending.view.phase = if previous == NotesToolPhase::Completed {
                        NotesModelPhase::ReplyObserved
                    } else {
                        NotesModelPhase::Closed
                    };
                    let _ = self
                        .session
                        .requests
                        .reconcile_notes_tool(&call)
                        .await
                        .map_err(text_error)?;
                    let _ = self.session.requests.release_notes_tool(&call);
                    return Ok(());
                }
            }
            pending.call = call;
            return Ok(());
        }
        if matches!(
            call.phase,
            NotesToolPhase::Completed | NotesToolPhase::Closed
        ) {
            self.session
                .requests
                .release_notes_tool(&call)
                .map_err(text_error)?;
            return Ok(());
        }
        if call.phase != NotesToolPhase::Pending {
            self.session
                .requests
                .reconcile_notes_tool(&call)
                .await
                .map_err(text_error)?;
            return Ok(());
        }
        let text = match proposed_text(&call.params) {
            Ok(text) => text,
            Err(_) => {
                self.session
                    .requests
                    .reply_notes_tool(
                        &mut call,
                        DynamicToolCallResponse {
                            content_items: vec![DynamicToolCallOutputContentItem::InputText {
                                text:
                                    "{\"status\":\"invalid_proposal\",\"repeat_authorized\":false}"
                                        .into(),
                            }],
                            success: false,
                        },
                    )
                    .await
                    .map_err(text_error)?;
                return Ok(());
            }
        };
        let run_id = adapter.run_id(&id)?;
        let retained = adapter.writer.retained_operation(&run_id).await?;
        let mut admission = ModelAdmission::NotStarted;
        let reviewed = if retained.is_some() {
            admission.mark_may_exist();
            check_retained_literal(&adapter.writer, &run_id, &text, LiteralPredecessor::Current)
                .await?;
            None
        } else {
            if self
                .session
                .requests
                .reconcile_notes_tool(&call)
                .await
                .map_err(text_error)?
                != NotesToolPhase::Pending
            {
                return Ok(());
            }
            let end = Instant::now() + adapter.deadline;
            let observed = tokio::time::timeout_at(end.into(), adapter.observe_ui_document(end))
                .await
                .map_err(|_| invalid("Notes model predecessor observation expired"))??;
            if observed.receipt_pending || observed.target != *adapter.observer.target() {
                return Ok(());
            }
            Some(observed)
        };
        if self.pending.len() >= 8 {
            let completed = self
                .pending
                .iter()
                .find(|(_, pending)| pending.admission.can_release_tracking(&pending.view))
                .map(|(id, _)| id.clone());
            if let Some(completed) = completed {
                self.pending.remove(&completed);
            } else {
                self.session.requests.reply_notes_tool(&mut call, DynamicToolCallResponse {
                    content_items: vec![DynamicToolCallOutputContentItem::InputText { text: "{\"status\":\"capacity_unavailable\",\"repeat_authorized\":false,\"instruction\":\"Capacity unavailable. Reconcile existing operation outcomes through their original retained identities; this refusal authorizes no execution or repetition.\"}".into() }],
                    success: false,
                }).await.map_err(text_error)?;
                return Ok(());
            }
        }
        let view = proposal_view(id.clone(), &call.params, reviewed.as_ref())?;
        self.pending.insert(
            id,
            ModelPending {
                call,
                view,
                reviewed,
                reply: None,
                settle_by: Instant::now() + Duration::from_secs(30),
                snapshot_after: Instant::now(),
                terminal_after: Instant::now(),
                admission,
            },
        );
        Ok(())
    }

    async fn refresh_result(
        adapter: &mut AgentdNotesLiteralAdapter,
        requests: &AgentdTextRequests,
        pending: &mut ModelPending,
    ) -> Result<(), AgentdError> {
        match pending.call.phase {
            NotesToolPhase::Completed => {
                pending.view.phase = NotesModelPhase::ReplyObserved;
            }
            NotesToolPhase::Closed => {
                if pending.view.phase != NotesModelPhase::ReplyObserved {
                    pending.view.phase = NotesModelPhase::Closed;
                }
            }
            NotesToolPhase::Pending | NotesToolPhase::ReplyStarted => {}
        }
        Self::refresh_owner_terminal(adapter, pending).await?;
        let run_id = adapter.run_id(&pending.view.proposal_id)?;
        if matches!(
            pending.view.phase,
            NotesModelPhase::ReplyObserved | NotesModelPhase::Closed
        ) {
            if pending.call.connection_id == requests.connection_id() {
                let _ = requests.release_notes_tool(&pending.call);
            }
            return Ok(());
        }
        if pending.call.phase == NotesToolPhase::ReplyStarted
            || pending.call.connection_id != requests.connection_id()
        {
            if Instant::now() >= pending.snapshot_after {
                pending.snapshot_after = Instant::now() + Duration::from_secs(1);
                let phase = requests
                    .reconcile_notes_tool(&pending.call)
                    .await
                    .map_err(text_error)?;
                if phase == NotesToolPhase::Completed {
                    pending.call.phase = phase;
                    pending.view.phase = NotesModelPhase::ReplyObserved;
                } else if phase == NotesToolPhase::Closed {
                    pending.call.phase = phase;
                    pending.view.phase = NotesModelPhase::Closed;
                }
            }
            return Ok(());
        }
        if pending.view.phase == NotesModelPhase::ReviewRequired {
            return Ok(());
        }
        if pending.reply.is_none() {
            if Instant::now() < pending.settle_by {
                return Ok(());
            }
            pending.view.result = Some(NotesModelResult::Unknown);
            pending.reply = Some(unresolved_response(
                &pending.view,
                &run_id,
                NotesModelResult::Unknown,
            )?);
        }
        if let Some(reply) = &pending.reply {
            pending.view.phase = NotesModelPhase::ReplyStarted;
            // Even an ambiguous response write never creates another effect.
            let _ = requests
                .reply_notes_tool(&mut pending.call, reply.clone())
                .await;
        }
        Ok(())
    }

    async fn refresh_owner_terminal(
        adapter: &AgentdNotesLiteralAdapter,
        pending: &mut ModelPending,
    ) -> Result<(), AgentdError> {
        if pending.view.phase == NotesModelPhase::ReviewRequired
            || pending.view.owner_terminal.is_some()
            || Instant::now() < pending.terminal_after
        {
            return Ok(());
        }
        pending.terminal_after = Instant::now() + Duration::from_secs(1);
        let run_id = adapter.run_id(&pending.view.proposal_id)?;
        if let Ok(Some(terminal)) = adapter.writer.observe_notes_terminal(&run_id).await {
            pending.admission.mark_may_exist();
            let (result, reply) = observe_owner_terminal(&run_id, &mut pending.view, &terminal)?;
            // A late receipt enriches only the owner observation. An earlier
            // unknown/declined reply and closed callback stay unchanged.
            if pending.reply.is_none() && pending.view.phase == NotesModelPhase::Retained {
                pending.view.result = Some(result);
                pending.view.application_receipt_sha256 =
                    Some(terminal.application_receipt_sha256.as_str().to_owned());
                pending.reply = Some(reply);
            }
        }
        Ok(())
    }
}

fn text_error(error: crate::text_session::TextSessionError) -> AgentdError {
    invalid(&format!("original Notes model route: {error}"))
}

#[cfg(test)]
#[path = "notes_model_admission_tests.rs"]
mod admission_tests;
