//! Owner-private, non-authorizing Rust -> real HF PyTorch Encoder shadow bridge.
//!
//! This is NOT a production microbatch owner: the pinned Python process loads
//! the model for a research batch, has no in-process generation fence, no signed
//! final-use admission. Only reviewed offline weight snapshots
//! are supported; worker output MUST NOT directly cause a Cell promotion.
//! It never simulates Encoder logits or returns a production receipt.

use std::collections::BTreeSet;
use std::fs;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::mpsc;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_infer_core::shared_feature_v2::ImmutableFeatureSnapshotV2;
use codex_hepta_infer_core::shared_feature_v2::SharedFeatureCacheV2;
use codex_hepta_infer_core::shared_feature_v2::SharedFeatureIdentityV2;
use codex_hepta_infer_core::shared_feature_v2::feature_content_digest_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::NonAuthorizingPosture;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;

use super::Error;

const MAX_SHADOW_BATCH: usize = 32;
const MAX_REQUEST_BYTES: usize = 128 * 1024;
const MAX_RESULT_BYTES: usize = 2 * 1024 * 1024;
const MAX_SHADOW_RUNTIME: Duration = Duration::from_secs(120);
const Q24_LIMIT: i64 = 8 * (1 << 24);

#[derive(Clone, Debug)]
pub(crate) struct PinnedShadowStemConfig {
    pub python_executable: PathBuf,
    pub reviewed_script: PathBuf,
    pub reviewed_script_sha256: String,
    pub manifest: PathBuf,
    pub manifest_sha256: String,
    pub expected_pipeline_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ShadowStemInput {
    pub question: String,
    pub options: Vec<String>,
    pub state: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ShadowStemCellRequest {
    pub scope_id: String,
    pub principal_id: String,
    pub purpose_id: String,
    pub cell_id: String,
    pub generation: u64,
    pub authority_epoch: u64,
    pub input: ShadowStemInput,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CheckedShadowStemRow {
    pub scope_id: String,
    pub principal_id: String,
    pub purpose_id: String,
    pub cell_id: String,
    pub generation: u64,
    pub authority_epoch: u64,
    pub input_digest: String,
    pub feature_digest: String,
    pub features_q24: Vec<i64>,
}

#[derive(Clone, Debug)]
pub(crate) struct CheckedShadowStemBatch {
    pub pipeline_digest: Digest32,
    pub rows: Vec<CheckedShadowStemRow>,
    pub unique_inputs: usize,
    pub actual_forward_calls_reported: usize,
    pub backend_latency_micros_reported: u64,
    pub authority: NonAuthorizingPosture,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawShadowBatch {
    mode: String,
    actual_pretrained_forward_calls: usize,
    distinct_inputs: usize,
    total_cell_requests: usize,
    encoder_latency_micros: u64,
    rows: Vec<RawShadowRow>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawShadowRow {
    scope_id: String,
    principal_id: String,
    purpose_id: String,
    cell_id: String,
    generation: u64,
    authority_epoch: u64,
    input_digest: String,
    features_q24: Vec<i64>,
    feature_digest: String,
    pipeline_digest: String,
    authority: String,
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn checked_regular_file(path: &PathBuf, expected_sha256: &str) -> Result<(), Error> {
    super::validate_digest(expected_sha256, "pinned artifact")?;
    if !path.is_absolute() {
        return Err(Error::FeatureContract);
    }
    let info = fs::symlink_metadata(path).map_err(|_| Error::FeatureContract)?;
    if !info.is_file() || info.file_type().is_symlink() {
        return Err(Error::FeatureContract);
    }
    let bytes = fs::read(path).map_err(|_| Error::FeatureContract)?;
    if sha256_hex(&bytes) != expected_sha256 {
        return Err(Error::FeatureContract);
    }
    Ok(())
}

/// Canonical Python-compatible joint input has *alphabetical* key order.
///
/// Avoid serde_json::Value here: Bazel's feature-unified serde_json may enable
/// preserve_order, changing a map's serialized bytes across targets and OSes.
/// A typed struct serializes fields in declaration order with either feature.
#[derive(Serialize)]
struct CanonicalJointInput<'a> {
    options: &'a [String],
    question: &'a str,
    state: &'a str,
}

fn input_hash(input: &ShadowStemInput) -> Result<String, Error> {
    // Match Python canonical_bytes: sorted keys, compact JSON, UTF-8. This
    // exact identity is a scope-fenced feature-cache key, not an authority.
    // A future input-schema change must version the digest and both goldens.
    let canonical = CanonicalJointInput {
        options: &input.options,
        question: &input.question,
        state: &input.state,
    };
    let bytes = serde_json::to_vec(&canonical).map_err(|_| Error::FeatureContract)?;
    Ok(sha256_hex(&bytes))
}

/// Runs one real-weight offline batch (if provisioned) and rejects any output
/// that cannot be mapped one-to-one to the original fenced Cell request.
///
/// This seam is deliberately private to the Worker crate. The caller cannot
/// infer permission, persistence, model signature or NDU from the result.
pub(crate) fn run_pinned_shadow_stem_batch(
    config: &PinnedShadowStemConfig,
    requests: &[ShadowStemCellRequest],
) -> Result<CheckedShadowStemBatch, Error> {
    if requests.is_empty() || requests.len() > MAX_SHADOW_BATCH {
        return Err(Error::RequestCapacity);
    }
    super::validate_digest(&config.expected_pipeline_digest, "Stem pipeline")?;
    checked_regular_file(&config.reviewed_script, &config.reviewed_script_sha256)?;
    checked_regular_file(&config.manifest, &config.manifest_sha256)?;
    if !config.python_executable.is_absolute() {
        return Err(Error::FeatureContract);
    }

    let first = &requests[0];
    let mut identities = BTreeSet::new();
    let mut input_keys = BTreeSet::new();
    let mut hashes = Vec::with_capacity(requests.len());
    for request in requests {
        for value in [
            &request.scope_id,
            &request.principal_id,
            &request.purpose_id,
            &request.cell_id,
        ] {
            super::validate_identity(value, "Stem identity")?;
        }
        if request.scope_id != first.scope_id
            || request.principal_id != first.principal_id
            || request.purpose_id != first.purpose_id
            || request.generation != first.generation
            || request.authority_epoch != first.authority_epoch
            || request.generation == 0
            || request.authority_epoch == 0
            || request.input.question.is_empty()
            || request.input.question.len() > 30_000
            || request.input.state.len() > 30_000
            || request.input.options.is_empty()
            || request.input.options.len() > 32
            || request
                .input
                .options
                .iter()
                .any(|option| option.is_empty() || option.len() > 4_000)
        {
            return Err(Error::FeatureContract);
        }
        if !identities.insert((
            request.scope_id.clone(),
            request.principal_id.clone(),
            request.cell_id.clone(),
        )) {
            return Err(Error::FeatureContract);
        }
        let hash = input_hash(&request.input)?;
        input_keys.insert((
            request.scope_id.clone(),
            request.principal_id.clone(),
            request.purpose_id.clone(),
            request.generation,
            request.authority_epoch,
            hash.clone(),
        ));
        hashes.push(hash);
    }
    let payload = serde_json::to_vec(requests).map_err(|_| Error::FeatureContract)?;
    if payload.len() > MAX_REQUEST_BYTES {
        return Err(Error::FeatureLimit);
    }

    // No shell, no downloaded weights and no implicit fallback. A genuine
    // production implementation must replace per-batch process creation with
    // a long-lived, owner-authenticated native backend and bounded deadlines.
    let mut child = Command::new(&config.python_executable)
        .arg("-I")
        .arg(&config.reviewed_script)
        .arg("--manifest")
        .arg(&config.manifest)
        .arg("--requests")
        .arg("-")
        // The untrusted model loader never inherits unrelated tokens, proxy
        // credentials or a user-controlled Python module search path.
        .env_clear()
        .env("HF_HUB_OFFLINE", "1")
        .env("TRANSFORMERS_OFFLINE", "1")
        .env("PYTHONNOUSERSITE", "1")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("TOKENIZERS_PARALLELISM", "false")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| Error::FeatureContract)?;
    // Even a 128 KiB request can exceed an OS pipe buffer. Never perform
    // synchronous stdin writes on the supervisor thread: a stalled Python
    // loader must not indefinitely block cancellation or the deadline.
    let Some(mut stdin) = child.stdin.take() else {
        let _ = child.kill();
        let _ = child.wait();
        return Err(Error::FeatureContract);
    };
    let (write_sender, write_receiver) = mpsc::sync_channel(1);
    thread::spawn(move || {
        let written = stdin.write_all(&payload).is_ok();
        let _ = write_sender.send(written);
    });
    // std::Child::wait_with_output would buffer unbounded stdout and does not
    // enforce a deadline. Read at most MAX_RESULT_BYTES + 1 on a separate
    // thread while supervising the process, then reject excess output.
    let stdout = child.stdout.take().ok_or(Error::FeatureContract)?;
    let (sender, receiver) = mpsc::sync_channel(1);
    thread::spawn(move || {
        let mut limited = stdout.take((MAX_RESULT_BYTES + 1) as u64);
        let mut bytes = Vec::new();
        let read_ok = limited.read_to_end(&mut bytes).is_ok();
        let _ = sender.send((read_ok, bytes));
    });
    let deadline = Instant::now() + MAX_SHADOW_RUNTIME;
    let mut write_complete = false;
    let status = loop {
        if !write_complete {
            match write_receiver.try_recv() {
                Ok(true) => write_complete = true,
                Ok(false) | Err(mpsc::TryRecvError::Disconnected) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(Error::FeatureContract);
                }
                Err(mpsc::TryRecvError::Empty) => {}
            }
        }
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {}
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(Error::FeatureContract);
            }
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err(Error::DeadlineExpired);
        }
        thread::sleep(Duration::from_millis(10));
    };
    if !write_complete
        && !matches!(
            write_receiver.recv_timeout(deadline.saturating_duration_since(Instant::now())),
            Ok(true)
        )
    {
        return Err(Error::FeatureContract);
    }
    let time_left = deadline.saturating_duration_since(Instant::now());
    let (read_ok, response_bytes) = receiver
        .recv_timeout(time_left)
        .map_err(|_| Error::DeadlineExpired)?;
    if !status.success() || !read_ok || response_bytes.len() > MAX_RESULT_BYTES {
        return Err(Error::FeatureContract);
    }
    let response: RawShadowBatch =
        serde_json::from_slice(&response_bytes).map_err(|_| Error::FeatureContract)?;
    if response.mode != "shadow_only"
        || response.actual_pretrained_forward_calls != 1
        || response.total_cell_requests != requests.len()
        || response.rows.len() != requests.len()
        || response.distinct_inputs != input_keys.len()
    {
        return Err(Error::FeatureContract);
    }
    let mut checked = Vec::with_capacity(requests.len());
    for ((request, expected_input), row) in requests.iter().zip(hashes).zip(response.rows) {
        if row.scope_id != request.scope_id
            || row.principal_id != request.principal_id
            || row.purpose_id != request.purpose_id
            || row.cell_id != request.cell_id
            || row.generation != request.generation
            || row.authority_epoch != request.authority_epoch
            || row.input_digest != expected_input
            || row.pipeline_digest != config.expected_pipeline_digest
            || row.authority != "DENY_ALL"
            || row.features_q24.is_empty()
            || row.features_q24.len() > 512
            || row
                .features_q24
                .iter()
                .any(|v| !(-Q24_LIMIT..=Q24_LIMIT).contains(v))
            || feature_content_digest_v2(&row.features_q24).to_string() != row.feature_digest
        {
            return Err(Error::FeatureContract);
        }
        checked.push(CheckedShadowStemRow {
            scope_id: row.scope_id,
            principal_id: row.principal_id,
            purpose_id: row.purpose_id,
            cell_id: row.cell_id,
            generation: row.generation,
            authority_epoch: row.authority_epoch,
            input_digest: row.input_digest,
            feature_digest: row.feature_digest,
            features_q24: row.features_q24,
        });
    }
    Ok(CheckedShadowStemBatch {
        pipeline_digest: Digest32::from_str(&config.expected_pipeline_digest)
            .map_err(|_| Error::FeatureContract)?,
        rows: checked,
        unique_inputs: response.distinct_inputs,
        actual_forward_calls_reported: response.actual_pretrained_forward_calls,
        backend_latency_micros_reported: response.encoder_latency_micros,
        authority: NonAuthorizingPosture::DENY_ALL,
    })
}

const MAX_SHADOW_SNAPSHOT_TTL_MS: u64 = 5 * 60 * 1000;

/// An independently reviewed, immutable Stem pipeline identity. These are
/// digest *claims* for shadow staging, not signed Artifact CAS observations.
#[derive(Clone, Copy, Debug)]
pub(crate) struct ShadowSnapshotPipeline {
    pub encoder_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub normalizer_digest: Digest32,
    pub quantization_digest: Digest32,
}

/// Stages an all-or-nothing mapping of verified offline feature rows into the
/// existing shared Arc snapshot cache. Committed snapshots carry DENY_ALL and
/// never bypass owner final-use admission, even when two Cells reuse one Arc.
///
/// Cloning the BTreeMap is intentional for the small research-only batch:
/// tensor buffers are Arc-shared, but this O(cache_entries) staging method is
/// NOT the production 4096-Cell hot-path transaction design.
pub(crate) fn stage_shadow_feature_snapshots(
    cache: &mut SharedFeatureCacheV2,
    batch: &CheckedShadowStemBatch,
    pipeline: ShadowSnapshotPipeline,
    now_ms: u64,
    expires_at_ms: u64,
) -> Result<Vec<Arc<ImmutableFeatureSnapshotV2>>, Error> {
    if batch.rows.is_empty()
        || batch.rows.len() > MAX_SHADOW_BATCH
        || expires_at_ms <= now_ms
        || expires_at_ms.saturating_sub(now_ms) > MAX_SHADOW_SNAPSHOT_TTL_MS
        || batch.authority.grants_any()
        || batch.pipeline_digest != pipeline.encoder_digest
        || [
            pipeline.encoder_digest,
            pipeline.tokenizer_digest,
            pipeline.normalizer_digest,
            pipeline.quantization_digest,
        ]
        .iter()
        .any(|digest| digest.is_zero())
    {
        return Err(Error::FeatureContract);
    }
    let mut staged = cache.clone();
    let mut all = Vec::with_capacity(batch.rows.len());
    for row in &batch.rows {
        let input = Digest32::from_str(&row.input_digest).map_err(|_| Error::FeatureContract)?;
        let content =
            Digest32::from_str(&row.feature_digest).map_err(|_| Error::FeatureContract)?;
        if row.features_q24.is_empty()
            || row.features_q24.len() > 512
            || content != feature_content_digest_v2(&row.features_q24)
        {
            return Err(Error::FeatureContract);
        }
        let identity = SharedFeatureIdentityV2 {
            scope_id: StableId::new(row.scope_id.clone()).map_err(|_| Error::FeatureContract)?,
            principal_id: StableId::new(row.principal_id.clone())
                .map_err(|_| Error::FeatureContract)?,
            purpose_id: StableId::new(row.purpose_id.clone())
                .map_err(|_| Error::FeatureContract)?,
            generation: Generation::new(row.generation).map_err(|_| Error::FeatureContract)?,
            authority_epoch: row.authority_epoch,
            encoder_digest: pipeline.encoder_digest,
            tokenizer_digest: pipeline.tokenizer_digest,
            normalizer_digest: pipeline.normalizer_digest,
            quantization_digest: pipeline.quantization_digest,
            input_digest: input,
        };
        let snapshot = if let Some(existing) = staged
            .get(now_ms, &identity)
            .map_err(|_| Error::FeatureContract)?
        {
            if existing.content_digest != content
                || existing.expires_at_ms != expires_at_ms
                || existing.features_q24.as_ref() != row.features_q24.as_slice()
            {
                return Err(Error::FeatureContract);
            }
            existing
        } else {
            staged
                .insert(
                    now_ms,
                    identity,
                    expires_at_ms,
                    Arc::from(row.features_q24.clone()),
                )
                .map_err(|_| Error::FeatureContract)?
        };
        all.push(snapshot);
    }
    *cache = staged;
    Ok(all)
}

#[cfg(test)]
#[path = "model_worker_stem_shadow_tests.rs"]
mod tests;
