//! Canonical JSON wire encoding for cognitive contracts.
//!
//! The codec is deliberately strict: encoded size is checked before parsing,
//! unknown fields are rejected by the contract types, values are validated
//! after decoding, and the received bytes must exactly equal the canonical
//! serde JSON representation.  This makes JSON a reproducible wire format
//! rather than a permissive interchange hint.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use serde::Serialize;
use serde::de::DeserializeOwned;

use crate::hnmf::CognitiveContractError;

const DIGEST_DOMAIN: &[u8] = b"hepta.cognitive.canonical-json.v1";

pub trait CanonicalContractV1: Serialize + DeserializeOwned + Sized {
    const SCHEMA_ID: &'static str;
    const MAX_ENCODED_BYTES: usize;

    fn validate_contract(&self) -> Result<(), CognitiveContractError>;
}

#[derive(Debug)]
pub enum CanonicalWireError {
    Contract(CognitiveContractError),
    Json(String),
    EncodedSizeExceeded {
        schema: &'static str,
        actual: usize,
        maximum: usize,
    },
    NonCanonicalJson {
        schema: &'static str,
    },
}

impl fmt::Display for CanonicalWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Contract(error) => error.fmt(formatter),
            Self::Json(error) => write!(formatter, "canonical JSON error: {error}"),
            Self::EncodedSizeExceeded {
                schema,
                actual,
                maximum,
            } => write!(
                formatter,
                "canonical JSON size exceeded for {schema}: {actual} > {maximum}"
            ),
            Self::NonCanonicalJson { schema } => {
                write!(formatter, "non-canonical JSON bytes for {schema}")
            }
        }
    }
}

impl StdError for CanonicalWireError {}

impl From<CognitiveContractError> for CanonicalWireError {
    fn from(value: CognitiveContractError) -> Self {
        Self::Contract(value)
    }
}

pub fn encode_canonical_json<T>(value: &T) -> Result<Vec<u8>, CanonicalWireError>
where
    T: CanonicalContractV1,
{
    value.validate_contract()?;
    let bytes =
        serde_json::to_vec(value).map_err(|error| CanonicalWireError::Json(error.to_string()))?;
    enforce_size::<T>(bytes.len())?;
    Ok(bytes)
}

pub fn decode_canonical_json<T>(bytes: &[u8]) -> Result<T, CanonicalWireError>
where
    T: CanonicalContractV1,
{
    enforce_size::<T>(bytes.len())?;
    let value = serde_json::from_slice::<T>(bytes)
        .map_err(|error| CanonicalWireError::Json(error.to_string()))?;
    value.validate_contract()?;
    let canonical = encode_canonical_json(&value)?;
    if canonical != bytes {
        return Err(CanonicalWireError::NonCanonicalJson {
            schema: T::SCHEMA_ID,
        });
    }
    Ok(value)
}

pub fn contract_digest<T>(value: &T) -> Result<Digest32, CanonicalWireError>
where
    T: CanonicalContractV1,
{
    let encoded = encode_canonical_json(value)?;
    let schema = T::SCHEMA_ID.as_bytes();
    let mut bytes = Vec::with_capacity(
        DIGEST_DOMAIN.len() + std::mem::size_of::<u32>() + schema.len() + encoded.len(),
    );
    bytes.extend_from_slice(DIGEST_DOMAIN);
    bytes.extend_from_slice(&(schema.len() as u32).to_be_bytes());
    bytes.extend_from_slice(schema);
    bytes.extend_from_slice(&encoded);
    Ok(Digest32::of_bytes(&bytes))
}

#[must_use]
pub const fn schema_id<T>() -> &'static str
where
    T: CanonicalContractV1,
{
    T::SCHEMA_ID
}

fn enforce_size<T>(actual: usize) -> Result<(), CanonicalWireError>
where
    T: CanonicalContractV1,
{
    if actual > T::MAX_ENCODED_BYTES {
        return Err(CanonicalWireError::EncodedSizeExceeded {
            schema: T::SCHEMA_ID,
            actual,
            maximum: T::MAX_ENCODED_BYTES,
        });
    }
    Ok(())
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
