use std::hint::black_box;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_cognitive_read::MAX_ENCODED_READ_RESULT_BYTES_V2;
use codex_hepta_cognitive_read::MAX_READ_IDS_V1;
use codex_hepta_cognitive_read::ReadFieldV1;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_cognitive_read::read_ids_v1;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

const RECORD_COUNT: usize = 16_384;
const ITERATIONS: usize = 32;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid benchmark id")
}

fn percentile(samples: &[Duration], numerator: usize, denominator: usize) -> Duration {
    let index = samples
        .len()
        .saturating_sub(1)
        .saturating_mul(numerator)
        / denominator;
    samples[index]
}

#[cfg(target_os = "linux")]
fn peak_rss_kib() -> Option<u64> {
    let status = std::fs::read_to_string("/proc/self/status").ok()?;
    status.lines().find_map(|line| {
        let value = line.strip_prefix("VmHWM:")?.trim();
        value
            .split_whitespace()
            .next()
            .and_then(|raw| raw.parse().ok())
    })
}

#[cfg(not(target_os = "linux"))]
fn peak_rss_kib() -> Option<u64> {
    None
}

fn main() {
    let records = (0..RECORD_COUNT)
        .map(|index| {
            let name = format!("memory:{index:05}");
            MemoryRecord {
                record_id: id(&name),
                revision: Revision::new(1).expect("revision"),
                kind: MemoryKind::Fact,
                content_digest: Digest32::of_bytes(name.as_bytes()),
                predecessor_digest: None,
                citations: Vec::new(),
                state: RecordState::Live,
            }
        })
        .collect::<Vec<_>>();
    let snapshot = build_snapshot(Generation::new(1).expect("generation"), records)
        .expect("maximum-size benchmark snapshot");
    let record_ids = (RECORD_COUNT - MAX_READ_IDS_V1..RECORD_COUNT)
        .map(|index| id(&format!("memory:{index:05}")))
        .collect::<Vec<_>>();
    let request = ReadIdsRequestV1 {
        snapshot_digest: snapshot.snapshot_digest,
        record_ids,
        fields: vec![ReadFieldV1::ContentDigest],
        maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
    };

    let warm = read_ids_v1(&snapshot, request.clone()).expect("warm read");
    black_box(warm);

    let mut samples = Vec::with_capacity(ITERATIONS);
    let started = Instant::now();
    for _ in 0..ITERATIONS {
        let iteration = Instant::now();
        let result = read_ids_v1(black_box(&snapshot), black_box(request.clone()))
            .expect("benchmark read");
        black_box(result);
        samples.push(iteration.elapsed());
    }
    let total = started.elapsed();
    samples.sort_unstable();

    let p50 = percentile(&samples, 50, 100).as_micros();
    let p95 = percentile(&samples, 95, 100).as_micros();
    let p99 = percentile(&samples, 99, 100).as_micros();
    let peak = peak_rss_kib()
        .map(|value| value.to_string())
        .unwrap_or_else(|| "null".to_string());

    println!(
        concat!(
            "{{",
            "\"schema\":\"hepta.cognitive.read.benchmark.v1\",",
            "\"records\":{},",
            "\"requested_ids\":{},",
            "\"iterations\":{},",
            "\"total_us\":{},",
            "\"p50_us\":{},",
            "\"p95_us\":{},",
            "\"p99_us\":{},",
            "\"peak_rss_kib\":{}",
            "}}"
        ),
        RECORD_COUNT,
        MAX_READ_IDS_V1,
        ITERATIONS,
        total.as_micros(),
        p50,
        p95,
        p99,
        peak,
    );
}
