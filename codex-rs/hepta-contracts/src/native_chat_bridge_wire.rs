//! Finite native chat bridge wire. A copied control fence is an observation,
//! never permission: the Root host compares it with the current original owner.
use serde::Deserialize;
use serde::Serialize;

use crate::chat_transport::ChatRequest;
use crate::chat_transport::ChatResponse;

pub const MAX_NATIVE_CHAT_REQUEST_BYTES: usize = 65_536;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NativeChatBinding {
    pub agent_id: String,
    pub supervisor_process_id: u32,
    pub agent_process_id: u32,
    pub control_fence: serde_json::Value,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum NativeChatRootRequest {
    Attach {
        binding: NativeChatBinding,
        session_id: String,
    },
    Dispatch {
        binding: NativeChatBinding,
        request: ChatRequest,
    },
    /// A current authenticated owner may recover the exact old operation,
    /// never replay it or rebind its original mutation to another process.
    Recover {
        binding: NativeChatBinding,
        original_binding: NativeChatBinding,
        request: ChatRequest,
    },
    /// Explicitly abandon only this creation's original pre-effect reservation.
    AbandonCreation {
        binding: NativeChatBinding,
        original_binding: NativeChatBinding,
        request: ChatRequest,
    },
}

impl NativeChatRootRequest {
    pub fn binding(&self) -> &NativeChatBinding {
        match self {
            Self::Attach { binding, .. }
            | Self::Dispatch { binding, .. }
            | Self::Recover { binding, .. }
            | Self::AbandonCreation { binding, .. } => binding,
        }
    }

    pub fn validate(&self) -> Result<(), &'static str> {
        let binding = self.binding();
        if binding.agent_id.len() != 36
            || binding.supervisor_process_id == 0
            || binding.agent_process_id == 0
            || !binding.control_fence.is_object()
            || serde_json::to_vec(&binding.control_fence)
                .map_err(|_| "invalid fence")?
                .len()
                > 8192
        {
            return Err("invalid original owner binding");
        }
        match self {
            Self::Attach { session_id, .. } => {
                if session_id.is_empty()
                    || session_id.len() > 256
                    || session_id.chars().any(char::is_control)
                {
                    return Err("invalid session correlation");
                }
            }
            Self::Dispatch { request, .. } => request.validate()?,
            Self::Recover {
                original_binding,
                request,
                ..
            }
            | Self::AbandonCreation {
                original_binding,
                request,
                ..
            } => {
                Self::Attach {
                    binding: original_binding.clone(),
                    session_id: request.session_id.clone(),
                }
                .validate()?;
                request.validate()?;
                if original_binding.agent_id != binding.agent_id
                    || !matches!(
                        request.command,
                        crate::chat_transport::ChatCommand::Send { .. }
                            | crate::chat_transport::ChatCommand::CreateOnce { .. }
                    )
                {
                    return Err(
                        "recovery requires an identified original operation and stable Agent",
                    );
                }
                if matches!(self, Self::AbandonCreation { .. })
                    && !matches!(
                        request.command,
                        crate::chat_transport::ChatCommand::CreateOnce { .. }
                    )
                {
                    return Err("abandonment requires the exact identified original creation");
                }
            }
        }
        if serde_json::to_vec(self)
            .map_err(|_| "invalid request")?
            .len()
            >= MAX_NATIVE_CHAT_REQUEST_BYTES
        {
            return Err("oversized native chat request");
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum NativeChatRootResponse {
    Attached {
        binding: NativeChatBinding,
        session_id: String,
        connection_generation: u64,
    },
    Response {
        binding: NativeChatBinding,
        response: ChatResponse,
    },
    Recovered {
        binding: NativeChatBinding,
        original_binding: NativeChatBinding,
        request: ChatRequest,
        observation: MessageObservation,
    },
    CreationRecovered {
        binding: NativeChatBinding,
        original_binding: NativeChatBinding,
        request: ChatRequest,
        observation: CreationObservation,
    },
    Rejected {
        code: String,
        outcome_unknown: bool,
    },
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum MessageObservation {
    Pending { queue_id: Option<String> },
    Persisted { turn_id: String },
    Cancelled,
    Missing,
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum CreationObservation {
    Pending {
        thread_id: String,
    },
    Materialized {
        thread_id: String,
    },
    Created {
        data: crate::chat_transport::ChatConversation,
    },
    Deleted {
        thread_id: String,
    },
    Abandoned {
        thread_id: String,
    },
    Missing,
    Unknown,
}

impl NativeChatRootResponse {
    pub fn validate_for(&self, request: &NativeChatRootRequest) -> Result<(), &'static str> {
        request.validate()?;
        let abandoning = matches!(request, NativeChatRootRequest::AbandonCreation { .. });
        match (self, request) {
            (
                Self::Attached {
                    binding,
                    session_id,
                    connection_generation,
                },
                NativeChatRootRequest::Attach {
                    binding: expected,
                    session_id: expected_session,
                },
            ) if binding == expected
                && session_id == expected_session
                && *connection_generation != 0 =>
            {
                Ok(())
            }
            (
                Self::Response { binding, response },
                NativeChatRootRequest::Dispatch {
                    binding: expected,
                    request,
                },
            ) if binding == expected => response.validate_for(request),
            (
                Self::Recovered {
                    binding,
                    original_binding,
                    request,
                    observation,
                },
                NativeChatRootRequest::Recover {
                    binding: expected,
                    original_binding: expected_original,
                    request: expected_request,
                },
            ) if binding == expected
                && original_binding == expected_original
                && request == expected_request
                && matches!(
                    request.command,
                    crate::chat_transport::ChatCommand::Send { .. }
                ) =>
            {
                let id = match observation {
                    MessageObservation::Pending { queue_id } => queue_id.as_deref(),
                    MessageObservation::Persisted { turn_id } => Some(turn_id.as_str()),
                    MessageObservation::Cancelled
                    | MessageObservation::Missing
                    | MessageObservation::Unknown => None,
                };
                if id.is_some_and(|id| {
                    id.is_empty() || id.len() > 256 || id.chars().any(char::is_control)
                }) {
                    return Err("invalid observed message identity");
                }
                Ok(())
            }
            (
                Self::CreationRecovered {
                    binding,
                    original_binding,
                    request,
                    observation,
                },
                NativeChatRootRequest::Recover {
                    binding: expected,
                    original_binding: expected_original,
                    request: expected_request,
                }
                | NativeChatRootRequest::AbandonCreation {
                    binding: expected,
                    original_binding: expected_original,
                    request: expected_request,
                },
            ) if binding == expected
                && original_binding == expected_original
                && request == expected_request
                && matches!(
                    request.command,
                    crate::chat_transport::ChatCommand::CreateOnce { .. }
                )
                && (!abandoning
                    || matches!(observation, CreationObservation::Abandoned { .. })) =>
            {
                let id = match observation {
                    CreationObservation::Pending { thread_id }
                    | CreationObservation::Materialized { thread_id }
                    | CreationObservation::Deleted { thread_id }
                    | CreationObservation::Abandoned { thread_id } => Some(thread_id.as_str()),
                    CreationObservation::Created { data } => {
                        if data.title.len() > 512 || data.preview.len() > 4096 {
                            return Err("oversized original creation observation");
                        }
                        Some(data.id.as_str())
                    }
                    CreationObservation::Missing | CreationObservation::Unknown => None,
                };
                if id.is_some_and(|id| {
                    id.is_empty() || id.len() > 256 || id.chars().any(char::is_control)
                }) {
                    return Err("invalid observed creation identity");
                }
                Ok(())
            }
            (Self::Rejected { code, .. }, _)
                if !code.is_empty() && code.len() <= 128 && !code.chars().any(char::is_control) =>
            {
                Ok(())
            }
            _ => Err("chat response does not bind the displayed instance and original request"),
        }
    }
}
