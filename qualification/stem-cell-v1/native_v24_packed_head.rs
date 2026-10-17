//! V24 source-bound, no-authority CPU research probe.
//!
//! Original frozen mmBERT features + two ORIGINAL physically trained V16 Heads
//! arrive in a bounded binary frame supplied by a separate Python source audit.
//! Every logical Head slot owns a real 1,540-scalar allocation; parameter VALUES
//! intentionally alternate between the two original models. This is not a
//! replacement for ModelDriver, InferenceWorker, Q24 or signed Final-use.
#![forbid(unsafe_code)]

use std::env;
use std::fmt::Write as _;
use std::fs::{self, OpenOptions};
use std::hint::black_box;
use std::io::Write as _;
use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

const MAGIC: &[u8; 8] = b"HPV24\0\0\x01";
const WIDTH: usize = 384;
const CLASSES: usize = 4;
const OBS: usize = 4;
const ACTIVE: usize = 32;
const ROUNDS: usize = 128;
const WARMUPS: usize = 8;
const MAX_SOURCE_BYTES: usize = 32 * 1024;
const MODEL_F32: usize = CLASSES * WIDTH + CLASSES;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Subject {
    generation: u64,
    fence: u64,
    epoch: u64,
    scope: u64,
    principal: u64,
    purpose: u64,
}

impl Subject {
    fn validate(self) -> Result<(), String> {
        if [self.generation, self.fence, self.epoch, self.scope, self.principal, self.purpose]
            .into_iter().any(|v| v == 0)
        {
            return Err("zero research-only subject binding".into());
        }
        Ok(())
    }
}

#[derive(Clone)]
struct Head {
    weights: [[f32; WIDTH]; CLASSES],
    bias: [f32; CLASSES],
}

struct Frame {
    slots: usize,
    scope: Subject,
    request: Subject,
    source_sha: [u8; 32],
    model_sha: [u8; 32],
    mean_sha: [u8; 32],
    features: Arc<[[f32; WIDTH]; OBS]>,
    heads: [Head; 2],
}

struct Reader<'a> {
    raw: &'a [u8],
    offset: usize,
}

impl Reader<'_> {
    fn bytes<const N: usize>(&mut self) -> Result<[u8; N], String> {
        let end = self.offset.checked_add(N).ok_or("frame offset overflow")?;
        let data = self.raw.get(self.offset..end).ok_or("short frame")?;
        self.offset = end;
        data.try_into().map_err(|_| "unreachable frame size".into())
    }
    fn u32(&mut self) -> Result<u32, String> { Ok(u32::from_le_bytes(self.bytes()?)) }
    fn u64(&mut self) -> Result<u64, String> { Ok(u64::from_le_bytes(self.bytes()?)) }
    fn f32(&mut self) -> Result<f32, String> {
        let value = f32::from_le_bytes(self.bytes()?);
        if !value.is_finite() || value.abs() > 10_000.0 {
            return Err("non-finite or unbounded frozen value".into());
        }
        Ok(value)
    }
    fn subject(&mut self) -> Result<Subject, String> {
        Ok(Subject { generation: self.u64()?, fence: self.u64()?, epoch: self.u64()?,
            scope: self.u64()?, principal: self.u64()?, purpose: self.u64()? })
    }
}

