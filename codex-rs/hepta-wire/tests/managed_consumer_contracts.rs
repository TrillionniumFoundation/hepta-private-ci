//! Public owner-path contracts for transport consumers of managed HPTM records.
//!
//! These tests use fixture channel bindings and keys. They verify consumption,
//! lifecycle, and resource semantics without creating a transport, durable
//! checkpoint owner, execution authority, or test-only product route.

use std::error::Error;
use std::sync::Arc;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::FrozenSchemaRegistryBuilder;
use codex_hepta_wire::ManagedAuthenticatedWireSession;
use codex_hepta_wire::ManagedRecordStream;
use codex_hepta_wire::NegotiationOffer;
use codex_hepta_wire::NegotiationTranscript;
use codex_hepta_wire::RecordStreamLimits;
use codex_hepta_wire::SchemaDescriptor;
use codex_hepta_wire::SchemaPolicy;
use codex_hepta_wire::SessionEndpoint;
use codex_hepta_wire::SessionLifecycleState;
use codex_hepta_wire::SessionMacKey;
use codex_hepta_wire::WireCapabilities;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireSession;
use codex_hepta_wire::WireVersion;
use codex_hepta_wire::negotiate;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn id(value: &str) -> TestResult<StableId> {
    Ok(StableId::new(value)?)
}

fn session(channel: u8) -> TestResult<WireSession> {
    let descriptor = SchemaDescriptor::new(
        id("schema.managed-consumer-contract.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        8192,
    )?;
    let role = id("role.managed-consumer-contract")?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![id("producer.managed-consumer-contract")?],
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
    Ok(WireSession::new(negotiated, role, registry, transcript)?)
}

fn owner(
    channel: u8,
    key: [u8; 32],
    endpoint: SessionEndpoint,
) -> TestResult<ManagedAuthenticatedWireSession> {
    Ok(ManagedAuthenticatedWireSession::new(
        session(channel)?,
        SessionMacKey::new(key)?,
        endpoint,
    )?)
}

fn envelope(value: u8, payload_bytes: usize) -> TestResult<DecodedEnvelope> {
    Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
        id("schema.managed-consumer-contract.v1")?,
        id("producer.managed-consumer-contract")?,
        Generation::new(u64::from(value) + 1)?,
        vec![value; payload_bytes],
    )?))
}

#[derive(Default)]
struct DriveStats {
    bytes_consumed: usize,
    yields: usize,
    terminal: bool,
}

fn drive(
    stream: &mut ManagedRecordStream,
    input: &[u8],
    chunk_bytes: usize,
    mut accept: impl FnMut(DecodedEnvelope) -> TestResult,
) -> TestResult<DriveStats> {
    if chunk_bytes == 0 {
        return Err("chunk size must be positive".into());
    }
    let mut stats = DriveStats::default();
    let mut offset = 0;
    while offset < input.len() && !stats.terminal {
        let end = (offset + chunk_bytes).min(input.len());
        while offset < end && !stats.terminal {
            let feed = stream.feed(&input[offset..end]);
            let consumed = feed.bytes_consumed();
            let yielded = feed.batch().yielded();
            let (batch, _) = feed.into_parts();
            let (frames, terminal_error) = batch.into_parts();
            for frame in frames {
                accept(frame)?;
            }
            if yielded {
                stats.yields += 1;
            }
            stats.terminal = terminal_error.is_some();
            if consumed == 0 && !stats.terminal {
                return Err("managed consumer made no progress without terminating".into());
            }
            offset += consumed;
            stats.bytes_consumed += consumed;
        }
    }
    Ok(stats)
}

