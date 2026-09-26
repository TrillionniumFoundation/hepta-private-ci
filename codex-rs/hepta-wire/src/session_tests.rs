use super::*;

use std::sync::Arc;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::FrozenSchemaRegistryBuilder;
use crate::NegotiationOffer;
use crate::NegotiationTranscript;
use crate::SchemaDescriptor;
use crate::SchemaPolicy;
use crate::WireCapabilities;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireSession;
use crate::negotiate;

fn stable(value: &str) -> Result<StableId, Box<dyn Error>> {
    Ok(StableId::new(value)?)
}

fn production_session() -> Result<WireSession, Box<dyn Error>> {
    let schema = stable("schema.session-stream.v1")?;
    let producer = stable("producer.session-stream")?;
    let role = stable("role.session-stream")?;
    let descriptor = SchemaDescriptor::new(
        schema,
        WireVersion::V2,
        WireVersion::V2,
        256,
    )?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST
        .union(WireCapabilities::SCHEMA_ADMISSION)
        .union(WireCapabilities::STREAM_DECODING);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![producer],
        vec![role.clone()],
        required,
    )?;
    let mut builder = FrozenSchemaRegistryBuilder::new();
    builder.register(policy)?;
    let registry = Arc::new(builder.freeze()?);
    let offer = NegotiationOffer::current();
    let negotiated = negotiate(&offer, &offer, required)?;
    let transcript = NegotiationTranscript::from_offers(
        &offer,
        &offer,
        negotiated,
        registry.snapshot_digest(),
        &[0x5a; 32],
    )?;
    Ok(WireSession::new(negotiated, role, registry, transcript))
}

#[test]
fn negotiated_v2_session_rejects_v1_frame_and_stays_poisoned() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &NegotiationOffer::current(),
        WireCapabilities::METADATA_BOUND_DIGEST,
    )?;
    let v1 = WireEnvelope::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();

    let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
    assert!(matches!(
        decoder.push(&v1),
        Err(NegotiatedDecodeError::VersionMismatch {
            negotiated: WireVersion::V2,
            observed: WireVersion::V1,
        })
    ));
    assert!(decoder.is_poisoned());
    assert!(matches!(
        decoder.push(&[]),
        Err(NegotiatedDecodeError::VersionMismatch { .. })
    ));
    Ok(())
}

#[test]
fn negotiated_session_preserves_valid_prefix_before_version_mismatch() -> Result<(), Box<dyn Error>>
{
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &NegotiationOffer::current(),
        WireCapabilities::METADATA_BOUND_DIGEST,
    )?;
    let v2 =
        WireEnvelopeV2::new(stable("s")?, stable("p")?, Generation::new(2)?, vec![2])?.encode();
    let v1 = WireEnvelope::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    let mut chunk = v2;
    chunk.extend_from_slice(&v1);

    let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
    let batch = decoder.push_batch(&chunk);
    assert_eq!(batch.frames().len(), 1);
    assert_eq!(batch.frames()[0].version(), WireVersion::V2);
    assert!(matches!(
        batch.terminal_error(),
        Some(NegotiatedDecodeError::VersionMismatch {
            negotiated: WireVersion::V2,
            observed: WireVersion::V1,
        })
    ));
    Ok(())
}

#[test]
fn v1_session_does_not_report_v2_metadata_binding_as_effective() -> Result<(), Box<dyn Error>> {
    let v1_only = NegotiationOffer::new(vec![1], WireCapabilities::CURRENT)?;
    let negotiated = negotiate(
        &v1_only,
        &NegotiationOffer::current(),
        WireCapabilities::NONE,
    )?;
    assert_eq!(negotiated.version(), WireVersion::V1);
    assert!(
        negotiated
            .common_advertised_capabilities()
            .contains(WireCapabilities::METADATA_BOUND_DIGEST)
    );
    assert!(
        !negotiated
            .capabilities()
            .contains(WireCapabilities::METADATA_BOUND_DIGEST)
    );
    Ok(())
}

