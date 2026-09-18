//! Canonical JSON wire envelope for HNMF V1 contracts.

use std::str::FromStr;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::Serializer;
use serde::de::DeserializeOwned;
use serde::de::Error as _;

use super::HnmfContractError;
use super::ValidateHnmfV1;

pub const CANONICAL_JSON_ENCODING: &str = "utf-8-json-no-whitespace";
pub const WIRE_SCHEMA_VERSION: u32 = 1;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct WireEnvelopeRef<'a, T> {
    schema: &'static str,
    schema_version: u32,
    payload: &'a T,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct WireEnvelopeOwned<T> {
    schema: String,
    schema_version: u32,
    payload: T,
}

/// Strict canonical JSON support for one HNMF V1 protocol object.
///
/// Decoding rejects oversized payloads, unknown envelope fields, schema drift,
/// invalid semantic values and any byte representation that differs from the
/// canonical serializer output (including whitespace or key reordering).
pub trait CanonicalJsonV1: Sized + Serialize + DeserializeOwned + ValidateHnmfV1 {
    const SCHEMA_ID: &'static str;
    const MAX_ENCODED_BYTES: usize;

    fn to_canonical_json(&self) -> Result<Vec<u8>, HnmfContractError> {
        self.validate()?;
        let bytes = serde_json::to_vec(&WireEnvelopeRef {
            schema: Self::SCHEMA_ID,
            schema_version: WIRE_SCHEMA_VERSION,
            payload: self,
        })
        .map_err(|error| HnmfContractError::Wire(error.to_string()))?;
        if bytes.len() > Self::MAX_ENCODED_BYTES {
            return Err(HnmfContractError::BoundExceeded("encoded bytes"));
        }
        Ok(bytes)
    }

    fn from_canonical_json(bytes: &[u8]) -> Result<Self, HnmfContractError> {
        if bytes.len() > Self::MAX_ENCODED_BYTES {
            return Err(HnmfContractError::BoundExceeded("encoded bytes"));
        }
        let envelope: WireEnvelopeOwned<Self> = serde_json::from_slice(bytes)
            .map_err(|error| HnmfContractError::Wire(error.to_string()))?;
        if envelope.schema != Self::SCHEMA_ID || envelope.schema_version != WIRE_SCHEMA_VERSION {
            return Err(HnmfContractError::SchemaMismatch);
        }
        envelope.payload.validate()?;
        let canonical = serde_json::to_vec(&WireEnvelopeRef {
            schema: Self::SCHEMA_ID,
            schema_version: WIRE_SCHEMA_VERSION,
            payload: &envelope.payload,
        })
        .map_err(|error| HnmfContractError::Wire(error.to_string()))?;
        if canonical != bytes {
            return Err(HnmfContractError::NonCanonicalJson);
        }
        Ok(envelope.payload)
    }
}

pub(crate) mod digest {
    use super::*;

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
        Digest32::from_str(&value).map_err(D::Error::custom)
    }
}

pub(crate) mod option_digest {
    use super::*;

    pub fn serialize<S>(value: &Option<Digest32>, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match value {
            Some(value) => serializer.serialize_some(&value.to_string()),
            None => serializer.serialize_none(),
        }
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Option<Digest32>, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Option::<String>::deserialize(deserializer)?;
        value
            .map(|value| Digest32::from_str(&value).map_err(D::Error::custom))
            .transpose()
    }
}
