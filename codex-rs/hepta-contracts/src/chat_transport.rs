//! Bounded chat wire contract. A session identifier is correlation, never authorization.
//! Hosts must authenticate the caller before dispatch and discard stale generations.
use serde::Deserialize;
use serde::Serialize;

pub const MAX_CHAT_TEXT_BYTES: usize = 16_384;
pub const MAX_CHAT_PAGE: u32 = 50;
pub const MAX_CHAT_FRAME_BYTES: usize = 1_048_576;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ChatRequest {
    pub session_id: String,
    pub connection_generation: u64,
    pub command: ChatCommand,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum ChatCommand {
    List {
        cursor: Option<String>,
        limit: u32,
    },
    Create,
    Timeline {
        thread_id: String,
        cursor: Option<String>,
        limit: u32,
    },
    Resume {
        thread_id: String,
    },
    Send {
        thread_id: String,
        operation_id: String,
        text: String,
    },
    Reconcile {
        thread_id: String,
        operation_id: String,
        text: String,
    },
    Cancel {
        thread_id: String,
        turn_id: String,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ChatResponse {
    pub session_id: String,
    pub connection_generation: u64,
    pub result: ChatResult,
    /// This surface declines privileged approval requests instead of granting them.
    pub approval_required: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum ChatResult {
    Conversations {
        data: Vec<ChatConversation>,
        next_cursor: Option<String>,
    },
    Conversation {
        data: ChatConversation,
    },
    Timeline {
        thread_id: String,
        data: Vec<ChatMessage>,
        next_cursor: Option<String>,
        active_turn_id: Option<String>,
    },
    Submission {
        operation_id: String,
        state: SubmissionState,
    },
    CancelRequested {
        thread_id: String,
        turn_id: String,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum SubmissionState {
    Queued { queue_id: String },
    Persisted { turn_id: String },
    Missing,
    Cancelled,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ChatConversation {
    pub id: String,
    pub title: String,
    pub preview: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ChatMessage {
    pub id: String,
    pub turn_id: String,
    pub sender: String,
    pub body: String,
}

impl ChatRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        identity(&self.session_id)?;
        if self.connection_generation == 0 {
            return Err("invalid generation");
        }
        match &self.command {
            ChatCommand::Create => {}
            ChatCommand::List { cursor, limit } => page(cursor, *limit)?,
            ChatCommand::Timeline {
                thread_id,
                cursor,
                limit,
            } => {
                identity(thread_id)?;
                page(cursor, *limit)?;
            }
            ChatCommand::Resume { thread_id } => identity(thread_id)?,
            ChatCommand::Send {
                thread_id,
                operation_id,
                text,
            }
            | ChatCommand::Reconcile {
                thread_id,
                operation_id,
                text,
            } => {
                identity(thread_id)?;
                identity(operation_id)?;
                if text.trim().is_empty() || text.len() > MAX_CHAT_TEXT_BYTES || text.contains('\0')
                {
                    return Err("invalid message");
                }
            }
            ChatCommand::Cancel { thread_id, turn_id } => {
                identity(thread_id)?;
                identity(turn_id)?;
            }
        }
        Ok(())
    }
}

fn identity(value: &str) -> Result<(), &'static str> {
    if value.is_empty() || value.len() > 256 || value.chars().any(char::is_control) {
        Err("invalid identity")
    } else {
        Ok(())
    }
}
fn page(cursor: &Option<String>, limit: u32) -> Result<(), &'static str> {
    if limit == 0
        || limit > MAX_CHAT_PAGE
        || cursor
            .as_ref()
            .is_some_and(|value| value.len() > 4096 || value.chars().any(char::is_control))
    {
        Err("invalid page")
    } else {
        Ok(())
    }
}

impl ChatResponse {
    pub fn validate_for(&self, request: &ChatRequest) -> Result<(), &'static str> {
        request.validate()?;
        if self.session_id != request.session_id
            || self.connection_generation != request.connection_generation
        {
            return Err("stale response");
        }
        match (&request.command, &self.result) {
            (ChatCommand::List { limit, .. }, ChatResult::Conversations { data, next_cursor }) => {
                page(next_cursor, *limit)?;
                if data.len() > *limit as usize {
                    return Err("oversized page");
                }
                let mut seen = std::collections::BTreeSet::new();
                for row in data {
                    conversation_valid(row)?;
                    if !seen.insert(&row.id) {
                        return Err("duplicate conversation");
                    }
                }
            }
            (ChatCommand::Create, ChatResult::Conversation { data }) => conversation_valid(data)?,
            (ChatCommand::Resume { thread_id }, ChatResult::Conversation { data }) => {
                conversation_valid(data)?;
                if &data.id != thread_id {
                    return Err("wrong conversation");
                }
            }
            (
                ChatCommand::Timeline {
                    thread_id, limit, ..
                },
                ChatResult::Timeline {
                    thread_id: actual,
                    data,
                    next_cursor,
                    active_turn_id,
                },
            ) => {
                if actual != thread_id || data.len() > *limit as usize {
                    return Err("wrong timeline");
                }
                page(next_cursor, *limit)?;
                if let Some(id) = active_turn_id {
                    identity(id)?;
                }
                let mut seen = std::collections::BTreeSet::new();
                for message in data {
                    identity(&message.id)?;
                    identity(&message.turn_id)?;
                    if !seen.insert(&message.id)
                        || !matches!(message.sender.as_str(), "user" | "assistant")
                        || message.body.len() > MAX_CHAT_TEXT_BYTES
                    {
                        return Err("invalid message");
                    }
                }
            }
            (
                ChatCommand::Send { operation_id, .. }
                | ChatCommand::Reconcile { operation_id, .. },
                ChatResult::Submission {
                    operation_id: actual,
                    state,
                },
            ) => {
                if operation_id != actual {
                    return Err("wrong operation");
                }
                match state {
                    SubmissionState::Queued { queue_id } => identity(queue_id)?,
                    SubmissionState::Persisted { turn_id } => identity(turn_id)?,
                    SubmissionState::Missing | SubmissionState::Cancelled => {}
                }
            }
            (
                ChatCommand::Cancel { thread_id, turn_id },
                ChatResult::CancelRequested {
                    thread_id: actual_thread,
                    turn_id: actual_turn,
                },
            ) => {
                if thread_id != actual_thread || turn_id != actual_turn {
                    return Err("wrong cancellation");
                }
            }
            _ => return Err("wrong result kind"),
        }
        Ok(())
    }
}
fn conversation_valid(value: &ChatConversation) -> Result<(), &'static str> {
    identity(&value.id)?;
    if value.title.len() > MAX_CHAT_TEXT_BYTES || value.preview.len() > MAX_CHAT_TEXT_BYTES {
        Err("oversized conversation")
    } else {
        Ok(())
    }
}
