//! Transient views of original App Server callback IDs. The original owner
//! retains/replays pending callbacks; this module creates no approval ledger.
use super::*;
use codex_app_server_protocol::CommandExecutionApprovalDecision;
use codex_app_server_protocol::CommandExecutionRequestApprovalResponse;
use codex_app_server_protocol::FileChangeApprovalDecision;
use codex_app_server_protocol::FileChangeRequestApprovalResponse;
use codex_app_server_protocol::ServerRequest;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TextApprovalDecision {
    AcceptOnce,
    Decline,
}

#[derive(Clone, Debug)]
pub struct TextApproval {
    pub connection_id: u64,
    /// Canonical JSON encoding distinguishes numeric and string RPC IDs.
    pub id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub item_id: String,
    pub title: String,
    pub details: String,
    pub can_accept: bool,
    pub can_decline: bool,
}

#[derive(Clone, Debug)]
pub enum TextApprovalObservation {
    Pending(TextApproval),
    Resolved {
        connection_id: u64,
        id: String,
    },
    Unavailable {
        connection_id: u64,
        id: String,
        message: String,
    },
}

#[derive(Clone)]
pub(super) struct PendingApproval {
    request: ServerRequest,
    can_accept: bool,
    responding: bool,
}

impl AgentdTextRequests {
    pub(super) async fn observe_approval(
        &self,
        request: &ServerRequest,
    ) -> Result<TextApprovalObservation, TextSessionError> {
        let id = serde_json::to_string(request.id()).map_err(unavailable)?;
        let unsupported = |message: &str| TextApprovalObservation::Unavailable {
            connection_id: self.connection_id(),
            id: id.clone(),
            message: message.into(),
        };
        if id.len() > 256 || serde_json::to_vec(request).map_err(unavailable)?.len() > 32 * 1024 {
            return Ok(unsupported(
                "Original request exceeds the native approval preview; use its original approval client",
            ));
        }
        let (thread, turn, item, title, mut details, mut can_accept) = match request {
            ServerRequest::CommandExecutionRequestApproval { params, .. } => (
                &params.thread_id,
                &params.turn_id,
                &params.item_id,
                "Command approval",
                serde_json::to_string_pretty(params).map_err(unavailable)?,
                params
                    .command
                    .as_ref()
                    .is_some_and(|command| !command.trim().is_empty())
                    && params.available_decisions.as_ref().is_none_or(|values| {
                        values.contains(&CommandExecutionApprovalDecision::Accept)
                    }),
            ),
            ServerRequest::FileChangeRequestApproval { params, .. } => (
                &params.thread_id,
                &params.turn_id,
                &params.item_id,
                "File change approval",
                serde_json::to_string_pretty(params).map_err(unavailable)?,
                false,
            ),
            _ => {
                return Ok(unsupported(
                    "Original request requires its registered input, credential, or tool client; this text lane cannot resolve it",
                ));
            }
        };
        if thread != &self.shared.config.thread_id || turn.is_empty() || item.is_empty() {
            return Err(TextSessionError::Identity);
        }
        if matches!(request, ServerRequest::FileChangeRequestApproval { .. }) {
            // The callback has no patch body. Approval is enabled only when the
            // exact original file-change item is visible in full to the human.
            let preview = async {
                let mut cursor = None;
                for _ in 0..256 {
                    let page: ThreadItemsListResponse = self
                        .call(ClientRequest::ThreadItemsList {
                            request_id: self.id(),
                            params: ThreadItemsListParams {
                                thread_id: thread.clone(),
                                turn_id: Some(turn.clone()),
                                cursor,
                                limit: Some(1),
                                sort_direction: Some(SortDirection::Asc),
                            },
                        })
                        .await?;
                    if page.data.len() > 1 || page.data.iter().any(|entry| &entry.turn_id != turn) {
                        return Err(TextSessionError::Identity);
                    }
                    if let Some(original) = page.data.into_iter().find(|entry| matches!(&entry.item, ThreadItem::FileChange { id, .. } if id == item)) {
                        return serde_json::to_string_pretty(&original.item).map(Some).map_err(unavailable);
                    }
                    cursor = page.next_cursor;
                    if cursor.is_none() {
                        break;
                    }
                }
                Ok(None)
            };
            // One total budget, not 256 independent five-second waits. This
            // cancels only a read-only preview; the original callback remains
            // pending and can still be explicitly declined on this connection.
            match tokio::time::timeout(REQUEST_TIMEOUT, preview).await {
                Ok(Ok(Some(preview))) => {
                    details.push_str("\nOriginal proposed changes:\n");
                    details.push_str(&preview);
                    can_accept = true;
                }
                Ok(Err(error @ (TextSessionError::Identity | TextSessionError::Fenced))) => {
                    return Err(error);
                }
                Ok(Ok(None)) | Ok(Err(_)) | Err(_) => {
                    details.push_str("\nOriginal file preview is incomplete or exceeded its total deadline. Approval is disabled; you can still decline this pending request.");
                }
            }
        }
        if details.len() > 8192 {
            can_accept = false;
            details = "Original request is too large to review completely here. Approval remains disabled; use the original approval client or decline this request.".into();
        }
        let mut state = self.shared.current()?;
        if let Some(old) = state.approvals.get(&id) {
            if old.request != *request {
                return Err(TextSessionError::Identity);
            }
            if old.responding {
                return Ok(unsupported(
                    "Waiting for the original request-resolution observation",
                ));
            }
        } else if state.approvals.len() >= 16 {
            return Ok(unsupported(
                "Original pending approval capacity reached; the original owner retains this request",
            ));
        }
        state.approvals.insert(
            id.clone(),
            PendingApproval {
                request: request.clone(),
                can_accept,
                responding: false,
            },
        );
        Ok(TextApprovalObservation::Pending(TextApproval {
            connection_id: self.connection_id(),
            id,
            thread_id: thread.clone(),
            turn_id: turn.clone(),
            item_id: item.clone(),
            title: title.into(),
            details,
            can_accept,
            can_decline: true,
        }))
    }

