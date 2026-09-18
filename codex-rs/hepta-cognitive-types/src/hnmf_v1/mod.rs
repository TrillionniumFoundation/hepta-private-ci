//! Canonical HNMF V1 cognitive/memory contracts and JSON wire encoding.
//!
//! These types are the single owner-local source for the HNMF contract surface.
//! They are bounded, deterministic, deny unknown JSON fields, and grant no
//! runtime, writer, model, provider, external-effect, selection, promotion or
//! release authority.

use std::fmt;

use codex_hepta_types::Digest32;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer, Serialize};

pub const PPM: u32 = 1_000_000;
pub const MAX_MODALITY_SPANS: usize = 32;
pub const MAX_BINDINGS: usize = 32;
pub const MAX_BINDING_SPANS: usize = 16;
pub const MAX_SEMANTIC_KEYS: usize = 64;
pub const MAX_PROVENANCE: usize = 64;
pub const MAX_EVENT_REFS: usize = 64;
pub const MAX_CUE_SEEDS: usize = 64;
pub const MAX_GRAPH_HOPS: u8 = 4;
pub const MAX_SUBGRAPH_NODES: usize = 4_096;
pub const MAX_RECALL_EVENTS: usize = 16;
pub const MAX_ACTIVATION_PATHS: usize = 32;
pub const MAX_REPLAY_SELECTION: usize = 256;
pub const MAX_WEIGHT_PROPOSALS: usize = 32_768;
pub const MAX_THRESHOLD_PROPOSALS: usize = 4_096;
pub const MAX_TOPOLOGY_LABEL_BYTES: usize = 128;

const CONTRACT_DIGEST_DOMAIN: &[u8] = b"hepta.cognitive.canonical-json.v1\0";

pub type EventIdV1 = u64;
pub type EpisodeIdV1 = u64;
pub type SpanIdV1 = u64;
pub type BindingIdV1 = u64;
pub type NodeIdV1 = u64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HnmfContractError {
    Invalid(&'static str),
    BoundExceeded(&'static str),
    Conflict(&'static str),
    Missing(&'static str),
    AuthorityGranted,
    Json(String),
    EncodedSize { actual: usize, maximum: usize },
}

impl fmt::Display for HnmfContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Invalid(message) => write!(formatter, "invalid contract: {message}"),
            Self::BoundExceeded(name) => write!(formatter, "contract bound exceeded: {name}"),
            Self::Conflict(message) => write!(formatter, "contract conflict: {message}"),
            Self::Missing(name) => write!(formatter, "contract object missing: {name}"),
            Self::AuthorityGranted => formatter.write_str("canonical cognitive contract grants authority"),
            Self::Json(message) => write!(formatter, "canonical JSON error: {message}"),
            Self::EncodedSize { actual, maximum } => {
                write!(formatter, "encoded contract size {actual} exceeds maximum {maximum}")
            }
        }
    }
}

impl std::error::Error for HnmfContractError {}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct WireEnvelopeRef<'a, T: Serialize> {
    schema: &'static str,
    schema_version: u32,
    payload: &'a T,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct WireEnvelopeOwned<T> {
    schema: String,
    schema_version: u32,
    payload: T,
}

pub trait CanonicalJsonV1: Serialize + DeserializeOwned + Sized {
    const SCHEMA_ID: &'static str;
    const SCHEMA_VERSION: u32 = 1;
    const MAX_ENCODED_BYTES: usize;

    fn validate(&self) -> Result<(), HnmfContractError>;

    fn encode_canonical_json(&self) -> Result<Vec<u8>, HnmfContractError> {
        self.validate()?;
        let envelope = WireEnvelopeRef {
            schema: Self::SCHEMA_ID,
            schema_version: Self::SCHEMA_VERSION,
            payload: self,
        };
        let encoded = serde_json::to_vec(&envelope)
            .map_err(|error| HnmfContractError::Json(error.to_string()))?;
        ensure_encoded_size(encoded.len(), Self::MAX_ENCODED_BYTES)?;
        Ok(encoded)
    }

