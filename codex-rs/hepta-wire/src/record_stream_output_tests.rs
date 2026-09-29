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
        StableId::new("schema.output-budget.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        MAX_WIRE_PAYLOAD_BYTES,
    )?;
    let role = StableId::new("role.output-budget")?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![StableId::new("producer.output-budget")?],
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
        StableId::new("schema.output-budget.v1")?,
        StableId::new("producer.output-budget")?,
        Generation::new(generation)?,
        vec![b'x'; size],
    )?))
}

fn stream(channel: u8) -> TestResult<ManagedRecordStream> {
    Ok(owner(channel, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?)
}

#[test]
fn normal_feed_caps_large_buffered_completion_plus_following_records() -> TestResult {
    let first = envelope(1, MAX_WIRE_PAYLOAD_BYTES)?;
    let first_size = first.encode().len();
    let second = envelope(2, MAX_WIRE_FRAME_BYTES - first_size + 1)?;
    assert!(first_size + second.encode().len() > MAX_WIRE_FRAME_BYTES);
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let first_record = sender.seal_envelope(&first)?;
    let second_record = sender.seal_envelope(&second)?;
    let mut receiver = stream(1)?;
    let cut = first_record.len() - 1;
    let mut offset = 0;
    while offset < cut {
        let feed = receiver.feed(&first_record[offset..cut]);
        assert!(feed.bytes_consumed() > 0);
        assert!(feed.batch().frames().is_empty());
        assert!(feed.batch().terminal_error().is_none());
        offset += feed.bytes_consumed();
    }
    let mut tail = first_record[cut..].to_vec();
    tail.extend_from_slice(&second_record);
    let feed = receiver.feed(&tail);
    assert_eq!(feed.bytes_consumed(), 1);
    assert_eq!(feed.batch().frames(), &[first]);
    assert!(feed.batch().yielded());
    assert_eq!(
        feed.batch().required_frame_bytes(),
        Some(second.encode().len())
    );
    assert_eq!(receiver.buffered_bytes(), 0);
    let resumed = receiver.feed(&tail[feed.bytes_consumed()..]);
    assert_eq!(resumed.batch().frames(), &[second]);
    assert!(resumed.batch().terminal_error().is_none());
    receiver.finish()?;
    Ok(())
}

#[test]
fn contiguous_capacity_yield_does_not_stage_or_advance_sequence() -> TestResult {
    let expected = envelope(1, 64)?;
    let size = expected.encode().len();
    let bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    for capacity in [0, size - 1] {
        let mut receiver = stream(1)?;
        let mut quota = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, capacity);
        let blocked = receiver.feed_with_budget(&bytes, &mut quota);
        assert_eq!(blocked.bytes_consumed(), 0);
        assert!(blocked.batch().yielded());
        assert!(blocked.batch().terminal_error().is_none());
        assert_eq!(blocked.batch().required_frame_bytes(), Some(size));
        assert_eq!(receiver.buffer_capacity_bytes(), 0);
        assert_eq!(quota.remaining_frame_bytes(), capacity);
        assert_eq!(quota.remaining_bytes(), bytes.len());
        assert_eq!(quota.remaining_records(), 1);
        let mut ready = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, size);
        assert_eq!(
            receiver.feed_with_budget(&bytes, &mut ready).batch().frames(),
            std::slice::from_ref(&expected)
        );
        assert_eq!(ready.remaining_frame_bytes(), 0);
        receiver.finish()?;
    }
    Ok(())
}

#[test]
fn fragmented_capacity_yield_stops_before_body_admission() -> TestResult {
    let expected = envelope(1, 128)?;
    let size = expected.encode().len();
    let bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    for split in [
        1,
        PREFIX_BYTES - 1,
        PREFIX_BYTES,
        PREFIX_BYTES + 1,
        bytes.len() - 1,
    ] {
        let mut receiver = stream(1)?;
        assert_eq!(receiver.feed(&bytes[..split]).bytes_consumed(), split);
        let mut blocked_quota = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, size - 1);
        let blocked = receiver.feed_with_budget(&bytes[split..], &mut blocked_quota);
        let header_tail = PREFIX_BYTES.saturating_sub(split);
        assert_eq!(blocked.bytes_consumed(), header_tail);
        assert_eq!(blocked.batch().required_frame_bytes(), Some(size));
        assert!(blocked.batch().terminal_error().is_none());
        assert_eq!(receiver.buffered_bytes(), split + header_tail);
        assert_eq!(blocked_quota.remaining_records(), 1);
        assert_eq!(blocked_quota.remaining_frame_bytes(), size - 1);
        let mut ready = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, size);
        let resumed = receiver.feed_with_budget(&bytes[split + header_tail..], &mut ready);
        assert_eq!(resumed.batch().frames(), std::slice::from_ref(&expected));
        assert_eq!(ready.remaining_frame_bytes(), 0);
        receiver.finish()?;
    }
    Ok(())
}

#[test]
fn full_frame_bytes_are_charged_once_at_every_two_part_partition() -> TestResult {
    let expected = envelope(1, 32)?;
    let size = expected.encode().len();
    let bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    for split in 0..=bytes.len() {
        let mut receiver = stream(1)?;
        let mut quota = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, size);
        let mut actual = Vec::new();
        for chunk in [&bytes[..split], &bytes[split..]] {
            let feed = receiver.feed_with_budget(chunk, &mut quota);
            assert_eq!(feed.bytes_consumed(), chunk.len());
            let (batch, _) = feed.into_parts();
            let (frames, error) = batch.into_parts();
            assert!(error.is_none());
            actual.extend(frames);
        }
        assert_eq!(actual.as_slice(), std::slice::from_ref(&expected));
        assert_eq!(quota.remaining_frame_bytes(), 0);
        receiver.finish()?;
    }
    Ok(())
}

