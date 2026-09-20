#![forbid(unsafe_code)]

use std::fmt;

pub const PPM: u32 = 1_000_000;
pub const MAX_MODALITY_SPANS: usize = 64;
pub const MAX_BINDINGS: usize = 32;
pub const MAX_BINDING_SPANS: usize = 16;
pub const MAX_SEMANTIC_KEYS: usize = 64;
pub const MAX_PROVENANCE: usize = 32;
pub const MAX_CUE_SEEDS: usize = 64;
pub const MAX_GRAPH_HOPS: u8 = 4;
pub const MAX_SUBGRAPH_NODES: usize = 4096;
pub const CURRENT_RUN_MUTATION_ALLOWED: bool = false;
pub const ONLINE_TOPOLOGY_ACTIVATION_ALLOWED: bool = false;
pub const PRODUCTION_AUTHORITY: bool = false;
pub const EXTERNAL_EFFECTS_ALLOWED: bool = false;

pub type EventId = u64;
pub type EpisodeId = u64;
pub type SpanId = u64;
pub type BindingId = u64;
pub type NodeId = u64;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct Digest32(String);

impl Digest32 {
    pub fn parse(value: impl Into<String>) -> Result<Self, ContractError> {
        let value = value.into();
        if value.len() != 64
            || value
                .bytes()
                .any(|byte| !byte.is_ascii_hexdigit() || byte.is_ascii_uppercase())
        {
            return Err(ContractError::Invalid(
                "digest must be 64 lowercase hexadecimal characters",
            ));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ModalityKind {
    Text,
    Image,
    Audio,
    Video,
    CodeAst,
    GuiState,
    ToolTrajectory,
    StructuredData,
    Sensor,
}

impl ModalityKind {
    pub const ALL: [Self; 9] = [
        Self::Text,
        Self::Image,
        Self::Audio,
        Self::Video,
        Self::CodeAst,
        Self::GuiState,
        Self::ToolTrajectory,
        Self::StructuredData,
        Self::Sensor,
    ];
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PrivacyClass {
    AgentPrivate,
    WorkspacePrivate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PrincipalScope {
    pub agent_id: String,
    pub workspace_sha256: Option<Digest32>,
}

impl PrincipalScope {
    pub fn validate(&self) -> Result<(), ContractError> {
        validate_text(&self.agent_id, 128, "principal agent id")
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MemoryScope {
    AgentPrivate {
        agent_id: String,
    },
    WorkspacePrivate {
        agent_id: String,
        workspace_sha256: Digest32,
    },
}

impl MemoryScope {
    pub fn validate(&self) -> Result<(), ContractError> {
        match self {
            Self::AgentPrivate { agent_id } | Self::WorkspacePrivate { agent_id, .. } => {
                validate_text(agent_id, 128, "scope agent id")
            }
        }
    }

    pub const fn privacy_class(&self) -> PrivacyClass {
        match self {
            Self::AgentPrivate { .. } => PrivacyClass::AgentPrivate,
            Self::WorkspacePrivate { .. } => PrivacyClass::WorkspacePrivate,
        }
    }

    pub fn permits(&self, principal: &PrincipalScope) -> bool {
        match self {
            Self::AgentPrivate { agent_id } => principal.agent_id == *agent_id,
            Self::WorkspacePrivate {
                agent_id,
                workspace_sha256,
            } => {
                principal.agent_id == *agent_id
                    && principal.workspace_sha256.as_ref() == Some(workspace_sha256)
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TimeInterval {
    pub start_unix_ms: i64,
    pub end_unix_ms: Option<i64>,
}

impl TimeInterval {
    pub fn validate(self) -> Result<(), ContractError> {
        if self
            .end_unix_ms
            .is_some_and(|end| end <= self.start_unix_ms)
        {
            return Err(ContractError::Invalid(
                "time interval end must be greater than start",
            ));
        }
        Ok(())
    }

    pub fn contains(self, now_unix_ms: i64) -> bool {
        self.start_unix_ms <= now_unix_ms && self.end_unix_ms.is_none_or(|end| now_unix_ms < end)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ContractError {
    Invalid(&'static str),
    BoundExceeded(&'static str),
    Conflict(&'static str),
    Missing(&'static str),
}

impl fmt::Display for ContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(formatter, "invalid contract: {message}"),
            Self::BoundExceeded(name) => write!(formatter, "contract bound exceeded: {name}"),
            Self::Conflict(message) => write!(formatter, "contract conflict: {message}"),
            Self::Missing(name) => write!(formatter, "contract object missing: {name}"),
        }
    }
}

impl std::error::Error for ContractError {}

pub(crate) fn validate_keys(
    keys: &std::collections::BTreeSet<String>,
) -> Result<(), ContractError> {
    if keys.is_empty() || keys.len() > MAX_SEMANTIC_KEYS {
        return Err(ContractError::BoundExceeded("semantic keys"));
    }
    if keys.iter().any(|key| {
        key.trim().is_empty()
            || key.len() > 128
            || key.chars().any(char::is_control)
            || key.to_lowercase() != *key
    }) {
        return Err(ContractError::Invalid(
            "semantic key must be bounded lowercase canonical text",
        ));
    }
    Ok(())
}

pub(crate) fn ppm(value: u32, name: &'static str) -> Result<(), ContractError> {
    if value > PPM {
        return Err(ContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn validate_text(
    value: &str,
    maximum_bytes: usize,
    name: &'static str,
) -> Result<(), ContractError> {
    if value.trim().is_empty() || value.len() > maximum_bytes || value.chars().any(char::is_control)
    {
        return Err(ContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn validate_bounded(
    value: &str,
    maximum_bytes: usize,
    name: &'static str,
) -> Result<(), ContractError> {
    if value.len() > maximum_bytes || value.chars().any(char::is_control) {
        return Err(ContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn increasing(start: u64, end: u64, name: &'static str) -> Result<(), ContractError> {
    if end <= start {
        return Err(ContractError::Invalid(name));
    }
    Ok(())
}

mod event;
mod ledger;
mod span;

pub use event::*;
pub use ledger::*;
pub use span::*;

#[cfg(test)]
mod tests;