fn parse(raw: &[u8]) -> Result<Frame, String> {
    if raw.len() > MAX_SOURCE_BYTES { return Err("oversized research-only input".into()); }
    let mut r = Reader { raw, offset: 0 };
    if &r.bytes::<8>()? != MAGIC { return Err("wrong protocol magic".into()); }
    let slots = r.u32()? as usize;
    let observations = r.u32()? as usize;
    if ![64, 256, 1024, 4096].contains(&slots) || observations != OBS {
        return Err("unregistered physical fleet or case count".into());
    }
    let scope = r.subject()?;
    let request = r.subject()?;
    scope.validate()?;
    request.validate()?;
    if scope != request { return Err("generation/fence/epoch/scope/principal/purpose drift".into()); }
    let source_sha = r.bytes::<32>()?;
    let model_sha = r.bytes::<32>()?;
    let mean_sha = r.bytes::<32>()?;
    if [source_sha, model_sha, mean_sha].iter().any(|digest| digest.iter().all(|x| *x == 0)) {
        return Err("missing original feature/model/normalizer origin".into());
    }
    let mut features = [[0f32; WIDTH]; OBS];
    for feature in &mut features {
        for value in feature.iter_mut() { *value = r.f32()?; }
    }
    let mut heads: [Head; 2] = std::array::from_fn(|_| Head {
        weights: [[0f32; WIDTH]; CLASSES], bias: [0f32; CLASSES],
    });
    for head in &mut heads {
        for row in &mut head.weights {
            for v in row.iter_mut() { *v = r.f32()?; }
        }
        for v in &mut head.bias { *v = r.f32()?; }
    }
    if r.offset != raw.len() { return Err("unexpected trailing source bytes".into()); }
    Ok(Frame { slots, scope, request, source_sha, model_sha, mean_sha,
        features: Arc::new(features), heads })
}

fn physical_bank(frame: &Frame) -> Result<Vec<Head>, String> {
    let mut bank = Vec::with_capacity(frame.slots);
    for slot in 0..frame.slots {
        // Copies physical tensor storage, NOT independently trained parameters.
        bank.push(frame.heads[slot % 2].clone());
    }
    if bank.len() != frame.slots { return Err("incomplete allocated head bank".into()); }
    Ok(bank)
}

fn selected_ids(slots: usize) -> [usize; ACTIVE] {
    std::array::from_fn(|i| i * slots / ACTIVE)
}

fn score(head: &Head, feature: &[f32; WIDTH]) -> [f32; CLASSES] {
    let mut result = [0f32; CLASSES];
    for (class, out) in result.iter_mut().enumerate() {
        // Deterministic f64 accumulation of *actual saved f32 scalar values*.
        // No claim of numerical parity with a production Q24 backend.
        let mut acc = head.bias[class] as f64;
        for (weight, x) in head.weights[class].iter().zip(feature.iter()) {
            acc += (*weight as f64) * (*x as f64);
        }
        *out = acc as f32;
    }
    result
}

fn baseline(bank: &[Head], feature: &[f32; WIDTH]) -> Vec<[f32; CLASSES]> {
    bank.iter().map(|head| score(head, feature)).collect()
}

fn packed(bank: &[Head], feature: &[f32; WIDTH]) -> Vec<[f32; CLASSES]> {
    // Real 16-Head tile: one source feature read feeds up to sixteen distinct
    // physical model slots. Each output retains its own f64 accumulation and
    // original dimension order. This is not a production fused SIMD kernel.
    let mut result = Vec::with_capacity(bank.len());
    for tile in bank.chunks(16) {
        let mut accumulators = vec![[0f64; CLASSES]; tile.len()];
        for (slot, head) in tile.iter().enumerate() {
            for class in 0..CLASSES {
                accumulators[slot][class] = head.bias[class] as f64;
            }
        }
        for dimension in 0..WIDTH {
            let shared_x = feature[dimension] as f64;
            for (slot, head) in tile.iter().enumerate() {
                for class in 0..CLASSES {
                    accumulators[slot][class] +=
                        (head.weights[class][dimension] as f64) * shared_x;
                }
            }
        }
        for scores in accumulators { result.push(scores.map(|v| v as f32)); }
    }
    result
}

fn max_difference(a: &[[f32; CLASSES]], b: &[[f32; CLASSES]]) -> Result<f32, String> {
    if a.len() != b.len() { return Err("different baseline/candidate cardinality".into()); }
    let mut maximum: f32 = 0.0;
    for (left, right) in a.iter().zip(b) {
        for (x, y) in left.iter().zip(right) {
            if !x.is_finite() || !y.is_finite() {
                return Err("invalid numerical output".into());
            }
            maximum = maximum.max((x - y).abs());
        }
    }
    Ok(maximum)
}

