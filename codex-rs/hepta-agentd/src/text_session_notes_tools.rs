//! Private callback correlation for the original Notes owner. No renderer or
//! generic text-approval command can supply a dynamic-tool result here.

use super::*;
use codex_app_server_protocol::DynamicToolCallParams;
use codex_app_server_protocol::DynamicToolCallResponse;
use codex_app_server_protocol::DynamicToolCallStatus;
use codex_app_server_protocol::ServerRequest;

use crate::notes_model_route::NOTES_MODEL_NAMESPACE;
use crate::notes_model_route::NOTES_MODEL_TOOL;

const MAX_NOTES_CALLBACKS: usize = 8;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum NotesToolPhase {
    Pending,
    ReplyStarted,
    Completed,
    Closed,
}

#[derive(Clone)]
pub(crate) struct NotesToolCall {
    pub(crate) connection_id: u64,
    pub(crate) request_id: RequestId,
    pub(crate) app_server_session_id: String,
    pub(crate) params: DynamicToolCallParams,
    pub(crate) phase: NotesToolPhase,
    response: Option<DynamicToolCallResponse>,
}

#[derive(Clone, Default)]
pub(super) struct NotesToolCallbacks {
    calls: BTreeMap<String, NotesToolCall>,
}

impl NotesToolCallbacks {
    pub(super) fn observe(
        &mut self,
        connection_id: u64,
        thread_id: &str,
        app_server_session_id: &str,
        request: &ServerRequest,
    ) -> Result<(), TextSessionError> {
        let ServerRequest::DynamicToolCall { request_id, params } = request else {
            return Ok(());
        };
        if params.namespace.as_deref() != Some(NOTES_MODEL_NAMESPACE)
            || params.tool != NOTES_MODEL_TOOL
        {
            return Ok(());
        }
        let id = serde_json::to_string(request_id).map_err(unavailable)?;
        if params.thread_id != thread_id
            || params.turn_id.is_empty()
            || params.turn_id.len() > 128
            || params.call_id.is_empty()
            || params.call_id.len() > 256
            || id.len() > 256
            || serde_json::to_vec(params).map_err(unavailable)?.len() > 16 * 1024
        {
            return Err(TextSessionError::Identity);
        }
        if let Some(previous) = self.calls.get(&id) {
            if previous.connection_id != connection_id
                || previous.app_server_session_id != app_server_session_id
                || previous.params != *params
            {
                return Err(TextSessionError::Identity);
            }
            // Replayed callbacks cannot reset a started response or decision.
            return Ok(());
        }
        if self.calls.values().any(|previous| {
            previous.params.turn_id == params.turn_id && previous.params.call_id == params.call_id
        }) {
            return Err(TextSessionError::Identity);
        }
        if self.calls.len() == MAX_NOTES_CALLBACKS {
            return Err(TextSessionError::Capacity);
        }
        self.calls.insert(
            id,
            NotesToolCall {
                connection_id,
                request_id: request_id.clone(),
                app_server_session_id: app_server_session_id.to_owned(),
                params: params.clone(),
                phase: NotesToolPhase::Pending,
                response: None,
            },
        );
        Ok(())
    }

    fn original_mut(
        &mut self,
        call: &NotesToolCall,
    ) -> Result<&mut NotesToolCall, TextSessionError> {
        let id = serde_json::to_string(&call.request_id).map_err(unavailable)?;
        let original = self
            .calls
            .get_mut(&id)
            .ok_or(TextSessionError::UnknownRequest)?;
        if original.connection_id != call.connection_id
            || original.app_server_session_id != call.app_server_session_id
            || original.params != call.params
        {
            return Err(TextSessionError::Identity);
        }
        Ok(original)
    }

    fn start_reply(
        &mut self,
        call: &NotesToolCall,
        response: DynamicToolCallResponse,
    ) -> Result<(), TextSessionError> {
        let original = self.original_mut(call)?;
        if original.phase != NotesToolPhase::Pending {
            return Err(TextSessionError::Identity);
        }
        original.response = Some(response);
        original.phase = NotesToolPhase::ReplyStarted;
        Ok(())
    }

    pub(super) fn observe_notification(
        &mut self,
        notification: &ServerNotification,
    ) -> Result<(), TextSessionError> {
        match notification {
            ServerNotification::ItemCompleted(completed) => {
                self.observe_item(&completed.thread_id, &completed.turn_id, &completed.item)?;
            }
            ServerNotification::TurnCompleted(completed) => {
                for call in self.calls.values_mut().filter(|call| {
                    call.params.thread_id == completed.thread_id
                        && call.params.turn_id == completed.turn.id
                }) {
                    if call.phase != NotesToolPhase::Completed {
                        call.phase = NotesToolPhase::Closed;
                    }
                }
            }
            _ => {}
        }
        Ok(())
    }

    fn observe_item(
        &mut self,
        thread_id: &str,
        turn_id: &str,
        item: &ThreadItem,
    ) -> Result<(), TextSessionError> {
        let ThreadItem::DynamicToolCall { id, .. } = item else {
            return Ok(());
        };
        let Some(call) = self.calls.values_mut().find(|call| {
            call.params.thread_id == thread_id
                && call.params.turn_id == turn_id
                && call.params.call_id == *id
        }) else {
            return Ok(());
        };
        call.observe_item(item)
    }

