//! Measure the existing managed ingress path under idle-retention policies.
//!
//! Fixture sessions are deliberately not deployed authenticated ingress. Output
//! is drained before the next record; observed Vec capacity is not allocator RSS.

use std::error::Error;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::FrozenSchemaRegistryBuilder;
use codex_hepta_wire::MAX_AUTHENTICATED_RECORD_BYTES;
use codex_hepta_wire::ManagedAuthenticatedWireSession;
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
const SMALL_BYTES: usize = 128;
const LARGE_BYTES: usize = 128 * 1024;
const CHUNK_BYTES: usize = 32 * 1024;

fn owner(endpoint: SessionEndpoint) -> ProfileResult<ManagedAuthenticatedWireSession> {
    let descriptor = SchemaDescriptor::new(
        StableId::new("schema.retention-profile.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        LARGE_BYTES,
    )?;
    let role = StableId::new("role.retention-profile")?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![StableId::new("producer.retention-profile")?],
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
        &[0x42; 32],
    )?;
    Ok(ManagedAuthenticatedWireSession::new(
        WireSession::new(negotiated, role, registry, transcript)?,
        SessionMacKey::new([0x59; 32])?,
        endpoint,
    )?)
}

fn measure(
    iterations: usize,
    pattern: &str,
    retention: &str,
    feed_bytes: usize,
) -> ProfileResult<Value> {
    let limits = RecordStreamLimits {
        max_feed_bytes: feed_bytes,
        ..RecordStreamLimits::default()
    };
    let mut sender = owner(SessionEndpoint::Initiator)?;
    let mut receiver = owner(SessionEndpoint::Responder)?.into_record_stream(limits)?;
    match retention {
        "default" => {}
        "none" => {
            receiver.set_idle_buffer_limit_bytes(0);
        }
        "large" => {
            receiver.set_idle_buffer_limit_bytes(MAX_AUTHENTICATED_RECORD_BYTES);
        }
        _ => return Err("unknown retention policy".into()),
    }
    let idle_limit = receiver.idle_buffer_limit_bytes();
    let mut latency_ns = Vec::with_capacity(iterations);
    let mut idle_capacity_bytes = Vec::with_capacity(iterations);
    let mut delivered = 0_usize;
    let mut payload_total = 0_usize;
    let mut wire_total = 0_usize;
    let mut feed_calls = 0_usize;
    let mut yields = 0_usize;
    let mut capacity_peak = 0_usize;
    let mut buffered_peak = 0_usize;
    let mut returned_peak = 0_usize;
    let mut maximum_record = 0_usize;

    for index in 0..iterations {
        let payload_bytes = match pattern {
            "small" => SMALL_BYTES,
            "large" => LARGE_BYTES,
            "alternating" if index.is_multiple_of(2) => SMALL_BYTES,
            "alternating" => LARGE_BYTES,
            _ => return Err("unknown traffic pattern".into()),
        };
        let expected = DecodedEnvelope::V2(WireEnvelopeV2::new(
            StableId::new("schema.retention-profile.v1")?,
            StableId::new("producer.retention-profile")?,
            Generation::new(u64::try_from(index + 1)?)?,
            vec![0x5a; payload_bytes],
        )?);
        let record = sender.seal_envelope(&expected)?;
        maximum_record = maximum_record.max(record.len());
        wire_total += record.len();
        let start = Instant::now();
        let mut offset = 0;
        while offset < record.len() {
            // A one-byte first fragment ensures that even small records use
            // staging. Subsequent reads exercise both default and small feeds.
            let end = if offset == 0 {
                1
            } else {
                (offset + CHUNK_BYTES).min(record.len())
            };
            let feed = receiver.feed(&record[offset..end]);
            let consumed = feed.bytes_consumed();
            if consumed == 0 || consumed > end - offset || consumed > feed_bytes {
                return Err("retention profile made invalid progress".into());
            }
            offset += consumed;
            feed_calls += 1;
            if feed.batch().yielded() {
                yields += 1;
                std::thread::yield_now();
            }
            capacity_peak = capacity_peak.max(receiver.buffer_capacity_bytes());
            buffered_peak = buffered_peak.max(receiver.buffered_bytes());
            returned_peak = returned_peak.max(feed.batch().frames().len());
            let (batch, _) = feed.into_parts();
            let (frames, error) = batch.into_parts();
            // Consume the accepted prefix before handling a possible error.
            // Do not retain a previous batch when admitting another record.
            for frame in frames {
                if frame != expected {
                    return Err("retention profile changed the delivered envelope".into());
                }
                payload_total += frame.payload().len();
                delivered += 1;
            }
            if let Some(error) = error {
                return Err(error.into());
            }
        }
        if delivered != index + 1 || receiver.buffered_bytes() != 0 {
            return Err("retention profile lost, duplicated or buffered a completed record".into());
        }
        let idle_capacity = receiver.buffer_capacity_bytes();
        if idle_capacity > idle_limit {
            return Err("retention profile exceeded the configured idle ceiling".into());
        }
        idle_capacity_bytes.push(idle_capacity);
        latency_ns.push(u64::try_from(start.elapsed().as_nanos())?);
    }
    let released = receiver.release_idle_buffer();
    let after_pressure = receiver.buffer_capacity_bytes();
    receiver.finish()?;
    sender.retire();
    Ok(json!({
        "pattern": pattern, "retention": retention, "iterations": iterations,
        "max_feed_bytes": feed_bytes, "chunk_bytes": CHUNK_BYTES,
        "idle_limit_bytes": idle_limit,
        "record_ceiling_bytes": limits.max_record_bytes,
        "maximum_record_bytes": maximum_record,
        "delivered_frames": delivered, "delivered_payload_bytes": payload_total,
        "wire_bytes": wire_total, "feed_calls": feed_calls, "budget_yields": yields,
        "observed_capacity_peak_bytes": capacity_peak,
        "observed_buffered_peak_bytes": buffered_peak,
        "peak_returned_frames": returned_peak,
        "idle_capacity_bytes": idle_capacity_bytes,
        "pressure_released_capacity_bytes": released,
        "capacity_after_pressure_bytes": after_pressure,
        "decode_and_delivery_latency_ns": latency_ns,
    }))
}

fn main() -> ProfileResult<()> {
    let arguments: Vec<_> = std::env::args().skip(1).collect();
    if arguments.len() > 1 {
        return Err("usage: managed_retention_profile [iterations:16..1024]".into());
    }
    let iterations = match arguments.first() {
        Some(value) => value.parse::<usize>()?,
        None => 64,
    };
    if !(16..=1024).contains(&iterations) || !iterations.is_multiple_of(2) {
        return Err("iterations must be an even integer in 16..1024".into());
    }
    let mut scenarios = Vec::new();
    for feed_bytes in [4096, 64 * 1024] {
        for pattern in ["small", "large", "alternating"] {
            for retention in ["default", "none", "large"] {
                scenarios.push(measure(iterations, pattern, retention, feed_bytes)?);
            }
        }
    }
    println!(
        "{}",
        serde_json::to_string(&json!({
            "schema": "hepta.platform-wire.retention-profile.v1",
            "profile": if cfg!(debug_assertions) { "debug" } else { "release" },
            "scope": "in-process normal managed feed; fixture sessions; drained consumer",
            "authenticated_network_ingress": false, "allocator_calls_measured": false,
            "host_rss_measured": false, "transport_queue_wait_measured": false,
            "five_path_grpc_qualified": false, "independent_acceptance": false,
            "activation": false, "release": false, "scenarios": scenarios,
        }))?
    );
    Ok(())
}
