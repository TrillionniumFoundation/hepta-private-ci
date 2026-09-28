//! Release measurements for multiple public managed HPTM owners.
//!
//! Fixture bindings and keys isolate in-process record handling. The report is
//! not authenticated network, transport queue, allocator, target-host, or
//! deployment evidence.

use std::error::Error;
use std::sync::Arc;
use std::time::Instant;

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
use codex_hepta_wire::SessionMacKey;
use codex_hepta_wire::WireCapabilities;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireSession;
use codex_hepta_wire::WireVersion;
use codex_hepta_wire::negotiate;
use serde_json::Value;
use serde_json::json;

type ProfileResult<T> = Result<T, Box<dyn Error>>;
const MAX_FEED_BYTES: usize = 64;

fn id(value: &str) -> ProfileResult<StableId> {
    Ok(StableId::new(value)?)
}

fn binding(sample: usize, peer: usize) -> ProfileResult<[u8; 32]> {
    let mut result = [0_u8; 32];
    result[..8].copy_from_slice(&u64::try_from(sample + 1)?.to_be_bytes());
    result[8..16].copy_from_slice(&u64::try_from(peer + 1)?.to_be_bytes());
    result[31] = 1;
    Ok(result)
}

fn session(channel_binding: &[u8; 32]) -> ProfileResult<WireSession> {
    let descriptor = SchemaDescriptor::new(
        id("schema.managed-fleet-profile.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        8192,
    )?;
    let role = id("role.managed-fleet-profile")?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![id("producer.managed-fleet-profile")?],
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
        channel_binding,
    )?;
    Ok(WireSession::new(negotiated, role, registry, transcript)?)
}

fn owner(
    channel_binding: &[u8; 32],
    key: [u8; 32],
    endpoint: SessionEndpoint,
) -> ProfileResult<ManagedAuthenticatedWireSession> {
    Ok(ManagedAuthenticatedWireSession::new(
        session(channel_binding)?,
        SessionMacKey::new(key)?,
        endpoint,
    )?)
}

fn envelope(generation: u64, value: u8, payload_bytes: usize) -> ProfileResult<DecodedEnvelope> {
    Ok(DecodedEnvelope::V2(WireEnvelopeV2::new(
        id("schema.managed-fleet-profile.v1")?,
        id("producer.managed-fleet-profile")?,
        Generation::new(generation)?,
        vec![value; payload_bytes],
    )?))
}

fn percentiles(samples: &mut [u64]) -> Value {
    samples.sort_unstable();
    let percentile = |percent: usize| {
        let index = (samples.len() * percent).div_ceil(100).saturating_sub(1);
        samples.get(index).copied().unwrap_or_default()
    };
    json!({"p50_ns": percentile(50), "p95_ns": percentile(95), "p99_ns": percentile(99)})
}

struct Peer {
    bytes: Vec<u8>,
    offset: usize,
    stream: ManagedRecordStream,
    delivered: usize,
    completed_turn: Option<usize>,
}