    pub(super) async fn resolve_approval(
        &self,
        connection_id: u64,
        id: &str,
        decision: TextApprovalDecision,
    ) -> Result<(), TextSessionError> {
        if connection_id != self.connection_id() {
            return Err(TextSessionError::Identity);
        }
        self.check_current_ingress().await?;
        let (request_id, response) = {
            let mut state = self.shared.current()?;
            let pending = state
                .approvals
                .get_mut(id)
                .ok_or(TextSessionError::UnknownRequest)?;
            if pending.responding
                || (decision == TextApprovalDecision::AcceptOnce && !pending.can_accept)
            {
                return Err(TextSessionError::Identity);
            }
            let response = match &pending.request {
                ServerRequest::CommandExecutionRequestApproval { .. } => {
                    serde_json::to_value(CommandExecutionRequestApprovalResponse {
                        decision: match decision {
                            TextApprovalDecision::AcceptOnce => {
                                CommandExecutionApprovalDecision::Accept
                            }
                            TextApprovalDecision::Decline => {
                                CommandExecutionApprovalDecision::Decline
                            }
                        },
                    })
                }
                ServerRequest::FileChangeRequestApproval { .. } => {
                    serde_json::to_value(FileChangeRequestApprovalResponse {
                        decision: match decision {
                            TextApprovalDecision::AcceptOnce => FileChangeApprovalDecision::Accept,
                            TextApprovalDecision::Decline => FileChangeApprovalDecision::Decline,
                        },
                    })
                }
                _ => return Err(TextSessionError::Identity),
            }
            .map_err(unavailable)?;
            pending.responding = true;
            (pending.request.id().clone(), response)
        };
        // A successful write is not an effect or completion receipt. The
        // original serverRequest/resolved observation closes this UI prompt.
        tokio::time::timeout(
            REQUEST_TIMEOUT,
            self.handle.resolve_server_request(request_id, response),
        )
        .await
        .map_err(unavailable)?
        .map_err(unavailable)
    }
}
