//! Deterministic resource-summary receipts over externally observed runtime samples.
//!
//! This code computes qualification statistics; it does not manufacture target-
//! host measurements. Callers must bind a real host profile and supply observed
//! per-tick samples from that host.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::NeuronResourceEnvelopeV1;

const PPM: u128 = 1_000_000;
const MIN_QUALIFICATION_SAMPLES: usize = 20;
const MAX_QUALIFICATION_SAMPLES: usize = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeResourceSampleV1 {
    pub execution_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub journal_bytes_written: u64,
    pub queue_age_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeResourceSummaryV1 {
    pub config_digest: Digest32,
    pub host_profile_digest: Digest32,
    pub sample_count: u32,
    pub p50_execution_micros: u64,
    pub p95_execution_micros: u64,
    pub p99_execution_micros: u64,
    pub maximum_transient_allocation_bytes: u64,
    pub maximum_checkpoint_bytes: u64,
    pub maximum_queue_age_micros: u64,
    pub write_amplification_ppm: u32,
    pub samples_digest: Digest32,
    pub summary_digest: Digest32,
    pub limits_met: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ResourceSummaryError {
    EmptyDigest(&'static str),
    SampleCountOutOfRange,
    ZeroCheckpointBytes,
    Arithmetic,
}

impl fmt::Display for ResourceSummaryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ResourceSummaryError {}

pub fn summarize_runtime_resources(
    config_digest: Digest32,
    host_profile_digest: Digest32,
    envelope: &NeuronResourceEnvelopeV1,
    samples: &[RuntimeResourceSampleV1],
) -> Result<RuntimeResourceSummaryV1, ResourceSummaryError> {
    if config_digest.is_zero() {
        return Err(ResourceSummaryError::EmptyDigest("config"));
    }
    if host_profile_digest.is_zero() {
        return Err(ResourceSummaryError::EmptyDigest("host profile"));
    }
    if !(MIN_QUALIFICATION_SAMPLES..=MAX_QUALIFICATION_SAMPLES).contains(&samples.len()) {
        return Err(ResourceSummaryError::SampleCountOutOfRange);
    }

    let mut execution = Vec::with_capacity(samples.len());
    let mut maximum_transient = 0_u64;
    let mut maximum_checkpoint = 0_u64;
    let mut maximum_queue = 0_u64;
    let mut total_checkpoint = 0_u128;
    let mut total_journal = 0_u128;
    for sample in samples {
        if sample.checkpoint_bytes == 0 {
            return Err(ResourceSummaryError::ZeroCheckpointBytes);
        }
        execution.push(sample.execution_micros);
        maximum_transient = maximum_transient.max(sample.transient_allocation_bytes);
        maximum_checkpoint = maximum_checkpoint.max(sample.checkpoint_bytes);
        maximum_queue = maximum_queue.max(sample.queue_age_micros);
        total_checkpoint = total_checkpoint
            .checked_add(u128::from(sample.checkpoint_bytes))
            .ok_or(ResourceSummaryError::Arithmetic)?;
        total_journal = total_journal
            .checked_add(u128::from(sample.journal_bytes_written))
            .ok_or(ResourceSummaryError::Arithmetic)?;
    }
    execution.sort_unstable();
    let amplification = total_journal
        .checked_mul(PPM)
        .ok_or(ResourceSummaryError::Arithmetic)?
        / total_checkpoint;
    let write_amplification_ppm =
        u32::try_from(amplification).map_err(|_| ResourceSummaryError::Arithmetic)?;
    let p50 = nearest_rank(&execution, 50)?;
    let p95 = nearest_rank(&execution, 95)?;
    let p99 = nearest_rank(&execution, 99)?;
    let sample_count =
        u32::try_from(samples.len()).map_err(|_| ResourceSummaryError::Arithmetic)?;
    let samples_digest = digest_samples(samples);
    let limits_met = p95 <= envelope.p95_latency_micros
        && p99 <= envelope.p99_latency_micros
        && maximum_transient <= envelope.transient_allocation_bytes
        && maximum_checkpoint <= envelope.checkpoint_bytes
        && write_amplification_ppm <= envelope.write_amplification_ppm;
    let summary_digest = digest_summary(
        config_digest,
        host_profile_digest,
        sample_count,
        p50,
        p95,
        p99,
        maximum_transient,
        maximum_checkpoint,
        maximum_queue,
        write_amplification_ppm,
        samples_digest,
        limits_met,
    );
    Ok(RuntimeResourceSummaryV1 {
        config_digest,
        host_profile_digest,
        sample_count,
        p50_execution_micros: p50,
        p95_execution_micros: p95,
        p99_execution_micros: p99,
        maximum_transient_allocation_bytes: maximum_transient,
        maximum_checkpoint_bytes: maximum_checkpoint,
        maximum_queue_age_micros: maximum_queue,
        write_amplification_ppm,
        samples_digest,
        summary_digest,
        limits_met,
    })
}

fn nearest_rank(sorted: &[u64], percentile: usize) -> Result<u64, ResourceSummaryError> {
    if sorted.is_empty() || !(1..=100).contains(&percentile) {
        return Err(ResourceSummaryError::SampleCountOutOfRange);
    }
    let rank = sorted
        .len()
        .checked_mul(percentile)
        .and_then(|value| value.checked_add(99))
        .ok_or(ResourceSummaryError::Arithmetic)?
        / 100;
    sorted
        .get(rank.saturating_sub(1))
        .copied()
        .ok_or(ResourceSummaryError::Arithmetic)
}

fn digest_samples(samples: &[RuntimeResourceSampleV1]) -> Digest32 {
    let mut bytes = b"hepta.neuron.runtime-resource-samples.v1".to_vec();
    bytes.extend_from_slice(&(samples.len() as u64).to_be_bytes());
    for sample in samples {
        for value in [
            sample.execution_micros,
            sample.transient_allocation_bytes,
            sample.checkpoint_bytes,
            sample.journal_bytes_written,
            sample.queue_age_micros,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_summary(
    config_digest: Digest32,
    host_profile_digest: Digest32,
    sample_count: u32,
    p50: u64,
    p95: u64,
    p99: u64,
    maximum_transient: u64,
    maximum_checkpoint: u64,
    maximum_queue: u64,
    write_amplification_ppm: u32,
    samples_digest: Digest32,
    limits_met: bool,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.runtime-resource-summary.v1".to_vec();
    for digest in [config_digest, host_profile_digest, samples_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&sample_count.to_be_bytes());
    for value in [
        p50,
        p95,
        p99,
        maximum_transient,
        maximum_checkpoint,
        maximum_queue,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&write_amplification_ppm.to_be_bytes());
    bytes.push(u8::from(limits_met));
    Digest32::of_bytes(&bytes)
}
