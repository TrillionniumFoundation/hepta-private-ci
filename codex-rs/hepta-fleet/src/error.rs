use codex_hepta_contracts::AgentId;
use thiserror::Error;

use crate::AgentLifecycle;

#[derive(Debug, Error)]
pub enum FleetRegistryError {
    #[error("invalid fleet control value: {0}")]
    Invalid(String),
    #[error("corrupt fleet control state: {0}")]
    Corrupt(String),
    #[error("agent {0} is already registered")]
    AlreadyRegistered(AgentId),
    #[error("unknown fleet release {0}")]
    UnknownRelease(String),
    #[error("release {release_id} is not allowed for agent {agent_id}")]
    ReleaseNotAllowed {
        agent_id: AgentId,
        release_id: String,
    },
    #[error("workspace for agent {agent_id} overlaps registered agent {registered_agent_id}")]
    WorkspaceConflict {
        agent_id: AgentId,
        registered_agent_id: AgentId,
    },
    #[error("stale generation for agent {agent_id}: expected {expected}, current {current}")]
    StaleGeneration {
        agent_id: AgentId,
        expected: u64,
        current: u64,
    },
    #[error("stale release state for agent {agent_id}: expected {expected}, current {current}")]
    StaleReleaseGeneration {
        agent_id: AgentId,
        expected: u64,
        current: u64,
    },
    #[error("invalid lifecycle transition for agent {agent_id}: {current:?} -> {requested:?}")]
    InvalidTransition {
        agent_id: AgentId,
        current: AgentLifecycle,
        requested: AgentLifecycle,
    },
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error("agent manifest encoding failed: {0}")]
    ManifestEncode(#[from] toml::ser::Error),
}
