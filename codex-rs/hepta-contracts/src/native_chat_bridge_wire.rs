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
}

impl NativeChatRootRequest {
    pub fn binding(&self) -> &NativeChatBinding {
        match self {
            Self::Attach { binding, .. } | Self::Dispatch { binding, .. } => binding,
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
    Rejected {
        code: String,
        outcome_unknown: bool,
    },
}

impl NativeChatRootResponse {
    pub fn validate_for(&self, request: &NativeChatRootRequest) -> Result<(), &'static str> {
        request.validate()?;
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
            (Self::Rejected { code, .. }, _)
                if !code.is_empty() && code.len() <= 128 && !code.chars().any(char::is_control) =>
            {
                Ok(())
            }
            _ => Err("chat response does not bind the displayed instance and original request"),
        }
    }
}
