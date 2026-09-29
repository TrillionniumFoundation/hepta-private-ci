//! Stable wire failure categories and payload-free JSON audit diagnostics.
//!
//! Display/source retain the historical developer diagnostic. Audit consumers
//! should use `violation()`, which never copies Serde's input-bearing JSON text.

use std::error::Error as StdError;
use std::fmt;

use crate::contract::ContractErrorCodeV1;
use crate::contract::ContractViolationV1;
use crate::hnmf::HnmfContractError;

#[derive(Debug)]
pub enum CognitiveWireError {
    Contract(HnmfContractError),
    Json(serde_json::Error),
    SchemaMismatch,
    VersionMismatch(u32),
    ContractMismatch,
    NonCanonicalInput,
    NonIntegerNumber,
    PayloadLength { actual: usize, maximum: usize },
    EnvelopeLength { actual: usize, maximum: usize },
}

impl fmt::Display for CognitiveWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Contract(error) => error.fmt(formatter),
            Self::Json(error) => error.fmt(formatter),
            Self::SchemaMismatch => formatter.write_str("cognitive wire schema mismatch"),
            Self::VersionMismatch(version) => {
                write!(formatter, "unsupported cognitive wire version {version}")
            }
            Self::ContractMismatch => formatter.write_str("cognitive wire contract mismatch"),
            Self::NonCanonicalInput => {
                formatter.write_str("cognitive wire bytes are not canonical V1 JSON")
            }
            Self::NonIntegerNumber => {
                formatter.write_str("canonical V1 JSON forbids non-integer numbers")
            }
            Self::PayloadLength { actual, maximum } => {
                write!(
                    formatter,
                    "cognitive payload length {actual} exceeds {maximum}"
                )
            }
            Self::EnvelopeLength { actual, maximum } => {
                write!(
                    formatter,
                    "cognitive envelope length {actual} exceeds {maximum}"
                )
            }
        }
    }
}

impl CognitiveWireError {
    #[must_use]
    pub fn violation(&self) -> ContractViolationV1 {
        match self {
            Self::Contract(error) => error.violation(),
            Self::Json(error) => ContractViolationV1::new(
                ContractErrorCodeV1::InvalidValue,
                "wire",
                format!(
                    "invalid wire JSON at line {} column {}",
                    error.line(),
                    error.column()
                ),
            ),
            Self::SchemaMismatch => ContractViolationV1::new(
                ContractErrorCodeV1::SchemaMismatch,
                "schema",
                "wire schema does not match the requested contract",
            ),
            Self::VersionMismatch(version) => ContractViolationV1::new(
                ContractErrorCodeV1::VersionMismatch,
                "schemaVersion",
                format!("unsupported cognitive wire version {version}"),
            ),
            Self::ContractMismatch => ContractViolationV1::new(
                ContractErrorCodeV1::ContractMismatch,
                "contract",
                "wire contract identity does not match the requested type",
            ),
            Self::NonCanonicalInput | Self::NonIntegerNumber => ContractViolationV1::new(
                ContractErrorCodeV1::NonCanonicalEncoding,
                "wire",
                self.to_string(),
            ),
            Self::PayloadLength { actual, maximum } => ContractViolationV1::new(
                ContractErrorCodeV1::LimitExceeded,
                "payload",
                format!("{actual} exceeds maximum {maximum}"),
            ),
            Self::EnvelopeLength { actual, maximum } => ContractViolationV1::new(
                ContractErrorCodeV1::LimitExceeded,
                "envelope",
                format!("{actual} exceeds maximum {maximum}"),
            ),
        }
    }
}

impl From<CognitiveWireError> for ContractViolationV1 {
    fn from(value: CognitiveWireError) -> Self {
        value.violation()
    }
}

impl StdError for CognitiveWireError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Contract(error) => Some(error),
            Self::Json(error) => Some(error),
            _ => None,
        }
    }
}
