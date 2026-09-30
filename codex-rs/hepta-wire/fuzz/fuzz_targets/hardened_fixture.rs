use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::BoundPayloadCodec;
use codex_hepta_wire::CanonicalizationProfile;
use codex_hepta_wire::HardenedManagedSessionError;
use codex_hepta_wire::HardenedManagedWireSession;
use codex_hepta_wire::HardenedRecordStreamError;
use codex_hepta_wire::HardenedWireSessionError;
use codex_hepta_wire::NegotiationOffer;
use codex_hepta_wire::PayloadCodec;
use codex_hepta_wire::RecordStreamLimits;
use codex_hepta_wire::SchemaCodecError;
use codex_hepta_wire::SchemaDescriptor;
use codex_hepta_wire::SessionEndpoint;
use codex_hepta_wire::SessionLifecycleState;
use codex_hepta_wire::SessionMacKey;

use crate::managed_fixture::Outcome;
use crate::managed_fixture::envelope;
use crate::managed_fixture::owner;
use crate::managed_fixture::session;

struct Codec {
    descriptor: SchemaDescriptor,
    revision: Digest32,
}

impl PayloadCodec for Codec {
    type Value = Vec<u8>;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        Ok(value.clone())
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        let end = payload
            .iter()
            .rposition(|byte| *byte != 0)
            .map_or(0, |index| index + 1);
        Ok(payload[..end].to_vec())
    }
}

impl BoundPayloadCodec for Codec {
    fn schema_revision(&self) -> Digest32 {
        self.revision
    }

    fn canonicalization_profile(&self) -> CanonicalizationProfile {
        CanonicalizationProfile::CodecOwnedStrictV1
    }
}

fn fixture(endpoint: SessionEndpoint) -> Outcome<(HardenedManagedWireSession, Codec)> {
    let session = session(/*channel*/ 1)?;
    let schema = StableId::new("schema.managed-fuzz.v1")?;
    let policy = session
        .registry()
        .policy(&schema)
        .ok_or("missing fuzz schema")?;
    let codec = Codec {
        descriptor: policy.descriptor().clone(),
        revision: policy.schema_revision(),
    };
    let offer = NegotiationOffer::current();
    let hardened = HardenedManagedWireSession::establish(
        &offer,
        &offer,
        session.negotiated().required_capabilities(),
        session.role().clone(),
        Arc::new(session.registry().clone()),
        &[1; 32],
        SessionMacKey::new([9; 32])?,
        endpoint,
    )?;
    Ok((hardened, codec))
}

pub fn exercise(data: &[u8]) -> Outcome {
    let mode = data.first().copied().unwrap_or(0) % 6;
    let chunk_size = usize::from(data.get(1).copied().unwrap_or(0)) + 1;
    let mut expected: Vec<u8> = data
        .get(2..)
        .unwrap_or_default()
        .iter()
        .take(4095)
        .map(|byte| byte | 1)
        .collect();
    if expected.is_empty() {
        expected.push(1);
    }
    let producer = StableId::new("producer.managed-fuzz")?;
    let generation = Generation::new(1)?;
    let (mut sender, sender_codec) = fixture(SessionEndpoint::Initiator)?;
    let record = sender.seal_bound_typed(producer.clone(), generation, &sender_codec, &expected)?;
    let mut bytes = record.clone();
    match mode {
        1 => {
            let index = chunk_size % bytes.len();
            bytes[index] ^= 1;
        }
        2 => bytes.extend_from_slice(&record),
        3 => {
            // A correctly authenticated but noncanonical payload must fail at re-encoding.
            let mut noncanonical = expected.clone();
            noncanonical.push(0);
            bytes = owner(/*channel*/ 1, SessionEndpoint::Initiator)?
                .seal_envelope(&envelope(&noncanonical, "producer.managed-fuzz")?)?;
        }
        4 => {
            let mut second =
                sender.seal_bound_typed(producer.clone(), generation, &sender_codec, &expected)?;
            let end = second.len() - 1;
            second[end] ^= 1;
            bytes.extend(second);
        }
        5 => bytes.truncate(1 + chunk_size % (bytes.len() - 1)),
        0 => {}
        _ => unreachable!(),
    }
    let (receiver, codec) = fixture(SessionEndpoint::Responder)?;
    let limits = RecordStreamLimits {
        max_feed_bytes: 37,
        max_records_per_feed: 1,
        ..RecordStreamLimits::default()
    };
    let mut stream = receiver.into_record_stream(codec, limits)?;
    let mut accepted = Vec::new();
    'chunks: for chunk in bytes.chunks(chunk_size) {
        let mut offset = 0;
        while offset < chunk.len() {
            let feed = stream.feed(&chunk[offset..]);
            let consumed = feed.bytes_consumed();
            assert!(consumed <= 37 && consumed <= chunk.len() - offset);
            let (values, error) = feed.into_parts().0.into_parts();
            accepted.extend(values);
            if error.is_some() {
                if mode == 3 {
                    assert!(matches!(
                        error,
                        Some(HardenedRecordStreamError::Session(
                            HardenedManagedSessionError::Hardened(
                                HardenedWireSessionError::NonCanonicalPayload { .. }
                            )
                        ))
                    ));
                }
                assert!(stream.is_terminal());
                assert_eq!(stream.buffer_capacity_bytes(), 0);
                let retry = stream.feed(&record);
                assert_eq!(retry.bytes_consumed(), 0);
                assert!(retry.batch().values().is_empty());
                assert!(
                    stream
                        .seal_bound_typed(producer.clone(), generation, &expected)
                        .is_err()
                );
                break 'chunks;
            }
            assert!(consumed > 0);
            offset += consumed;
        }
    }
    if matches!(mode, 0 | 2 | 4) {
        assert_eq!(accepted, vec![expected.clone()]);
    } else {
        assert!(accepted.is_empty());
    }
    if mode == 0 {
        stream.finish()?;
        let (mut direct, codec) = fixture(SessionEndpoint::Responder)?;
        assert_eq!(direct.open_bound_typed(&record, &codec)?, expected);
        assert!(direct.open_bound_typed(&record, &codec).is_err());
        assert_eq!(direct.state(), SessionLifecycleState::Poisoned);
    } else {
        assert!(stream.finish().is_err());
    }
    Ok(())
}
