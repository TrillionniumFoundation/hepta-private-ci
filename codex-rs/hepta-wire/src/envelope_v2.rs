use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::envelope::MAX_WIRE_PAYLOAD_BYTES;

const MAGIC: [u8; 4] = *b"HPTA";
const WIRE_VERSION: u16 = 2;
const HEADER_FIXED_BYTES: usize = 4 + 2 + 2 + 2 + 8 + 32 + 4;
const MAX_ID_BYTES: usize = 128;
const FRAME_DIGEST_DOMAIN: &[u8] = b"hepta.platform.wire.hpta.v2.frame-digest\0";

/// HPTA V2 envelope whose embedded digest binds metadata and payload.
///
/// The frame digest is corruption/integrity evidence, not authentication. A
/// caller that needs tamper resistance must authenticate the encoded frame (or
/// the equivalent session transcript) outside this authority-free codec.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WireEnvelopeV2 {
    schema: StableId,
    producer: StableId,
    generation: Generation,
    frame_digest: Digest32,
    payload: Vec<u8>,
}

impl WireEnvelopeV2 {
    pub fn new(
        schema: StableId,
        producer: StableId,
        generation: Generation,
        payload: Vec<u8>,
    ) -> Result<Self, WireV2Error> {
        validate_payload_length(payload.len())?;
        let frame_digest = compute_frame_digest(&schema, &producer, generation, &payload);
        Ok(Self {
            schema,
            producer,
            generation,
            frame_digest,
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

    pub const fn frame_digest(&self) -> Digest32 {
        self.frame_digest
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
        encoded.extend_from_slice(self.frame_digest.as_array());
        encoded.extend_from_slice(&(self.payload.len() as u32).to_be_bytes());
        encoded.extend_from_slice(schema);
        encoded.extend_from_slice(producer);
        encoded.extend_from_slice(&self.payload);
        encoded
    }

    pub fn decode(encoded: &[u8]) -> Result<Self, WireV2Error> {
        if encoded.len() < HEADER_FIXED_BYTES {
            return Err(WireV2Error::Truncated);
        }
        if encoded[..4] != MAGIC {
            return Err(WireV2Error::Magic);
        }
        let version = read_u16(encoded, 4)?;
        if version != WIRE_VERSION {
            return Err(WireV2Error::Version(version));
        }
        let schema_length = usize::from(read_u16(encoded, 6)?);
        let producer_length = usize::from(read_u16(encoded, 8)?);
        if !(1..=MAX_ID_BYTES).contains(&schema_length)
            || !(1..=MAX_ID_BYTES).contains(&producer_length)
        {
            return Err(WireV2Error::IdentityLength);
        }
        let generation =
            Generation::new(read_u64(encoded, 10)?).map_err(|_| WireV2Error::Generation)?;
        let digest_start = 18;
        let digest_end = digest_start + 32;
        let mut digest = [0_u8; 32];
        digest.copy_from_slice(&encoded[digest_start..digest_end]);
        let payload_length = usize::try_from(read_u32(encoded, digest_end)?)
            .map_err(|_| WireV2Error::PayloadLength)?;
        validate_payload_length(payload_length)?;

        let body_start = HEADER_FIXED_BYTES;
        let schema_end = body_start
            .checked_add(schema_length)
            .ok_or(WireV2Error::LengthMismatch)?;
        let producer_end = schema_end
            .checked_add(producer_length)
            .ok_or(WireV2Error::LengthMismatch)?;
        let payload_end = producer_end
            .checked_add(payload_length)
            .ok_or(WireV2Error::LengthMismatch)?;
        if payload_end != encoded.len() {
            return Err(WireV2Error::LengthMismatch);
        }

        let schema = std::str::from_utf8(&encoded[body_start..schema_end])
            .map_err(|_| WireV2Error::IdentityEncoding)
            .and_then(parse_id)?;
        let producer = std::str::from_utf8(&encoded[schema_end..producer_end])
            .map_err(|_| WireV2Error::IdentityEncoding)
            .and_then(parse_id)?;
        let payload = &encoded[producer_end..payload_end];
        let expected = Digest32::from_array(digest);
        let observed = compute_frame_digest(&schema, &producer, generation, payload);
        if observed != expected {
            return Err(WireV2Error::FrameDigestMismatch { expected, observed });
        }

        Ok(Self {
            schema,
            producer,
            generation,
            frame_digest: expected,
            payload: payload.to_vec(),
        })
    }
}

fn compute_frame_digest(
    schema: &StableId,
    producer: &StableId,
    generation: Generation,
    payload: &[u8],
) -> Digest32 {
    let schema = schema.as_str().as_bytes();
    let producer = producer.as_str().as_bytes();
    let mut bytes = Vec::with_capacity(
        FRAME_DIGEST_DOMAIN.len()
            + 4
            + 2
            + 2
            + 2
            + 8
            + 4
            + schema.len()
            + producer.len()
            + payload.len(),
    );
    bytes.extend_from_slice(FRAME_DIGEST_DOMAIN);
    bytes.extend_from_slice(&MAGIC);
    bytes.extend_from_slice(&WIRE_VERSION.to_be_bytes());
    bytes.extend_from_slice(&(schema.len() as u16).to_be_bytes());
    bytes.extend_from_slice(&(producer.len() as u16).to_be_bytes());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    bytes.extend_from_slice(schema);
    bytes.extend_from_slice(producer);
    bytes.extend_from_slice(payload);
    Digest32::of_bytes(&bytes)
}

fn parse_id(value: &str) -> Result<StableId, WireV2Error> {
    StableId::new(value).map_err(|_| WireV2Error::IdentityEncoding)
}

fn validate_payload_length(length: usize) -> Result<(), WireV2Error> {
    if length == 0 || length > MAX_WIRE_PAYLOAD_BYTES {
        return Err(WireV2Error::PayloadLength);
    }
    Ok(())
}

fn read_u16(bytes: &[u8], start: usize) -> Result<u16, WireV2Error> {
    let end = start.checked_add(2).ok_or(WireV2Error::Truncated)?;
    let raw: [u8; 2] = bytes
        .get(start..end)
        .ok_or(WireV2Error::Truncated)?
        .try_into()
        .map_err(|_| WireV2Error::Truncated)?;
    Ok(u16::from_be_bytes(raw))
}

fn read_u32(bytes: &[u8], start: usize) -> Result<u32, WireV2Error> {
    let end = start.checked_add(4).ok_or(WireV2Error::Truncated)?;
    let raw: [u8; 4] = bytes
        .get(start..end)
        .ok_or(WireV2Error::Truncated)?
        .try_into()
        .map_err(|_| WireV2Error::Truncated)?;
    Ok(u32::from_be_bytes(raw))
}

fn read_u64(bytes: &[u8], start: usize) -> Result<u64, WireV2Error> {
    let end = start.checked_add(8).ok_or(WireV2Error::Truncated)?;
    let raw: [u8; 8] = bytes
        .get(start..end)
        .ok_or(WireV2Error::Truncated)?
        .try_into()
        .map_err(|_| WireV2Error::Truncated)?;
    Ok(u64::from_be_bytes(raw))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireV2Error {
    Truncated,
    Magic,
    Version(u16),
    IdentityLength,
    IdentityEncoding,
    Generation,
    PayloadLength,
    LengthMismatch,
    FrameDigestMismatch {
        expected: Digest32,
        observed: Digest32,
    },
}

impl fmt::Display for WireV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated => formatter.write_str("wire V2 envelope is truncated"),
            Self::Magic => formatter.write_str("wire V2 envelope magic mismatch"),
            Self::Version(version) => write!(formatter, "unsupported wire V2 version {version}"),
            Self::IdentityLength => formatter.write_str("wire V2 identity length is outside bounds"),
            Self::IdentityEncoding => formatter.write_str("wire V2 identity is not canonical"),
            Self::Generation => formatter.write_str("wire V2 generation must be non-zero"),
            Self::PayloadLength => formatter.write_str("wire V2 payload length is outside bounds"),
            Self::LengthMismatch => formatter.write_str("wire V2 envelope length mismatch"),
            Self::FrameDigestMismatch { expected, observed } => write!(
                formatter,
                "wire V2 frame digest mismatch: expected {expected}, observed {observed}"
            ),
        }
    }
}

impl Error for WireV2Error {}

#[cfg(test)]
#[path = "envelope_v2_tests.rs"]
mod tests;
