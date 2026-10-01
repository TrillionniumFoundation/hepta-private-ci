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

fn session(channel: u8) -> TestResult<WireSession> {
    let descriptor = SchemaDescriptor::new(
        StableId::new("schema.record-stream.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        4096,
    )?;
    let role = StableId::new("role.record-stream")?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![StableId::new("producer.record-stream")?],
        vec![role.clone()],
        required,
    )?;
    let mut builder = FrozenSchemaRegistryBuilder::new();
    builder.register(policy)?;
    let registry = Arc::new(builder.freeze()?);
    let offer = NegotiationOffer::current();
    let negotiated = negotiate(&offer, &offer, required)?;
    let transcript = NegotiationTranscript::from_offers(
        &offer, &offer, negotiated, registry.snapshot_digest(), &[channel; 32],
    )?;
    Ok(WireSession::new(negotiated, role, registry, transcript)?)
}

fn owner(channel: u8, endpoint: SessionEndpoint) -> TestResult<ManagedAuthenticatedWireSession> {
    Ok(ManagedAuthenticatedWireSession::new(
        session(channel)?, SessionMacKey::new([9; 32])?, endpoint,
    )?)
}

fn envelope(generation: u64) -> TestResult<DecodedEnvelope> {
    Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
        StableId::new("schema.record-stream.v1")?,
        StableId::new("producer.record-stream")?,
        Generation::new(generation)?,
        format!("private-payload-{generation}").into_bytes(),
    )?))
}

fn records(count: u64) -> TestResult<(Vec<DecodedEnvelope>, Vec<u8>)> {
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let mut expected = Vec::new();
    let mut bytes = Vec::new();
    for generation in 1..=count {
        let frame = envelope(generation)?;
        bytes.extend(sender.seal_envelope(&frame)?);
        expected.push(frame);
    }
    Ok((expected, bytes))
}

fn consume(stream: &mut ManagedRecordStream, bytes: &[u8]) -> TestResult<Vec<DecodedEnvelope>> {
    let mut consumed = 0;
    let mut frames = Vec::new();
    while consumed < bytes.len() {
        let feed = stream.feed(&bytes[consumed..]);
        let progress = feed.bytes_consumed();
        assert!(progress > 0 && progress <= bytes.len() - consumed);
        assert!(stream.buffered_bytes() <= stream.limits.max_record_bytes);
        let (batch, _) = feed.into_parts();
        let (prefix, error) = batch.into_parts();
        frames.extend(prefix);
        if let Some(error) = error {
            return Err(error.into());
        }
        consumed += progress;
    }
    Ok(frames)
}

#[test]
fn every_transport_split_preserves_exact_frames() -> TestResult {
    let (expected, bytes) = records(3)?;
    for split in 0..=bytes.len() {
        let limits = RecordStreamLimits {
            max_feed_bytes: 37,
            max_records_per_feed: 1,
            ..RecordStreamLimits::default()
        };
        let mut stream = owner(1, SessionEndpoint::Responder)?.into_record_stream(limits)?;
        let mut actual = consume(&mut stream, &bytes[..split])?;
        actual.extend(consume(&mut stream, &bytes[split..])?);
        assert_eq!(actual, expected, "split={split}");
        stream.finish()?;
    }
    Ok(())
}

#[test]
fn byte_and_record_yields_preserve_unconsumed_suffix() -> TestResult {
    let (expected, bytes) = records(65)?;
    for byte_budget in [1, 17, 64 * 1024] {
        for frame_budget in [1, 3, 16] {
            let limits = RecordStreamLimits {
                max_feed_bytes: byte_budget,
                max_records_per_feed: frame_budget,
                ..RecordStreamLimits::default()
            };
            let mut stream = owner(1, SessionEndpoint::Responder)?.into_record_stream(limits)?;
            let mut actual = Vec::new();
            let mut offset = 0;
            while offset < bytes.len() {
                let feed = stream.feed(&bytes[offset..]);
                assert!(feed.bytes_consumed() > 0);
                assert!(feed.bytes_consumed() <= byte_budget);
                assert!(feed.batch().frames().len() <= frame_budget);
                assert_eq!(feed.batch().yielded(), offset + feed.bytes_consumed() < bytes.len());
                offset += feed.bytes_consumed();
                let (batch, _) = feed.into_parts();
                let (frames, error) = batch.into_parts();
                assert!(error.is_none());
                actual.extend(frames);
            }
            assert_eq!(actual, expected);
            stream.finish()?;
        }
    }
    Ok(())
}

#[test]
fn every_truncated_second_record_preserves_first_at_eof() -> TestResult {
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let first = envelope(1)?;
    let first_bytes = sender.seal_envelope(&first)?;
    let second_bytes = sender.seal_envelope(&envelope(2)?)?;
    for cut in 1..second_bytes.len() {
        let mut bytes = first_bytes.clone();
        bytes.extend_from_slice(&second_bytes[..cut]);
        let mut stream = owner(1, SessionEndpoint::Responder)?
            .into_record_stream(RecordStreamLimits::default())?;
        assert_eq!(consume(&mut stream, &bytes)?, vec![first.clone()]);
        assert!(matches!(stream.finish(), Err(RecordStreamError::UnexpectedEof { .. })));
    }
    Ok(())
}

