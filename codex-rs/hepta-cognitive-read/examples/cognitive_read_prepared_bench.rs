//! Compare equivalent two-projection requests, including index construction.

use std::error::Error;
use std::hint::black_box;
use std::time::Instant;

use codex_hepta_cognitive_read::MAX_ENCODED_READ_RESULT_BYTES_V2;
use codex_hepta_cognitive_read::PreparedReadSnapshotV1;
use codex_hepta_cognitive_read::ReadFieldV1;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_cognitive_read::read_ids_v1;
use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

const ITERATIONS: usize = 32;

fn distribution(mut samples: Vec<u128>) -> String {
    samples.sort_unstable();
    let last = samples.len() - 1;
    let p50 = samples[last * 50 / 100];
    let p95 = samples[last * 95 / 100];
    let p99 = samples[last * 99 / 100];
    format!("{{\"p50_ns\":{p50},\"p95_ns\":{p95},\"p99_ns\":{p99}}}")
}

fn case(record_count: usize, depth: usize, requested: usize) -> Result<String, Box<dyn Error>> {
    let heads = record_count / depth;
    let mut records = Vec::with_capacity(record_count);
    for head in 0..heads {
        let record_id = StableId::new(format!("memory:{head:05}"))?;
        let mut predecessor_digest = None;
        for revision in 1..=depth {
            let record = MemoryRecord {
                record_id: record_id.clone(),
                revision: Revision::new(u64::try_from(revision)?)?,
                kind: MemoryKind::Fact,
                content_digest: Digest32::of_bytes(format!("{head}:{revision}").as_bytes()),
                predecessor_digest,
                citations: vec![Citation {
                    source_id: StableId::new("source:benchmark")?,
                    source_digest: Digest32::of_bytes(b"benchmark source"),
                }],
                state: RecordState::Live,
            };
            predecessor_digest = Some(record.record_digest());
            records.push(record);
        }
    }
    let snapshot = build_snapshot(Generation::new(1)?, records)?;
    let requested = requested.min(heads);
    let ids = (heads - requested..heads)
        .map(|head| StableId::new(format!("memory:{head:05}")))
        .collect::<Result<Vec<_>, _>>()?;
    let admission = ReadIdsRequestV1 {
        snapshot_digest: snapshot.snapshot_digest,
        record_ids: ids.clone(),
        fields: vec![ReadFieldV1::ContentDigest, ReadFieldV1::Citations],
        maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
    };
    let selected = ReadIdsRequestV1 {
        snapshot_digest: snapshot.snapshot_digest,
        record_ids: ids.into_iter().take(4).collect(),
        fields: vec![ReadFieldV1::ContentDigest],
        maximum_encoded_bytes: 8192,
    };
    // Reject a performance result if the two implementations are not identical.
    let prepared = PreparedReadSnapshotV1::new(&snapshot)?;
    for request in [&admission, &selected] {
        if prepared.read_ids(request.clone())? != read_ids_v1(&snapshot, request.clone())? {
            return Err("prepared/one-shot result mismatch".into());
        }
    }
    let mut one_shot_pair = Vec::with_capacity(ITERATIONS);
    let mut prepared_pair = Vec::with_capacity(ITERATIONS);
    let mut preparation = Vec::with_capacity(ITERATIONS);
    let mut projection = Vec::with_capacity(ITERATIONS);
    for iteration in 0..ITERATIONS {
        // Alternate order to avoid consistently giving one mode the warmer run.
        for mode in [iteration % 2, (iteration + 1) % 2] {
            let start = Instant::now();
            if mode == 0 {
                black_box(read_ids_v1(black_box(&snapshot), admission.clone())?);
                black_box(read_ids_v1(black_box(&snapshot), selected.clone())?);
                one_shot_pair.push(start.elapsed().as_nanos());
            } else {
                let view = PreparedReadSnapshotV1::new(black_box(&snapshot))?;
                black_box(view.read_ids(admission.clone())?);
                black_box(view.read_ids(selected.clone())?);
                drop(view);
                prepared_pair.push(start.elapsed().as_nanos());
            }
        }
        let start = Instant::now();
        let view = PreparedReadSnapshotV1::new(black_box(&snapshot))?;
        preparation.push(start.elapsed().as_nanos());
        let start = Instant::now();
        black_box(view.read_ids(admission.clone())?);
        projection.push(start.elapsed().as_nanos());
    }
    let one_shot_pair = distribution(one_shot_pair);
    let prepared_pair = distribution(prepared_pair);
    let preparation = distribution(preparation);
    let projection = distribution(projection);
    Ok(format!(
        "{{\"records\":{record_count},\"heads\":{heads},\"revision_depth\":{depth},\"requested_ids\":{requested},\"citations_per_revision\":1,\"one_shot_pair\":{one_shot_pair},\"prepared_pair_including_build\":{prepared_pair},\"prepare_only\":{preparation},\"projection_only\":{projection}}}"
    ))
}

fn peak_rss_kib() -> Option<u64> {
    let status = std::fs::read_to_string("/proc/self/status").ok()?;
    let line = status.lines().find(|line| line.starts_with("VmHWM:"))?;
    line.split_whitespace().nth(1)?.parse().ok()
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut cases = Vec::new();
    for records in [128, 4096, 16_384] {
        for depth in [1, 8] {
            for requested in [1, 512] {
                cases.push(case(records, depth, requested)?);
            }
        }
    }
    let cases = cases.join(",");
    let rss = peak_rss_kib().map_or_else(|| "null".to_string(), |rss| rss.to_string());
    println!(
        "{{\"schema\":\"hepta.cognitive.read.prepared-benchmark.v1\",\"iterations\":{ITERATIONS},\"cases\":[{cases}],\"process_peak_rss_kib\":{rss},\"scope\":\"in_memory_structure_not_sqlite_or_model_latency\"}}"
    );
    Ok(())
}
