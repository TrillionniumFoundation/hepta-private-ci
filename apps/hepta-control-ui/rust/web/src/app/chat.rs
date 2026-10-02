//! Authenticated same-origin chat host. Never infer delivery from request completion.
use super::*;
use hepta_control_core::{
    chat::{ChatAvailability, Conversation, Message},
    chat_transport::{ChatCommand, ChatRequest, ChatResponse, ChatResult, SubmissionState},
};
use web_sys::{HtmlInputElement, HtmlTextAreaElement};

pub(super) struct ChatHost {
    pub note: String,
    pub show_list: bool,
    busy: bool,
    pending: Option<ChatCommand>,
    turn: Option<(String, String)>,
}

impl Default for ChatHost {
    fn default() -> Self {
        Self {
            note: String::new(),
            show_list: true,
            busy: false,
            pending: None,
            turn: None,
        }
    }
}

pub(super) fn attach(
    app: &Rc<RefCell<BrowserApp>>,
    document: &Document,
) -> Result<(), ControlError> {
    let weak = Rc::downgrade(app);
    listen(
        app,
        element(document, "chat-back")?.as_ref(),
        "click",
        move |_| {
            if let Some(app) = weak.upgrade() {
                let mut state = app.borrow_mut();
                state.chat_host.show_list = true;
                state.render();
            }
        },
    )?;
    for (id, input) in [("room-filter", true), ("message-draft", false)] {
        let weak = Rc::downgrade(app);
        listen(
            app,
            element(document, id)?.as_ref(),
            "input",
            move |event| {
                if let Some(app) = weak.upgrade() {
                    let mut state = app.borrow_mut();
                    if state.destroyed {
                        return;
                    }
                    if input {
                        if let Some(node) = event
                            .target()
                            .and_then(|n| n.dyn_into::<HtmlInputElement>().ok())
                        {
                            state.chat.filter = node.value();
                        }
                    } else if let Some(node) = event
                        .target()
                        .and_then(|n| n.dyn_into::<HtmlTextAreaElement>().ok())
                    {
                        state.chat.draft = node.value();
                    }
                    state.render();
                }
            },
        )?;
    }
    for id in [
        "chat-refresh",
        "new-conversation",
        "send-message",
        "reconcile-message",
        "cancel-message",
    ] {
        let weak = Rc::downgrade(app);
        listen(app, element(document, id)?.as_ref(), "click", move |_| {
            if let Some(app) = weak.upgrade() {
                spawn_local(async move {
                    match id {
                        "chat-refresh" => load(app).await,
                        "new-conversation" => execute(app, ChatCommand::Create).await,
                        "send-message" => send(app).await,
                        "reconcile-message" => {
                            let command = app.borrow().chat_host.pending.clone();
                            if let Some(ChatCommand::Send {
                                thread_id,
                                operation_id,
                                text,
                            }) = command
                            {
                                execute(
                                    app,
                                    ChatCommand::Reconcile {
                                        thread_id,
                                        operation_id,
                                        text,
                                    },
                                )
                                .await;
                            }
                        }
                        "cancel-message" => {
                            let turn = app.borrow().chat_host.turn.clone();
                            if let Some((thread_id, turn_id)) = turn {
                                execute(app, ChatCommand::Cancel { thread_id, turn_id }).await;
                            }
                        }
                        _ => {}
                    }
                });
            }
        })?;
    }
    let weak = Rc::downgrade(app);
    listen(
        app,
        element(document, "conversation-list")?.as_ref(),
        "click",
        move |event| {
            let Some(app) = weak.upgrade() else {
                return;
            };
            let id = event
                .target()
                .and_then(|n| n.dyn_into::<web_sys::Element>().ok())
                .and_then(|n| n.closest("[data-room]").ok().flatten())
                .and_then(|n| n.get_attribute("data-room"));
            if let Some(id) = id {
                let selected = {
                    let mut state = app.borrow_mut();
                    let selected = state.chat.select(&id);
                    if selected {
                        state.chat_host.show_list = false;
                    }
                    state.render();
                    selected
                };
                if selected {
                    spawn_local(execute(
                        app,
                        ChatCommand::Timeline {
                            thread_id: id,
                            cursor: None,
                            limit: 50,
                        },
                    ));
                }
            }
        },
    )?;
    Ok(())
}

pub(super) async fn load(app: Rc<RefCell<BrowserApp>>) {
    execute(
        app.clone(),
        ChatCommand::List {
            cursor: None,
            limit: 50,
        },
    )
    .await;
    let selected = app.borrow().chat.selected.clone();
    if let Some(thread_id) = selected {
        execute(
            app,
            ChatCommand::Timeline {
                thread_id,
                cursor: None,
                limit: 50,
            },
        )
        .await;
    }
}