fn pcentile(ns: &[u128], p: f64) -> f64 {
    let mut sorted = ns.to_vec();
    sorted.sort_unstable();
    let pos = (sorted.len() - 1) as f64 * p;
    let low = pos.floor() as usize;
    let high = (low + 1).min(sorted.len() - 1);
    let weight = pos - (low as f64);
    (sorted[low] as f64 * (1.0 - weight) + sorted[high] as f64 * weight) / 1e6
}

fn format_samples(samples: &[u128]) -> String {
    let mut text = String::from("[");
    for (i, value) in samples.iter().enumerate() {
        if i != 0 { text.push(','); }
        write!(&mut text, "{}", value).expect("formatting into string cannot fail");
    }
    text.push(']');
    text
}

fn hex(bytes: &[u8]) -> String {
    let mut text = String::with_capacity(bytes.len() * 2);
    for b in bytes { write!(&mut text, "{:02x}", b).expect("format hex"); }
    text
}

fn current_rss_bytes() -> Option<usize> {
    let contents = fs::read_to_string("/proc/self/status").ok()?;
    let line = contents.lines().find(|line| line.starts_with("VmRSS:"))?;
    let value = line.split_whitespace().nth(1)?.parse::<usize>().ok()?;
    value.checked_mul(1024)
}

fn whole_peak_rss_bytes() -> Option<usize> {
    let contents = fs::read_to_string("/proc/self/status").ok()?;
    let line = contents.lines().find(|line| line.starts_with("VmHWM:"))?;
    let value = line.split_whitespace().nth(1)?.parse::<usize>().ok()?;
    value.checked_mul(1024)
}

fn write_exclusive(path: &Path, raw: &[u8]) -> Result<(), String> {
    if path.symlink_metadata().is_ok() { return Err("existing output refused".into()); }
    if !path.parent().ok_or("missing parent path")?.is_dir() {
        return Err("output parent must already exist".into());
    }
    let mut stream = OpenOptions::new().write(true).create_new(true).open(path)
        .map_err(|e| format!("create-only output: {e}"))?;
    stream.write_all(raw).map_err(|e| format!("write output: {e}"))?;
    stream.sync_all().map_err(|e| format!("sync output: {e}"))?;
    Ok(())
}

