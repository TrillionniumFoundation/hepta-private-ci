//! Linux-only, bounded resource experiment over private copies of one task Head.
//! This measures template replication, never independent learned tasks or an Encoder.

use std::error::Error;
use std::fs::File;
use std::hint::black_box;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_neuron::LoadedTaskHeadV1;
use codex_hepta_neuron::TaskFeatureIdentityV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const MEMORY_LIMIT: u64 = 800 * 1024 * 1024;
const INPUT_ROWS: usize = 256;
const DISPATCH_SAMPLES: usize = 4096;
const FANOUT_SAMPLES: usize = 16;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    identity: TaskFeatureIdentityV1,
    features: Vec<f32>,
    present_mask: u8,
    source_record_digest: String,
}

fn read_bounded(path: &Path, limit: usize) -> Result<Vec<u8>> {
    if !path.symlink_metadata()?.file_type().is_file() {
        return Err("regular, non-symlink input file required".into());
    }
    let mut bytes = Vec::new();
    File::open(path)?
        .take((limit + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > limit {
        return Err("input file byte budget".into());
    }
    Ok(bytes)
}

fn check_time(start: Instant) -> Result<()> {
    if start.elapsed() > Duration::from_secs(/*secs*/ 85) {
        return Err("native experiment wall-time budget".into());
    }
    Ok(())
}

fn resident(start: Instant) -> Result<Value> {
    check_time(start)?;
    let raw = read_bounded(Path::new("/proc/self/status"), /*limit*/ 65536)?;
    let status = std::str::from_utf8(&raw)?;
    let kib = |key: &str| -> Result<u64> {
        let prefix = format!("{key}:");
        let value = status
            .lines()
            .find_map(|line| line.strip_prefix(&prefix))
            .ok_or("missing proc memory field")?;
        let fields: Vec<_> = value.split_whitespace().collect();
        if fields.len() != 2 || fields[1] != "kB" {
            return Err("invalid proc memory units".into());
        }
        Ok(fields[0]
            .parse::<u64>()?
            .checked_mul(/*rhs*/ 1024)
            .ok_or("proc overflow")?)
    };
    let rss = kib("VmRSS")?;
    let peak = kib("VmHWM")?;
    if rss > MEMORY_LIMIT || peak > MEMORY_LIMIT {
        return Err("native resident-memory budget".into());
    }
    let pid: u32 = status
        .lines()
        .find_map(|line| line.strip_prefix("Pid:"))
        .ok_or("missing self pid")?
        .trim()
        .parse()?;
    Ok(
        json!({"source":"native /proc/self/status", "proc_self_pid":pid,
        "getpid":std::process::id(), "rss_bytes":rss, "rss_anon_bytes":kib("RssAnon")?,
        "post_exec_peak_rss_bytes":peak, "virtual_bytes":kib("VmSize")?}),
    )
}

fn elapsed_ns(start: Instant) -> Result<u64> {
    let nanos = u64::try_from(start.elapsed().as_nanos())?;
    if nanos == 0 {
        return Err("clock resolution cannot measure this call".into());
    }
    Ok(nanos)
}

fn run() -> Result<()> {
    if !cfg!(target_os = "linux") {
        return Err("this resource experiment requires Linux proc and rlimits".into());
    }
    let start = Instant::now();
    let arguments: Vec<String> = std::env::args().collect();
    let [
        _,
        manifest_path,
        weights_path,
        expected_manifest,
        requests_path,
        expected_requests,
        count,
    ] = arguments.as_slice()
    else {
        return Err("usage: native_task_head_pool MANIFEST WEIGHTS MANIFEST_SHA REQUESTS REQUESTS_SHA CELL_COUNT".into());
    };
    let cells: usize = count.parse()?;
    if ![1, 32, 256, 4096].contains(&cells) {
        return Err("unsupported bounded Cell count".into());
    }
    let limits = read_bounded(Path::new("/proc/self/limits"), /*limit*/ 65536)?;
    let limits = std::str::from_utf8(&limits)?;
    let address = limits
        .lines()
        .find_map(|line| line.strip_prefix("Max address space"))
        .ok_or("missing address-space limit")?;
    let fields: Vec<_> = address.split_whitespace().collect();
    if fields.len() != 3
        || fields[0].parse::<u64>()? != MEMORY_LIMIT
        || fields[1].parse::<u64>()? != MEMORY_LIMIT
        || fields[2] != "bytes"
    {
        return Err("the fixed 800 MiB address-space hard limit is required".into());
    }
    let manifest = read_bounded(Path::new(manifest_path), /*limit*/ 65536)?;
    let weights = read_bounded(Path::new(weights_path), /*limit*/ 1024 * 1024)?;
    let raw = read_bounded(Path::new(requests_path), /*limit*/ 32 * 1024 * 1024)?;
    let manifest_sha: Digest32 = expected_manifest.parse()?;
    let request_sha: Digest32 = expected_requests.parse()?;
    if request_sha.is_zero() || Digest32::of_bytes(&raw) != request_sha || !raw.ends_with(b"\n") {
        return Err("request stream digest or newline mismatch".into());
    }
    let mut requests = Vec::new();
    for line in raw.split_inclusive(|byte| *byte == b'\n') {
        if requests.len() >= INPUT_ROWS || line.len() > 256 * 1024 {
            return Err("bounded input rows required".into());
        }
        let row: Request = serde_json::from_slice(line)?;
        let source: Digest32 = row.source_record_digest.parse()?;
        if source.is_zero()
            || row.present_mask != 3
            || row.features.len() > 4096
            || row.features.iter().any(|value| !value.is_finite())
        {
            return Err("valid paired finite research input required".into());
        }
        requests.push(row);
    }
    if requests.len() != INPUT_ROWS {
        return Err("exactly 256 original paired rows required".into());
    }
    let request_bytes = raw.len();
    drop(raw);
    let baseline = resident(start)?;
    let allocation_start = Instant::now();
    let mut heads = Vec::with_capacity(cells);
    // Each call parses an independent owned Vec<f32>; no Arc or shared Head is used.
    for _ in 0..cells {
        heads.push(LoadedTaskHeadV1::from_artifact(
            &manifest,
            &weights,
            manifest_sha,
        )?);
        if heads.len().is_multiple_of(/*rhs*/ 32) {
            resident(start)?;
        }
    }
    let allocation_ns = elapsed_ns(allocation_start)?;
    let total_weights: usize = heads.iter().map(LoadedTaskHeadV1::weights_bytes).sum();
    if total_weights
        != cells
            .checked_mul(weights.len())
            .ok_or("weight count overflow")?
    {
        return Err("private parameter payload count differs".into());
    }
    let post_load = resident(start)?;
    let references = requests
        .iter()
        .map(|row| heads[0].predict(&row.features, &row.identity, row.present_mask))
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let warmup_start = Instant::now();
    for (index, head) in heads.iter().enumerate() {
        let row = &requests[index % INPUT_ROWS];
        let prediction = black_box(head.predict(&row.features, &row.identity, row.present_mask)?);
        if prediction != references[index % INPUT_ROWS] {
            return Err("private Head warmup differs from reference".into());
        }
        if index.is_multiple_of(/*rhs*/ 64) {
            check_time(start)?;
        }
    }
    let warmup_ns = elapsed_ns(warmup_start)?;
    let post_warmup = resident(start)?;
    let mut dispatch = Vec::with_capacity(DISPATCH_SAMPLES);
    let mut visits = vec![0usize; cells];
    for index in 0..DISPATCH_SAMPLES {
        let tick = Instant::now();
        let cell = index % cells;
        let row = &requests[index % INPUT_ROWS];
        let prediction =
            black_box(heads[cell].predict(&row.features, &row.identity, row.present_mask)?);
        dispatch.push(elapsed_ns(tick)?);
        if prediction != references[index % INPUT_ROWS] {
            return Err("dispatch prediction differs from reference".into());
        }
        visits[cell] += 1;
        if index.is_multiple_of(/*rhs*/ 256) {
            check_time(start)?;
        }
    }
    let mut fanout = Vec::with_capacity(FANOUT_SAMPLES);
    for row in requests.iter().take(FANOUT_SAMPLES) {
        let tick = Instant::now();
        let predictions = heads
            .iter()
            .map(|head| black_box(head.predict(&row.features, &row.identity, row.present_mask)))
            .collect::<std::result::Result<Vec<_>, _>>()?;
        fanout.push(elapsed_ns(tick)?);
        let reference = heads[0].predict(&row.features, &row.identity, row.present_mask)?;
        if predictions
            .iter()
            .any(|prediction| *prediction != reference)
        {
            return Err("fanout prediction differs from reference".into());
        }
        check_time(start)?;
    }
    let post_measurement = resident(start)?;
    let references = serde_json::to_value(references)?;
    let reference_bytes = serde_json::to_vec(&references)?;
    let output = json!({"schema":"hepta.native-task-head-pool.v1", "status":"PASS",
        "cells":cells, "resident_heads":heads.len(), "independently_trained_templates":1,
        "weights_bytes_per_head":weights.len(), "private_weights_payload_bytes":total_weights,
        "allocation_nanoseconds":allocation_ns, "manifest_sha256":manifest_sha.to_string(),
        "weights_sha256":Digest32::of_bytes(&weights).to_string(),
        "request_stream_sha256":request_sha.to_string(), "input_rows":INPUT_ROWS,
        "input_stream_bytes":request_bytes, "reference_predictions":references,
        "reference_predictions_sha256":Digest32::of_bytes(&reference_bytes).to_string(),
        "reference_source_record_digests":requests.iter().map(|row| &row.source_record_digest).collect::<Vec<_>>(),
        "warmup_calls":cells, "warmup_nanoseconds":warmup_ns,
        "dispatch_nanoseconds":dispatch, "dispatch_calls_per_head":visits,
        "fanout_nanoseconds":fanout, "fanout_predictions_per_sample":cells,
        "validation_extra_reference_calls":INPUT_ROWS + FANOUT_SAMPLES,
        "reference_validation_outside_measurement":true,
        "baseline":baseline, "post_load":post_load, "post_warmup":post_warmup,
        "post_measurement":post_measurement, "rss_budget_bytes":MEMORY_LIMIT,
        "address_space_hard_limit_bytes":MEMORY_LIMIT, "elapsed_nanoseconds":elapsed_ns(start)?,
        "mode":"SHADOW_ONLY", "authority":"DENY_ALL", "task_admission_allowed":false,
        "action_execution_allowed":false, "native_encoder_executed":false,
        "new_training_or_calibration":false, "new_independent_quality_trial":false,
        "target_device_qualified":false, "energy_joules":null,
        "scope":"private replicas of one frozen task Head; zero state; Linux shared-host resource observation"});
    let mut stdout = io::stdout().lock();
    serde_json::to_writer(&mut stdout, &output)?;
    stdout.write_all(b"\n")?;
    Ok(())
}

fn main() -> Result<()> {
    run()
}
