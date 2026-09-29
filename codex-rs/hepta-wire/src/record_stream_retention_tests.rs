use std::error::Error;
use std::sync::Arc;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::FrozenSchemaRegistryBuilder;
use crate::MAX_WIRE_PAYLOAD_BYTES;
use crate::NegotiationOffer;
use crate::NegotiationTranscript;
use crate::SchemaDescriptor;
use crate::SchemaPolicy;
use crate::SessionEndpoint;
use crate::SessionMacKey;
use crate::WireCapabilities;
use crate::WireEnvelopeV2;
use crate::WireSession;
use crate::WireVersion;
use crate::negotiate;

use super::*;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn owner(channel: u8, endpoint: SessionEndpoint) -> TestResult<ManagedAuthenticatedWireSession> {
    let descriptor = SchemaDescriptor::new(
        StableId::new("schema.retention.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        MAX_WIRE_PAYLOAD_BYTES,
    )?;
    let role = StableId::new("role.retention")?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![StableId::new("producer.retention")?],
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
        &[channel; 32],
    )?;
    Ok(ManagedAuthenticatedWireSession::new(
        WireSession::new(negotiated, role, registry, transcript)?,
        SessionMacKey::new([9; 32])?,
        endpoint,
    )?)
}

fn envelope(generation: u32, size: usize) -> TestResult<DecodedEnvelope> {
    Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
        StableId::new("schema.retention.v1")?,
        StableId::new("producer.retention")?,
        Generation::new(generation)?,
        vec![b'x'; size],
    )?))
}