fn measure(rounds: usize, peer_count: usize, base_payload_bytes: usize) -> ProfileResult<Value> {
    let limits = RecordStreamLimits {
        max_feed_bytes: MAX_FEED_BYTES,
        max_records_per_feed: 1,
        ..RecordStreamLimits::default()
    };
    let mut elapsed_ns = Vec::with_capacity(rounds);
    let mut delivered_frames = 0_usize;
    let mut feed_calls = 0_usize;
    let mut budget_yields = 0_usize;
    let mut aggregate_capacity_peak = 0_usize;
    let mut aggregate_buffered_peak = 0_usize;
    let mut retained_capacity_peak = 0_usize;
    let mut retained_buffered_peak = 0_usize;
    let mut capacity_after_retire = 0_usize;
    let mut wire_bytes_per_round_max = 0_usize;
    let mut first_completion_turn_max = 0_usize;
    let mut last_completion_turn_max = 0_usize;
    let mut fairness_gap_turns_max = 0_usize;

    for sample in 0..rounds {
        let started = Instant::now();
        let mut peers = Vec::with_capacity(peer_count);
        for peer_index in 0..peer_count {
            let channel_binding = binding(sample, peer_index)?;
            let key_byte = u8::try_from(peer_index + 1)?;
            let key = [key_byte; 32];
            let generation = u64::try_from(sample * peer_count + peer_index + 1)?;
            let payload_bytes = base_payload_bytes + peer_index * 17;
            let expected = envelope(generation, key_byte, payload_bytes)?;
            let mut sender = owner(&channel_binding, key, SessionEndpoint::Initiator)?;
            let bytes = sender.seal_envelope(&expected)?;
            sender.retire();
            peers.push(Peer {
                bytes,
                offset: 0,
                stream: owner(&channel_binding, key, SessionEndpoint::Responder)?
                    .into_record_stream(limits)?,
                delivered: 0,
                completed_turn: None,
            });
        }
        let wire_bytes: usize = peers.iter().map(|peer| peer.bytes.len()).sum();
        wire_bytes_per_round_max = wire_bytes_per_round_max.max(wire_bytes);
        let mut scheduler_turn = 0_usize;
        while peers.iter().any(|peer| peer.offset < peer.bytes.len()) {
            scheduler_turn += 1;
            if scheduler_turn > 4096 {
                return Err("managed fleet failed to make bounded progress".into());
            }
            for peer in &mut peers {
                if peer.offset == peer.bytes.len() {
                    continue;
                }
                let feed = peer.stream.feed(&peer.bytes[peer.offset..]);
                let consumed = feed.bytes_consumed();
                if consumed == 0 || consumed > limits.max_feed_bytes {
                    return Err("managed fleet made invalid progress".into());
                }
                if feed.batch().terminal_error().is_some() {
                    return Err("managed fleet observed a terminal record error".into());
                }
                feed_calls += 1;
                budget_yields += usize::from(feed.batch().yielded());
                peer.offset += consumed;
                peer.delivered += feed.batch().frames().len();
                if peer.delivered > 1 {
                    return Err("managed fleet duplicated a frame".into());
                }
                if peer.delivered == 1 && peer.completed_turn.is_none() {
                    peer.completed_turn = Some(scheduler_turn);
                }
            }
            let aggregate_capacity: usize = peers
                .iter()
                .map(|peer| peer.stream.buffer_capacity_bytes())
                .sum();
            let aggregate_buffered: usize = peers
                .iter()
                .map(|peer| peer.stream.buffered_bytes())
                .sum();
            aggregate_capacity_peak = aggregate_capacity_peak.max(aggregate_capacity);
            aggregate_buffered_peak = aggregate_buffered_peak.max(aggregate_buffered);
        }
        if peers.iter().any(|peer| peer.delivered != 1) {
            return Err("managed fleet lost a frame".into());
        }
        delivered_frames += peer_count;
        let first_completion = peers
            .iter()
            .filter_map(|peer| peer.completed_turn)
            .min()
            .ok_or("managed fleet recorded no completion")?;
        let last_completion = peers
            .iter()
            .filter_map(|peer| peer.completed_turn)
            .max()
            .ok_or("managed fleet recorded no completion")?;
        first_completion_turn_max = first_completion_turn_max.max(first_completion);
        last_completion_turn_max = last_completion_turn_max.max(last_completion);
        fairness_gap_turns_max = fairness_gap_turns_max.max(last_completion - first_completion);

        let retained_capacity: usize = peers
            .iter()
            .map(|peer| peer.stream.buffer_capacity_bytes())
            .sum();
        let retained_buffered: usize = peers
            .iter()
            .map(|peer| peer.stream.buffered_bytes())
            .sum();
        retained_capacity_peak = retained_capacity_peak.max(retained_capacity);
        retained_buffered_peak = retained_buffered_peak.max(retained_buffered);
        for peer in &mut peers {
            peer.stream.retire();
        }
        capacity_after_retire = capacity_after_retire.max(
            peers
                .iter()
                .map(|peer| peer.stream.buffer_capacity_bytes())
                .sum(),
        );
        elapsed_ns.push(u64::try_from(started.elapsed().as_nanos())?);
    }

    Ok(json!({
        "rounds": rounds,
        "peer_count": peer_count,
        "base_payload_bytes": base_payload_bytes,
        "payload_stride_bytes": 17,
        "max_feed_bytes": limits.max_feed_bytes,
        "max_records_per_feed": limits.max_records_per_feed,
        "delivered_frames": delivered_frames,
        "feed_calls": feed_calls,
        "budget_yields": budget_yields,
        "wire_bytes_per_round_max": wire_bytes_per_round_max,
        "aggregate_record_buffer_capacity_peak_bytes": aggregate_capacity_peak,
        "aggregate_record_buffered_peak_bytes": aggregate_buffered_peak,
        "aggregate_record_buffer_capacity_after_workload_peak_bytes": retained_capacity_peak,
        "aggregate_record_buffered_after_workload_peak_bytes": retained_buffered_peak,
        "aggregate_record_buffer_capacity_after_retire_bytes": capacity_after_retire,
        "scheduler_turns_to_first_completion_max": first_completion_turn_max,
        "scheduler_turns_to_last_completion_max": last_completion_turn_max,
        "scheduler_fairness_gap_turns_max": fairness_gap_turns_max,
        "round_elapsed": percentiles(&mut elapsed_ns),
    }))
}

fn main() -> ProfileResult<()> {
    let arguments: Vec<_> = std::env::args().skip(1).collect();
    if arguments.len() > 1 {
        return Err("usage: managed_fleet_profile [rounds:8..256]".into());
    }
    let rounds = match arguments.first() {
        Some(value) => value.parse::<usize>()?,
        None => 32,
    };
    if !(8..=256).contains(&rounds) {
        return Err("rounds must be in 8..256".into());
    }
    let mut scenarios = Vec::new();
    for peer_count in [4, 16, 32] {
        for base_payload_bytes in [64, 4096] {
            scenarios.push(measure(rounds, peer_count, base_payload_bytes)?);
        }
    }
    println!(
        "{}",
        serde_json::to_string(&json!({
            "schema": "hepta.platform-wire.managed-fleet-profile.v1",
            "scope": "in-process public managed HPTM owners; fresh fixture sessions and keys",
            "profile": if cfg!(debug_assertions) { "debug" } else { "release" },
            "independent_acceptance": false,
            "authenticated_network_ingress": false,
            "target_host_measured": false,
            "allocator_calls_measured": false,
            "transport_queue_wait_measured": false,
            "multi_process_pressure_measured": false,
            "scenarios": scenarios,
        }))?
    );
    Ok(())
}