fn execute(input: &Path, out: &Path, report: &Path) -> Result<(), String> {
    let info = input.symlink_metadata().map_err(|e| format!("source stat: {e}"))?;
    if !info.is_file() || info.len() as usize > MAX_SOURCE_BYTES {
        return Err("source must be bounded regular file (no symlink)".into());
    }
    let frame = parse(&fs::read(input).map_err(|e| format!("source read: {e}"))?)?;
    let bank = physical_bank(&frame)?;
    let ids = selected_ids(frame.slots);
    let active: Vec<Head> = ids.iter().map(|i| bank[*i].clone()).collect();
    let cached_head_bytes = ACTIVE * MODEL_F32 * std::mem::size_of::<f32>();
    let actual_head_bytes = frame.slots * MODEL_F32 * std::mem::size_of::<f32>();
    let rss_after = current_rss_bytes();
    let mut proof_max = 0f32;
    let mut serialized = Vec::with_capacity(OBS * frame.slots * CLASSES * 4);
    for x in frame.features.iter() {
        let scalar = baseline(&bank, x);
        let batched = packed(&bank, x);
        proof_max = proof_max.max(max_difference(&scalar, &batched)?);
        let scalar_selected = baseline(&active, x);
        let packed_selected = packed(&active, x);
        proof_max = proof_max.max(max_difference(&scalar_selected, &packed_selected)?);
        for row in batched {
            for value in row {
                serialized.extend_from_slice(&value.to_le_bytes());
            }
        }
    }
    if proof_max > 1e-6 { return Err("real model baseline/packed output mismatch".into()); }
    let mut base_ns = Vec::with_capacity(ROUNDS);
    let mut batch_ns = Vec::with_capacity(ROUNDS);
    let mut active_ns = Vec::with_capacity(ROUNDS);
    let mut rolling = 0f64;
    for i in 0..(WARMUPS + ROUNDS) {
        let feature = &frame.features[i % OBS];
        let variants: [fn(&[Head], &[f32; WIDTH]) -> Vec<[f32; CLASSES]>; 3] =
            [baseline, packed, packed];
        let mut elapsed = [0u128; 3];
        for step in 0..3 {
            let k = (step + i) % 3;
            let source = if k == 2 { &active } else { &bank };
            let start = Instant::now();
            let output = black_box(variants[k](source, black_box(feature)));
            elapsed[k] = start.elapsed().as_nanos().max(1);
            rolling += output[0][0] as f64;
        }
        if i >= WARMUPS {
            base_ns.push(elapsed[0]); batch_ns.push(elapsed[1]); active_ns.push(elapsed[2]);
        }
    }
    if !rolling.is_finite() { return Err("nonfinite consumed benchmark output".into()); }
    let body = format!(
        "{{\"schema\":\"hepta.stem.v24.rust-packed-worker-shadow.research\",\"authority\":\"DENY_ALL\",\"production_authorized\":false,\"rust_source_input_is_signature_authenticated\":false,\"worker_model_driver_integrated\":false,\"q24_policy_parity_verified\":false,\"original_encoder_forward_count\":0,\"future_source_count\":0,\"original_pretrained_cell_skills\":2,\"physically_allocated_head_slots\":{},\"logical_active_heads\":{},\"feature_width\":{},\"original_train_probes\":{},\"source_feature_sha256\":\"{}\",\"v16_model_sha256\":\"{}\",\"v15_mean_sha256\":\"{}\",\"research_generation\":{},\"research_fence\":{},\"research_epoch\":{},\"research_scope\":{},\"research_principal\":{},\"research_purpose\":{},\"allocated_head_weight_bytes\":{},\"selected_cache_head_weight_bytes\":{},\"shared_feature_bytes\":{},\"whole_process_rss_after_bank_bytes\":{},\"whole_process_peak_rss_bytes\":{},\"timed_rounds\":{},\"warmups\":{},\"max_reference_packed_logit_abs_error\":{},\"comparison_only_accumulation\":\"f64-of-original-f32\",\"scalar_full_wall_samples_ns\":{},\"packed_full_wall_samples_ns\":{},\"packed_active32_wall_samples_ns\":{},\"scalar_p99_ms\":{},\"packed_p99_ms\":{},\"active32_p99_ms\":{},\"rolling_consumed_output\":{}}}\n",
        frame.slots, ACTIVE, WIDTH, OBS,
        hex(&frame.source_sha),hex(&frame.model_sha),hex(&frame.mean_sha),
        frame.scope.generation,frame.scope.fence,frame.scope.epoch,frame.scope.scope,
        frame.scope.principal,frame.scope.purpose,
        actual_head_bytes,cached_head_bytes,OBS * WIDTH * 4,
        rss_after.map_or("null".into(),|v| v.to_string()),
        whole_peak_rss_bytes().map_or("null".into(),|v| v.to_string()),
        ROUNDS,WARMUPS,proof_max,format_samples(&base_ns),format_samples(&batch_ns),
        format_samples(&active_ns),pcentile(&base_ns,0.99),pcentile(&batch_ns,0.99),
        pcentile(&active_ns,0.99),rolling,
    );
    // No partial success report if physical numerical outputs fail to materialize.
    write_exclusive(out, &serialized)?;
    write_exclusive(report, body.as_bytes())?;
    Ok(())
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 {
        eprintln!("usage: native_v24_packed_head <bounded-input> <new-f32-output> <new-json-report>");
        std::process::exit(2);
    }
    if let Err(err) = execute(Path::new(&args[1]), Path::new(&args[2]), Path::new(&args[3])) {
        eprintln!("V24 research-only fail closed: {err}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(slots: usize) -> Vec<u8> {
        let mut result = MAGIC.to_vec();
        result.extend_from_slice(&(slots as u32).to_le_bytes());
        result.extend_from_slice(&(OBS as u32).to_le_bytes());
        for _ in 0..2 {
            for k in [11_u64, 17, 23, 29, 31, 37] {
                result.extend_from_slice(&k.to_le_bytes());
            }
        }
        result.extend(std::iter::repeat_n(0x32_u8, 96));
        result.extend(std::iter::repeat_n(0_u8, (OBS * WIDTH + 2 * MODEL_F32) * 4));
        result
    }

    #[test]
    fn all_fleet_sizes_allocate_independent_slots() {
        for n in [64, 256, 1024, 4096] {
            let frame = parse(&fixture(n)).expect("valid original-shaped private test fixture");
            let bank = physical_bank(&frame).expect("physical allocation");
            assert_eq!(bank.len(), n);
            assert_eq!(std::mem::size_of::<Head>(), MODEL_F32 * 4);
            assert_eq!(frame.features.len(), OBS);
            assert_eq!(frame.request, frame.scope);
            assert_eq!(max_difference(&baseline(&bank, &frame.features[0]),
                &packed(&bank, &frame.features[0])).unwrap(), 0.0);
        }
    }

    #[test]
    fn stale_generation_and_fence_fail_closed() {
        for i in 0..6 {
            let mut raw = fixture(64);
            // Request tuple begins after magic, sizes, and first six u64 fields.
            let position = 8 + 8 + 6 * 8 + i * 8;
            raw[position] ^= 1;
            assert!(parse(&raw).is_err());
        }
    }

    #[test]
    fn missing_authority_or_source_origin_fails_closed() {
        let mut data = fixture(64);
        data[16..24].fill(0);
        assert!(parse(&data).is_err());
        let mut data = fixture(64);
        let digest_position = 8 + 8 + 12 * 8;
        data[digest_position..digest_position + 32].fill(0);
        assert!(parse(&data).is_err());
    }

    #[test]
    fn truncated_oversized_foreign_and_nan_rejected() {
        let base = fixture(64);
        for cut in [0, 8, 16, 60, base.len() - 1] {
            assert!(parse(&base[..cut]).is_err());
        }
        let mut data = base.clone();
        data[0] = b'X';
        assert!(parse(&data).is_err());
        let mut data = base.clone();
        data.extend_from_slice(&[1]);
        assert!(parse(&data).is_err());
        let mut data = base.clone();
        let first_feature = 8 + 8 + 12 * 8 + 96;
        data[first_feature..first_feature + 4].copy_from_slice(&f32::NAN.to_le_bytes());
        assert!(parse(&data).is_err());
        assert!(parse(&vec![0u8; MAX_SOURCE_BYTES + 1]).is_err());
    }

    #[test]
    fn alternate_original_trainable_heads_change_scores() {
        let mut raw = fixture(64);
        let head_start = 8 + 8 + 12 * 8 + 96 + OBS * WIDTH * 4;
        // One weight of the second independent trained parameter VALUE set.
        let second_head = head_start + MODEL_F32 * 4;
        raw[second_head..second_head+4].copy_from_slice(&1f32.to_le_bytes());
        let first_feature = 8 + 8 + 12 * 8 + 96;
        raw[first_feature..first_feature+4].copy_from_slice(&1f32.to_le_bytes());
        let frame = parse(&raw).unwrap();
        let bank = physical_bank(&frame).unwrap();
        let output = packed(&bank, &frame.features[0]);
        assert_eq!(output[0][0], 0.0);
        assert_eq!(output[1][0], 1.0);
    }
}