    fn reconcile_snapshot(
        &mut self,
        connection_id: u64,
        call: &NotesToolCall,
        item: &ThreadItem,
    ) -> Result<NotesToolPhase, TextSessionError> {
        if call.connection_id == connection_id {
            // The event pump may have observed completion while the read was
            // in flight. Return that original table's monotonic merged state.
            let original = self.original_mut(call)?;
            original.observe_item(item)?;
            Ok(original.phase)
        } else {
            let mut observed = call.clone();
            observed.observe_item(item)?;
            Ok(observed.phase)
        }
    }
}

impl NotesToolCall {
    fn observe_item(&mut self, item: &ThreadItem) -> Result<(), TextSessionError> {
        let ThreadItem::DynamicToolCall {
            id,
            namespace,
            tool,
            arguments,
            status,
            content_items,
            success,
            ..
        } = item
        else {
            return Err(TextSessionError::Identity);
        };
        if self.params.call_id != *id
            || self.params.namespace != *namespace
            || self.params.tool != *tool
            || self.params.arguments != *arguments
        {
            return Err(TextSessionError::Identity);
        }
        if *status == DynamicToolCallStatus::InProgress {
            return Ok(());
        }
        let phase = match &self.response {
            Some(response)
                if *success == Some(response.success)
                    && content_items.as_ref() == Some(&response.content_items)
                    && *status
                        == if response.success {
                            DynamicToolCallStatus::Completed
                        } else {
                            DynamicToolCallStatus::Failed
                        } =>
            {
                NotesToolPhase::Completed
            }
            // Another client, cancellation or a lost callback cannot attest
            // that the original owner response entered the model's history.
            _ => NotesToolPhase::Closed,
        };
        if self.phase == NotesToolPhase::Completed && phase != NotesToolPhase::Completed {
            return Err(TextSessionError::Identity);
        }
        self.phase = phase;
        Ok(())
    }
}

impl AgentdTextRequests {
    pub(crate) fn notes_tool_calls(&self) -> Result<Vec<NotesToolCall>, TextSessionError> {
        Ok(self
            .shared
            .current()?
            .notes_tools
            .calls
            .values()
            .cloned()
            .collect())
    }

    pub(crate) async fn reply_notes_tool(
        &self,
        call: &mut NotesToolCall,
        response: DynamicToolCallResponse,
    ) -> Result<(), TextSessionError> {
        if call.connection_id != self.connection_id()
            || call.phase != NotesToolPhase::Pending
            || response.content_items.len() != 1
            || serde_json::to_vec(&response).map_err(unavailable)?.len() > 8192
        {
            return Err(TextSessionError::Identity);
        }
        self.check_current_ingress().await?;
        self.shared
            .current()?
            .notes_tools
            .start_reply(call, response.clone())?;
        call.response = Some(response.clone());
        call.phase = NotesToolPhase::ReplyStarted;
        // The transient write fence is set before I/O. Only the original
        // completed item, never successful socket I/O, confirms the response.
        tokio::time::timeout(
            REQUEST_TIMEOUT,
            self.handle.resolve_server_request(
                call.request_id.clone(),
                serde_json::to_value(response).map_err(unavailable)?,
            ),
        )
        .await
        .map_err(unavailable)?
        .map_err(unavailable)
    }

    pub(crate) async fn reconcile_notes_tool(
        &self,
        call: &NotesToolCall,
    ) -> Result<NotesToolPhase, TextSessionError> {
        if call.params.thread_id != self.shared.config.thread_id
            || call.app_server_session_id != self.shared.config.app_server_session_id
        {
            return Err(TextSessionError::Identity);
        }
        tokio::time::timeout(REQUEST_TIMEOUT, async {
            let mut cursor = None;
            for _ in 0..256 {
                let page: ThreadItemsListResponse = self
                    .call(ClientRequest::ThreadItemsList {
                        request_id: self.id(),
                        params: ThreadItemsListParams {
                            thread_id: call.params.thread_id.clone(),
                            turn_id: Some(call.params.turn_id.clone()),
                            cursor,
                            limit: Some(1),
                            sort_direction: Some(SortDirection::Asc),
                        },
                    })
                    .await?;
                if page.data.len() > 1
                    || page
                        .data
                        .iter()
                        .any(|item| item.turn_id != call.params.turn_id)
                {
                    return Err(TextSessionError::Identity);
                }
                if let Some(item) = page
                    .data
                    .iter()
                    .find(|item| item.item.id() == call.params.call_id)
                {
                    // Old typed callbacks can read the same original history
                    // after reconnect. This never inserts a new pending handle.
                    return self.shared.current()?.notes_tools.reconcile_snapshot(
                        self.connection_id(),
                        call,
                        &item.item,
                    );
                }
                cursor = page.next_cursor;
                if cursor.is_none() {
                    break;
                }
            }
            Err(TextSessionError::UnknownRequest)
        })
        .await
        .map_err(unavailable)?
    }

    pub(crate) fn release_notes_tool(&self, call: &NotesToolCall) -> Result<(), TextSessionError> {
        let mut state = self.shared.current()?;
        if !matches!(
            state.notes_tools.original_mut(call)?.phase,
            NotesToolPhase::Completed | NotesToolPhase::Closed
        ) {
            return Err(TextSessionError::Identity);
        }
        let id = serde_json::to_string(&call.request_id).map_err(unavailable)?;
        state.notes_tools.calls.remove(&id);
        Ok(())
    }
}

#[cfg(test)]
#[path = "text_session_notes_tools_tests.rs"]
mod tests;
