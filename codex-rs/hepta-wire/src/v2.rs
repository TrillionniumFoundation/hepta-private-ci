use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::envelope::HEADER_FIXED_BYTES;
use crate::envelope::MAGIC;
use crate::envelope::WireError;
use crate::envelope::parse_frame_header;
use crate::envelope::parse_id;
use crate::envelope::validate_payload_length;

pub const WIRE_VERSION_V2: u16 = 2;
const V2_INTEGRITY_DOMAIN: &[u8] = b"HPTA-FRAME-V2\0";

/// HPTA V2 envelope with a digest that binds all serialized semantic metadata
/// and payload bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WireEnvelopeV2 {
    schema: StableId,
    producer: StableId,
    generation: Generation,
    integrity_digest: Digest32,
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
        let integrity_digest =
            compute_integrity_digest(&schema, &producer, generation, &payload);
        Ok(Self {
            schema,
            producer,
            generation,
            integrity_digest,
            payload,
        })
    }

    pub const fn wire_version(&self) -> u16 {
        WIRE_VERSION_V2
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

    pub const fn integrity_digest(&self) -> Digest32 {
        self.integrity_digest
    }

    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    pub fn encoded_len(&self) -> usize {
        HEADER_FIXED_BYTES
            + self.schema.as_str().len()
            + self.producer.as_str().len()
            + self.payload.len()
    }

    pub fn encode(&self) -> Vec<u8> {
        let schema = self.schema.as_str().as_bytes();
        let producer = self.producer.as_str().as_bytes();
        let mut encoded = Vec::with_capacity(self.encoded_len());
        encoded.extend_from_slice(&MAGIC);
        encoded.extend_from_slice(&WIRE_VERSION_V2.to_be_bytes());
        encoded.extend_from_slice(&(schema.len() as u16).to_be_bytes());
        encoded.extend_from_slice(&(producer.len() as u16).to_be_bytes());
        encoded.extend_from_slice(&self.generation.get().to_be_bytes());
        encoded.extend_from_slice(self.integrity_digest.as_array());
        encoded.extend_from_slice(&(self.payload.len() as u32).to_be_bytes());
        encoded.extend_from_slice(schema);
        encoded.extend_from_slice(producer);
        encoded.extend_from_slice(&self.payload);
        encoded
    }

    pub fn decode(encoded: &[u8]) -> Result<Self, WireError> {
        let header = parse_frame_header(encoded)?;
        if header.version != WIRE_VERSION_V2 {
            return Err(WireError::Version(header.version));
        }
        if header.total_length != encoded.len() {
            return Err(WireError::LengthMismatch);
        }

        let body_start = HEADER_FIXED_BYTES;
        let schema_end = body_start + header.schema_length;
        let producer_end = schema_end + header.producer_length;
        let payload_end = producer_end + header.payload_length;
        let schema = std::str::from_utf8(&encoded[body_start..schema_end])
            .map_err(|_| WireError::IdentityEncoding)
            .and_then(parse_id)?;
        let producer = std::str::from_utf8(&encoded[schema_end..producer_end])
            .map_err(|_| WireError::IdentityEncoding)
            .and_then(parse_id)?;
        let payload = &encoded[producer_end..payload_end];
        let observed =
            compute_integrity_digest(&schema, &producer, header.generation, payload);
        if observed != header.digest {
            return Err(WireError::IntegrityMismatch {
                expected: header.digest,
                observed,
            });
        }

        Ok(Self {
            schema,
            producer,
            generation: header.generation,
            integrity_digest: header.digest,
            payload: payload.to_vec(),
        })
    }
}