#[test]
fn consumer_driver_preserves_sequence_across_partitions_and_yields() -> TestResult {
    let expected: Vec<_> = (0..6)
        .map(|value| envelope(value, 1 + usize::from(value) * 47))
        .collect::<TestResult<_>>()?;
    for budget in [1, 7, 49, 50, 51, 127] {
        for chunk_bytes in [1, 19, 73, 1024] {
            let mut sender = owner(1, [23; 32], SessionEndpoint::Initiator)?;
            let mut bytes = Vec::new();
            for frame in &expected {
                bytes.extend(sender.seal_envelope(frame)?);
            }
            let limits = RecordStreamLimits {
                max_feed_bytes: budget,
                max_records_per_feed: 1,
                ..RecordStreamLimits::default()
            };
            let mut stream = owner(1, [23; 32], SessionEndpoint::Responder)?
                .into_record_stream(limits)?;
            let mut actual = Vec::new();
            let stats = drive(&mut stream, &bytes, chunk_bytes, |frame| {
                actual.push(frame);
                Ok(())
            })?;
            assert_eq!(stats.bytes_consumed, bytes.len());
            assert!(!stats.terminal);
            assert_eq!(actual, expected, "budget={budget}, chunk={chunk_bytes}");
            if chunk_bytes > budget {
                assert!(stats.yields > 0, "budget={budget}, chunk={chunk_bytes}");
            }
            stream.finish()?;
            sender.retire();
        }
    }
    Ok(())
}

#[test]
fn consumer_checkpoint_stops_at_authenticated_prefix_before_terminal_suffix() -> TestResult {
    let first = envelope(1, 31)?;
    let second = envelope(2, 47)?;
    let mut sender = owner(2, [23; 32], SessionEndpoint::Initiator)?;
    let first_record = sender.seal_envelope(&first)?;
    let mut invalid_suffix = sender.seal_envelope(&second)?;
    *invalid_suffix.last_mut().ok_or("missing authenticated tag")? ^= 1;
    let mut bytes = first_record.clone();
    bytes.extend(invalid_suffix);

    let limits = RecordStreamLimits {
        max_feed_bytes: 17,
        max_records_per_feed: 1,
        ..RecordStreamLimits::default()
    };
    let mut stream = owner(2, [23; 32], SessionEndpoint::Responder)?
        .into_record_stream(limits)?;
    // This counter models consumer ordering only; it is not a durable checkpoint
    // and does not move persistence ownership into platform.wire.
    let mut committed_prefix = Vec::new();
    let stats = drive(&mut stream, &bytes, bytes.len(), |frame| {
        committed_prefix.push(frame);
        Ok(())
    })?;
    assert!(stats.terminal);
    assert_eq!(committed_prefix, vec![first]);
    assert!(stream.is_terminal());
    assert_eq!(stream.buffer_capacity_bytes(), 0);

    let replay = stream.feed(&first_record);
    assert_eq!(replay.bytes_consumed(), 0);
    assert!(replay.batch().frames().is_empty());
    assert_eq!(committed_prefix.len(), 1);
    Ok(())
}

#[test]
fn unauthenticated_first_record_never_calls_the_consumer() -> TestResult {
    let frame = envelope(3, 63)?;
    let mut sender = owner(3, [23; 32], SessionEndpoint::Initiator)?;
    let mut record = sender.seal_envelope(&frame)?;
    *record.last_mut().ok_or("missing authenticated tag")? ^= 1;
    let mut stream = owner(3, [23; 32], SessionEndpoint::Responder)?
        .into_record_stream(RecordStreamLimits::default())?;
    let mut accepted = 0_usize;
    let stats = drive(&mut stream, &record, 29, |_| {
        accepted += 1;
        Ok(())
    })?;
    assert!(stats.terminal);
    assert_eq!(accepted, 0);
    assert!(stream.is_terminal());
    assert_eq!(stream.buffer_capacity_bytes(), 0);
    Ok(())
}

