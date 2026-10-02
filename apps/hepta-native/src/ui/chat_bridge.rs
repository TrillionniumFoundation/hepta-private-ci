//! UI task admission and observation projection for the separate chat owner.
use super::*;
use crate::chat_runtime::wire::{ChatCommand, ChatResult, MAX_CHAT_PAGE, SubmissionState};
use crate::chat_runtime::{ChatConfig, ChatRuntime};
use std::collections::VecDeque;

#[derive(Default)]
pub(super) struct ChatBridge {
    runtime: Option<ChatRuntime>,
    config: Option<ChatConfig>,
    pending: VecDeque<(ChatCommand, u64, u64)>,
    pub(super) error: Option<String>,
    submission: Option<(String, String, String)>,
    next_poll: Option<Instant>,
    pub(super) list_cursor: Option<String>,
    pub(super) active_turn: Option<String>,
}

impl chat_app::ChatShell {
    pub fn configure_chat(&mut self, config: ChatConfig) -> Result<(), String> {
        let mut nonce = [0u8; 16];
        getrandom::fill(&mut nonce).map_err(|_| "Cannot create chat session identifier")?;
        let session = nonce
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let runtime = ChatRuntime::spawn(config.clone(), session)?;
        if self.chat_bridge.config.as_ref().is_some_and(|old| {
            old.agent_id != config.agent_id
                || old.generation != config.generation
                || old.project_id != config.project_id
                || old.workspace != config.workspace
                || old.agentd_socket != config.agentd_socket
        }) {
            self.chat.reset_session();
            self.chat_bridge.submission = None;
        }
        self.chat_bridge.runtime = Some(runtime);
        self.chat_bridge.config = Some(config);
        self.chat_bridge.pending.clear();
        self.chat_bridge.error = None;
        self.chat.availability = chat_model::ChatAvailability::Loading;
        self.request_chat(ChatCommand::List {
            cursor: None,
            limit: MAX_CHAT_PAGE,
        })
    }

    pub(super) fn request_chat(&mut self, command: ChatCommand) -> Result<(), String> {
        if self
            .chat_bridge
            .pending
            .iter()
            .any(|(pending, _, _)| pending == &command)
        {
            return Ok(());
        }
        let runtime = self
            .chat_bridge
            .runtime
            .as_ref()
            .ok_or("Messaging is not configured")?;
        runtime.request(command.clone())?;
        let page_epoch = if matches!(command, ChatCommand::Timeline { .. }) {
            self.chat.page.begin()
        } else {
            self.chat.page.epoch
        };
        self.chat_bridge
            .pending
            .push_back((command, self.chat.selection_epoch, page_epoch));
        Ok(())
    }

    pub(super) fn select_chat(&mut self, id: &str) {
        if self.chat.select(id) {
            self.chat_show_list = false;
            self.chat_bridge.active_turn = None;
            if let Err(error) = self.request_chat(ChatCommand::Resume {
                thread_id: id.into(),
            }) {
                self.chat_bridge.error = Some(error);
            }
        }
    }

    pub(super) fn timeline_page(&mut self, cursor: Option<String>) {
        if let Some(thread_id) = self.chat.selected.clone()
            && let Err(error) = self.request_chat(ChatCommand::Timeline {
                thread_id,
                cursor,
                limit: MAX_CHAT_PAGE,
            })
        {
            self.chat_bridge.error = Some(error);
        }
    }

    pub(super) fn refresh_chats(&mut self, cursor: Option<String>) {
        if let Err(error) = self.request_chat(ChatCommand::List {
            cursor,
            limit: MAX_CHAT_PAGE,
        }) {
            self.chat_bridge.error = Some(error);
        }
    }

    pub(super) fn stop_chat(&mut self) {
        if let (Some(thread_id), Some(turn_id)) = (
            self.chat.selected.clone(),
            self.chat_bridge.active_turn.clone(),
        ) && let Err(error) = self.request_chat(ChatCommand::Cancel { thread_id, turn_id })
        {
            self.chat_bridge.error = Some(error);
        }
    }

    pub(super) fn create_chat(&mut self) {
        if let Err(error) = self.request_chat(ChatCommand::Create) {
            self.chat_bridge.error = Some(error);
        }
    }

    pub(super) fn retry_chat(&mut self) {
        if let Some(config) = self.chat_bridge.config.clone()
            && let Err(error) = self.configure_chat(config)
        {
            self.chat_bridge.error = Some(error);
        }
    }

    pub(super) fn send_chat(&mut self) {
        if !self.chat.can_send() || self.chat_bridge.submission.is_some() {
            return;
        }
        let Some(thread) = self.chat.selected.clone() else {
            return;
        };
        let text = self.chat.draft.clone();
        let mut nonce = [0u8; 16];
        if getrandom::fill(&mut nonce).is_err() {
            self.chat_bridge.error = Some("Cannot create message identity".into());
            return;
        }
        let operation = nonce
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        match self.request_chat(ChatCommand::Send {
            thread_id: thread.clone(),
            operation_id: operation.clone(),
            text: text.clone(),
        }) {
            Ok(()) => {
                self.chat.sending = true;
                self.chat_bridge.submission = Some((thread, operation, text));
            }
            Err(error) => self.chat_bridge.error = Some(error),
        }
    }

    pub(super) fn chat_transport_ready(&self) -> bool {
        self.chat_bridge.runtime.is_some()
            && self.chat.availability == chat_model::ChatAvailability::Ready
    }

