//! Transport chunking and terminal-prefix regressions; no external effects.

use std::error::Error;
use std::sync::Arc;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::FrozenSchemaRegistryBuilder;
use codex_hepta_wire::MAX_BUFFERED_WIRE_FRAMES;
use codex_hepta_wire::MAX_WIRE_FRAME_BYTES;
use codex_hepta_wire::MAX_WIRE_FRAMES_PER_FEED;
use codex_hepta_wire::MAX_WIRE_PAYLOAD_BYTES;
use codex_hepta_wire::NegotiatedStreamingDecoder;
use codex_hepta_wire::NegotiationOffer;
use codex_hepta_wire::NegotiationTranscript;
use codex_hepta_wire::SchemaDescriptor;
use codex_hepta_wire::SchemaPolicy;
use codex_hepta_wire::StreamingDecoder;
use codex_hepta_wire::WireCapabilities;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireSession;
use codex_hepta_wire::WireSessionDecoder;
use codex_hepta_wire::WireVersion;
use codex_hepta_wire::negotiate;

fn frame(generation: u64, size: usize) -> Result<DecodedEnvelope, Box<dyn Error>> {
    Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
        StableId::new("schema.review")?,
        StableId::new("producer.review")?,
        Generation::new(generation)?,
        vec![0x5a; size],
    )?))
}

fn session() -> Result<WireSession, Box<dyn Error>> {
    let required =
        WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let descriptor = SchemaDescriptor::new(
        StableId::new("schema.review")?,
        WireVersion::V2,
        WireVersion::V2,
        MAX_WIRE_PAYLOAD_BYTES,
    )?;
    let policy = SchemaPolicy::new(
        descriptor,
        vec![StableId::new("producer.review")?],
        vec![StableId::new("role.review")?],
        required,
    )?;
    let mut builder = FrozenSchemaRegistryBuilder::new();
    builder.register(policy)?;
    let registry = Arc::new(builder.freeze()?);
    let offer = NegotiationOffer::current();
    let posture = negotiate(&offer, &offer, required)?;
    let transcript = NegotiationTranscript::from_offers(
        &offer,
        &offer,
        posture,
        registry.snapshot_digest(),
        &[0x37; 32],
    )?;
    Ok(WireSession::new(
        posture,
        StableId::new("role.review")?,
        registry,
        transcript,
    )?)
}

fn drain(decoder: &mut StreamingDecoder, input: &[u8]) -> Vec<DecodedEnvelope> {
    let mut offset = 0;
    let mut frames = Vec::new();
    while offset < input.len() {
        let (batch, consumed) = decoder.feed(&input[offset..]).into_parts();
        assert!(consumed > 0 && consumed <= input.len() - offset);
        assert!(batch.terminal_error().is_none());
        frames.extend(batch.into_parts().0);
        offset += consumed;
        assert!(!decoder.is_poisoned());
        assert!(decoder.buffered_len() <= MAX_WIRE_FRAME_BYTES);
    }
    frames
}

#[test]
fn coalesced_large_frames_yield_without_rejecting_valid_streams() -> Result<(), Box<dyn Error>> {
    let frames: Vec<_> = (1..=5)
        .map(|generation| frame(generation, MAX_WIRE_PAYLOAD_BYTES / 2))
        .collect::<Result<_, _>>()?;
    let input: Vec<_> = frames.iter().flat_map(DecodedEnvelope::encode).collect();
    assert!(input.len() > MAX_WIRE_FRAME_BYTES * MAX_BUFFERED_WIRE_FRAMES);
    let mut coalesced = StreamingDecoder::new();
    assert_eq!(drain(&mut coalesced, &input), frames);
    assert_eq!(coalesced.buffered_len(), 0);
    for size in [53, 54, 55, 4096, MAX_WIRE_FRAME_BYTES] {
        let mut decoder = StreamingDecoder::new();
        let mut received = Vec::new();
        for chunk in input.chunks(size) {
            received.extend(drain(&mut decoder, chunk));
        }
        assert_eq!(received, frames);
        assert_eq!(decoder.buffered_len(), 0);
    }
    Ok(())
}