/// V2 digest preimage:
/// domain || magic || version || schema_len || producer_len || generation ||
/// payload_len || schema || producer || payload.
///
/// The on-wire digest field itself is excluded to avoid a circular preimage.
fn compute_integrity_digest(
    schema: &StableId,
    producer: &StableId,
    generation: Generation,
    payload: &[u8],
) -> Digest32 {
    let schema = schema.as_str().as_bytes();
    let producer = producer.as_str().as_bytes();
    let mut preimage = Vec::with_capacity(
        V2_INTEGRITY_DOMAIN.len()
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
    preimage.extend_from_slice(V2_INTEGRITY_DOMAIN);
    preimage.extend_from_slice(&MAGIC);
    preimage.extend_from_slice(&WIRE_VERSION_V2.to_be_bytes());
    preimage.extend_from_slice(&(schema.len() as u16).to_be_bytes());
    preimage.extend_from_slice(&(producer.len() as u16).to_be_bytes());
    preimage.extend_from_slice(&generation.get().to_be_bytes());
    preimage.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    preimage.extend_from_slice(schema);
    preimage.extend_from_slice(producer);
    preimage.extend_from_slice(payload);
    Digest32::of_bytes(&preimage)
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use super::*;

    fn envelope() -> Result<WireEnvelopeV2, Box<dyn Error>> {
        Ok(WireEnvelopeV2::new(
            StableId::new("hepta.test.v2")?,
            StableId::new("platform.wire")?,
            Generation::new(7)?,
            b"bounded-payload".to_vec(),
        )?)
    }

    #[test]
    fn v2_round_trip_is_exact() -> Result<(), Box<dyn Error>> {
        let envelope = envelope()?;
        let encoded = envelope.encode();
        assert_eq!(WireEnvelopeV2::decode(&encoded), Ok(envelope));
        Ok(())
    }

    #[test]
    fn metadata_and_payload_tamper_fail_integrity() -> Result<(), Box<dyn Error>> {
        let envelope = WireEnvelopeV2::new(
            StableId::new("schema-a")?,
            StableId::new("producer-a")?,
            Generation::new(9)?,
            vec![1, 2, 3],
        )?;

        let mut schema_tamper = envelope.encode();
        schema_tamper[HEADER_FIXED_BYTES] = b'b';
        assert!(matches!(
            WireEnvelopeV2::decode(&schema_tamper),
            Err(WireError::IntegrityMismatch { .. })
        ));

        let mut producer_tamper = envelope.encode();
        let producer_start = HEADER_FIXED_BYTES + "schema-a".len();
        producer_tamper[producer_start] = b'q';
        assert!(matches!(
            WireEnvelopeV2::decode(&producer_tamper),
            Err(WireError::IntegrityMismatch { .. })
        ));

        let mut generation_tamper = envelope.encode();
        generation_tamper[17] ^= 1;
        assert!(matches!(
            WireEnvelopeV2::decode(&generation_tamper),
            Err(WireError::IntegrityMismatch { .. })
        ));

        let mut payload_tamper = envelope.encode();
        let last = payload_tamper.len() - 1;
        payload_tamper[last] ^= 1;
        assert!(matches!(
            WireEnvelopeV2::decode(&payload_tamper),
            Err(WireError::IntegrityMismatch { .. })
        ));
        Ok(())
    }

    #[test]
    fn v2_matches_independent_frozen_vector() -> Result<(), Box<dyn Error>> {
        let golden: [u8; 59] = [
            0x48, 0x50, 0x54, 0x41, 0x00, 0x02, 0x00, 0x01, 0x00, 0x01, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x11, 0x1f, 0x5b, 0xfd,
            0x88, 0x14, 0x5a, 0x71, 0x5c, 0x61, 0xa8, 0xd0, 0x90, 0xbf, 0x0e,
            0xe8, 0x20, 0xb9, 0x24, 0xd4, 0x64, 0x96, 0x16, 0x04, 0x73, 0xc8,
            0x47, 0x05, 0x73, 0xb6, 0x31, 0x5d, 0x00, 0x00, 0x00, 0x03, b's',
            b'p', 0x01, 0x02, 0x03,
        ];
        let expected = WireEnvelopeV2::new(
            StableId::new("s")?,
            StableId::new("p")?,
            Generation::new(1)?,
            vec![1, 2, 3],
        )?;
        assert_eq!(expected.encode(), golden);
        assert_eq!(WireEnvelopeV2::decode(&golden), Ok(expected));
        Ok(())
    }
}
