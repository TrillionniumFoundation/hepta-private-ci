//! Strict JSON shape decoding into owner-local objective source fields.
//! This module deliberately does not implement canonical encoding or admission.

use std::error::Error;
use std::fmt;

use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveStructureError;
use crate::source_envelope_json_dto::Envelope;

/// Raw ingress budget chosen to not exceed the registry's 262144-byte envelope
/// ceiling. This counts supplied JSON bytes, including whitespace and escapes;
/// it does not certify canonical or nested aggregate encoded-byte bounds.
pub const MAX_OBJECTIVE_SOURCE_JSON_INPUT_BYTES: usize = 262_144;

/// Safe structural errors. Raw serde errors can contain source keys/values and
/// are intentionally neither retained nor exposed through `Error::source`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveSourceJsonError {
    InputTooLarge { actual: usize, maximum: usize },
    InvalidJson { line: usize, column: usize },
    Structure(ObjectiveStructureError),
}

impl fmt::Display for ObjectiveSourceJsonError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InputTooLarge { actual, maximum } => {
                write!(
                    formatter,
                    "objective JSON has {actual} input bytes; maximum is {maximum}"
                )
            }
            Self::InvalidJson { line, column } => {
                write!(
                    formatter,
                    "invalid objective JSON structure at line {line}, column {column}"
                )
            }
            Self::Structure(error) => fmt::Display::fmt(error, formatter),
        }
    }
}

impl Error for ObjectiveSourceJsonError {}

/// Decode exactly one JSON object, preserving every source field and its order
/// within arrays. Each object rejects unknown, missing and duplicate keys;
/// decoded key aliases count as duplicates. Optional deadline may be absent,
/// but present null is rejected along with all other nonnullable null values.
///
/// Integer widths, enum spellings and lowercase hex digest syntax are exact.
/// No digest is recomputed or authenticated. Identifier/time syntax, NFC,
/// canonical bytes, profile semantics, freshness and authority remain unverified.
/// A successful decode is not an admitted input to the existing scalar compiler.
pub fn decode_source_envelope_json_v1(
    input: &[u8],
) -> Result<ObjectiveSourceEnvelopeV1, ObjectiveSourceJsonError> {
    if input.len() > MAX_OBJECTIVE_SOURCE_JSON_INPUT_BYTES {
        return Err(ObjectiveSourceJsonError::InputTooLarge {
            actual: input.len(),
            maximum: MAX_OBJECTIVE_SOURCE_JSON_INPUT_BYTES,
        });
    }
    let mut deserializer = serde_json::Deserializer::from_slice(input);
    let source = Envelope::decode(&mut deserializer).map_err(json_error)?;
    deserializer.end().map_err(json_error)?;
    source
        .validate_structure()
        .map_err(ObjectiveSourceJsonError::Structure)?;
    Ok(source)
}

fn json_error(error: serde_json::Error) -> ObjectiveSourceJsonError {
    ObjectiveSourceJsonError::InvalidJson {
        line: error.line(),
        column: error.column(),
    }
}

#[cfg(test)]
#[path = "source_envelope_json_tests.rs"]
mod tests;
