use std::error::Error;
use std::fs;
use std::hint::black_box;
use std::path::PathBuf;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use serde_json::json;

const DEFAULT_SAMPLES: usize = 200;
const MAX_SAMPLES: usize = 512;

type Result<T> = std::result::Result<T, Box<dyn Error + Send + Sync>>;

fn main() -> Result<()> {
    let samples = parse_samples()?;
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let path = std::env::temp_dir().join(format!(
        "runtime-codex-microprofile-{}-{nonce}.journal",
        std::process::id()
    ));
    let mut control = DurableInferenceControl::open(&path, samples + 16)?;

    let mut reserve_us = Vec::with_capacity(samples);
    let mut dispatch_us = Vec::with_capacity(samples);
    let mut abort_prepare_us = Vec::with_capacity(samples);
    let mut abort_confirm_us = Vec::with_capacity(samples);

    for index in 0..samples {
        let request_id = format!("profile.request.{index}");
        let owner_run_id = format!("profile.run.{index}");
        let digest = format!("{index:064x}");
        let binding_digest = format!("{:064x}", index + samples + 1);

        let started = Instant::now();
        let reserved = control.reserve_native(
            NativeRequest {
                request_id: request_id.clone(),
                principal_id: "profile.principal".to_string(),
                worker_generation: 1,
                model: "profile-model".to_string(),
                payload_digest: digest.clone(),
            },
            samples,
        )?;
        black_box(&reserved);
        reserve_us.push(elapsed_us(started));

        let started = Instant::now();
        let (dispatched, token) = control.dispatch_native_with_pre_effect_abort(
            &request_id,
            NativeDispatch {
                thread_id: format!("profile.thread.{index}"),
                model_provider: "profile-provider".to_string(),
                context_digest: digest,
                owner_context_digest: None,
                codex_payload_digest: None,
                codex_request_digest: None,
                app_server_version: None,
                protocol_id: None,
                codex_source_admission_digest: None,
                codex_home_digest: None,
                codex_connection_id: None,
                codex_session_id: None,
                codex_deadline_ms: None,
                codex_authority_epoch: None,
                codex_revocation_revision: None,
                codex_revocation_head_sha256: None,
                codex_authority_witness_sha256: None,
            },
        )?;
        black_box(&dispatched);
        dispatch_us.push(elapsed_us(started));

        // Force commitment derivation into the measured source path without
        // serializing or exposing the live token before abort preparation.
        black_box(token.commitment_digest(&owner_run_id, &binding_digest)?);
        let started = Instant::now();
        let pending = control.prepare_native_abort_before_effect(
            token,
            owner_run_id,
            3,
            binding_digest,
            "repository microprofile pre-effect abort".to_string(),
        )?;
        black_box(&pending);
        abort_prepare_us.push(elapsed_us(started));

        let proof = pending
            .pre_effect_abort
            .as_ref()
            .ok_or("AbortPending record omitted its proof")?
            .proof_digest
            .clone();
        let started = Instant::now();
        let confirmed = control.confirm_native_abort_before_effect(&request_id, &proof)?;
        black_box(&confirmed);
        abort_confirm_us.push(elapsed_us(started));
    }

    drop(control);
    let journal_bytes = fs::metadata(&path)?.len();
    let output = json!({
        "schema": "hepta.runtime-codex.repository-microprofile.v1",
        "schemaVersion": 1,
        "module": "runtime.codex",
        "samples": samples,
        "host": {
            "os": std::env::consts::OS,
            "arch": std::env::consts::ARCH,
            "peakRssKiB": peak_rss_kib(),
        },
        "journalBytes": journal_bytes,
        "journalBytesPerSample": journal_bytes as f64 / samples as f64,
        "latencyMicros": {
            "reserve": summary(&mut reserve_us),
            "dispatchFsync": summary(&mut dispatch_us),
            "abortPendingFsync": summary(&mut abort_prepare_us),
            "abortConfirmFsync": summary(&mut abort_confirm_us),
        },
        "claimBoundary": {
            "repositoryMicroprofileOnly": true,
            "realProvider": false,
            "targetHostAccepted": false,
            "productionSlo": false,
        }
    });
    println!("{}", serde_json::to_string_pretty(&output)?);
    fs::remove_file(path)?;
    Ok(())
}

fn parse_samples() -> Result<usize> {
    let mut args = std::env::args().skip(1);
    let Some(flag) = args.next() else {
        return Ok(DEFAULT_SAMPLES);
    };
    if flag != "--samples" {
        return Err(format!("unknown argument: {flag}").into());
    }
    let value: usize = args.next().ok_or("--samples requires a value")?.parse()?;
    if args.next().is_some() || !(1..=MAX_SAMPLES).contains(&value) {
        return Err(format!("samples must be 1..={MAX_SAMPLES}").into());
    }
    Ok(value)
}

fn elapsed_us(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn summary(values: &mut [u64]) -> serde_json::Value {
    values.sort_unstable();
    json!({
        "minimum": values[0],
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "maximum": values[values.len() - 1],
    })
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    let rank = values.len().saturating_mul(percentile).saturating_add(99) / 100;
    values[rank.saturating_sub(1).min(values.len() - 1)]
}

#[cfg(target_os = "linux")]
fn peak_rss_kib() -> Option<u64> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    status.lines().find_map(|line| {
        let value = line.strip_prefix("VmHWM:")?.trim();
        value.split_whitespace().next()?.parse().ok()
    })
}

#[cfg(not(target_os = "linux"))]
fn peak_rss_kib() -> Option<u64> {
    None
}

#[allow(dead_code)]
fn _journal_path_for_diagnostics(path: PathBuf) -> PathBuf {
    path
}
