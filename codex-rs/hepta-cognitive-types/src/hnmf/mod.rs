//! Canonical HNMF cognitive and memory contracts.
//!
//! These are production-owned, authority-free V1 contracts for the HNMF
//! event/span/engram/recall/replay/plasticity/forget surface. Constructors
//! validate semantic invariants before values are published. Canonical wire
//! acceptance must use [`CanonicalJsonV1::from_canonical_json`], which enforces
//! schema identity, size bounds, strict top-level fields, semantic validation,
//! and byte-for-byte canonical JSON.

#![allow(clippy::module_name_repetitions)]

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use serde::Deserialize;
use serde::Serialize;

pub mod engram;
pub mod event;
pub mod forget;
pub mod plasticity;
pub mod recall;
pub mod replay;
pub mod span;
pub mod wire;

pub use engram::*;
pub use event::*;
pub use forget::*;
pub use plasticity::*;
pub use recall::*;
pub use replay::*;
pub use span::*;
pub use wire::CanonicalJsonV1;

pub const PPM: i64 = 1_000_000;
pub const MAX_MODALITY_SPANS: usize = 64;
pub const MAX_BINDINGS: usize = 32;
pub const MAX_BINDING_SPANS: usize = 16;
pub const MAX_SEMANTIC_KEYS: usize = 64;
pub const MAX_PROVENANCE: usize = 32;
pub const MAX_CUE_SEEDS: usize = 64;
pub const MAX_SUPPORT_ITEMS: usize = 64;
pub const MAX_RECALL_EVENTS: usize = 16;
pub const MAX_ACTIVATION_PATHS: usize = 32;
pub const MAX_REPLAY_SELECTION: usize = 256;
pub const MAX_WEIGHT_PROPOSALS: usize = 32_768;
pub const MAX_THRESHOLD_PROPOSALS: usize = 4_096;
pub const MAX_FORGET_NODES: usize = 4_096;
pub const MAX_FORGET_SYNAPSES: usize = 32_768;
pub const Q16_ONE: i32 = 65_536;

pub type EventIdV1 = u64;
pub type EpisodeIdV1 = u64;
pub type SpanIdV1 = u64;
pub type BindingIdV1 = u64;
pub type NodeIdV1 = u64;
pub type CueIdV1 = u64;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
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

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PrivacyClassV1 {
    AgentPrivate,
    WorkspacePrivate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HnmfContractError {
    Invalid(&'static str),
    BoundExceeded(&'static str),
    Conflict(&'static str),
    Missing(&'static str),
    Wire(String),
    SchemaMismatch,
    NonCanonicalJson,
}

impl fmt::Display for HnmfContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(formatter, "invalid HNMF contract: {message}"),
            Self::BoundExceeded(name) => write!(formatter, "HNMF contract bound exceeded: {name}"),
            Self::Conflict(message) => write!(formatter, "HNMF contract conflict: {message}"),
            Self::Missing(name) => write!(formatter, "HNMF contract object missing: {name}"),
            Self::Wire(message) => write!(formatter, "HNMF wire error: {message}"),
            Self::SchemaMismatch => formatter.write_str("HNMF wire schema mismatch"),
            Self::NonCanonicalJson => formatter.write_str("HNMF JSON is not canonical"),
        }
    }
}

impl StdError for HnmfContractError {}

pub trait ValidateHnmfV1 {
    fn validate(&self) -> Result<(), HnmfContractError>;
}

pub(crate) fn validate_keys(
    keys: &BTreeSet<String>,
    maximum: usize,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if keys.is_empty() || keys.len() > maximum {
        return Err(HnmfContractError::BoundExceeded(name));
    }
    if keys.iter().any(|key| {
        key.trim().is_empty()
            || key.len() > 128
            || key.chars().any(char::is_control)
            || key.to_lowercase() != *key
    }) {
        return Err(HnmfContractError::Invalid(
            "semantic key must be bounded lowercase canonical text",
        ));
    }
    Ok(())
}

pub(crate) fn validate_text(
    value: &str,
    maximum_bytes: usize,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if value.trim().is_empty() || value.len() > maximum_bytes || value.chars().any(char::is_control)
    {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn validate_bounded(
    value: &str,
    maximum_bytes: usize,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if value.len() > maximum_bytes || value.chars().any(char::is_control) {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn increasing(
    start: u64,
    end: u64,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if end <= start {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn ppm(value: u32, name: &'static str) -> Result<(), HnmfContractError> {
    if u64::from(value) > PPM as u64 {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn signed_ppm(value: i32, name: &'static str) -> Result<(), HnmfContractError> {
    if !(-(PPM as i32)..=PPM as i32).contains(&value) {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

pub(crate) fn q16_unit(value: i32, name: &'static str) -> Result<(), HnmfContractError> {
    if !(-Q16_ONE..=Q16_ONE).contains(&value) {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;
