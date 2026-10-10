use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAGIC: [u8; 4] = *b"HPTA";
const WIRE_VERSION: u16 = 1;
const HEADER_FIXED_BYTES: usize = 4 + 2 + 2 + 2 + 8 + 32 + 4;
pub const MAX_WIRE_PAYLOAD_BYTES: usize = 1_048_576;
const MAX_ID_BYTES: usize = 128;

/// One immutable, content-bound module message.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WireEnvelope {
    schema: StableId,
    producer: StableId,
    generation: Generation,
    payload_digest: Digest32,
    payload: Vec<u8>,
}

impl WireEnvelope {
    pub fn new(
        schema: StableId,
        producer: StableId,
        generation: Generation,
        payload: Vec<u8>,
    ) -> Result<Self, WireError> {
        validate_payload_length(payload.len())?;
        let payload_digest = Digest32::of_bytes(&payload);
        Ok(Self {
            schema,
            producer,
            generation,
            payload_digest,
            payload,
        })
    }

    pub fn schema(&self) -> &StableId {
        &self.schema
    }

    pub fn producer(&self) -> &StableId {
        &self.producer
    }

    pub const fn generation(&self) -> Generation {
        self.generation
    }

    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    pub fn encode(&self) -> Vec<u8> {
        let schema = self.schema.as_str().as_bytes();
        let producer = self.producer.as_str().as_bytes();
        let mut encoded = Vec::with_capacity(
            HEADER_FIXED_BYTES + schema.len() + producer.len() + self.payload.len(),
        );
        encoded.extend_from_slice(&MAGIC);
        encoded.extend_from_slice(&WIRE_VERSION.to_be_bytes());
        encoded.extend_from_slice(&(schema.len() as u16).to_be_bytes());
        encoded.extend_from_slice(&(producer.len() as u16).to_be_bytes());
        encoded.extend_from_slice(&self.generation.get().to_be_bytes());
        encoded.extend_from_slice(self.payload_digest.as_array());
        encoded.extend_from_slice(&(self.payload.len() as u32).to_be_bytes());
        encoded.extend_from_slice(schema);
        encoded.extend_from_slice(producer);
        encoded.extend_from_slice(&self.payload);
        encoded
    }

    pub fn decode(encoded: &[u8]) -> Result<Self, WireError> {
        if encoded.len() < HEADER_FIXED_BYTES {
            return Err(WireError::Truncated);
        }
        if encoded[..4] != MAGIC {
            return Err(WireError::Magic);
        }
        let version = read_u16(encoded, /*start*/ 4)?;
        if version != WIRE_VERSION {
            return Err(WireError::Version(version));
        }
        let schema_length = usize::from(read_u16(encoded, /*start*/ 6)?);
        let producer_length = usize::from(read_u16(encoded, /*start*/ 8)?);
        if !(1..=MAX_ID_BYTES).contains(&schema_length)
            || !(1..=MAX_ID_BYTES).contains(&producer_length)
        {
            return Err(WireError::IdentityLength);
        }
        let generation =
            Generation::new(read_u64(encoded, /*start*/ 10)?).map_err(|_| WireError::Generation)?;
        let digest_start = 18;
        let digest_end = digest_start + 32;
        let mut digest = [0; 32];
        digest.copy_from_slice(&encoded[digest_start..digest_end]);
        let payload_length = usize::try_from(read_u32(encoded, digest_end)?)
            .map_err(|_| WireError::PayloadLength)?;
        validate_payload_length(payload_length)?;
        let body_start = HEADER_FIXED_BYTES;
        let schema_end = body_start
            .checked_add(schema_length)
            .ok_or(WireError::PayloadLength)?;
        let producer_end = schema_end
            .checked_add(producer_length)
            .ok_or(WireError::PayloadLength)?;
        let payload_end = producer_end
            .checked_add(payload_length)
            .ok_or(WireError::PayloadLength)?;
        if payload_end != encoded.len() {
            return Err(WireError::LengthMismatch);
        }
        let schema = std::str::from_utf8(&encoded[body_start..schema_end])
            .map_err(|_| WireError::IdentityEncoding)
            .and_then(parse_id)?;
        let producer = std::str::from_utf8(&encoded[schema_end..producer_end])
            .map_err(|_| WireError::IdentityEncoding)
            .and_then(parse_id)?;
        let payload = &encoded[producer_end..payload_end];
        let expected = Digest32::from_array(digest);
        let observed = Digest32::of_bytes(payload);
        if observed != expected {
            return Err(WireError::DigestMismatch { expected, observed });
        }
        Ok(Self {
            schema,
            producer,
            generation,
            payload_digest: expected,
            payload: payload.to_vec(),
        })
    }
}

fn parse_id(value: &str) -> Result<StableId, WireError> {
    StableId::new(value).map_err(|_| WireError::IdentityEncoding)
}

fn validate_payload_length(length: usize) -> Result<(), WireError> {
    if length == 0 || length > MAX_WIRE_PAYLOAD_BYTES {
        return Err(WireError::PayloadLength);
    }
    Ok(())
}

fn read_u16(bytes: &[u8], start: usize) -> Result<u16, WireError> {
    let end = start.checked_add(2).ok_or(WireError::Truncated)?;
    let raw: [u8; 2] = bytes
        .get(start..end)
        .ok_or(WireError::Truncated)?
        .try_into()
        .map_err(|_| WireError::Truncated)?;
    Ok(u16::from_be_bytes(raw))
}

fn read_u32(bytes: &[u8], start: usize) -> Result<u32, WireError> {
    let end = start.checked_add(4).ok_or(WireError::Truncated)?;
    let raw: [u8; 4] = bytes
        .get(start..end)
        .ok_or(WireError::Truncated)?
        .try_into()
        .map_err(|_| WireError::Truncated)?;
    Ok(u32::from_be_bytes(raw))
}

fn read_u64(bytes: &[u8], start: usize) -> Result<u64, WireError> {
    let end = start.checked_add(8).ok_or(WireError::Truncated)?;
    let raw: [u8; 8] = bytes
        .get(start..end)
        .ok_or(WireError::Truncated)?
        .try_into()
        .map_err(|_| WireError::Truncated)?;
    Ok(u64::from_be_bytes(raw))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireError {
    Truncated,
    Magic,
    Version(u16),
    IdentityLength,
    IdentityEncoding,
    Generation,
    PayloadLength,
    LengthMismatch,
    DigestMismatch {
        expected: Digest32,
        observed: Digest32,
    },
}

impl fmt::Display for WireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated => formatter.write_str("wire envelope is truncated"),
            Self::Magic => formatter.write_str("wire envelope magic mismatch"),
            Self::Version(version) => write!(formatter, "unsupported wire version {version}"),
            Self::IdentityLength => formatter.write_str("wire identity length is outside bounds"),
            Self::IdentityEncoding => formatter.write_str("wire identity is not canonical"),
            Self::Generation => formatter.write_str("wire generation must be non-zero"),
            Self::PayloadLength => formatter.write_str("wire payload length is outside bounds"),
            Self::LengthMismatch => formatter.write_str("wire envelope length mismatch"),
            Self::DigestMismatch { expected, observed } => {
                write!(
                    formatter,
                    "wire payload digest mismatch: expected {expected}, observed {observed}"
                )
            }
        }
    }
}

impl Error for WireError {}

#[cfg(test)]
#[path = "envelope_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "boundary_tests.rs"]
mod boundary_tests;
