use std::error::Error;
use std::hint::black_box;
use std::time::Instant;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::MAX_WIRE_PAYLOAD_BYTES;
use codex_hepta_wire::StreamingDecoder;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::decode_frame;

const DEFAULT_NEAR_LIMIT_ITERATIONS: usize = 32;
const DEFAULT_LONG_CONNECTION_FRAMES: usize = 10_000;
const LONG_CONNECTION_PAYLOAD_BYTES: usize = 4 * 1024;

fn main() -> Result<(), Box<dyn Error>> {
    let mut args = std::env::args().skip(1);
    let near_limit_iterations = parse_count(
        args.next(),
        DEFAULT_NEAR_LIMIT_ITERATIONS,
        "near-limit iterations",
    )?;
    let long_connection_frames = parse_count(
        args.next(),
        DEFAULT_LONG_CONNECTION_FRAMES,
        "long-connection frames",
    )?;
    if args.next().is_some() {
        return Err("expected at most two numeric arguments".into());
    }

    let near_limit = encoded_frame(MAX_WIRE_PAYLOAD_BYTES, 1)?;
    let near_started = Instant::now();
    for _ in 0..near_limit_iterations {
        let decoded = decode_frame(black_box(&near_limit))?;
        black_box(decoded);
    }
    let near_elapsed = near_started.elapsed();
    let near_total_bytes = near_limit
        .len()
        .checked_mul(near_limit_iterations)
        .ok_or("near-limit byte count overflow")?;

    let connection_frame = encoded_frame(LONG_CONNECTION_PAYLOAD_BYTES, 2)?;
    let mut decoder = StreamingDecoder::new();
    let connection_started = Instant::now();
    let mut decoded_frames = 0_usize;
    for _ in 0..long_connection_frames {
        let batch = decoder.push_batch(black_box(&connection_frame));
        if let Some(error) = batch.terminal_error() {
            return Err(format!("long-connection decode failed: {error}").into());
        }
        decoded_frames = decoded_frames
            .checked_add(batch.frames().len())
            .ok_or("decoded frame count overflow")?;
    }
    let connection_elapsed = connection_started.elapsed();
    if decoded_frames != long_connection_frames || decoder.buffered_len() != 0 {
        return Err("long-connection decoder did not deliver every complete frame".into());
    }
    let connection_total_bytes = connection_frame
        .len()
        .checked_mul(long_connection_frames)
        .ok_or("long-connection byte count overflow")?;

    println!(
        concat!(
            "{{",
            "\"schema\":\"hepta.platform-wire.throughput-probe.v1\",",
            "\"near_limit_iterations\":{},",
            "\"near_limit_frame_bytes\":{},",
            "\"near_limit_elapsed_ns\":{},",
            "\"near_limit_bytes_per_second\":{:.3},",
            "\"long_connection_frames\":{},",
            "\"long_connection_frame_bytes\":{},",
            "\"long_connection_elapsed_ns\":{},",
            "\"long_connection_frames_per_second\":{:.3},",
            "\"long_connection_bytes_per_second\":{:.3}",
            "}}"
        ),
        near_limit_iterations,
        near_limit.len(),
        near_elapsed.as_nanos(),
        rate(near_total_bytes, near_elapsed.as_secs_f64()),
        long_connection_frames,
        connection_frame.len(),
        connection_elapsed.as_nanos(),
        rate(long_connection_frames, connection_elapsed.as_secs_f64()),
        rate(
            connection_total_bytes,
            connection_elapsed.as_secs_f64()
        ),
    );
    Ok(())
}

fn encoded_frame(payload_bytes: usize, generation: u64) -> Result<Vec<u8>, Box<dyn Error>> {
    let envelope = WireEnvelopeV2::new(
        StableId::new("hepta.throughput-probe.v1")?,
        StableId::new("platform.wire.benchmark")?,
        Generation::new(generation)?,
        vec![0xa5; payload_bytes],
    )?;
    let encoded = envelope.encode();
    if !matches!(decode_frame(&encoded)?, DecodedEnvelope::V2(_)) {
        return Err("throughput fixture did not decode as HPTA V2".into());
    }
    Ok(encoded)
}

fn parse_count(
    raw: Option<String>,
    default: usize,
    name: &str,
) -> Result<usize, Box<dyn Error>> {
    let value = match raw {
        Some(raw) => raw.parse::<usize>()?,
        None => default,
    };
    if value == 0 {
        return Err(format!("{name} must be non-zero").into());
    }
    Ok(value)
}

fn rate(units: usize, seconds: f64) -> f64 {
    if seconds == 0.0 {
        0.0
    } else {
        units as f64 / seconds
    }
}
