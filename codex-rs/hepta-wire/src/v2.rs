use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAGIC: [u8; 4] = *b"HPTA";
const WIRE_VERSION_V2: u16 = 2;
pub const HPTA_V2_HEADER_BYTES: usize = 4 + 2 + 2 + 2 + 8 + 32 + 32 + 4;
const MAX_ID_BYTES: usize = 128;
const FRAME_DIGEST_DOMAIN: &[u8] = b"HPTA-FRAME-V2\0";

/// HPTA V2 preserves the V1 payload digest and additionally binds every
/// semantic frame field into a second digest.
///
/// The frame digest is not a signature or MAC. Callers that need adversarial
/// tamper resistance must authenticate the encoded frame (or an out-of-band
/// copy of frame_digest) at the transport/session boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WireEnvelopeV2 {
    schema: StableId,
    producer: StableId,
    generation: Generation,
    payload_digest: Digest32,
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
        validate_identity_lengths(&schema, &producer)?;
        validate_payload_length(payload.len())?;
        let payload_digest = Digest32::of_bytes(&payload);
        let frame_digest =
            calculate_frame_digest(&schema, &producer, generation, payload_digest, &payload);
        Ok(Self {
            schema,
            producer,
            generation,
            payload_digest,
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

    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
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
            HPTA_V2_HEADER_BYTES + schema.len() + producer.len() + self.payload.len(),
        );
        encoded.extend_from_slice(&MAGIC);
        encoded.extend_from_slice(&WIRE_VERSION_V2.to_be_bytes());
        encoded.extend_from_slice(&(schema.len() as u16).to_be_bytes());
        encoded.extend_from_slice(&(producer.len() as u16).to_be_bytes());
        encoded.extend_from_slice(&self.generation.get().to_be_bytes());
        encoded.extend_from_slice(self.payload_digest.as_array());
        encoded.extend_from_slice(self.frame_digest.as_array());
        encoded.extend_from_slice(&(self.payload.len() as u32).to_be_bytes());
        encoded.extend_from_slice(schema);
        encoded.extend_from_slice(producer);
        encoded.extend_from_slice(&self.payload);
        encoded
    }

    pub fn decode(encoded: &[u8]) -> Result<Self, WireV2Error> {
        if encoded.len() < HPTA_V2_HEADER_BYTES {
            return Err(WireV2Error::Truncated);
        }
        if encoded[..4] != MAGIC {
            return Err(WireV2Error::Magic);
        }
        let version = read_u16(encoded, 4)?;
        if version != WIRE_VERSION_V2 {
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

        let mut payload_digest_raw = [0_u8; 32];
        payload_digest_raw.copy_from_slice(&encoded[18..50]);
        let payload_digest = Digest32::from_array(payload_digest_raw);

        let mut frame_digest_raw = [0_u8; 32];
        frame_digest_raw.copy_from_slice(&encoded[50..82]);
        let expected_frame_digest = Digest32::from_array(frame_digest_raw);

        let payload_length =
            usize::try_from(read_u32(encoded, 82)?).map_err(|_| WireV2Error::PayloadLength)?;
        validate_payload_length(payload_length)?;

        let schema_end = HPTA_V2_HEADER_BYTES
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

        let schema = std::str::from_utf8(&encoded[HPTA_V2_HEADER_BYTES..schema_end])
            .map_err(|_| WireV2Error::IdentityEncoding)
            .and_then(parse_id)?;
        let producer = std::str::from_utf8(&encoded[schema_end..producer_end])
            .map_err(|_| WireV2Error::IdentityEncoding)
            .and_then(parse_id)?;
        let payload = &encoded[producer_end..payload_end];

        let observed_payload_digest = Digest32::of_bytes(payload);
        if observed_payload_digest != payload_digest {
            return Err(WireV2Error::PayloadDigestMismatch {
                expected: payload_digest,
                observed: observed_payload_digest,
            });
        }

        let observed_frame_digest =
            calculate_frame_digest(&schema, &producer, generation, payload_digest, payload);
        if observed_frame_digest != expected_frame_digest {
            return Err(WireV2Error::FrameDigestMismatch {
                expected: expected_frame_digest,
                observed: observed_frame_digest,
            });
        }

        Ok(Self {
            schema,
            producer,
            generation,
            payload_digest,
            frame_digest: expected_frame_digest,
            payload: payload.to_vec(),
        })
    }

    /// Verify a V2 frame and additionally require a binding digest received
    /// from an authenticated out-of-band channel.
    pub fn decode_bound(encoded: &[u8], expected_binding: Digest32) -> Result<Self, WireV2Error> {
        let decoded = Self::decode(encoded)?;
        if decoded.frame_digest != expected_binding {
            return Err(WireV2Error::BindingMismatch {
                expected: expected_binding,
                observed: decoded.frame_digest,
            });
        }
        Ok(decoded)
    }
}

