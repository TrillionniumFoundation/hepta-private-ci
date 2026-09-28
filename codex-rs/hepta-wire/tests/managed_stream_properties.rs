//! Deterministic generated properties through the public managed owner.
//! Keys, channel bindings, and the round-robin driver are fixtures, not host acceptance.

use std::error::Error;
use std::sync::Arc;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::FrozenSchemaRegistryBuilder;
use codex_hepta_wire::ManagedAuthenticatedWireSession;
use codex_hepta_wire::NegotiationOffer;
use codex_hepta_wire::NegotiationTranscript;
use codex_hepta_wire::RecordStreamError;
use codex_hepta_wire::RecordStreamLimits;
use codex_hepta_wire::SchemaDescriptor;
use codex_hepta_wire::SchemaPolicy;
use codex_hepta_wire::SessionEndpoint;
use codex_hepta_wire::SessionMacKey;
use codex_hepta_wire::WireCapabilities;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireSession;
use codex_hepta_wire::WireVersion;
use codex_hepta_wire::negotiate;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn owner(channel: u8, endpoint: SessionEndpoint) -> TestResult<ManagedAuthenticatedWireSession> {
    let descriptor = SchemaDescriptor::new(
        StableId::new("schema.stream-property.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        4096,
    )?;
    let role = StableId::new("role.stream-property")?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![StableId::new("producer.stream-property")?],
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
        SessionMacKey::new([23; 32])?,
        endpoint,
    )?)
}

fn envelope(value: u8, length: usize) -> TestResult<DecodedEnvelope> {
    Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
        StableId::new("schema.stream-property.v1")?,
        StableId::new("producer.stream-property")?,
        Generation::new(u64::from(value) + 1)?,
        vec![value; length],
    )?))
}

#[test]
fn generated_partitions_and_work_budgets_preserve_exact_frame_sequence() -> TestResult {
    let expected: Vec<_> = (0..8)
        .map(|index| envelope(index, 1 + usize::from(index) * 23))
        .collect::<TestResult<_>>()?;
    for byte_budget in [1, 2, 49, 50, 51, 127, 8192] {
        for case in 0..24_u64 {
            let mut sender = owner(1, SessionEndpoint::Initiator)?;
            let mut bytes = Vec::new();
            for frame in &expected {
                bytes.extend(sender.seal_envelope(frame)?);
            }
            let limits = RecordStreamLimits {
                max_feed_bytes: byte_budget,
                max_records_per_feed: 1,
                ..RecordStreamLimits::default()
            };
            let mut stream = owner(1, SessionEndpoint::Responder)?.into_record_stream(limits)?;
            let mut seed = case + 1;
            let mut offset = 0;
            let mut actual = Vec::new();
            while offset < bytes.len() {
                seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
                let chunk = usize::try_from(seed % 311)? + 1;
                let end = (offset + chunk).min(bytes.len());
                while offset < end {
                    let feed = stream.feed(&bytes[offset..end]);
                    let consumed = feed.bytes_consumed();
                    assert!(consumed > 0 && consumed <= byte_budget);
                    assert!(feed.batch().terminal_error().is_none());
                    assert!(feed.batch().frames().len() <= 1);
                    offset += consumed;
                    let (batch, _) = feed.into_parts();
                    actual.extend(batch.into_parts().0);
                }
                let empty = stream.feed(&[]);
                assert_eq!(empty.bytes_consumed(), 0);
                assert!(empty.batch().frames().is_empty());
                assert!(!empty.batch().yielded());
            }
            assert_eq!(actual, expected, "case={case}, budget={byte_budget}");
            stream.finish()?;
        }
    }
    Ok(())
}

#[test]
fn every_truncated_second_record_preserves_only_the_first_frame() -> TestResult {
    let first = envelope(1, 17)?;
    let second = envelope(2, 29)?;
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let first_record = sender.seal_envelope(&first)?;
    let second_record = sender.seal_envelope(&second)?;
    for cut in 1..second_record.len() {
        let mut bytes = first_record.clone();
        bytes.extend_from_slice(&second_record[..cut]);
        let mut stream = owner(1, SessionEndpoint::Responder)?
            .into_record_stream(RecordStreamLimits::default())?;
        let feed = stream.feed(&bytes);
        assert_eq!(feed.bytes_consumed(), bytes.len());
        assert_eq!(feed.batch().frames(), std::slice::from_ref(&first));
        assert!(feed.batch().terminal_error().is_none());
        assert!(matches!(
            stream.finish(),
            Err(RecordStreamError::UnexpectedEof { .. })
        ));
    }
    Ok(())
}

