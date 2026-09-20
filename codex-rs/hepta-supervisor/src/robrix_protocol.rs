//! Backend-owned, read-only projection of the supervisord control protocol.
//!
//! The administrator protocol deliberately retains lifecycle mutations.  This
//! projection is a separate capability surface for Robrix and therefore has no
//! mutation request constructor and no mutation-success response variant.

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use serde::Deserialize;
use serde::Serialize;

use crate::daemon_protocol::MAX_SUPERVISORD_ROSTER;
use crate::daemon_protocol::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use crate::daemon_protocol::SupervisordAgentStatus;
use crate::daemon_protocol::SupervisordHealth;
use crate::daemon_protocol::SupervisordMatrixStatus;
use crate::daemon_protocol::SupervisordMethod;
use crate::daemon_protocol::SupervisordPayload;
use crate::daemon_protocol::SupervisordRequest;
use crate::daemon_protocol::SupervisordResponse;

pub const ROBRIX_SUPERVISORD_ALLOWED_METHODS: [&str; 3] = ["health", "roster", "snapshot"];

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RobrixSupervisordRequest {
    pub schema_version: u32,
    pub request_id: u64,
    pub method: RobrixSupervisordMethod,
}

impl RobrixSupervisordRequest {
    pub fn new(request_id: u64, method: RobrixSupervisordMethod) -> Self {
        Self {
            schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
            request_id,
            method,
        }
    }

    pub fn validate(&self) -> Result<(), RobrixProtocolError> {
        if self.schema_version != SUPERVISORD_CONTROL_SCHEMA_VERSION || self.request_id == 0 {
            return Err(RobrixProtocolError::InvalidEnvelope);
        }
        if let RobrixSupervisordMethod::Roster { limit } = self.method
            && !(1..=MAX_SUPERVISORD_ROSTER).contains(&limit)
        {
            return Err(RobrixProtocolError::InvalidRosterLimit);
        }
        Ok(())
    }
}