fn calculate_frame_digest(
    schema: &StableId,
    producer: &StableId,
    generation: Generation,
    payload_digest: Digest32,
    payload: &[u8],
) -> Digest32 {
    let schema = schema.as_str().as_bytes();
    let producer = producer.as_str().as_bytes();
    let mut material = Vec::with_capacity(
        FRAME_DIGEST_DOMAIN.len() + 54 + schema.len() + producer.len() + payload.len(),
    );
    material.extend_from_slice(FRAME_DIGEST_DOMAIN);
    material.extend_from_slice(&MAGIC);
    material.extend_from_slice(&WIRE_VERSION_V2.to_be_bytes());
    material.extend_from_slice(&(schema.len() as u16).to_be_bytes());
    material.extend_from_slice(&(producer.len() as u16).to_be_bytes());
    material.extend_from_slice(&generation.get().to_be_bytes());
    material.extend_from_slice(payload_digest.as_array());
    material.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    material.extend_from_slice(schema);
    material.extend_from_slice(producer);
    material.extend_from_slice(payload);
    Digest32::of_bytes(&material)
}

fn parse_id(value: &str) -> Result<StableId, WireV2Error> {
    StableId::new(value).map_err(|_| WireV2Error::IdentityEncoding)
}

fn validate_identity_lengths(schema: &StableId, producer: &StableId) -> Result<(), WireV2Error> {
    if !(1..=MAX_ID_BYTES).contains(&schema.as_str().len())
        || !(1..=MAX_ID_BYTES).contains(&producer.as_str().len())
    {
        return Err(WireV2Error::IdentityLength);
    }
    Ok(())
}

fn validate_payload_length(length: usize) -> Result<(), WireV2Error> {
    if length == 0 || length > crate::MAX_WIRE_PAYLOAD_BYTES {
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
    PayloadDigestMismatch {
        expected: Digest32,
        observed: Digest32,
    },
    FrameDigestMismatch {
        expected: Digest32,
        observed: Digest32,
    },
    BindingMismatch {
        expected: Digest32,
        observed: Digest32,
    },
}

impl fmt::Display for WireV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Truncated => formatter.write_str("wire V2 envelope is truncated"),
            Self::Magic => formatter.write_str("wire V2 envelope magic mismatch"),
            Self::Version(version) => write!(formatter, "unsupported V2 decoder version {version}"),
            Self::IdentityLength => formatter.write_str("wire V2 identity length is outside bounds"),
            Self::IdentityEncoding => formatter.write_str("wire V2 identity is not canonical"),
            Self::Generation => formatter.write_str("wire V2 generation must be non-zero"),
            Self::PayloadLength => formatter.write_str("wire V2 payload length is outside bounds"),
            Self::LengthMismatch => formatter.write_str("wire V2 envelope length mismatch"),
            Self::PayloadDigestMismatch { expected, observed } => write!(
                formatter,
                "wire V2 payload digest mismatch: expected {expected}, observed {observed}"
            ),
            Self::FrameDigestMismatch { expected, observed } => write!(
                formatter,
                "wire V2 frame digest mismatch: expected {expected}, observed {observed}"
            ),
            Self::BindingMismatch { expected, observed } => write!(
                formatter,
                "wire V2 authenticated binding mismatch: expected {expected}, observed {observed}"
            ),
        }
    }
}

impl Error for WireV2Error {}