#[test]
fn tampered_suffix_never_retracts_or_duplicates_the_authenticated_prefix() -> TestResult {
    let first = envelope(1, 17)?;
    let second = envelope(2, 29)?;
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let mut bytes = sender.seal_envelope(&first)?;
    let mut invalid = sender.seal_envelope(&second)?;
    if let Some(tag) = invalid.last_mut() {
        *tag ^= 1;
    }
    bytes.extend(invalid);
    for chunk_size in [1, 7, 49, 50, 51, 101, 4096] {
        let mut stream = owner(1, SessionEndpoint::Responder)?
            .into_record_stream(RecordStreamLimits::default())?;
        let mut actual = Vec::new();
        let mut terminal = false;
        for chunk in bytes.chunks(chunk_size) {
            let feed = stream.feed(chunk);
            terminal |= feed.batch().terminal_error().is_some();
            let (batch, _) = feed.into_parts();
            actual.extend(batch.into_parts().0);
        }
        assert!(terminal);
        assert_eq!(actual, vec![first.clone()]);
        assert!(stream.is_terminal());
        assert_eq!(stream.buffer_capacity_bytes(), 0);
        let replay = stream.feed(&bytes);
        assert_eq!(replay.bytes_consumed(), 0);
        assert!(replay.batch().frames().is_empty());
        assert!(stream.seal_envelope(&first).is_err());
    }
    Ok(())
}

#[test]
fn cooperative_byte_budget_allows_a_small_peer_to_complete_before_a_large_peer() -> TestResult {
    let mut slow_sender = owner(1, SessionEndpoint::Initiator)?;
    let mut fast_sender = owner(2, SessionEndpoint::Initiator)?;
    let slow = slow_sender.seal_envelope(&envelope(1, 4096)?)?;
    let fast = fast_sender.seal_envelope(&envelope(2, 1)?)?;
    let limits = RecordStreamLimits {
        max_feed_bytes: 64,
        max_records_per_feed: 1,
        ..RecordStreamLimits::default()
    };
    let mut slow_stream = owner(1, SessionEndpoint::Responder)?.into_record_stream(limits)?;
    let mut fast_stream = owner(2, SessionEndpoint::Responder)?.into_record_stream(limits)?;
    let mut slow_offset = 0;
    let mut fast_offset = 0;
    let mut published = 0;
    while fast_offset < fast.len() {
        let slow_feed = slow_stream.feed(&slow[slow_offset..]);
        assert!(slow_feed.bytes_consumed() > 0 && slow_feed.bytes_consumed() <= 64);
        assert!(slow_feed.batch().terminal_error().is_none());
        assert!(slow_feed.batch().frames().is_empty());
        slow_offset += slow_feed.bytes_consumed();
        let fast_feed = fast_stream.feed(&fast[fast_offset..]);
        assert!(fast_feed.bytes_consumed() > 0 && fast_feed.bytes_consumed() <= 64);
        assert!(fast_feed.batch().terminal_error().is_none());
        published += fast_feed.batch().frames().len();
        fast_offset += fast_feed.bytes_consumed();
    }
    assert_eq!(published, 1);
    assert!(slow_offset < slow.len());
    fast_stream.finish()?;
    slow_stream.retire();
    assert!(slow_stream.is_terminal());
    assert_eq!(slow_stream.buffer_capacity_bytes(), 0);
    Ok(())
}

#[test]
fn reconnect_does_not_reuse_partial_input_or_admit_the_previous_session() -> TestResult {
    let frame = envelope(1, 17)?;
    let mut old_sender = owner(1, SessionEndpoint::Initiator)?;
    let old_record = old_sender.seal_envelope(&frame)?;
    let mut old_stream = owner(1, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    assert_eq!(old_stream.feed(&old_record[..51]).bytes_consumed(), 51);
    old_stream.retire();
    assert_eq!(old_stream.buffer_capacity_bytes(), 0);
    assert_eq!(old_stream.feed(&old_record[51..]).bytes_consumed(), 0);
    let mut new_stream = owner(2, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    let rejected = new_stream.feed(&old_record);
    assert_eq!(rejected.bytes_consumed(), 50);
    assert!(rejected.batch().frames().is_empty());
    assert!(matches!(
        rejected.batch().terminal_error(),
        Some(RecordStreamError::SessionIdentityMismatch)
    ));
    assert!(new_stream.is_terminal());
    Ok(())
}
