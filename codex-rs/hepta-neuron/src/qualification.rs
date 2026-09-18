//! Executable qualification helpers for neuron.runtime.
//!
//! Resource summaries aggregate caller-observed measurements; they do not
//! manufacture timing data. Longitudinal bindings only bind independently
//! produced evidence digests and never self-certify efficacy.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::NeuronResourceReceiptV1;
use crate::SparseAblationV1;
use crate::SparseConfig;
use crate::SparseError;
use crate::SparseTick;
use crate::sparse_tick_ablated;

const MAX_RESOURCE_SAMPLES: usize = 100_000;
const MAX_ABLATION_TICKS: usize = 4096;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceSummaryV1 {
    pub sample_count: u32,
    pub p95_execution_micros: u64,
    pub p99_execution_micros: u64,
    pub maximum_transient_allocation_bytes: u64,
    pub maximum_checkpoint_bytes: u64,
    pub maximum_saturation_count: u32,
    pub maximum_queue_age_micros: u64,
    pub summary_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AblationFixtureResultV1 {
    pub ablation: SparseAblationV1,
    pub final_checkpoint_digest: Digest32,
    pub mean_prediction_error_q24: i64,
    pub mean_active_fraction_ppm: u32,
    pub final_eligibility_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AblationReceiptV1 {
    pub fixture_digest: Digest32,
    pub results: Vec<AblationFixtureResultV1>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LongitudinalEvidenceBindingV1 {
    pub future_window_digest: Digest32,
    pub retention_digest: Digest32,
    pub unlearning_non_resurrection_digest: Digest32,
    pub evaluator_digest: Digest32,
    pub binding_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualificationError {
    EmptySamples,
    SampleLimit,
    EmptyFixture,
    FixtureLimit,
    InvalidEvidence(&'static str),
    Sparse(SparseError),
    Arithmetic,
}

impl fmt::Display for QualificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for QualificationError {}

impl From<SparseError> for QualificationError {
    fn from(value: SparseError) -> Self {
        Self::Sparse(value)
    }
}

pub fn summarize_resource_samples(
    samples: &[NeuronResourceReceiptV1],
) -> Result<ResourceSummaryV1, QualificationError> {
    if samples.is_empty() {
        return Err(QualificationError::EmptySamples);
    }
    if samples.len() > MAX_RESOURCE_SAMPLES {
        return Err(QualificationError::SampleLimit);
    }
    let mut execution: Vec<u64> = samples
        .iter()
        .map(|sample| sample.execution_micros)
        .collect();
    execution.sort_unstable();
    let p95 = percentile(&execution, 95)?;
    let p99 = percentile(&execution, 99)?;
    let maximum_transient_allocation_bytes = samples
        .iter()
        .map(|sample| sample.transient_allocation_bytes)
        .max()
        .unwrap_or(0);
    let maximum_checkpoint_bytes = samples
        .iter()
        .map(|sample| sample.checkpoint_bytes)
        .max()
        .unwrap_or(0);
    let maximum_saturation_count = samples
        .iter()
        .map(|sample| sample.saturation_count)
        .max()
        .unwrap_or(0);
    let maximum_queue_age_micros = samples
        .iter()
        .map(|sample| sample.queue_age_micros)
        .max()
        .unwrap_or(0);
    let sample_count = u32::try_from(samples.len()).map_err(|_| QualificationError::Arithmetic)?;
    let mut bytes = b"hepta.neuron.resource-summary.v1".to_vec();
    bytes.extend_from_slice(&sample_count.to_be_bytes());
    for value in [
        p95,
        p99,
        maximum_transient_allocation_bytes,
        maximum_checkpoint_bytes,
        u64::from(maximum_saturation_count),
        maximum_queue_age_micros,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(ResourceSummaryV1 {
        sample_count,
        p95_execution_micros: p95,
        p99_execution_micros: p99,
        maximum_transient_allocation_bytes,
        maximum_checkpoint_bytes,
        maximum_saturation_count,
        maximum_queue_age_micros,
        summary_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn run_ablation_fixture(
    config: &SparseConfig,
    ticks: &[SparseTick],
) -> Result<AblationReceiptV1, QualificationError> {
    if ticks.is_empty() {
        return Err(QualificationError::EmptyFixture);
    }
    if ticks.len() > MAX_ABLATION_TICKS {
        return Err(QualificationError::FixtureLimit);
    }
    let fixture_digest = digest_fixture(config, ticks)?;
    let profiles = [
        SparseAblationV1::NONE,
        SparseAblationV1 {
            no_temporal_state: true,
            ..SparseAblationV1::NONE
        },
        SparseAblationV1 {
            no_inhibition: true,
            ..SparseAblationV1::NONE
        },
        SparseAblationV1 {
            no_homeostasis: true,
            ..SparseAblationV1::NONE
        },
        SparseAblationV1 {
            no_eligibility: true,
            ..SparseAblationV1::NONE
        },
    ];
    let mut results = Vec::with_capacity(profiles.len());
    for ablation in profiles {
        let mut state = None;
        let mut prediction_error_sum = 0_i128;
        let mut active_sum = 0_u128;
        for tick in ticks {
            let (next, receipt) = sparse_tick_ablated(config, tick, state.as_ref(), ablation)?;
            prediction_error_sum = prediction_error_sum
                .checked_add(i128::from(receipt.prediction_error_q24))
                .ok_or(QualificationError::Arithmetic)?;
            active_sum = active_sum
                .checked_add(u128::from(receipt.active_fraction_ppm))
                .ok_or(QualificationError::Arithmetic)?;
            state = Some(next);
        }
        let count_i128 = i128::try_from(ticks.len()).map_err(|_| QualificationError::Arithmetic)?;
        let count_u128 = u128::try_from(ticks.len()).map_err(|_| QualificationError::Arithmetic)?;
        let state = state.ok_or(QualificationError::EmptyFixture)?;
        let mean_prediction_error_q24 = i64::try_from(prediction_error_sum / count_i128)
            .map_err(|_| QualificationError::Arithmetic)?;
        let mean_active_fraction_ppm =
            u32::try_from(active_sum / count_u128).map_err(|_| QualificationError::Arithmetic)?;
        let final_eligibility_digest = digest_q24(
            b"hepta.neuron.ablation-eligibility.v1",
            state.eligibility_q24(),
        )?;
        results.push(AblationFixtureResultV1 {
            ablation,
            final_checkpoint_digest: state.digest(),
            mean_prediction_error_q24,
            mean_active_fraction_ppm,
            final_eligibility_digest,
        });
    }
    let receipt_digest = digest_ablation_receipt(fixture_digest, &results)?;
    Ok(AblationReceiptV1 {
        fixture_digest,
        results,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

impl LongitudinalEvidenceBindingV1 {
    pub fn new(
        future_window_digest: Digest32,
        retention_digest: Digest32,
        unlearning_non_resurrection_digest: Digest32,
        evaluator_digest: Digest32,
    ) -> Result<Self, QualificationError> {
        for (name, digest) in [
            ("future window", future_window_digest),
            ("retention", retention_digest),
            ("unlearning", unlearning_non_resurrection_digest),
            ("evaluator", evaluator_digest),
        ] {
            if digest.is_zero() {
                return Err(QualificationError::InvalidEvidence(name));
            }
        }
        let mut bytes = b"hepta.neuron.longitudinal-evidence-binding.v1".to_vec();
        for digest in [
            future_window_digest,
            retention_digest,
            unlearning_non_resurrection_digest,
            evaluator_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(Self {
            future_window_digest,
            retention_digest,
            unlearning_non_resurrection_digest,
            evaluator_digest,
            binding_digest: Digest32::of_bytes(&bytes),
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

fn percentile(sorted: &[u64], percentile: usize) -> Result<u64, QualificationError> {
    let numerator = sorted
        .len()
        .checked_mul(percentile)
        .and_then(|value| value.checked_add(99))
        .ok_or(QualificationError::Arithmetic)?;
    let rank = numerator / 100;
    let index = rank.saturating_sub(1).min(sorted.len() - 1);
    Ok(sorted[index])
}

fn digest_fixture(
    config: &SparseConfig,
    ticks: &[SparseTick],
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.neuron.ablation-fixture.v1".to_vec();
    bytes.extend_from_slice(config.digest()?.as_array());
    let length = u32::try_from(ticks.len()).map_err(|_| QualificationError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for tick in ticks {
        bytes.extend_from_slice(&tick.sequence.to_be_bytes());
        bytes.extend_from_slice(&tick.monotonic_micros.to_be_bytes());
        for digest in [
            tick.scope_digest,
            tick.objective_digest,
            tick.ndu_digest,
            tick.body_digest,
            tick.input_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        append_q24(&mut bytes, &tick.drive_q24)?;
        append_q24(&mut bytes, &tick.prediction_q24)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_ablation_receipt(
    fixture_digest: Digest32,
    results: &[AblationFixtureResultV1],
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.neuron.ablation-receipt.v1".to_vec();
    bytes.extend_from_slice(fixture_digest.as_array());
    let length = u32::try_from(results.len()).map_err(|_| QualificationError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for result in results {
        bytes.push(ablation_code(result.ablation));
        bytes.extend_from_slice(result.final_checkpoint_digest.as_array());
        bytes.extend_from_slice(&result.mean_prediction_error_q24.to_be_bytes());
        bytes.extend_from_slice(&result.mean_active_fraction_ppm.to_be_bytes());
        bytes.extend_from_slice(result.final_eligibility_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn ablation_code(value: SparseAblationV1) -> u8 {
    u8::from(value.no_temporal_state)
        | (u8::from(value.no_inhibition) << 1)
        | (u8::from(value.no_homeostasis) << 2)
        | (u8::from(value.no_eligibility) << 3)
}

fn digest_q24(domain: &[u8], values: &[i64]) -> Result<Digest32, QualificationError> {
    let mut bytes = domain.to_vec();
    append_q24(&mut bytes, values)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn append_q24(bytes: &mut Vec<u8>, values: &[i64]) -> Result<(), QualificationError> {
    let length = u32::try_from(values.len()).map_err(|_| QualificationError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(())
}

#[cfg(test)]
#[path = "qualification_tests.rs"]
mod tests;