pub(super) async fn poll(app: Rc<RefCell<BrowserApp>>) {
    let selected = {
        let state = app.borrow();
        if state.chat.availability != ChatAvailability::Ready
            || state.chat_host.busy
            || state.chat.tab != AppTab::Chat
        {
            return;
        }
        state.chat.selected.clone()
    };
    if let Some(thread_id) = selected {
        execute(
            app,
            ChatCommand::Timeline {
                thread_id,
                cursor: None,
                limit: 50,
            },
        )
        .await;
    }
}

async fn send(app: Rc<RefCell<BrowserApp>>) {
    let command = {
        let mut state = app.borrow_mut();
        if !state.chat.can_send() || state.chat_host.pending.is_some() {
            return;
        }
        let Some(thread_id) = state.chat.selected.clone() else {
            return;
        };
        let Ok(crypto) = state.window.crypto() else {
            return;
        };
        let command = ChatCommand::Send {
            thread_id,
            operation_id: format!("chat:{}", crypto.random_uuid()),
            text: state.chat.draft.clone(),
        };
        state.chat_host.pending = Some(command.clone());
        command
    };
    execute(app, command).await;
}

async fn execute(app: Rc<RefCell<BrowserApp>>, command: ChatCommand) {
    let prepared = {
        let mut state = app.borrow_mut();
        if state.destroyed || state.chat_host.busy {
            return;
        }
        let view = state.core.view(now());
        let (Some(session_id), Some(connection_generation)) =
            (view.session_id, view.connection_generation)
        else {
            return;
        };
        if !view.connected {
            return;
        }
        let request = ChatRequest {
            session_id,
            connection_generation,
            command: command.clone(),
        };
        if request.validate().is_err() {
            return;
        }
        state.chat_host.busy = true;
        state.chat.sending = true;
        state.chat_host.note = "Contacting messaging service…".into();
        if matches!(command, ChatCommand::List { .. }) {
            state.chat.availability = ChatAvailability::Loading;
        }
        state.render();
        (
            request,
            state.transport.clone(),
            state.lifecycle.signal(),
            state.epoch,
            state.chat.selection_epoch,
        )
    };
    let (request, transport, signal, epoch, selection_epoch) = prepared;
    let result = match serde_json::to_value(&request) {
        Ok(body) => transport.chat(&body, Some(signal)).await.and_then(|v| {
            serde_json::from_value::<ChatResponse>(v).map_err(|_| ControlError::invalid())
        }),
        Err(_) => Err(ControlError::invalid()),
    };
    let mut state = app.borrow_mut();
    if state.active(epoch).is_err() {
        return;
    }
    let current = state.core.view(now());
    if current.session_id.as_deref() != Some(&request.session_id)
        || current.connection_generation != Some(request.connection_generation)
    {
        return;
    }
    state.chat_host.busy = false;
    state.chat.sending = false;
    match result {
        Ok(response)
            if response.validate_for(&request).is_ok()
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
                    }
                }
                ChatResult::Timeline {
                    thread_id,
                    data,
                    active_turn_id,
                    ..
                } => {
                    if state.chat.selected.as_ref() == Some(&thread_id)
                        && state.chat.selection_epoch == selection_epoch
                    {
                        state.chat_host.turn = active_turn_id.map(|turn| (thread_id.clone(), turn));
                    }
                    state.chat.observe_messages(
                        &thread_id,
                        selection_epoch,
                        data.into_iter()
                            .map(|m| Message {
                                id: m.id,
                                sender: m.sender,
                                body: m.body,
                                timestamp: String::new(),
                            })
                            .collect(),
                    );
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
            state.chat.availability = ChatAvailability::Failed;
            state.chat_host.note =
                "Messaging response belongs to a different session. Content discarded.".into();
        }
        Err(error) => {
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
    state.chat.sending = state.chat_host.pending.is_some();
    state.render();
}

pub(super) fn render_actions(document: &Document, host: &ChatHost) {
    for (id, disabled) in [
        ("reconcile-message", host.pending.is_none()),
        ("cancel-message", host.turn.is_none()),
    ] {
        if let Ok(node) =
            element(document, id).and_then(crate::dom::cast::<web_sys::HtmlButtonElement>)
        {
            node.set_disabled(disabled || host.busy);
            node.set_hidden(disabled);
        }
    }
}
