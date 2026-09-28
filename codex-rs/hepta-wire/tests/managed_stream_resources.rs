//! Public-API regressions for connection-local HPTM resource admission.
//! The binding and keys are fixtures, not evidence of an authenticated network.

use std::error::Error;
use std::sync::Arc;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::FrozenSchemaRegistryBuilder;
use codex_hepta_wire::MAX_WIRE_FRAME_BYTES;
use codex_hepta_wire::ManagedAuthenticatedWireSession;
use codex_hepta_wire::ManagedRecordStream;
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

const PREFIX_BYTES: usize = 50;
type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn owner(channel: u8, endpoint: SessionEndpoint) -> TestResult<ManagedAuthenticatedWireSession> {
    let descriptor = SchemaDescriptor::new(
        StableId::new("schema.stream-resource.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        4096,
    )?;
    let role = StableId::new("role.stream-resource")?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![StableId::new("producer.stream-resource")?],
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

fn envelope() -> TestResult<DecodedEnvelope> {
    Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
        StableId::new("schema.stream-resource.v1")?,
        StableId::new("producer.stream-resource")?,
        Generation::new(1)?,
        vec![0x5a; 4096],
    )?))
}

fn announced_maximum() -> TestResult<Vec<u8>> {
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let mut bytes = sender.seal_envelope(&envelope()?)?;
    let length = u32::try_from(MAX_WIRE_FRAME_BYTES)?;
    bytes[46..50].copy_from_slice(&length.to_be_bytes());
    bytes.truncate(PREFIX_BYTES + 1);
    Ok(bytes)
}

#[test]
fn announced_maximum_does_not_preallocate_unreceived_body() -> TestResult {
    let bytes = announced_maximum()?;
    let mut stream = owner(1, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    let feed = stream.feed(&bytes);
    assert_eq!(feed.bytes_consumed(), PREFIX_BYTES + 1);
    assert!(feed.batch().frames().is_empty());
    assert!(feed.batch().terminal_error().is_none());
    assert_eq!(stream.buffered_bytes(), PREFIX_BYTES + 1);
    assert!(stream.buffer_capacity_bytes() <= 2 * (PREFIX_BYTES + 1));
    assert!(matches!(
        stream.finish(),
        Err(RecordStreamError::UnexpectedEof { .. })
    ));
    Ok(())
}

#[test]
fn wrong_session_rejects_at_prefix_and_retires_both_directions() -> TestResult {
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let bytes = sender.seal_envelope(&envelope()?)?;
    let mut stream = owner(2, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    let feed = stream.feed(&bytes);
    assert_eq!(feed.bytes_consumed(), PREFIX_BYTES);
    assert!(matches!(
        feed.batch().terminal_error(),
        Some(RecordStreamError::SessionIdentityMismatch)
    ));
    assert!(feed.batch().frames().is_empty());
    assert!(stream.is_terminal());
    assert_eq!(stream.buffer_capacity_bytes(), 0);
    assert_eq!(stream.feed(&bytes).bytes_consumed(), 0);
    assert!(matches!(
        stream.seal_envelope(&envelope()?),
        Err(RecordStreamError::Terminated)
    ));
    Ok(())
}

#[test]
fn early_header_rejection_delivers_accepted_prefix_exactly_once() -> TestResult {
    let frame = envelope()?;
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let mut bytes = sender.seal_envelope(&frame)?;
    let first_length = bytes.len();
    let mut wrong_session = sender.seal_envelope(&frame)?;
    wrong_session[6] ^= 1;
    bytes.extend(wrong_session);
    let mut stream = owner(1, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    let feed = stream.feed(&bytes);
    assert_eq!(feed.bytes_consumed(), first_length + PREFIX_BYTES);
    assert_eq!(feed.batch().frames(), &[frame]);
    assert!(matches!(
        feed.batch().terminal_error(),
        Some(RecordStreamError::SessionIdentityMismatch)
    ));
    assert_eq!(stream.buffer_capacity_bytes(), 0);
    assert!(stream.feed(&bytes).batch().frames().is_empty());
    Ok(())
}

#[test]
fn one_byte_fragments_grow_geometrically_and_preserve_authenticated_frame() -> TestResult {
    let frame = envelope()?;
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let bytes = sender.seal_envelope(&frame)?;
    let limits = RecordStreamLimits {
        max_feed_bytes: 1,
        max_records_per_feed: 1,
        ..RecordStreamLimits::default()
    };
    let mut stream = owner(1, SessionEndpoint::Responder)?.into_record_stream(limits)?;
    let mut actual = Vec::new();
    let mut previous_capacity = 0;
    let mut growths = 0;
    for byte in &bytes {
        let feed = stream.feed(std::slice::from_ref(byte));
        assert_eq!(feed.bytes_consumed(), 1);
        assert!(feed.batch().terminal_error().is_none());
        let capacity = stream.buffer_capacity_bytes();
        if capacity != previous_capacity {
            growths += 1;
            previous_capacity = capacity;
        }
        if stream.buffered_bytes() > 0 {
            assert!(capacity <= PREFIX_BYTES.max(2 * stream.buffered_bytes()));
        }
        let (batch, _) = feed.into_parts();
        actual.extend(batch.into_parts().0);
    }
    assert_eq!(actual, vec![frame]);
    assert!(growths <= 16, "unexpected buffer growth count: {growths}");
    stream.finish()?;
    Ok(())
}

#[test]
fn slow_partial_peers_cannot_reserve_declared_bodies_in_aggregate() -> TestResult {
    let bytes = announced_maximum()?;
    let mut streams = Vec::new();
    for _ in 0..32 {
        let mut stream = owner(1, SessionEndpoint::Responder)?
            .into_record_stream(RecordStreamLimits::default())?;
        let feed = stream.feed(&bytes);
        assert_eq!(feed.bytes_consumed(), bytes.len());
        assert!(feed.batch().terminal_error().is_none());
        streams.push(stream);
    }
    let retained: usize = streams
        .iter()
        .map(ManagedRecordStream::buffer_capacity_bytes)
        .sum();
    assert!(retained <= 32 * 2 * bytes.len());
    for stream in &mut streams {
        stream.retire();
        assert_eq!(stream.buffer_capacity_bytes(), 0);
        assert!(stream.is_terminal());
    }
    Ok(())
}

#[test]
fn empty_input_neither_allocates_nor_advances_partial_record() -> TestResult {
    let mut stream = owner(1, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    let empty = stream.feed(&[]);
    assert_eq!(empty.bytes_consumed(), 0);
    assert!(!empty.batch().yielded());
    assert_eq!(stream.buffer_capacity_bytes(), 0);
    let bytes = announced_maximum()?;
    let partial = stream.feed(&bytes);
    assert_eq!(partial.bytes_consumed(), bytes.len());
    let capacity = stream.buffer_capacity_bytes();
    let buffered = stream.buffered_bytes();
    for _ in 0..16 {
        let feed = stream.feed(&[]);
        assert_eq!(feed.bytes_consumed(), 0);
        assert!(!feed.batch().yielded());
        assert!(feed.batch().frames().is_empty());
        assert!(feed.batch().terminal_error().is_none());
        assert_eq!(stream.buffer_capacity_bytes(), capacity);
        assert_eq!(stream.buffered_bytes(), buffered);
    }
    stream.retire();
    assert_eq!(stream.buffer_capacity_bytes(), 0);
    Ok(())
}