#[test]
fn authenticated_prefix_survives_tampered_suffix_without_replay() -> TestResult {
    let mut sender = owner(1, SessionEndpoint::Initiator)?;
    let first = envelope(1)?;
    let mut bytes = sender.seal_envelope(&first)?;
    let mut bad = sender.seal_envelope(&envelope(2)?)?;
    let end = bad.len() - 1;
    bad[end] ^= 1;
    bytes.extend(bad);
    let mut stream = owner(1, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    let feed = stream.feed(&bytes);
    assert_eq!(feed.batch().frames(), &[first]);
    assert!(feed.batch().terminal_error().is_some());
    assert!(stream.is_terminal());
    assert_eq!(stream.buffered_bytes(), 0);
    assert_eq!(stream.owner.state(), SessionLifecycleState::Retired);
    assert!(stream.feed(&bytes).batch().frames().is_empty());
    assert!(stream.seal_envelope(&envelope(3)?).is_err());
    Ok(())
}

#[test]
fn mutation_of_every_record_byte_never_delivers_or_reactivates() -> TestResult {
    let (_, bytes) = records(1)?;
    for index in 0..bytes.len() {
        let mut bad = bytes.clone();
        bad[index] ^= 1;
        let mut stream = owner(1, SessionEndpoint::Responder)?
            .into_record_stream(RecordStreamLimits::default())?;
        let feed = stream.feed(&bad);
        assert!(feed.batch().frames().is_empty(), "mutation={index}");
        // A changed length may defer rejection until consuming EOF, never admit.
        if stream.is_terminal() {
            assert!(stream.feed(&bytes).batch().frames().is_empty());
        }
        assert!(stream.finish().is_err(), "mutation={index}");
    }
    Ok(())
}

#[test]
fn oversized_record_rejects_at_prefix_before_body_admission() -> TestResult {
    let (_, mut bytes) = records(1)?;
    bytes[46..50].copy_from_slice(&u32::MAX.to_be_bytes());
    let mut stream = owner(1, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    let feed = stream.feed(&bytes);
    assert_eq!(feed.bytes_consumed(), PREFIX_BYTES);
    assert!(matches!(feed.batch().terminal_error(), Some(RecordStreamError::RecordLimit)));
    assert_eq!(stream.buffered_bytes(), 0);
    Ok(())
}

#[test]
fn reflection_replay_and_cross_session_replay_are_terminal() -> TestResult {
    let (_, bytes) = records(1)?;
    for (channel, endpoint) in [(1, SessionEndpoint::Initiator), (2, SessionEndpoint::Responder)] {
        let mut stream = owner(channel, endpoint)?.into_record_stream(RecordStreamLimits::default())?;
        assert!(stream.feed(&bytes).batch().frames().is_empty());
        assert!(stream.is_terminal());
    }
    let mut stream = owner(1, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    assert_eq!(consume(&mut stream, &bytes)?.len(), 1);
    assert!(stream.feed(&bytes).batch().frames().is_empty());
    assert!(stream.is_terminal());
    Ok(())
}

#[test]
fn cancellation_retires_the_same_bidirectional_owner() -> TestResult {
    let (_, bytes) = records(1)?;
    let mut stream = owner(1, SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    assert!(stream.feed(&bytes[..7]).batch().frames().is_empty());
    stream.retire();
    assert_eq!(stream.buffered_bytes(), 0);
    assert!(stream.feed(&bytes).batch().terminal_error().is_some());
    assert!(stream.seal_envelope(&envelope(1)?).is_err());
    assert!(stream.finish().is_err());
    Ok(())
}

#[test]
fn invalid_budgets_cannot_construct_a_stream() -> TestResult {
    for limits in [
        RecordStreamLimits { max_feed_bytes: 0, ..RecordStreamLimits::default() },
        RecordStreamLimits { max_records_per_feed: 0, ..RecordStreamLimits::default() },
        RecordStreamLimits { max_record_bytes: usize::MAX, ..RecordStreamLimits::default() },
    ] {
        assert!(owner(1, SessionEndpoint::Responder)?.into_record_stream(limits).is_err());
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn unix_transport_uses_the_normal_managed_owner() -> TestResult {
    use std::io::Read;
    use std::io::Write;
    use std::os::unix::net::UnixStream;
    use std::time::Duration;

    let (expected, bytes) = records(17)?;
    let (mut writer, mut reader) = UnixStream::pair()?;
    reader.set_read_timeout(Some(Duration::from_secs(5)))?;
    writer.set_write_timeout(Some(Duration::from_secs(5)))?;
    let worker = std::thread::spawn(move || -> std::io::Result<()> {
        for chunk in bytes.chunks(13) {
            writer.write_all(chunk)?;
        }
        Ok(())
    });
    let limits = RecordStreamLimits { max_records_per_feed: 1, ..RecordStreamLimits::default() };
    let mut stream = owner(1, SessionEndpoint::Responder)?.into_record_stream(limits)?;
    let mut actual = Vec::new();
    let mut buffer = [0_u8; 31];
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        actual.extend(consume(&mut stream, &buffer[..count])?);
    }
    worker.join().map_err(|_| "transport fixture worker panicked")??;
    assert_eq!(actual, expected);
    stream.finish()?;
    Ok(())
}
