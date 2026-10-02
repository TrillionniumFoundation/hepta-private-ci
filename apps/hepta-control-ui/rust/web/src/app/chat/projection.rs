//! Validated chat observations; no request dispatch or optimistic timeline writes.
use super::*;

pub(super) fn apply(
    state: &mut BrowserApp,
    request: &ChatRequest,
    result: Result<ChatResponse, ControlError>,
    selection_epoch: u64,
    page_epoch: u64,
) {
    match result {
        Ok(response)
            if response.validate_for(request).is_ok()
                && response.session_id == request.session_id
                && response.connection_generation == request.connection_generation =>
        {
            state.chat.availability = ChatAvailability::Ready;
            state.chat_host.note =
                "Messages shown are backend observations. Refresh to load updates.".into();
            let approval_required = response.approval_required;
            match response.result {
                ChatResult::Conversations { data, .. } => {
                    state.chat.conversations = data
                        .into_iter()
                        .take(50)
                        .map(|r| Conversation {
                            id: r.id,
                            title: r.title,
                            preview: r.preview,
                            unread: 0,
                        })
                        .collect();
                }
                ChatResult::Conversation { data } => {
                    let id = data.id.clone();
                    state.chat.conversations.insert(
                        0,
                        Conversation {
                            id: data.id,
                            title: data.title,
                            preview: data.preview,
                            unread: 0,
                        },
                    );
                    state.chat.conversations.truncate(50);
                    if state.chat.selection_epoch == selection_epoch {
                        state.chat.select(&id);
                        state.chat_host.show_list = false;
                        state.chat.page.next_cursor = None;
                        state.chat.page.cursor = None;
                    }
                }
                ChatResult::Timeline {
                    thread_id,
                    data,
                    active_turn_id,
                    next_cursor,
                } => {
                    let cursor = if let ChatCommand::Timeline { cursor, .. } = &request.command {
                        cursor.clone()
                    } else {
                        None
                    };
                    if state.chat.observe_timeline_page(
                        &thread_id,
                        selection_epoch,
                        page_epoch,
                        cursor,
                        next_cursor,
                        data.into_iter()
                            .map(|m| Message {
                                id: m.id,
                                sender: m.sender,
                                body: m.body,
                                timestamp: String::new(),
                            })
                            .collect(),
                    ) {
                        state.chat_host.turn = active_turn_id.map(|turn| (thread_id, turn));
                    }
                }
                ChatResult::Submission {
                    operation_id,
                    state: observation,
                } => {
                    let expected = match &request.command {
                        ChatCommand::Send { operation_id, .. }
                        | ChatCommand::Reconcile { operation_id, .. } => Some(operation_id),
                        _ => None,
                    };
                    if expected != Some(&operation_id) {
                        state.chat_host.note =
                            "Messaging returned a mismatched operation. Original send retained."
                                .into();
                    } else {
                        match observation {
                            SubmissionState::Queued { .. } => {
                                state.chat_host.note = "Queued by the server. Check send to observe persistence; no reply is implied.".into();
                            }
                            SubmissionState::Persisted { .. } => {
                                if let SubmissionState::Persisted { turn_id } = &observation
                                    && let ChatCommand::Send { thread_id, .. }
                                    | ChatCommand::Reconcile { thread_id, .. } = &request.command
                                {
                                    state.chat_host.turn =
                                        Some((thread_id.clone(), turn_id.clone()));
                                }
                                state.chat_host.pending = None;
                                if let ChatCommand::Send {
                                    thread_id, text, ..
                                }
                                | ChatCommand::Reconcile {
                                    thread_id, text, ..
                                } = &request.command
                                {
                                    if state.chat.selected.as_ref() == Some(thread_id)
                                        && state.chat.draft == *text
                                    {
                                        state.chat.draft.clear();
                                    }
                                    if state.chat.drafts.get(thread_id) == Some(text) {
                                        state.chat.drafts.remove(thread_id);
                                    }
                                }
                                state.chat_host.note = "Accepted by the conversation queue. Refresh to observe the reply.".into();
                            }
                            SubmissionState::Missing => {
                                state.chat_host.note = "Not observed yet. Reconcile the original message; do not resend.".into();
                            }
                            SubmissionState::Cancelled => {
                                state.chat_host.pending = None;
                                state.chat_host.note =
                                    "The original submission was cancelled.".into();
                            }
                        }
                    }
                }
                ChatResult::CancelRequested { .. } => {
                    state.chat_host.turn = None;
                    state.chat_host.note =
                        "Cancellation requested. Refresh to observe the final state.".into();
                }
            }
            if approval_required {
                state.chat_host.note = "The server requested approval. This chat surface declined it; use an approval-capable client to continue.".into();
            }
        }
        Ok(_) => {
            state.chat.page.failed(page_epoch);
            state.chat.availability = ChatAvailability::Failed;
            state.chat_host.note =
                "Messaging response belongs to a different session. Content discarded.".into();
        }
        Err(error) => {
            state.chat.page.failed(page_epoch);
            if matches!(request.command, ChatCommand::Send { .. })
                && (error.request_dispatched == Some(false)
                    || matches!(
                        error.code,
                        ErrorCode::BackendRejected
                            | ErrorCode::PermissionDenied
                            | ErrorCode::SessionExpired
                            | ErrorCode::SessionRevoked
                    ))
            {
                state.chat_host.pending = None;
            }
            let status = error.details.get("status").and_then(Value::as_u64);
            state.chat.availability = if matches!(status, Some(404 | 501)) {
                ChatAvailability::Unavailable
            } else {
                ChatAvailability::Failed
            };
            state.chat_host.note = if state.chat_host.pending.is_some() {
                "Send outcome unknown. Reconcile the original message before sending again."
            } else {
                "Messaging transport is unavailable. Nothing will be sent."
            }
            .into();
        }
    }
}
