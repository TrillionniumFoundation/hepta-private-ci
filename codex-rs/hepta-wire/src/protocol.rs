use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::envelope::parse_frame_header;
use crate::envelope::WIRE_VERSION_V1;
use crate::v2::WIRE_VERSION_V2;

/// Read-only semantic view shared by V1 and V2 envelopes.
pub trait EnvelopeView {
    fn wire_version(&self) -> u16;
    fn schema(&self) -> &StableId;
    fn producer(&self) -> &StableId;
    fn generation(&self) -> Generation;
    fn payload(&self) -> &[u8];
}

impl EnvelopeView for WireEnvelope {
    fn wire_version(&self) -> u16 {
        self.wire_version()
    }

    fn schema(&self) -> &StableId {
        self.schema()
    }

    fn producer(&self) -> &StableId {
        self.producer()
    }

    fn generation(&self) -> Generation {
        self.generation()
    }

    fn payload(&self) -> &[u8] {
        self.payload()
    }
}

impl EnvelopeView for WireEnvelopeV2 {
    fn wire_version(&self) -> u16 {
        self.wire_version()
    }

    fn schema(&self) -> &StableId {
        self.schema()
    }

    fn producer(&self) -> &StableId {
        self.producer()
    }

    fn generation(&self) -> Generation {
        self.generation()
    }

    fn payload(&self) -> &[u8] {
        self.payload()
    }
}

/// A decoded HPTA frame. V1 remains immutable and payload-digest-only; V2 binds
/// metadata and payload under a full semantic integrity digest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireFrame {
    V1(WireEnvelope),
    V2(WireEnvelopeV2),
}

impl WireFrame {
    pub fn decode(encoded: &[u8]) -> Result<Self, WireError> {
        let header = parse_frame_header(encoded)?;
        match header.version {
            WIRE_VERSION_V1 => WireEnvelope::decode(encoded).map(Self::V1),
            WIRE_VERSION_V2 => WireEnvelopeV2::decode(encoded).map(Self::V2),
            version => Err(WireError::Version(version)),
        }
    }

    pub fn wire_version(&self) -> u16 {
        match self {
            Self::V1(envelope) => envelope.wire_version(),
            Self::V2(envelope) => envelope.wire_version(),
        }
    }

    pub fn encode(&self) -> Vec<u8> {
        match self {
            Self::V1(envelope) => envelope.encode(),
            Self::V2(envelope) => envelope.encode(),
        }
    }
}

impl EnvelopeView for WireFrame {
    fn wire_version(&self) -> u16 {
        WireFrame::wire_version(self)
    }

    fn schema(&self) -> &StableId {
        match self {
            Self::V1(envelope) => envelope.schema(),
            Self::V2(envelope) => envelope.schema(),
        }
    }

    fn producer(&self) -> &StableId {
        match self {
            Self::V1(envelope) => envelope.producer(),
            Self::V2(envelope) => envelope.producer(),
        }
    }

    fn generation(&self) -> Generation {
        match self {
            Self::V1(envelope) => envelope.generation(),
            Self::V2(envelope) => envelope.generation(),
        }
    }

    fn payload(&self) -> &[u8] {
        match self {
            Self::V1(envelope) => envelope.payload(),
            Self::V2(envelope) => envelope.payload(),
        }
    }
}

#[cfg(test)]
mod tests {
    use std::panic::catch_unwind;

    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    use super::*;

    fn next(state: &mut u64) -> u64 {
        *state ^= *state << 13;
        *state ^= *state >> 7;
        *state ^= *state << 17;
        *state
    }

    #[test]
    fn deterministic_property_round_trips_many_frames() {
        let mut state = 0x4d59_5df4_d0f3_3173_u64;
        for index in 1..=1_024_u64 {
            let payload_len = (next(&mut state) as usize % 4_096) + 1;
            let mut payload = Vec::with_capacity(payload_len);
            for _ in 0..payload_len {
                payload.push(next(&mut state) as u8);
            }
            let schema = StableId::new(format!("wire.property.schema.{index}")).expect("schema");
            let producer =
                StableId::new(format!("wire.property.producer.{index}")).expect("producer");
            let generation = Generation::new(index).expect("generation");

            let v1 = WireFrame::V1(
                WireEnvelope::new(
                    schema.clone(),
                    producer.clone(),
                    generation,
                    payload.clone(),
                )
                .expect("v1"),
            );
            let v2 = WireFrame::V2(
                WireEnvelopeV2::new(schema, producer, generation, payload).expect("v2"),
            );

            for frame in [v1, v2] {
                let encoded = frame.encode();
                let decoded = WireFrame::decode(&encoded).expect("decode");
                assert_eq!(decoded, frame);
                assert_eq!(decoded.encode(), encoded);
            }
        }
    }

    #[test]
    fn arbitrary_bytes_never_panic() {
        let mut state = 0x9e37_79b9_7f4a_7c15_u64;
        for _ in 0..4_096 {
            let length = next(&mut state) as usize % 512;
            let mut input = Vec::with_capacity(length);
            for _ in 0..length {
                input.push(next(&mut state) as u8);
            }
            assert!(catch_unwind(|| WireFrame::decode(&input)).is_ok());
        }
    }
}
