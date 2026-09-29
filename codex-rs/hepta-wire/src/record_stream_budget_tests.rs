use std::error::Error;
use std::sync::Arc;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::FrozenSchemaRegistryBuilder;
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
        StableId::new("schema.record-budget.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        4096,
    )?;
    let role = StableId::new("role.record-budget")?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![StableId::new("producer.record-budget")?],
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
    let session = WireSession::new(negotiated, role, registry, transcript)?;
    Ok(ManagedAuthenticatedWireSession::new(
        session,
        SessionMacKey::new([9; 32])?,
        endpoint,
    )?)
}

fn records(channel: u8, count: u32) -> TestResult<(Vec<DecodedEnvelope>, Vec<u8>)> {
    let mut sender = owner(channel, SessionEndpoint::Initiator)?;
    let mut expected = Vec::new();
    let mut bytes = Vec::new();
    for generation in 1..=count {
        let frame = DecodedEnvelope::V2(WireEnvelopeV2::new(
            StableId::new("schema.record-budget.v1")?,
            StableId::new("producer.record-budget")?,
            Generation::new(generation)?,
            format!("private-payload-{generation}").into_bytes(),
        )?);
        bytes.extend(sender.seal_envelope(&frame)?);
        expected.push(frame);
    }
    Ok((expected, bytes))
}