    pub(super) fn poll_chat(&mut self, ctx: &egui::Context) {
        let responses = self
            .chat_bridge
            .runtime
            .as_ref()
            .map(ChatRuntime::poll)
            .unwrap_or_default();
        for response in responses {
            let Some((command, epoch, page_epoch)) = self.chat_bridge.pending.pop_front() else {
                continue;
            };
            match response {
                Ok(response) => {
                    self.chat.availability = chat_model::ChatAvailability::Ready;
                    if response.approval_required {
                        self.chat_bridge.error = Some("This turn requires tool approval. Open the authorized approval interface to review it; this chat surface does not grant permissions.".into());
                    }
                    self.apply_chat_result(response.result, command, epoch, page_epoch);
                }
                Err(error) => {
                    self.chat.availability = chat_model::ChatAvailability::Offline;
                    self.chat_bridge.error = Some(error);
                    self.chat_bridge.runtime = None;
                    self.chat_bridge.pending.clear();
                    self.chat.page.loading = false;
                    break;
                }
            }
        }
        if self.chat_bridge.runtime.is_some() {
            ctx.request_repaint_after(Duration::from_millis(100));
            if self.chat_bridge.pending.is_empty()
                && self
                    .chat_bridge
                    .next_poll
                    .is_none_or(|when| Instant::now() >= when)
            {
                let command = if let Some((thread, operation, text)) = &self.chat_bridge.submission
                {
                    Some(ChatCommand::Reconcile {
                        thread_id: thread.clone(),
                        operation_id: operation.clone(),
                        text: text.clone(),
                    })
                } else if self.chat.page.cursor.is_none() {
                    self.chat
                        .selected
                        .clone()
                        .map(|thread_id| ChatCommand::Timeline {
                            thread_id,
                            cursor: None,
                            limit: MAX_CHAT_PAGE,
                        })
                } else {
                    None
                };
                if let Some(command) = command
                    && let Err(error) = self.request_chat(command)
                {
                    self.chat_bridge.error = Some(error);
                }
                self.chat_bridge.next_poll = Some(Instant::now() + Duration::from_secs(1));
            }
        }
    }

    fn apply_chat_result(
        &mut self,
        result: ChatResult,
        command: ChatCommand,
        epoch: u64,
        page_epoch: u64,
    ) {
        match result {
            ChatResult::Conversations { data, next_cursor } => {
                if matches!(command, ChatCommand::List { cursor: None, .. }) {
                    self.chat.conversations.clear();
                }
                self.chat_bridge.list_cursor = next_cursor;
                for room in data.into_iter().take(MAX_CHAT_PAGE as usize) {
                    if self.chat.conversations.len() < 200
                        && !self
                            .chat
                            .conversations
                            .iter()
                            .any(|existing| existing.id == room.id)
                    {
                        self.chat.conversations.push(chat_model::Conversation {
                            id: room.id,
                            title: room.title,
                            preview: room.preview,
                            unread: 0,
                        });
                    }
                }
            }
            ChatResult::Conversation { data } => {
                let id = data.id.clone();
                if let Some(existing) = self
                    .chat
                    .conversations
                    .iter_mut()
                    .find(|room| room.id == id)
                {
                    existing.title = data.title;
                    existing.preview = data.preview;
                } else {
                    self.chat.conversations.push(chat_model::Conversation {
                        id: id.clone(),
                        title: data.title,
                        preview: data.preview,
                        unread: 0,
                    });
                }
                if matches!(command, ChatCommand::Create) {
                    self.chat.select(&id);
                    self.chat_bridge.active_turn = None;
                    self.chat_show_list = false;
                }
            }
            ChatResult::Timeline {
                thread_id,
                data,
                active_turn_id,
                next_cursor,
            } => {
                let messages = data
                    .into_iter()
                    .map(|message| chat_model::Message {
                        id: message.id,
                        sender: message.sender,
                        body: message.body,
                        timestamp: String::new(),
                    })
                    .collect();
                if let ChatCommand::Timeline { cursor, .. } = command {
                    if self.chat.observe_timeline_page(
                        &thread_id,
                        epoch,
                        page_epoch,
                        cursor,
                        next_cursor,
                        messages,
                    ) {
                        self.chat_bridge.active_turn = active_turn_id;
                    } else if self.chat.selected.as_deref() == Some(thread_id.as_str())
                        && epoch == self.chat.selection_epoch
                        && page_epoch == self.chat.page.epoch
                    {
                        self.chat.page.failed(page_epoch);
                        self.chat_bridge.error =
                            Some("Message page was invalid; the previous page is retained.".into());
                    }
                }
            }
            ChatResult::Submission {
                operation_id,
                state,
            } => {
                if let Some((thread, operation, text)) = &self.chat_bridge.submission
                    && operation == &operation_id
                {
                    match state {
                        SubmissionState::Persisted { .. } => {
                            if self.chat.selected.as_ref() == Some(thread)
                                && &self.chat.draft == text
                            {
                                self.chat.draft.clear();
                            }
                            if self.chat.drafts.get(thread) == Some(text) {
                                self.chat.drafts.remove(thread);
                            }
                            self.chat_bridge.submission = None;
                            self.chat.sending = false;
                        }
                        SubmissionState::Queued { .. } => {}
                        SubmissionState::Missing => {
                            self.chat_bridge.error = Some("Message delivery is not confirmed. The original send identity and draft are retained; checking status does not send it again.".into());
                        }
                        SubmissionState::Cancelled => {
                            self.chat_bridge.error = Some(
                                "The server cancelled this submission. Your draft is retained."
                                    .into(),
                            );
                            self.chat_bridge.submission = None;
                            self.chat.sending = false;
                        }
                    }
                }
            }
            ChatResult::CancelRequested { .. } => {}
        }
    }
}

#[cfg(test)]
#[path = "chat_bridge_tests.rs"]
mod tests;