    fn decode_json(encoded: &[u8]) -> Result<Self, HnmfContractError> {
        ensure_encoded_size(encoded.len(), Self::MAX_ENCODED_BYTES)?;
        let envelope: WireEnvelopeOwned<Self> = serde_json::from_slice(encoded)
            .map_err(|error| HnmfContractError::Json(error.to_string()))?;
        if envelope.schema != Self::SCHEMA_ID {
            return Err(HnmfContractError::Invalid("wire schema id"));
        }
        if envelope.schema_version != Self::SCHEMA_VERSION {
            return Err(HnmfContractError::Invalid("wire schema version"));
        }
        envelope.payload.validate()?;
        Ok(envelope.payload)
    }

    fn semantic_digest(&self) -> Result<Digest32, HnmfContractError> {
        let encoded = self.encode_canonical_json()?;
        let mut bytes = Vec::with_capacity(CONTRACT_DIGEST_DOMAIN.len() + encoded.len());
        bytes.extend_from_slice(CONTRACT_DIGEST_DOMAIN);
        bytes.extend_from_slice(&encoded);
        Ok(Digest32::of_bytes(&bytes))
    }
}

mod exact_u64 {
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S>(value: &u64, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&value.to_string())
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<u64, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        if value.is_empty()
            || (value.len() > 1 && value.starts_with('0'))
            || !value.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err(serde::de::Error::custom("u64 must be canonical decimal text"));
        }
        value
            .parse::<u64>()
            .map_err(|_| serde::de::Error::custom("u64 decimal overflow"))
    }
}

mod exact_i64 {
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S>(value: &i64, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&value.to_string())
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<i64, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        let digits = value.strip_prefix('-').unwrap_or(&value);
        if digits.is_empty()
            || (digits.len() > 1 && digits.starts_with('0'))
            || value == "-0"
            || !digits.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err(serde::de::Error::custom("i64 must be canonical decimal text"));
        }
        value
            .parse::<i64>()
            .map_err(|_| serde::de::Error::custom("i64 decimal overflow"))
    }
}

mod exact_i64_option {
    use serde::{Deserialize, Deserializer, Serialize, Serializer};

    pub fn serialize<S>(value: &Option<i64>, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        value.map(|number| number.to_string()).serialize(serializer)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Option<i64>, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Option::<String>::deserialize(deserializer)?;
        value
            .map(|value| {
                let digits = value.strip_prefix('-').unwrap_or(&value);
                if digits.is_empty()
                    || (digits.len() > 1 && digits.starts_with('0'))
                    || value == "-0"
                    || !digits.bytes().all(|byte| byte.is_ascii_digit())
                {
                    return Err(serde::de::Error::custom(
                        "optional i64 must be canonical decimal text",
                    ));
                }
                value
                    .parse::<i64>()
                    .map_err(|_| serde::de::Error::custom("i64 decimal overflow"))
            })
            .transpose()
    }
}

mod exact_u64_vec {
    use serde::{Deserialize, Deserializer, Serialize, Serializer};

