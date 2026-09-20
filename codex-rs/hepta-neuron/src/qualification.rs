//! Qualification helpers over observed runtime receipts and preregistered
//! mechanism ablations.
//!
//! These helpers summarize supplied measurements and deterministic lesion inputs.
//! They do not prove target-host representativeness, future-time efficacy,
//! independent evaluation or release readiness.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::EligibilityTraceSampleV1;
use crate::NeuronResourceEnvelopeV1;
use crate::NeuronResourceReceiptV1;
use crate::ParameterGroupMapV1;
use crate::SparseConfig;

const MAX_RESOURCE_SAMPLES: usize = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronResourceSampleV1 {
    pub host_profile_digest: Digest32,
    pub exact_candidate_digest: Digest32,
    pub observed_at_micros: u64,
    pub receipt: NeuronResourceReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronResourceSummaryV1 {
    pub host_profile_digest: Digest32,
    pub exact_candidate_digest: Digest32,
    pub sample_count: u64,
    pub p95_execution_micros: u64,
    pub p99_execution_micros: u64,
    pub maximum_transient_allocation_bytes: u64,
    pub maximum_checkpoint_bytes: u64,
    pub maximum_write_amplification_ppm: u32,
    pub pilot_ceiling_passed_for_supplied_samples: bool,
    pub sample_set_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum NeuronAblationProfileV1 {
    FullMechanism,
    NoInhibition,
    NoHomeostasis,
    NoEligibility,
    NoReplay,
    ShuffledModulator,
    StatelessTemporal,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualificationError {
    SampleCountOutOfRange,
    EmptyDigest(&'static str),
    MixedHostProfile,
    MixedCandidate,
    InvalidObservationTime,
    Arithmetic,
    ShuffledModulatorRequiresTwoGroups,
}

impl fmt::Display for QualificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for QualificationError {}

pub fn summarize_resource_samples(
    samples: &[NeuronResourceSampleV1],
    envelope: &NeuronResourceEnvelopeV1,
) -> Result<NeuronResourceSummaryV1, QualificationError> {
    if !(1..=MAX_RESOURCE_SAMPLES).contains(&samples.len()) {
        return Err(QualificationError::SampleCountOutOfRange);
    }
    let host = samples[0].host_profile_digest;
    let candidate = samples[0].exact_candidate_digest;
    if host.is_zero() {
        return Err(QualificationError::EmptyDigest("host profile"));
    }
    if candidate.is_zero() {
        return Err(QualificationError::EmptyDigest("exact candidate"));
    }
    if samples
        .iter()
        .any(|sample| sample.host_profile_digest != host)
    {
        return Err(QualificationError::MixedHostProfile);
    }
    if samples
        .iter()
        .any(|sample| sample.exact_candidate_digest != candidate)
    {
        return Err(QualificationError::MixedCandidate);
    }
    if samples.iter().any(|sample| sample.observed_at_micros == 0) {
        return Err(QualificationError::InvalidObservationTime);
    }

    let mut execution = samples
        .iter()
        .map(|sample| sample.receipt.execution_micros)
        .collect::<Vec<_>>();
    execution.sort_unstable();
    let p95 = nearest_rank(&execution, 95)?;
    let p99 = nearest_rank(&execution, 99)?;
    let maximum_transient_allocation_bytes = samples
        .iter()
        .map(|sample| sample.receipt.transient_allocation_bytes)
        .max()
        .unwrap_or(0);
    let maximum_checkpoint_bytes = samples
        .iter()
        .map(|sample| sample.receipt.checkpoint_bytes)
        .max()
        .unwrap_or(0);
    let maximum_write_amplification_ppm = samples
        .iter()
        .map(|sample| sample.receipt.write_amplification_ppm)
        .max()
        .unwrap_or(0);
    let passed = p95 <= envelope.p95_latency_micros
        && p99 <= envelope.p99_latency_micros
        && maximum_transient_allocation_bytes <= envelope.transient_allocation_bytes
        && maximum_checkpoint_bytes <= envelope.checkpoint_bytes
        && maximum_write_amplification_ppm <= envelope.write_amplification_ppm;

    let mut canonical = samples.to_vec();
    canonical.sort_by(|left, right| {
        left.observed_at_micros
            .cmp(&right.observed_at_micros)
            .then_with(|| {
                left.receipt
                    .execution_micros
                    .cmp(&right.receipt.execution_micros)
            })
    });
    let mut bytes = b"hepta.neuron.resource-samples.v1".to_vec();
    bytes.extend_from_slice(host.as_array());
    bytes.extend_from_slice(candidate.as_array());
    for sample in &canonical {
        bytes.extend_from_slice(&sample.observed_at_micros.to_be_bytes());
        bytes.extend_from_slice(&sample.receipt.execution_micros.to_be_bytes());
        bytes.extend_from_slice(&sample.receipt.transient_allocation_bytes.to_be_bytes());
        bytes.extend_from_slice(&sample.receipt.checkpoint_bytes.to_be_bytes());
        bytes.extend_from_slice(&sample.receipt.journal_bytes_written.to_be_bytes());
        bytes.extend_from_slice(&sample.receipt.write_amplification_ppm.to_be_bytes());
        bytes.extend_from_slice(&sample.receipt.saturation_count.to_be_bytes());
        bytes.extend_from_slice(&sample.receipt.queue_age_micros.to_be_bytes());
    }
    Ok(NeuronResourceSummaryV1 {
        host_profile_digest: host,
        exact_candidate_digest: candidate,
        sample_count: u64::try_from(samples.len()).map_err(|_| QualificationError::Arithmetic)?,
        p95_execution_micros: p95,
        p99_execution_micros: p99,
        maximum_transient_allocation_bytes,
        maximum_checkpoint_bytes,
        maximum_write_amplification_ppm,
        pilot_ceiling_passed_for_supplied_samples: passed,
        sample_set_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn ablate_sparse_config(
    config: &SparseConfig,
    profile: NeuronAblationProfileV1,
) -> SparseConfig {
    let mut value = config.clone();
    match profile {
        NeuronAblationProfileV1::NoInhibition => {
            value.inhibition_gain_q24 = 0;
            value.inhibition.clear();
        }
        NeuronAblationProfileV1::NoHomeostasis => {
            value.threshold_rate_q24 = 0;
        }
        NeuronAblationProfileV1::StatelessTemporal => {
            value.temporal_decay_q24 = 0;
        }
        NeuronAblationProfileV1::FullMechanism
        | NeuronAblationProfileV1::NoEligibility
        | NeuronAblationProfileV1::NoReplay
        | NeuronAblationProfileV1::ShuffledModulator => {}
    }
    value
}

pub fn ablate_eligibility_history(
    history: &[EligibilityTraceSampleV1],
    profile: NeuronAblationProfileV1,
) -> Vec<EligibilityTraceSampleV1> {
    let mut result = history.to_vec();
    if profile == NeuronAblationProfileV1::NoEligibility {
        for sample in &mut result {
            sample.eligibility_q24.fill(0);
        }
    }
    result
}

pub fn ablate_parameter_groups(
    groups: &[ParameterGroupMapV1],
    profile: NeuronAblationProfileV1,
) -> Result<Vec<ParameterGroupMapV1>, QualificationError> {
    let mut result = groups.to_vec();
    if profile != NeuronAblationProfileV1::ShuffledModulator {
        return Ok(result);
    }
    if result.len() < 2 {
        return Err(QualificationError::ShuffledModulatorRequiresTwoGroups);
    }
    result.sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let rows = result
        .iter()
        .map(|group| group.modulator_projection_q24.clone())
        .collect::<Vec<_>>();
    for (index, group) in result.iter_mut().enumerate() {
        group.modulator_projection_q24 = rows[(index + 1) % rows.len()].clone();
    }
    Ok(result)
}

pub const fn requires_external_replay_ablation(profile: NeuronAblationProfileV1) -> bool {
    matches!(profile, NeuronAblationProfileV1::NoReplay)
}

fn nearest_rank(sorted: &[u64], percentile: usize) -> Result<u64, QualificationError> {
    let numerator = sorted
        .len()
        .checked_mul(percentile)
        .and_then(|value| value.checked_add(99))
        .ok_or(QualificationError::Arithmetic)?;
    let rank = numerator / 100;
    sorted
        .get(rank.saturating_sub(1))
        .copied()
        .ok_or(QualificationError::Arithmetic)
}

#[cfg(test)]
#[path = "qualification_tests.rs"]
mod tests;