impl From<RobrixSupervisordRequest> for SupervisordRequest {
    fn from(request: RobrixSupervisordRequest) -> Self {
        let method = match request.method {
            RobrixSupervisordMethod::Health => SupervisordMethod::Health,
            RobrixSupervisordMethod::Roster { limit } => SupervisordMethod::Roster { limit },
            RobrixSupervisordMethod::Snapshot { agent_id } => {
                SupervisordMethod::Snapshot { agent_id }
            }
        };
        Self {
            schema_version: request.schema_version,
            request_id: request.request_id,
            method,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum RobrixSupervisordMethod {
    Health,
    Roster { limit: u16 },
    Snapshot { agent_id: AgentId },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RobrixSupervisordResponse {
    pub schema_version: u32,
    pub request_id: u64,
    pub payload: RobrixSupervisordPayload,
}

impl RobrixSupervisordResponse {
    pub fn validate(&self, expected_request_id: u64) -> Result<(), RobrixProtocolError> {
        if expected_request_id == 0
            || self.schema_version != SUPERVISORD_CONTROL_SCHEMA_VERSION
            || self.request_id != expected_request_id
        {
            return Err(RobrixProtocolError::InvalidEnvelope);
        }
        match &self.payload {
            RobrixSupervisordPayload::Health(health) => validate_health(health),
            RobrixSupervisordPayload::Roster { agents } => {
                if agents.len() > usize::from(MAX_SUPERVISORD_ROSTER) {
                    return Err(RobrixProtocolError::InvalidAgentStatus);
                }
                agents.iter().try_for_each(validate_agent_status)
            }
            RobrixSupervisordPayload::Agent(status) => validate_agent_status(status),
            RobrixSupervisordPayload::Error {
                code,
                message,
                actual,
            } => {
                validate_safe_code(code)?;
                validate_safe_message(message)?;
                if let Some(status) = actual {
                    validate_agent_status(status)?;
                }
                Ok(())
            }
        }
    }
}

impl TryFrom<SupervisordResponse> for RobrixSupervisordResponse {
    type Error = RobrixProtocolError;

    fn try_from(response: SupervisordResponse) -> Result<Self, Self::Error> {
        let payload = match response.payload {
            SupervisordPayload::Health(health) => RobrixSupervisordPayload::Health(health),
            SupervisordPayload::Roster { agents } => RobrixSupervisordPayload::Roster { agents },
            SupervisordPayload::Agent(status) => RobrixSupervisordPayload::Agent(status),
            SupervisordPayload::Error {
                code,
                message,
                actual,
            } => RobrixSupervisordPayload::Error {
                code,
                message,
                actual,
            },
            SupervisordPayload::MutationAccepted { .. } => {
                return Err(RobrixProtocolError::MutationPayloadForbidden);
            }
        };
        Ok(Self {
            schema_version: response.schema_version,
            request_id: response.request_id,
            payload,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum RobrixSupervisordPayload {
    Health(SupervisordHealth),
    Roster {
        agents: Vec<SupervisordAgentStatus>,
    },
    Agent(SupervisordAgentStatus),
    Error {
        code: String,
        message: String,
        actual: Option<SupervisordAgentStatus>,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum RobrixProtocolError {
    #[error("invalid Robrix control envelope")]
    InvalidEnvelope,
    #[error("invalid Robrix roster limit")]
    InvalidRosterLimit,
    #[error("invalid Robrix supervisord health")]
    InvalidHealth,
    #[error("invalid Robrix supervisord Agent status")]
    InvalidAgentStatus,
    #[error("unsafe Robrix control error")]
    UnsafeError,
    #[error("supervisord mutation payload is outside the Robrix projection")]
    MutationPayloadForbidden,
}

fn validate_health(health: &SupervisordHealth) -> Result<(), RobrixProtocolError> {
    if health.process_id == 0 {
        Err(RobrixProtocolError::InvalidHealth)
    } else {
        Ok(())
    }
}

fn validate_agent_status(status: &SupervisordAgentStatus) -> Result<(), RobrixProtocolError> {
    status
        .control_fence
        .validate()
        .map_err(|_| RobrixProtocolError::InvalidAgentStatus)?;
    validate_matrix_status(&status.matrix)?;
    if status.agent_id != status.control_fence.agent_id
        || status.lifecycle != status.control_fence.lifecycle
        || status.lifecycle_generation != status.control_fence.lifecycle_generation
        || status.spawn_generation != status.control_fence.spawn_generation
        || status.runtime_generation != status.control_fence.runtime_generation
        || status.current_release != status.control_fence.current_release
        || status.previous_release != status.control_fence.previous_release
        || status.release_change_pending != status.control_fence.release_change_pending
        || (status.healthy && (!status.active || status.lifecycle != AgentLifecycle::Running))
        || (status.matrix.active
            && (!status.active
                || status.lifecycle != AgentLifecycle::Running
                || status.matrix.attached_agent_generation != status.spawn_generation))
        || status.process_id == Some(0)
    {
        return Err(RobrixProtocolError::InvalidAgentStatus);
    }
    Ok(())
}

fn validate_matrix_status(status: &SupervisordMatrixStatus) -> Result<(), RobrixProtocolError> {
    let runtime_fields_present = status.process_id.is_some()
        && status.attached_agent_generation.is_some()
        && status.binding_revision.is_some();
    let runtime_fields_absent = status.process_id.is_none()
        && status.attached_agent_generation.is_none()
        && status.binding_revision.is_none();
    if status.active != runtime_fields_present
        || (!status.active && !runtime_fields_absent)
        || (status.healthy && (!status.configured || !status.active || status.degraded))
        || (!status.configured
            && (status.active
                || status.healthy
                || status.degraded
                || !runtime_fields_absent
                || status.last_error.is_some()))
        || status.process_id == Some(0)
        || status.attached_agent_generation == Some(0)
        || status.binding_revision == Some(0)
    {
        return Err(RobrixProtocolError::InvalidAgentStatus);
    }
    Ok(())
}

fn validate_safe_code(value: &str) -> Result<(), RobrixProtocolError> {
    if value.is_empty()
        || value.len() > 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
    {
        return Err(RobrixProtocolError::UnsafeError);
    }
    Ok(())
}

fn validate_safe_message(value: &str) -> Result<(), RobrixProtocolError> {
    if value.is_empty()
        || value.len() > 1_024
        || value.chars().any(|character| {
            character.is_control()
                || matches!(
                    character,
                    '\u{061c}'
                        | '\u{200e}'..='\u{200f}'
                        | '\u{202a}'..='\u{202e}'
                        | '\u{2066}'..='\u{2069}'
                )
        })
    {
        return Err(RobrixProtocolError::UnsafeError);
    }
    Ok(())
}