#[test]
fn work_budget_is_a_resumable_yield() -> Result<(), Box<dyn Error>> {
    let value = frame(1, 1)?;
    let input = value.encode().repeat(MAX_WIRE_FRAMES_PER_FEED + 3);
    let mut decoder = StreamingDecoder::with_limits(1, 2)?;
    let values = drain(&mut decoder, &input);
    assert_eq!(values.len(), MAX_WIRE_FRAMES_PER_FEED + 3);
    assert!(values.iter().all(|observed| *observed == value));
    Ok(())
}

#[test]
fn every_single_split_of_good_bad_good_preserves_prefix_and_poison() -> Result<(), Box<dyn Error>> {
    let good = frame(1, 1)?;
    let mut bad = frame(2, 1)?.encode();
    *bad.last_mut().ok_or("empty frame")? ^= 1;
    let input = [good.encode(), bad, good.encode()].concat();
    for split in 0..=input.len() {
        let mut decoder = StreamingDecoder::new();
        let mut received = Vec::new();
        let mut failed = false;
        for chunk in [&input[..split], &input[split..]] {
            if failed {
                break;
            }
            let (batch, consumed) = decoder.feed(chunk).into_parts();
            assert!(consumed <= chunk.len());
            failed = batch.terminal_error().is_some();
            received.extend(batch.into_parts().0);
        }
        assert!(failed && decoder.is_poisoned());
        assert_eq!(received, vec![good.clone()]);
        let again = decoder.feed(&good.encode());
        assert_eq!(again.bytes_consumed(), 0);
        assert!(again.batch().frames().is_empty());
        assert!(again.batch().terminal_error().is_some());
    }
    Ok(())
}

#[test]
fn session_decoders_preserve_consumption_across_yields() -> Result<(), Box<dyn Error>> {
    let session = session()?;
    let input = frame(1, 1)?.encode().repeat(MAX_WIRE_FRAMES_PER_FEED + 1);
    let mut selected = NegotiatedStreamingDecoder::new(session.negotiated());
    let mut policy = WireSessionDecoder::new(session);
    let first = selected.feed(&input);
    let second = policy.feed(&input);
    assert_eq!(first.bytes_consumed(), second.bytes_consumed());
    assert_eq!(first.batch().frames().len(), MAX_WIRE_FRAMES_PER_FEED);
    assert!(first.batch().terminal_error().is_none());
    assert!(second.batch().terminal_error().is_none());
    assert_eq!(
        selected
            .feed(&input[first.bytes_consumed()..])
            .batch()
            .frames()
            .len(),
        1
    );
    assert_eq!(
        policy
            .feed(&input[second.bytes_consumed()..])
            .batch()
            .frames()
            .len(),
        1
    );
    Ok(())
}

#[test]
fn eof_rejects_every_truncated_frame_without_retracting_delivered_prefix()
-> Result<(), Box<dyn Error>> {
    let first = frame(1, 5)?;
    let second = frame(2, 5)?.encode();
    for cut in 1..second.len() {
        let mut decoder = StreamingDecoder::new();
        let bytes = [first.encode(), second[..cut].to_vec()].concat();
        let (batch, consumed) = decoder.feed(&bytes).into_parts();
        assert_eq!(consumed, bytes.len());
        assert_eq!(batch.frames(), std::slice::from_ref(&first));
        assert!(batch.terminal_error().is_none());
        let final_batch = decoder.finish();
        assert!(final_batch.frames().is_empty());
        assert!(final_batch.terminal_error().is_some());
    }
    let mut decoder = WireSessionDecoder::new(session()?);
    let encoded = first.encode();
    assert_eq!(decoder.feed(&encoded).batch().frames().len(), 1);
    assert!(decoder.finish().terminal_error().is_none());
    Ok(())
}
