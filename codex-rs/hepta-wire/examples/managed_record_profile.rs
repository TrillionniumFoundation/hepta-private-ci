//! Measurements of the real managed record owner with explicit fixture keys.
//! No TLS, host RSS, allocator-call count or deployment acceptance is inferred.

use std::error::Error;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::FrozenSchemaRegistryBuilder;
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

fn owner(endpoint: SessionEndpoint) -> ProfileResult<ManagedAuthenticatedWireSession> {
    let descriptor = SchemaDescriptor::new(
        StableId::new("schema.managed-profile.v1")?,
        WireVersion::V2,
        WireVersion::V2,
        4096,
    )?;
    let role = StableId::new("role.managed-profile")?;
    let required = WireCapabilities::METADATA_BOUND_DIGEST.union(WireCapabilities::SCHEMA_ADMISSION);
    let policy = SchemaPolicy::new(
        descriptor,
        vec![StableId::new("producer.managed-profile")?],
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
        &[7; 32],
    )?;
    Ok(ManagedAuthenticatedWireSession::new(
        WireSession::new(negotiated, role, registry, transcript)?,
        SessionMacKey::new([9; 32])?,
        endpoint,
    )?)
}

fn percentiles(samples: &mut [u64]) -> Value {
    samples.sort_unstable();
    let percentile = |percent: usize| {
        let index = (samples.len() * percent).div_ceil(100).saturating_sub(1);
        samples.get(index).copied().unwrap_or_default()
    };
    json!({"p50_ns": percentile(50), "p95_ns": percentile(95), "p99_ns": percentile(99)})
}

fn measure(iterations: usize, payload_bytes: usize, chunk_bytes: usize) -> ProfileResult<Value> {
    let expected = DecodedEnvelope::V2(WireEnvelopeV2::new(
        StableId::new("schema.managed-profile.v1")?,
        StableId::new("producer.managed-profile")?,
        Generation::new(1)?,
        vec![0x5a; payload_bytes],
    )?);
    let mut sender = owner(SessionEndpoint::Initiator)?;
    let limits = RecordStreamLimits {
        max_feed_bytes: 37,
        max_records_per_feed: 1,
        ..RecordStreamLimits::default()
    };
    let mut stream = owner(SessionEndpoint::Responder)?.into_record_stream(limits)?;
    let mut seal_ns = Vec::with_capacity(iterations);
    let mut decode_ns = Vec::with_capacity(iterations);
    let mut feed_calls = 0_usize;
    let mut yields = 0_usize;
    let mut growths = 0_usize;
    let mut peak_capacity = 0_usize;
    let mut peak_buffered = 0_usize;
    let mut wire_bytes = 0_usize;
    let mut delivered = 0_usize;
    for _ in 0..iterations {
        let start = Instant::now();
        let record = sender.seal_envelope(&expected)?;
        seal_ns.push(u64::try_from(start.elapsed().as_nanos())?);
        wire_bytes += record.len();
        let start = Instant::now();
        for chunk in record.chunks(chunk_bytes) {
            let mut offset = 0;
            while offset < chunk.len() {
                let previous_capacity = stream.buffer_capacity_bytes();
                let feed = stream.feed(&chunk[offset..]);
                let progress = feed.bytes_consumed();
                if progress == 0 || progress > chunk.len() - offset {
                    return Err("managed profile made invalid progress".into());
                }
                offset += progress;
                feed_calls += 1;
                if feed.batch().yielded() {
                    yields += 1;
                    std::thread::yield_now();
                }
                let capacity = stream.buffer_capacity_bytes();
                growths += usize::from(capacity > previous_capacity);
                peak_capacity = peak_capacity.max(capacity);
                peak_buffered = peak_buffered.max(stream.buffered_bytes());
                let (batch, _) = feed.into_parts();
                let (frames, error) = batch.into_parts();
                // Deliver the valid prefix before interpreting a terminal suffix.
                for frame in frames {
                    if frame != expected {
                        return Err("managed profile delivered a different frame".into());
                    }
                    delivered += 1;
                }
                if let Some(error) = error {
                    return Err(error.into());
                }
            }
        }
        decode_ns.push(u64::try_from(start.elapsed().as_nanos())?);
    }
    if delivered != iterations {
        return Err("managed profile lost or duplicated frames".into());
    }
    let decode_total_ns: u64 = decode_ns.iter().sum();
    let retained_capacity = stream.buffer_capacity_bytes();
    let retained_length = stream.buffered_bytes();
    stream.finish()?;
    sender.retire();
    Ok(json!({
        "iterations": iterations,
        "payload_bytes": payload_bytes,
        "chunk_bytes": chunk_bytes,
        "max_feed_bytes": limits.max_feed_bytes,
        "max_records_per_feed": limits.max_records_per_feed,
        "wire_bytes": wire_bytes,
        "delivered_frames": delivered,
        "feed_calls": feed_calls,
        "budget_yields": yields,
        "record_buffer_growth_events": growths,
        "record_buffer_capacity_peak_bytes": peak_capacity,
        "record_buffer_length_observed_peak_bytes": peak_buffered,
        "record_buffer_capacity_after_workload_bytes": retained_capacity,
        "record_buffer_length_after_workload_bytes": retained_length,
        "returned_payload_bytes_per_frame": payload_bytes,
        "seal": percentiles(&mut seal_ns),
        "decode_and_delivery": percentiles(&mut decode_ns),
        "decode_and_delivery_total_ns": decode_total_ns
    }))
}

fn main() -> ProfileResult<()> {
    let arguments: Vec<_> = std::env::args().skip(1).collect();
    if arguments.len() > 1 {
        return Err("usage: managed_record_profile [iterations:64..4096]".into());
    }
    let iterations = match arguments.first() {
        Some(value) => value.parse::<usize>()?,
        None => 256,
    };
    if !(64..=4096).contains(&iterations) {
        return Err("iterations must be in 64..4096".into());
    }
    let mut scenarios = Vec::new();
    // HPTA intentionally rejects empty payloads; one byte is the legal minimum.
    for payload_bytes in [1, 64, 4096] {
        for chunk_bytes in [1, 37, 512] {
            scenarios.push(measure(iterations, payload_bytes, chunk_bytes)?);
        }
    }
    println!(
        "{}",
        serde_json::to_string(&json!({
            "schema": "hepta.platform-wire.managed-profile.v1",
            "scope": "in-process managed HPTM owner; fixture channel and keys",
            "profile": if cfg!(debug_assertions) { "debug" } else { "release" },
            "independent_acceptance": false,
            "authenticated_network_ingress": false,
            "host_rss_measured": false,
            "allocator_calls_measured": false,
            "queue_wait_measured": false,
            "scenarios": scenarios
        }))?
    );
    Ok(())
}
