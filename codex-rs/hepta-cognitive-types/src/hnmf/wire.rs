use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;

use super::ContractErrorV1;

pub const CANONICAL_JSON_VERSION_V1: u16 = 1;
pub const CANONICAL_JSON_MEDIA_TYPE_V1: &str = "application/vnd.hepta.hnmf+json;version=1";

pub trait CanonicalContractV1: Serialize + DeserializeOwned {
    const SCHEMA_ID: &'static str;
    const MAX_ENCODED_BYTES: usize;

    fn validate_contract(&self) -> Result<(), ContractErrorV1>;
}

#[derive(Debug)]
pub enum CanonicalWireErrorV1 {
    Contract(ContractErrorV1),
    Serialization(String),
    Decode(String),
    SchemaMismatch {
        expected: &'static str,
        actual: String,
    },
    VersionMismatch(u16),
    SizeExceeded {
        actual: usize,
        maximum: usize,
    },
    NonCanonicalEncoding,
}

impl fmt::Display for CanonicalWireErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Contract(error) => error.fmt(formatter),
            Self::Serialization(error) => write!(formatter, "canonical JSON serialization failed: {error}"),
            Self::Decode(error) => write!(formatter, "canonical JSON decode failed: {error}"),
            Self::SchemaMismatch { expected, actual } => {
                write!(formatter, "canonical JSON schema mismatch: expected {expected}, found {actual}")
            }
            Self::VersionMismatch(version) => {
                write!(formatter, "canonical JSON version mismatch: {version}")
            }
            Self::SizeExceeded { actual, maximum } => {
                write!(formatter, "canonical JSON size {actual} exceeds {maximum}")
            }
            Self::NonCanonicalEncoding => formatter.write_str(
                "JSON is semantically decodable but is not the canonical byte encoding",
            ),
        }
    }
}

impl StdError for CanonicalWireErrorV1 {}

impl From<ContractErrorV1> for CanonicalWireErrorV1 {
    fn from(value: ContractErrorV1) -> Self {
        Self::Contract(value)
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct CanonicalEnvelopeV1<T> {
    schema_id: String,
    version: u16,
    payload: T,
}

pub fn canonical_json_bytes<T>(value: &T) -> Result<Vec<u8>, CanonicalWireErrorV1>
where
    T: CanonicalContractV1,
{
    value.validate_contract()?;
    let envelope = CanonicalEnvelopeV1 {
        schema_id: T::SCHEMA_ID.to_owned(),
        version: CANONICAL_JSON_VERSION_V1,
        payload: value,
    };
    let bytes = serde_json::to_vec(&envelope)
        .map_err(|error| CanonicalWireErrorV1::Serialization(error.to_string()))?;
    if bytes.len() > T::MAX_ENCODED_BYTES {
        return Err(CanonicalWireErrorV1::SizeExceeded {
            actual: bytes.len(),
            maximum: T::MAX_ENCODED_BYTES,
        });
    }
    Ok(bytes)
}

pub fn canonical_json_digest<T>(value: &T) -> Result<Digest32, CanonicalWireErrorV1>
where
    T: CanonicalContractV1,
{
    canonical_json_bytes(value).map(|bytes| Digest32::of_bytes(&bytes))
}

pub fn decode_canonical_json<T>(bytes: &[u8]) -> Result<T, CanonicalWireErrorV1>
where
    T: CanonicalContractV1,
{
    if bytes.len() > T::MAX_ENCODED_BYTES {
        return Err(CanonicalWireErrorV1::SizeExceeded {
            actual: bytes.len(),
            maximum: T::MAX_ENCODED_BYTES,
        });
    }

    let envelope: CanonicalEnvelopeV1<T> = serde_json::from_slice(bytes)
        .map_err(|error| CanonicalWireErrorV1::Decode(error.to_string()))?;
    if envelope.schema_id != T::SCHEMA_ID {
        return Err(CanonicalWireErrorV1::SchemaMismatch {
            expected: T::SCHEMA_ID,
            actual: envelope.schema_id,
        });
    }
    if envelope.version != CANONICAL_JSON_VERSION_V1 {
        return Err(CanonicalWireErrorV1::VersionMismatch(envelope.version));
    }
    envelope.payload.validate_contract()?;

    let canonical = canonical_json_bytes(&envelope.payload)?;
    if canonical != bytes {
        return Err(CanonicalWireErrorV1::NonCanonicalEncoding);
    }
    Ok(envelope.payload)
}