    pub fn serialize<S>(values: &[u64], serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        values
            .iter()
            .map(u64::to_string)
            .collect::<Vec<_>>()
            .serialize(serializer)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Vec<u64>, D::Error>
    where
        D: Deserializer<'de>,
    {
        let values = Vec::<String>::deserialize(deserializer)?;
        values
            .into_iter()
            .map(|value| {
                if value.is_empty()
                    || (value.len() > 1 && value.starts_with('0'))
                    || !value.bytes().all(|byte| byte.is_ascii_digit())
                {
                    return Err(serde::de::Error::custom(
                        "u64 vector item must be canonical decimal text",
                    ));
                }
                value
                    .parse::<u64>()
                    .map_err(|_| serde::de::Error::custom("u64 decimal overflow"))
            })
            .collect()
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct Sha256DigestV1(String);

impl Sha256DigestV1 {
    pub fn parse(value: impl Into<String>) -> Result<Self, HnmfContractError> {
        let value = value.into();
        if value.len() != 64
            || value
                .bytes()
                .any(|byte| !byte.is_ascii_hexdigit() || byte.is_ascii_uppercase())
            || value.bytes().all(|byte| byte == b'0')
        {
            return Err(HnmfContractError::Invalid(
                "digest must be non-zero 64-character lowercase hexadecimal SHA-256",
            ));
        }
        Ok(Self(value))
    }

    pub fn from_bytes(bytes: &[u8]) -> Self {
        Self(Digest32::of_bytes(bytes).to_string())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for Sha256DigestV1 {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse(value).map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuthorityPostureV1 {
    pub runtime: bool,
    pub production_writer: bool,
    pub model_invocation: bool,
    pub provider_dispatch: bool,
    pub external_effect: bool,
    pub selection: bool,
    pub promotion: bool,
    pub release: bool,
}

impl AuthorityPostureV1 {
    pub const DENY_ALL: Self = Self {
        runtime: false,
        production_writer: false,
        model_invocation: false,
        provider_dispatch: false,
        external_effect: false,
        selection: false,
        promotion: false,
        release: false,
    };

    pub const fn grants_any(self) -> bool {
        self.runtime
            || self.production_writer
            || self.model_invocation
            || self.provider_dispatch
            || self.external_effect
            || self.selection
            || self.promotion
            || self.release
    }

    fn validate(self) -> Result<(), HnmfContractError> {
        if self.grants_any() {
            return Err(HnmfContractError::AuthorityGranted);
        }
        Ok(())
    }
}

mod event;
mod graph;
mod learning;
mod span;

pub use event::*;
pub use graph::*;
pub use learning::*;
pub use span::*;

fn ensure_encoded_size(actual: usize, maximum: usize) -> Result<(), HnmfContractError> {
    if actual > maximum {
        return Err(HnmfContractError::EncodedSize { actual, maximum });
    }
    Ok(())
}

fn validate_sorted_unique_text(
    values: &[String],
    maximum: usize,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if values.is_empty() || values.len() > maximum {
        return Err(HnmfContractError::BoundExceeded(name));
    }
    let mut previous: Option<&str> = None;
    for value in values {
        validate_text(value, 128, name)?;
        if value.to_lowercase() != *value {
            return Err(HnmfContractError::Invalid("semantic key must be lowercase canonical text"));
        }
        if previous.is_some_and(|left| left >= value.as_str()) {
            return Err(HnmfContractError::Conflict("canonical text collection is not strictly sorted/unique"));
        }
        previous = Some(value);
    }
    Ok(())
}

fn validate_sorted_unique_u64(values: &[u64], name: &'static str) -> Result<(), HnmfContractError> {
    let mut previous = 0_u64;
    for (index, value) in values.iter().copied().enumerate() {
        if value == 0 || (index > 0 && value <= previous) {
            return Err(HnmfContractError::Invalid(name));
        }
        previous = value;
    }
    Ok(())
}

fn validate_sorted_unique_u64_bounded(
    values: &[u64],
    maximum: usize,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if values.len() > maximum {
        return Err(HnmfContractError::BoundExceeded(name));
    }
    validate_sorted_unique_u64(values, name)
}

fn validate_sorted_unique_enum<T: Ord>(values: &[T], name: &'static str) -> Result<(), HnmfContractError> {
    for pair in values.windows(2) {
        if pair[0] >= pair[1] {
            return Err(HnmfContractError::Conflict(name));
        }
    }
    Ok(())
}

fn ppm(value: u32, name: &'static str) -> Result<(), HnmfContractError> {
    if value > PPM {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

fn validate_text(
    value: &str,
    maximum_bytes: usize,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if value.trim().is_empty() || value.len() > maximum_bytes || value.chars().any(char::is_control) {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

fn validate_bounded(
    value: &str,
    maximum_bytes: usize,
    name: &'static str,
) -> Result<(), HnmfContractError> {
    if value.len() > maximum_bytes || value.chars().any(char::is_control) {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

fn increasing(start: u64, end: u64, name: &'static str) -> Result<(), HnmfContractError> {
    if end <= start {
        return Err(HnmfContractError::Invalid(name));
    }
    Ok(())
}

#[cfg(test)]
mod tests;