#[test]
fn rotation_uses_fresh_identity_and_old_records_fail_closed() -> TestResult {
    let old_frame = envelope(4, 79)?;
    let mut old_sender = owner(4, [23; 32], SessionEndpoint::Initiator)?;
    let old_receiver = owner(4, [23; 32], SessionEndpoint::Responder)?;
    let old_record = old_sender.seal_envelope(&old_frame)?;

    let duplicate = owner(4, [23; 32], SessionEndpoint::Initiator)?;
    assert!(duplicate
        .rotate(session(4)?, SessionMacKey::new([31; 32])?)
        .is_err());

    let mut new_sender = old_sender.rotate(session(5)?, SessionMacKey::new([31; 32])?)?;
    let mut new_receiver = old_receiver.rotate(session(5)?, SessionMacKey::new([31; 32])?)?;
    let new_frame = envelope(5, 97)?;
    let new_record = new_sender.seal_envelope(&new_frame)?;
    assert_eq!(new_receiver.open_record(&new_record)?, new_frame);

    let mut replay_probe = owner(5, [31; 32], SessionEndpoint::Responder)?;
    assert!(replay_probe.open_record(&old_record).is_err());
    assert_eq!(replay_probe.state(), SessionLifecycleState::Poisoned);
    assert!(replay_probe.open_record(&new_record).is_err());
    Ok(())
}

struct Peer {
    bytes: Vec<u8>,
    offset: usize,
    stream: ManagedRecordStream,
    delivered: usize,
    completed_round: Option<usize>,
    peak_capacity: usize,
}

#[test]
fn round_robin_peers_make_progress_and_release_retained_capacity() -> TestResult {
    let limits = RecordStreamLimits {
        max_feed_bytes: 64,
        max_records_per_feed: 1,
        ..RecordStreamLimits::default()
    };
    let mut peers = Vec::new();
    for channel in 1..=8_u8 {
        let frame = envelope(channel, usize::from(channel) * 257)?;
        let mut sender = owner(channel, [23; 32], SessionEndpoint::Initiator)?;
        let bytes = sender.seal_envelope(&frame)?;
        peers.push(Peer {
            bytes,
            offset: 0,
            stream: owner(channel, [23; 32], SessionEndpoint::Responder)?
                .into_record_stream(limits)?,
            delivered: 0,
            completed_round: None,
            peak_capacity: 0,
        });
    }
    let total_wire_bytes: usize = peers.iter().map(|peer| peer.bytes.len()).sum();
    let mut aggregate_peak_capacity = 0_usize;
    let mut round = 0_usize;
    while peers.iter().any(|peer| peer.offset < peer.bytes.len()) {
        round += 1;
        if round > 10_000 {
            return Err("round-robin consumer failed to converge".into());
        }
        for peer in &mut peers {
            if peer.offset == peer.bytes.len() {
                continue;
            }
            let feed = peer.stream.feed(&peer.bytes[peer.offset..]);
            let consumed = feed.bytes_consumed();
            assert!(consumed > 0 && consumed <= limits.max_feed_bytes);
            assert!(feed.batch().terminal_error().is_none());
            peer.offset += consumed;
            peer.delivered += feed.batch().frames().len();
            if peer.delivered == 1 && peer.completed_round.is_none() {
                peer.completed_round = Some(round);
            }
            peer.peak_capacity = peer
                .peak_capacity
                .max(peer.stream.buffer_capacity_bytes());
        }
        let aggregate: usize = peers
            .iter()
            .map(|peer| peer.stream.buffer_capacity_bytes())
            .sum();
        aggregate_peak_capacity = aggregate_peak_capacity.max(aggregate);
    }

    assert!(aggregate_peak_capacity <= 2 * total_wire_bytes);
    assert!(peers.iter().all(|peer| peer.delivered == 1));
    assert!(peers[0].completed_round < peers[7].completed_round);
    for peer in &mut peers {
        assert!(peer.peak_capacity <= 2 * peer.bytes.len());
        peer.stream.retire();
        assert!(peer.stream.is_terminal());
        assert_eq!(peer.stream.buffer_capacity_bytes(), 0);
    }
    assert_eq!(
        peers
            .iter()
            .map(|peer| peer.stream.buffer_capacity_bytes())
            .sum::<usize>(),
        0
    );
    Ok(())
}