fn stream(channel: u8) -> TestResult<ManagedRecordStream> {
    Ok(owner(channel, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?)
}

fn deliver_fragmented(
    receiver: &mut ManagedRecordStream,
    bytes: &[u8],
) -> Vec<DecodedEnvelope> {
    let mut offset = 0;
    let mut actual = Vec::new();
    // Force staging even for records small enough for direct authentication.
    while offset < bytes.len() {
        let end = (offset + 4093).min(bytes.len());
        let end = if offset == 0 { 1 } else { end };
        let feed = receiver.feed(&bytes[offset..end]);
        assert!(feed.bytes_consumed() > 0);
        assert!(feed.bytes_consumed() <= end - offset);
        offset += feed.bytes_consumed();
        let (batch, _) = feed.into_parts();
        let (frames, error) = batch.into_parts();
        assert!(error.is_none());
        actual.extend(frames);
    }
    actual
}

#[test]
fn large_records_release_idle_capacity_on_the_normal_feed_path() -> TestResult {
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let mut receiver = stream(1)?;
    assert_eq!(receiver.idle_buffer_limit_bytes(), 64 * 1024);
    for generation in 1..=3 {
        let expected = envelope(generation, 128 * 1024)?;
        let bytes = sender.seal_envelope(&expected)?;
        assert_eq!(deliver_fragmented(&mut receiver, &bytes), vec![expected]);
        assert_eq!(receiver.buffered_bytes(), 0);
        assert_eq!(receiver.buffer_capacity_bytes(), 0);
        assert!(!receiver.is_terminal());
    }
    receiver.finish()?;
    Ok(())
}

#[test]
fn small_fragmented_records_reuse_the_same_allocation() -> TestResult {
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let mut receiver = stream(1)?;
    let mut previous_capacity = 0;
    let mut previous_pointer = std::ptr::null();
    for generation in 1..=3 {
        let expected = envelope(generation, 128)?;
        let bytes = sender.seal_envelope(&expected)?;
        assert_eq!(deliver_fragmented(&mut receiver, &bytes), vec![expected]);
        let capacity = receiver.buffer_capacity_bytes();
        assert!(capacity >= bytes.len());
        assert!(capacity <= receiver.idle_buffer_limit_bytes());
        if generation > 1 {
            assert_eq!(capacity, previous_capacity);
            assert_eq!(receiver.pending.as_ptr(), previous_pointer);
        }
        previous_capacity = capacity;
        previous_pointer = receiver.pending.as_ptr();
    }
    receiver.finish()?;
    Ok(())
}

#[test]
fn lowering_limit_never_discards_a_partial_record_at_any_partition() -> TestResult {
    let expected = envelope(1, 32)?;
    let bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    for split in 1..bytes.len() {
        let mut receiver = stream(1)?;
        assert_eq!(receiver.feed(&bytes[..split]).bytes_consumed(), split);
        let capacity = receiver.buffer_capacity_bytes();
        assert_eq!(receiver.set_idle_buffer_limit_bytes(0), 0);
        assert_eq!(receiver.release_idle_buffer(), 0);
        assert_eq!(receiver.buffered_bytes(), split);
        assert_eq!(receiver.buffer_capacity_bytes(), capacity);
        let tail = receiver.feed(&bytes[split..]);
        assert_eq!(tail.bytes_consumed(), bytes.len() - split);
        assert_eq!(tail.batch().frames(), std::slice::from_ref(&expected));
        assert!(tail.batch().terminal_error().is_none());
        assert_eq!(receiver.buffer_capacity_bytes(), 0);
        receiver.finish()?;
    }
    Ok(())
}

#[test]
fn pressure_release_is_idempotent_and_does_not_reset_replay_state() -> TestResult {
    let expected = envelope(1, 128)?;
    let bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    let mut receiver = stream(1)?;
    assert_eq!(deliver_fragmented(&mut receiver, &bytes), vec![expected]);
    let capacity = receiver.buffer_capacity_bytes();
    assert!(capacity > 0);
    assert_eq!(receiver.release_idle_buffer(), capacity);
    assert_eq!(receiver.release_idle_buffer(), 0);
    assert!(!receiver.is_terminal());
    let replay = receiver.feed(&bytes);
    assert!(replay.batch().frames().is_empty());
    assert!(replay.batch().terminal_error().is_some());
    assert!(receiver.is_terminal());
    assert_eq!(receiver.buffer_capacity_bytes(), 0);
    Ok(())
}

#[test]
fn memory_pressure_does_not_change_egress_identity_or_sequence() -> TestResult {
    let incoming = envelope(1, 128)?;
    let mut initiator = owner(1, SessionEndpoint::Initiator)?;
    let mut receiver = stream(1)?;
    let bytes = initiator.seal_envelope(&incoming)?;
    assert_eq!(deliver_fragmented(&mut receiver, &bytes), vec![incoming]);
    assert!(receiver.release_idle_buffer() > 0);
    for generation in 1..=2 {
        let expected = envelope(generation, 128)?;
        receiver.set_idle_buffer_limit_bytes(0);
        let response = receiver.seal_envelope(&expected)?;
        assert_eq!(initiator.open_record(&response)?, expected);
    }
    receiver.finish()?;
    Ok(())
}

#[test]
fn idle_limit_is_independent_of_record_admission_and_clamped() -> TestResult {
    let mut receiver = stream(1)?;
    assert_eq!(receiver.set_idle_buffer_limit_bytes(usize::MAX), 0);
    assert_eq!(receiver.idle_buffer_limit_bytes(), MAX_AUTHENTICATED_RECORD_BYTES);
    let expected = envelope(1, 128 * 1024)?;
    let bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    assert_eq!(deliver_fragmented(&mut receiver, &bytes), vec![expected]);
    let capacity = receiver.buffer_capacity_bytes();
    assert!(capacity >= bytes.len());
    assert_eq!(receiver.set_idle_buffer_limit_bytes(capacity), 0);
    assert_eq!(receiver.buffer_capacity_bytes(), capacity);
    assert_eq!(receiver.set_idle_buffer_limit_bytes(capacity - 1), capacity);
    assert_eq!(receiver.buffer_capacity_bytes(), 0);
    assert!(!receiver.is_terminal());
    receiver.finish()?;
    Ok(())
}

#[test]
fn memory_pressure_and_work_yield_preserve_the_exact_suffix() -> TestResult {
    let expected = envelope(1, 128)?;
    let bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    let mut receiver = stream(1)?;
    let mut quota = RecordStreamBudget::with_frame_bytes(PREFIX_BYTES, 1, MAX_WIRE_FRAME_BYTES);
    let prefix = receiver.feed_with_budget(&bytes, &mut quota);
    assert_eq!(prefix.bytes_consumed(), PREFIX_BYTES);
    assert!(prefix.batch().yielded());
    receiver.set_idle_buffer_limit_bytes(0);
    let mut blocked = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, 0);
    let feed = receiver.feed_with_budget(&bytes[PREFIX_BYTES..], &mut blocked);
    assert_eq!(feed.bytes_consumed(), 0);
    assert!(feed.batch().yielded());
    assert_eq!(receiver.release_idle_buffer(), 0);
    assert_eq!(receiver.buffered_bytes(), PREFIX_BYTES);
    let mut ready = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, MAX_WIRE_FRAME_BYTES);
    let tail = receiver.feed_with_budget(&bytes[PREFIX_BYTES..], &mut ready);
    assert_eq!(tail.bytes_consumed(), bytes.len() - PREFIX_BYTES);
    assert_eq!(tail.batch().frames(), &[expected]);
    assert_eq!(receiver.buffer_capacity_bytes(), 0);
    receiver.finish()?;
    Ok(())
}

