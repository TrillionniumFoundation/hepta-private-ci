//! Canonical HNMF V1 cognitive and memory contracts.
//!
//! These types are authority-free, bounded value objects. Canonical values are
//! only constructible through validating constructors; wire decoding re-runs the
//! same validation before returning a value.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

mod engram;
mod event;
mod forget;
mod plasticity;
mod recall;
mod replay;
mod span;
mod wire;

pub use engram::*;
pub use event::*;
pub use forget::*;
pub use plasticity::*;
pub use recall::*;
pub use replay::*;
pub use span::*;
pub use wire::*;

pub const PPM: i64 = 1_000_000;
pub const MAX_MODALITY_SPANS: usize = 64;
pub const MAX_BINDINGS: usize = 32;
pub const MAX_BINDING_SPANS: usize = 16;
pub const MAX_SEMANTIC_KEYS: usize = 64;
pub const MAX_PROVENANCE: usize = 32;
pub const MAX_CUE_SEEDS: usize = 64;
pub const MAX_SUPPORT_EVENTS: usize = 64;
pub const MAX_REPLAY_SELECTION: usize = 256;
pub const MAX_REPLAY_CANDIDATES: usize = 4_096;

pub type EventIdV1 = u64;
pub type EpisodeIdV1 = u64;
pub type SpanIdV1 = u64;
pub type BindingIdV1 = u64;
pub type NodeIdV1 = u64;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ModalityKindV1 {
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

impl ModalityKindV1 {
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

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PrivacyClassV1 {
    AgentPrivate,
    WorkspacePrivate,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(transparent)]
pub struct CanonicalDigestV1(#[serde(with = "digest_hex")] Digest32);

impl CanonicalDigestV1 {
    pub fn new(value: Digest32) -> Result<Self, ContractErrorV1> {
        if value.is_zero() {
            return Err(ContractErrorV1::Invalid("digest must be non-zero"));
        }
        Ok(Self(value))
    }

    pub fn parse(value: &str) -> Result<Self, ContractErrorV1> {
        let digest = Digest32::from_str(value)
            .map_err(|_| ContractErrorV1::Invalid("digest must be lowercase SHA-256 hex"))?;
        Self::new(digest)
    }

    #[must_use]
    pub const fn as_digest(&self) -> Digest32 {
        self.0
    }
}

impl fmt::Display for CanonicalDigestV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum MemoryScopeV1 {
    AgentPrivate {
        agent_id: String,
    },
    WorkspacePrivate {
        agent_id: String,
        workspace_sha256: CanonicalDigestV1,
    },
}

impl MemoryScopeV1 {
    pub fn try_agent_private(agent_id: impl Into<String>) -> Result<Self, ContractErrorV1> {
        let agent_id = agent_id.into();
        validate_text(&agent_id, 128, "scope agent id")?;
        Ok(Self::AgentPrivate { agent_id })
    }

    pub fn try_workspace_private(
        agent_id: impl Into<String>,
        workspace_sha256: CanonicalDigestV1,
    ) -> Result<Self, ContractErrorV1> {
        let agent_id = agent_id.into();
        validate_text(&agent_id, 128, "scope agent id")?;
        Ok(Self::WorkspacePrivate {
            agent_id,
            workspace_sha256,
        })
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        match self {
            Self::AgentPrivate { agent_id } | Self::WorkspacePrivate { agent_id, .. } => {
                validate_text(agent_id, 128, "scope agent id")
            }
        }
    }

    #[must_use]
    pub const fn privacy_class(&self) -> PrivacyClassV1 {
        match self {
            Self::AgentPrivate { .. } => PrivacyClassV1::AgentPrivate,
            Self::WorkspacePrivate { .. } => PrivacyClassV1::WorkspacePrivate,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct TimeIntervalV1 {
    start_unix_ms: i64,
    end_unix_ms: Option<i64>,
}

impl TimeIntervalV1 {
    pub fn try_new(start_unix_ms: i64, end_unix_ms: Option<i64>) -> Result<Self, ContractErrorV1> {
        let value = Self {
            start_unix_ms,
            end_unix_ms,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ContractErrorV1> {
        if self.end_unix_ms.is_some_and(|end| end <= self.start_unix_ms) {
            return Err(ContractErrorV1::Invalid(
                "time interval end must be greater than start",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub const fn start_unix_ms(&self) -> i64 {
        self.start_unix_ms
    }

    #[must_use]
    pub const fn end_unix_ms(&self) -> Option<i64> {
        self.end_unix_ms
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ContractErrorV1 {
    Invalid(&'static str),
    BoundExceeded(&'static str),
    Conflict(&'static str),
    Missing(&'static str),
    AuthorityBoundary,
}

impl fmt::Display for ContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(formatter, "invalid HNMF contract: {message}"),
            Self::BoundExceeded(name) => write!(formatter, "HNMF bound exceeded: {name}"),
            Self::Conflict(message) => write!(formatter, "HNMF contract conflict: {message}"),
            Self::Missing(name) => write!(formatter, "HNMF contract object missing: {name}"),
            Self::AuthorityBoundary => formatter.write_str("HNMF authority boundary violated"),
        }
    }
}

impl StdError for ContractErrorV1 {}

pub(crate) fn validate_ppm(value: u32, name: &'static str) -> Result<(), ContractErrorV1> {
    if u64::from(value) > PPM as u64 {
        return Err(ContractErrorV1::Invalid(name));
    }
    Ok(())
}

pub(crate) fn validate_signed_ppm(
    value: i32,
    name: &'static str,
) -> Result<(), ContractErrorV1> {
    if !(-(PPM as i32)..=PPM as i32).contains(&value) {
        return Err(ContractErrorV1::Invalid(name));
    }
    Ok(())
}

pub(crate) fn validate_nonzero(value: u64, name: &'static str) -> Result<(), ContractErrorV1> {
    if value == 0 {
        return Err(ContractErrorV1::Invalid(name));
    }
    Ok(())
}

pub(crate) fn validate_text(
    value: &str,
    maximum_bytes: usize,
    name: &'static str,
) -> Result<(), ContractErrorV1> {
    if value.trim().is_empty() || value.len() > maximum_bytes || value.chars().any(char::is_control)
    {
        return Err(ContractErrorV1::Invalid(name));
    }
    Ok(())
}

pub(crate) fn validate_semantic_keys(keys: &BTreeSet<String>) -> Result<(), ContractErrorV1> {
    if keys.is_empty() || keys.len() > MAX_SEMANTIC_KEYS {
        return Err(ContractErrorV1::BoundExceeded("semantic keys"));
    }
    for key in keys {
        if key.trim().is_empty()
            || key.len() > 128
            || key.chars().any(char::is_control)
            || key.to_lowercase() != *key
        {
            return Err(ContractErrorV1::Invalid(
                "semantic key must be bounded lowercase canonical text",
            ));
        }
    }
    Ok(())
}

mod digest_hex {
    use codex_hepta_types::Digest32;
    use serde::Deserialize;
    use serde::Deserializer;
    use serde::Serializer;
    use std::str::FromStr;

    pub fn serialize<S>(value: &Digest32, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&value.to_string())
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Digest32, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        let digest = Digest32::from_str(&value).map_err(serde::de::Error::custom)?;
        if digest.is_zero() {
            return Err(serde::de::Error::custom("digest must be non-zero"));
        }
        Ok(digest)
    }
}

#[cfg(test)]
#[path = "hnmf_tests.rs"]
mod tests;