#[test]
fn shared_frame_capacity_bounds_peers_even_while_the_first_batch_is_retained() -> TestResult {
    let expected = envelope(1, 64)?;
    let size = expected.encode().len();
    let first_bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    let second_bytes = owner(2, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    let mut first = stream(1)?;
    let mut second = stream(2)?;
    let mut quota =
        RecordStreamBudget::with_frame_bytes(first_bytes.len() + second_bytes.len(), 2, size);
    let retained = first.feed_with_budget(&first_bytes, &mut quota);
    assert_eq!(retained.batch().frames(), std::slice::from_ref(&expected));
    let blocked = second.feed_with_budget(&second_bytes, &mut quota);
    assert_eq!(blocked.bytes_consumed(), 0);
    assert_eq!(blocked.batch().required_frame_bytes(), Some(size));
    assert_eq!(quota.remaining_records(), 1);
    assert!(!second.is_terminal());
    drop(retained);
    // The consumer releases/accounts for its old batch before creating a new turn.
    let mut next = RecordStreamBudget::with_frame_bytes(second_bytes.len(), 1, size);
    assert_eq!(
        second
            .feed_with_budget(&second_bytes, &mut next)
            .batch()
            .frames(),
        &[expected]
    );
    first.finish()?;
    second.finish()?;
    Ok(())
}

#[test]
fn failed_mac_is_charged_full_frame_bytes_without_losing_the_prefix() -> TestResult {
    let first = envelope(1, 64)?;
    let second = envelope(2, 64)?;
    let size = first.encode().len() + second.encode().len();
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let mut bytes = sender.seal_envelope(&first)?;
    bytes.extend(sender.seal_envelope(&second)?);
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    let mut receiver = stream(1)?;
    let mut quota = RecordStreamBudget::with_frame_bytes(bytes.len(), 2, size);
    let feed = receiver.feed_with_budget(&bytes, &mut quota);
    assert_eq!(feed.batch().frames(), &[first]);
    assert!(feed.batch().terminal_error().is_some());
    assert_eq!(quota.remaining_frame_bytes(), 0);
    assert_eq!(quota.remaining_records(), 0);
    assert_eq!(quota.remaining_bytes(), 0);
    assert!(receiver.is_terminal());
    Ok(())
}

#[test]
fn invalid_prefix_is_not_a_capacity_yield_or_a_decode_attempt() -> TestResult {
    let expected = envelope(1, 64)?;
    let mut bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    bytes[0] ^= 1;
    let mut receiver = stream(1)?;
    let mut quota = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, 0);
    let feed = receiver.feed_with_budget(&bytes, &mut quota);
    assert_eq!(feed.bytes_consumed(), PREFIX_BYTES);
    assert!(matches!(
        feed.batch().terminal_error(),
        Some(RecordStreamError::InvalidPrefix)
    ));
    assert!(!feed.batch().yielded());
    assert_eq!(feed.batch().required_frame_bytes(), None);
    assert_eq!(quota.remaining_records(), 1);
    assert_eq!(quota.remaining_frame_bytes(), 0);
    Ok(())
}

#[test]
fn capacity_yield_and_a_new_budget_never_reset_replay_protection() -> TestResult {
    let expected = envelope(1, 64)?;
    let size = expected.encode().len();
    let bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    let mut receiver = stream(1)?;
    assert_eq!(receiver.feed(&bytes).batch().frames(), &[expected]);
    let mut blocked = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, 0);
    assert_eq!(
        receiver
            .feed_with_budget(&bytes, &mut blocked)
            .bytes_consumed(),
        0
    );
    let mut ready = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, size);
    let replay = receiver.feed_with_budget(&bytes, &mut ready);
    assert!(replay.batch().frames().is_empty());
    assert!(replay.batch().terminal_error().is_some());
    assert_eq!(ready.remaining_frame_bytes(), 0);
    assert!(receiver.is_terminal());
    Ok(())
}

#[test]
fn capacity_blocked_partial_record_is_still_an_error_at_eof() -> TestResult {
    let expected = envelope(1, 64)?;
    let bytes = owner(1, SessionEndpoint::Initiator)?.seal_envelope(&expected)?;
    let mut receiver = stream(1)?;
    let prefix = receiver.feed(&bytes[..1]);
    assert_eq!(prefix.bytes_consumed(), 1);
    let mut quota = RecordStreamBudget::with_frame_bytes(bytes.len(), 1, 0);
    let blocked = receiver.feed_with_budget(&bytes[1..], &mut quota);
    assert_eq!(blocked.bytes_consumed(), PREFIX_BYTES - 1);
    assert!(blocked.batch().yielded());
    assert!(matches!(
        receiver.finish(),
        Err(RecordStreamError::UnexpectedEof { .. })
    ));
    Ok(())
}

#[test]
fn empty_input_and_retirement_do_not_charge_frame_capacity() -> TestResult {
    let mut receiver = stream(1)?;
    let mut quota = RecordStreamBudget::with_frame_bytes(0, 0, 0);
    let empty = receiver.feed_with_budget(&[], &mut quota);
    assert!(!empty.batch().yielded());
    assert!(empty.batch().terminal_error().is_none());
    receiver.retire();
    let retired = receiver.feed_with_budget(&[0], &mut quota);
    assert_eq!(retired.bytes_consumed(), 0);
    assert!(matches!(
        retired.batch().terminal_error(),
        Some(RecordStreamError::Terminated)
    ));
    assert_eq!(quota.remaining_frame_bytes(), 0);
    assert_eq!(receiver.buffer_capacity_bytes(), 0);
    Ok(())
}
