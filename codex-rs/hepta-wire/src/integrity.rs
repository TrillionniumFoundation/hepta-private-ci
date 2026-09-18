use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::envelope::HEADER_FIXED_BYTES;
use crate::envelope::MAGIC;
use crate::envelope::WIRE_VERSION;
use crate::envelope::WireEnvelope;
use crate::envelope::WireError;
use crate::envelope::body_offsets;
use crate::envelope::parse_id;
use crate::envelope::read_u16;
use crate::envelope::read_u32;
use crate::envelope::read_u64;
use crate::envelope::validate_identity_lengths;
use crate::envelope::validate_payload_length;

pub const HPTA_V1: u16 = WIRE_VERSION;
pub const HPTA_V2: u16 = 2;
pub const FRAME_V2_DIGEST_DOMAIN: &[u8] = b"HPTA-FRAME-V2\0";

/// HPTA V2 keeps V1's fixed header shape but changes the digest scope.
///
/// The 32-byte digest binds the canonical metadata and payload. It is still an
/// unkeyed SHA-256 digest, so adversarial source authentication remains the
/// responsibility of an authenticated transport or an owning signature/MAC
/// layer.
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
    ) -> Result<Self, WireError> {
        validate_payload_length(payload.len())?;
        let frame_digest = complete_frame_digest(&schema, &producer, generation, &payload);
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

    pub const fn version(&self) -> u16 {
        HPTA_V2
    }

    pub fn encode(&self) -> Vec<u8> {
        let schema = self.schema.as_str().as_bytes();
        let producer = self.producer.as_str().as_bytes();
        let mut encoded = Vec::with_capacity(
            HEADER_FIXED_BYTES + schema.len() + producer.len() + self.payload.len(),
        );
        encoded.extend_from_slice(&MAGIC);
        encoded.extend_from_slice(&HPTA_V2.to_be_bytes());
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

    pub fn decode(encoded: &[u8]) -> Result<Self, WireError> {
        if encoded.len() < HEADER_FIXED_BYTES {
            return Err(WireError::Truncated);
        }
        if encoded[..4] != MAGIC {
            return Err(WireError::Magic);
        }
        let version = read_u16(encoded, 4)?;
        if version != HPTA_V2 {
            return Err(WireError::Version(version));
        }
        let schema_length = usize::from(read_u16(encoded, 6)?);
        let producer_length = usize::from(read_u16(encoded, 8)?);
        validate_identity_lengths(schema_length, producer_length)?;
        let generation = Generation::new(read_u64(encoded, 10)?)
            .map_err(|_| WireError::Generation)?;

        let digest_start = 18;
        let digest_end = digest_start + 32;
        let mut digest = [0; 32];
        digest.copy_from_slice(&encoded[digest_start..digest_end]);

        let payload_length = usize::try_from(read_u32(encoded, digest_end)?)
            .map_err(|_| WireError::PayloadLength)?;
        validate_payload_length(payload_length)?;
        let (schema_end, producer_end, payload_end) =
            body_offsets(schema_length, producer_length, payload_length)?;
        if payload_end != encoded.len() {
            return Err(WireError::LengthMismatch);
        }

        let schema = std::str::from_utf8(&encoded[HEADER_FIXED_BYTES..schema_end])
            .map_err(|_| WireError::IdentityEncoding)
            .and_then(parse_id)?;
        let producer = std::str::from_utf8(&encoded[schema_end..producer_end])
            .map_err(|_| WireError::IdentityEncoding)
            .and_then(parse_id)?;
        let payload = &encoded[producer_end..payload_end];

        let expected = Digest32::from_array(digest);
        let observed = complete_frame_digest(&schema, &producer, generation, payload);
        if observed != expected {
            return Err(WireError::FrameDigestMismatch { expected, observed });
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

pub fn complete_frame_digest(
    schema: &StableId,
    producer: &StableId,
    generation: Generation,
    payload: &[u8],
) -> Digest32 {
    let schema_bytes = schema.as_str().as_bytes();
    let producer_bytes = producer.as_str().as_bytes();
    let mut material = Vec::with_capacity(
        FRAME_V2_DIGEST_DOMAIN.len()
            + HEADER_FIXED_BYTES
            + schema_bytes.len()
            + producer_bytes.len()
            + payload.len(),
    );
    material.extend_from_slice(FRAME_V2_DIGEST_DOMAIN);
    material.extend_from_slice(&MAGIC);
    material.extend_from_slice(&HPTA_V2.to_be_bytes());
    material.extend_from_slice(&(schema_bytes.len() as u16).to_be_bytes());
    material.extend_from_slice(&(producer_bytes.len() as u16).to_be_bytes());
    material.extend_from_slice(&generation.get().to_be_bytes());
    material.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    material.extend_from_slice(schema_bytes);
    material.extend_from_slice(producer_bytes);
    material.extend_from_slice(payload);
    Digest32::of_bytes(&material)
}

/// A multi-version decoding adapter that never asks the V1 decoder to accept V2
/// bytes and never reinterprets an unknown version.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireFrame {
    V1(WireEnvelope),
    V2(WireEnvelopeV2),
}

impl WireFrame {
    pub fn decode(encoded: &[u8]) -> Result<Self, WireError> {
        if encoded.len() < 6 {
            return Err(WireError::Truncated);
        }
        let version = read_u16(encoded, 4)?;
        match version {
            HPTA_V1 => WireEnvelope::decode(encoded).map(Self::V1),
            HPTA_V2 => WireEnvelopeV2::decode(encoded).map(Self::V2),
            other => Err(WireError::Version(other)),
        }
    }

    pub fn encode(&self) -> Vec<u8> {
        match self {
            Self::V1(value) => value.encode(),
            Self::V2(value) => value.encode(),
        }
    }

    pub const fn version(&self) -> u16 {
        match self {
            Self::V1(_) => HPTA_V1,
            Self::V2(_) => HPTA_V2,
        }
    }

    pub fn schema(&self) -> &StableId {
        match self {
            Self::V1(value) => value.schema(),
            Self::V2(value) => value.schema(),
        }
    }

    pub fn producer(&self) -> &StableId {
        match self {
            Self::V1(value) => value.producer(),
            Self::V2(value) => value.producer(),
        }
    }

    pub const fn generation(&self) -> Generation {
        match self {
            Self::V1(value) => value.generation(),
            Self::V2(value) => value.generation(),
        }
    }

    pub fn payload(&self) -> &[u8] {
        match self {
            Self::V1(value) => value.payload(),
            Self::V2(value) => value.payload(),
        }
    }
}