#[test]
fn negotiated_version_is_rejected_at_header_before_body_arrives() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &NegotiationOffer::current(),
        WireCapabilities::METADATA_BOUND_DIGEST,
    )?;
    let v1 = WireEnvelope::new(
        stable("s")?,
        stable("p")?,
        Generation::new(1)?,
        vec![1; crate::MAX_WIRE_PAYLOAD_BYTES],
    )?
    .encode();
    let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
    let batch = decoder.push_batch(&v1[..crate::WIRE_HEADER_BYTES]);
    assert!(batch.frames().is_empty());
    assert_eq!(
        batch.terminal_error(),
        Some(&NegotiatedDecodeError::VersionMismatch {
            negotiated: WireVersion::V2,
            observed: WireVersion::V1,
        })
    );
    assert_eq!(decoder.buffered_len(), 0);
    assert!(decoder.is_poisoned());
    Ok(())
}

#[test]
fn negotiated_header_error_preserves_prefix_at_every_split() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &NegotiationOffer::current(),
        WireCapabilities::METADATA_BOUND_DIGEST,
    )?;
    let v2 = WireEnvelopeV2::new(stable("s")?, stable("p")?, Generation::new(2)?, vec![2])?;
    let v1 = WireEnvelope::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    let mut bytes = v2.encode();
    bytes.extend_from_slice(&v1[..crate::WIRE_HEADER_BYTES]);
    for split in 0..=bytes.len() {
        let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
        let (mut frames, first_error) = decoder.push_batch(&bytes[..split]).into_parts();
        let (tail, last_error) = decoder.push_batch(&bytes[split..]).into_parts();
        frames.extend(tail);
        assert_eq!(frames, vec![DecodedEnvelope::V2(v2.clone())]);
        assert_eq!(
            first_error.or(last_error),
            Some(NegotiatedDecodeError::VersionMismatch {
                negotiated: WireVersion::V2,
                observed: WireVersion::V1,
            }),
            "split {split}"
        );
        assert_eq!(decoder.buffered_len(), 0, "split {split}");
    }
    Ok(())
}

#[test]
fn negotiated_mismatch_discards_following_partial_frame() -> Result<(), Box<dyn Error>> {
    let negotiated = negotiate(
        &NegotiationOffer::current(),
        &NegotiationOffer::current(),
        WireCapabilities::METADATA_BOUND_DIGEST,
    )?;
    let v1 = WireEnvelope::new(stable("s")?, stable("p")?, Generation::new(1)?, vec![1])?.encode();
    let large = WireEnvelopeV2::new(
        stable("s")?,
        stable("p")?,
        Generation::new(2)?,
        vec![2; crate::MAX_WIRE_PAYLOAD_BYTES],
    )?
    .encode();
    let mut chunk = v1;
    chunk.extend_from_slice(&large[..large.len() - 1]);
    let mut decoder = NegotiatedStreamingDecoder::new(negotiated);
    let batch = decoder.push_batch(&chunk);
    assert!(matches!(
        batch.terminal_error(),
        Some(NegotiatedDecodeError::VersionMismatch { .. })
    ));
    assert_eq!(decoder.buffered_len(), 0);
    let later = decoder.push_batch(&large);
    assert!(later.frames().is_empty());
    assert_eq!(later.terminal_error(), batch.terminal_error());
    Ok(())
}

#[test]
fn wire_session_decoder_applies_registry_role_and_producer_policy()
-> Result<(), Box<dyn Error>> {
    let session = production_session()?;
    let session_id = session.session_id();
    let valid = WireEnvelopeV2::new(
        stable("schema.session-stream.v1")?,
        stable("producer.session-stream")?,
        Generation::new(1)?,
        b"valid".to_vec(),
    )?
    .encode();
    let denied = WireEnvelopeV2::new(
        stable("schema.session-stream.v1")?,
        stable("producer.not-admitted")?,
        Generation::new(2)?,
        b"denied".to_vec(),
    )?
    .encode();
    let mut chunk = valid;
    chunk.extend_from_slice(&denied);

    let mut decoder = WireSessionDecoder::new(session);
    let batch = decoder.push_batch(&chunk);
    assert_eq!(batch.frames().len(), 1);
    assert_eq!(batch.frames()[0].payload(), b"valid");
    assert!(matches!(
        batch.terminal_error(),
        Some(WireSessionDecodeError::Session(
            WireSessionError::Admission { context, .. }
        )) if context.session_id() == session_id
    ));
    assert!(decoder.is_poisoned());
    assert_eq!(decoder.buffered_len(), 0);
    Ok(())
}