fn stream(channel: u8) -> TestResult<ManagedRecordStream> {
    Ok(owner(channel, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?)
}

#[test]
fn complete_records_do_not_allocate_framing_staging() -> TestResult {
    let (expected, bytes) = records(1, 3)?;
    let mut receiver = stream(1)?;
    let feed = receiver.feed(&bytes);
    assert_eq!(feed.bytes_consumed(), bytes.len());
    assert_eq!(feed.batch().frames(), expected);
    assert!(feed.batch().terminal_error().is_none());
    assert!(!feed.batch().yielded());
    assert_eq!(receiver.buffered_bytes(), 0);
    assert_eq!(receiver.buffer_capacity_bytes(), 0);
    receiver.finish()?;
    Ok(())
}

#[test]
fn fragmented_and_contiguous_delivery_agree_at_every_partition() -> TestResult {
    let (expected, bytes) = records(1, 3)?;
    for split in 0..=bytes.len() {
        let mut receiver = stream(1)?;
        let mut allowance = RecordStreamBudget::new(bytes.len(), 3);
        let mut actual = Vec::new();
        for chunk in [&bytes[..split], &bytes[split..]] {
            let feed = receiver.feed_with_budget(chunk, &mut allowance);
            assert_eq!(feed.bytes_consumed(), chunk.len(), "split={split}");
            let (batch, _) = feed.into_parts();
            let (frames, error) = batch.into_parts();
            assert!(error.is_none(), "split={split}");
            actual.extend(frames);
        }
        assert_eq!(actual, expected, "split={split}");
        assert_eq!(allowance.remaining_bytes(), 0);
        assert_eq!(allowance.remaining_records(), 0);
        receiver.finish()?;
    }
    Ok(())
}

#[test]
fn one_allowance_bounds_work_across_independent_peers() -> TestResult {
    let (first_expected, first_bytes) = records(1, 2)?;
    let (second_expected, second_bytes) = records(2, 2)?;
    let mut first = stream(1)?;
    let mut second = stream(2)?;
    let total_bytes = first_bytes.len() + second_bytes.len();
    let mut allowance = RecordStreamBudget::new(total_bytes, 3);
    let a = first.feed_with_budget(&first_bytes, &mut allowance);
    assert_eq!(a.batch().frames(), first_expected);
    let b = second.feed_with_budget(&second_bytes, &mut allowance);
    assert_eq!(b.batch().frames(), &second_expected[..1]);
    assert!(b.batch().yielded());
    assert_eq!(allowance.remaining_records(), 0);
    let offset = b.bytes_consumed();
    assert_eq!(allowance.remaining_bytes(), second_bytes.len() - offset);
    let retained = second.buffered_bytes();
    let blocked = second.feed_with_budget(&second_bytes[offset..], &mut allowance);
    assert_eq!(blocked.bytes_consumed(), 0);
    assert!(blocked.batch().yielded());
    assert!(blocked.batch().terminal_error().is_none());
    assert_eq!(second.buffered_bytes(), retained);
    let mut next = RecordStreamBudget::new(second_bytes.len() - offset, 1);
    let tail = second.feed_with_budget(&second_bytes[offset..], &mut next);
    assert_eq!(tail.batch().frames(), &second_expected[1..]);
    first.finish()?;
    second.finish()?;
    Ok(())
}

#[test]
fn zero_allowances_yield_without_consumption_or_retirement() -> TestResult {
    let (expected, bytes) = records(1, 1)?;
    for (byte_budget, record_budget) in [(0, 1), (bytes.len(), 0), (0, 0)] {
        let mut receiver = stream(1)?;
        let mut allowance = RecordStreamBudget::new(byte_budget, record_budget);
        let feed = receiver.feed_with_budget(&bytes, &mut allowance);
        assert_eq!(feed.bytes_consumed(), 0);
        assert!(feed.batch().frames().is_empty());
        assert!(feed.batch().yielded());
        assert!(feed.batch().terminal_error().is_none());
        assert!(!receiver.is_terminal());
        assert_eq!(receiver.buffer_capacity_bytes(), 0);
        assert_eq!(allowance.remaining_bytes(), byte_budget);
        assert_eq!(allowance.remaining_records(), record_budget);
        assert_eq!(receiver.feed(&bytes).batch().frames(), expected);
        receiver.finish()?;
    }
    Ok(())
}

#[test]
fn shared_byte_budget_preserves_a_fragment_for_the_next_turn() -> TestResult {
    let (expected, bytes) = records(1, 1)?;
    for byte_budget in [1, PREFIX_BYTES - 1, PREFIX_BYTES, bytes.len() - 1] {
        let mut receiver = stream(1)?;
        let mut allowance = RecordStreamBudget::new(byte_budget, 1);
        let feed = receiver.feed_with_budget(&bytes, &mut allowance);
        assert_eq!(feed.bytes_consumed(), byte_budget);
        assert!(feed.batch().yielded());
        assert!(feed.batch().frames().is_empty());
        assert_eq!(allowance.remaining_bytes(), 0);
        assert_eq!(allowance.remaining_records(), 1);
        assert_eq!(receiver.buffered_bytes(), byte_budget);
        let mut next = RecordStreamBudget::new(bytes.len() - byte_budget, 1);
        let tail = receiver.feed_with_budget(&bytes[byte_budget..], &mut next);
        assert_eq!(tail.batch().frames(), expected);
        assert_eq!(next.remaining_bytes(), 0);
        assert_eq!(next.remaining_records(), 0);
        receiver.finish()?;
    }
    Ok(())
}

#[test]
fn stream_local_limits_still_dominate_a_larger_shared_allowance() -> TestResult {
    let (expected, bytes) = records(1, 3)?;
    let limits = RecordStreamLimits {
        max_records_per_feed: 1,
        ..RecordStreamLimits::default()
    };
    let mut receiver = owner(1, SessionEndpoint::Responder)?.into_record_stream(limits)?;
    let mut allowance = RecordStreamBudget::new(bytes.len(), 3);
    let mut offset = 0;
    for frame in expected {
        let feed = receiver.feed_with_budget(&bytes[offset..], &mut allowance);
        assert_eq!(feed.batch().frames(), &[frame]);
        offset += feed.bytes_consumed();
    }
    assert_eq!(offset, bytes.len());
    assert_eq!(allowance.remaining_records(), 0);
    receiver.finish()?;
    Ok(())
}

#[test]
fn stream_local_byte_limit_is_not_bypassed_by_direct_authentication() -> TestResult {
    let (expected, bytes) = records(1, 1)?;
    let limits = RecordStreamLimits {
        max_feed_bytes: PREFIX_BYTES - 1,
        ..RecordStreamLimits::default()
    };
    let mut receiver = owner(1, SessionEndpoint::Responder)?.into_record_stream(limits)?;
    let mut allowance = RecordStreamBudget::new(bytes.len(), 1);
    let mut offset = 0;
    let mut actual = Vec::new();
    while offset < bytes.len() {
        let feed = receiver.feed_with_budget(&bytes[offset..], &mut allowance);
        assert!(feed.bytes_consumed() > 0);
        assert!(feed.bytes_consumed() <= limits.max_feed_bytes);
        offset += feed.bytes_consumed();
        let (batch, _) = feed.into_parts();
        let (frames, error) = batch.into_parts();
        assert!(error.is_none());
        actual.extend(frames);
    }
    assert_eq!(actual, expected);
    assert_eq!(allowance.remaining_bytes(), 0);
    assert_eq!(allowance.remaining_records(), 0);
    receiver.finish()?;
    Ok(())
}

#[test]
fn failed_authentication_is_charged_and_preserves_the_valid_prefix() -> TestResult {
    let (expected, mut bytes) = records(1, 2)?;
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    let mut receiver = stream(1)?;
    let mut allowance = RecordStreamBudget::new(bytes.len(), 2);
    let feed = receiver.feed_with_budget(&bytes, &mut allowance);
    assert_eq!(feed.batch().frames(), &expected[..1]);
    assert_eq!(feed.bytes_consumed(), bytes.len());
    assert!(feed.batch().terminal_error().is_some());
    assert_eq!(allowance.remaining_bytes(), 0);
    assert_eq!(allowance.remaining_records(), 0);
    assert_eq!(receiver.buffer_capacity_bytes(), 0);
    assert!(receiver.is_terminal());
    let mut next = RecordStreamBudget::new(bytes.len(), 2);
    let repeated = receiver.feed_with_budget(&bytes, &mut next);
    assert_eq!(repeated.bytes_consumed(), 0);
    assert!(repeated.batch().frames().is_empty());
    assert_eq!(next.remaining_records(), 2);
    Ok(())
}

#[test]
fn invalid_prefix_consumes_only_the_prefix_without_staging_the_body() -> TestResult {
    let (_, bytes) = records(1, 1)?;
    for offset in [0, 5, 6, 46] {
        let mut bad = bytes.clone();
        bad[offset] ^= 0xff;
        let mut receiver = stream(1)?;
        let mut allowance = RecordStreamBudget::new(bad.len(), 1);
        let feed = receiver.feed_with_budget(&bad, &mut allowance);
        assert_eq!(feed.bytes_consumed(), PREFIX_BYTES, "offset={offset}");
        assert!(feed.batch().terminal_error().is_some());
        assert!(feed.batch().frames().is_empty());
        assert_eq!(allowance.remaining_bytes(), bad.len() - PREFIX_BYTES);
        assert_eq!(allowance.remaining_records(), 1);
        assert_eq!(receiver.buffer_capacity_bytes(), 0);
    }
    Ok(())
}

#[test]
fn empty_feed_with_no_allowance_is_not_eof() -> TestResult {
    let (expected, bytes) = records(1, 1)?;
    let mut receiver = stream(1)?;
    let mut allowance = RecordStreamBudget::new(0, 0);
    let feed = receiver.feed_with_budget(&[], &mut allowance);
    assert_eq!(feed.bytes_consumed(), 0);
    assert!(!feed.batch().yielded());
    assert!(feed.batch().terminal_error().is_none());
    assert_eq!(receiver.feed(&bytes).batch().frames(), expected);
    receiver.finish()?;
    Ok(())
}

#[test]
fn retirement_does_not_require_or_refund_a_work_allowance() -> TestResult {
    let (_, bytes) = records(1, 1)?;
    let mut receiver = stream(1)?;
    let mut allowance = RecordStreamBudget::new(PREFIX_BYTES, 1);
    let feed = receiver.feed_with_budget(&bytes, &mut allowance);
    assert_eq!(feed.bytes_consumed(), PREFIX_BYTES);
    assert_eq!(allowance.remaining_bytes(), 0);
    receiver.retire();
    assert_eq!(receiver.buffer_capacity_bytes(), 0);
    assert!(receiver.is_terminal());
    assert_eq!(allowance.remaining_bytes(), 0);
    assert!(receiver.finish().is_err());
    Ok(())
}

#[test]
fn eof_rejects_truncation_even_after_a_budget_yield() -> TestResult {
    let (_, bytes) = records(1, 1)?;
    for cut in [1, PREFIX_BYTES, bytes.len() - 1] {
        let mut receiver = stream(1)?;
        let mut allowance = RecordStreamBudget::new(cut, 1);
        let feed = receiver.feed_with_budget(&bytes, &mut allowance);
        assert!(feed.batch().yielded());
        assert!(matches!(
            receiver.finish(),
            Err(RecordStreamError::UnexpectedEof { .. })
        ));
    }
    Ok(())
}

#[test]
fn a_retired_peer_does_not_consume_another_peers_allowance() -> TestResult {
    let (_, first_bytes) = records(1, 1)?;
    let (expected, second_bytes) = records(2, 1)?;
    let mut first = stream(1)?;
    first.retire();
    let mut second = stream(2)?;
    let mut allowance = RecordStreamBudget::new(second_bytes.len(), 1);
    let rejected = first.feed_with_budget(&first_bytes, &mut allowance);
    assert_eq!(rejected.bytes_consumed(), 0);
    let accepted = second.feed_with_budget(&second_bytes, &mut allowance);
    assert_eq!(accepted.batch().frames(), expected);
    assert_eq!(allowance.remaining_records(), 0);
    second.finish()?;
    Ok(())
}

#[test]
fn a_new_allowance_does_not_reset_replay_protection() -> TestResult {
    let (expected, bytes) = records(1, 1)?;
    let mut receiver = stream(1)?;
    let mut first = RecordStreamBudget::new(bytes.len(), 1);
    assert_eq!(
        receiver.feed_with_budget(&bytes, &mut first).batch().frames(),
        expected
    );
    let mut next = RecordStreamBudget::new(bytes.len(), 1);
    let replay = receiver.feed_with_budget(&bytes, &mut next);
    assert!(replay.batch().frames().is_empty());
    assert!(replay.batch().terminal_error().is_some());
    assert!(receiver.is_terminal());
    assert_eq!(next.remaining_records(), 0);
    Ok(())
}