#[test]
fn valid_prefix_survives_retirement_and_reclamation_of_a_bad_suffix() -> TestResult {
    let expected = envelope(1, 128)?;
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let mut bytes = sender.seal_envelope(&expected)?;
    bytes.extend(sender.seal_envelope(&envelope(2, 128)?)?);
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    let mut receiver = stream(1)?;
    receiver.set_idle_buffer_limit_bytes(0);
    assert_eq!(receiver.feed(&bytes[..1]).bytes_consumed(), 1);
    let feed = receiver.feed(&bytes[1..]);
    assert_eq!(feed.bytes_consumed(), bytes.len() - 1);
    assert_eq!(feed.batch().frames(), &[expected]);
    assert!(feed.batch().terminal_error().is_some());
    assert_eq!(receiver.buffer_capacity_bytes(), 0);
    assert_eq!(receiver.release_idle_buffer(), 0);
    assert!(receiver.is_terminal());
    Ok(())
}

#[test]
fn pressure_release_cannot_turn_truncated_eof_into_success() -> TestResult {
    let expected = envelope(1, 32)?;
    let bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    for cut in 1..bytes.len() {
        let mut receiver = stream(1)?;
        assert_eq!(receiver.feed(&bytes[..cut]).bytes_consumed(), cut);
        assert_eq!(receiver.set_idle_buffer_limit_bytes(0), 0);
        assert_eq!(receiver.release_idle_buffer(), 0);
        assert!(matches!(
            receiver.finish(),
            Err(RecordStreamError::UnexpectedEof { buffered, .. }) if buffered == cut
        ));
    }
    Ok(())
}

#[test]
fn reclamation_is_per_peer_and_cannot_reopen_a_retired_owner() -> TestResult {
    let expected = envelope(1, 128)?;
    let bytes_a = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    let bytes_b = owner(2, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    let mut a = stream(1)?;
    let mut b = stream(2)?;
    assert_eq!(deliver_fragmented(&mut a, &bytes_a), vec![expected.clone()]);
    assert_eq!(b.feed(&bytes_b[..1]).bytes_consumed(), 1);
    assert!(a.release_idle_buffer() > 0);
    assert_eq!(b.buffered_bytes(), 1);
    a.retire();
    a.set_idle_buffer_limit_bytes(usize::MAX);
    assert_eq!(a.release_idle_buffer(), 0);
    assert!(a.is_terminal());
    assert!(a.seal_envelope(&expected).is_err());
    let tail = b.feed(&bytes_b[1..]);
    assert_eq!(tail.batch().frames(), &[expected]);
    assert!(tail.batch().terminal_error().is_none());
    b.finish()?;
    Ok(())
}
