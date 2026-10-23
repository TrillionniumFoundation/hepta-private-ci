//! Signature-gated future-window structural comparison, not topology promotion.
//!
//! The external evaluator must attest real matched-compute, no-change,
//! ablation, retention, negative-transfer and host resource observations.
//! This module only judges supplied, independently signed measurements.

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StructuralMutationKindV1 {
    Split,
    Merge,
    Rewire,
}

impl StructuralMutationKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Split => 0,
            Self::Merge => 1,
            Self::Rewire => 2,
        }
    }
}

/// This is immutable experiment design, not an observed outcome.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenStructuralComparisonV1 {
    pub candidate_id: StableId,
    pub predecessor_id: StableId,
    pub no_change_id: StableId,
    pub mutation: StructuralMutationKindV1,
    pub topology_admission_digest: Digest32,
    pub objective_digest: Digest32,
    pub rollback_plan_digest: Digest32,
    pub generation: u64,
    pub frozen_plan_digest: Digest32,
    pub dataset_digest: Digest32,
    pub metric_policy_digest: Digest32,
    pub frozen_at_unix_ms: u64,
    pub future_start_unix_ms: u64,
    pub future_end_unix_ms: u64,
    pub maximum_compute_increase_ppm: u32,
    pub maximum_latency_increase_ppm: u32,
    pub maximum_rss_increase_ppm: u32,
    pub maximum_negative_transfer_ppm: u32,
    pub maximum_retention_loss_ppm: u32,
    pub minimum_ablation_delta_q24: i64,
}

/// Actual observations must come from a host other than the candidate generator.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StructuralComparisonObservationV1 {
    pub candidate_utility_q24: i64,
    pub predecessor_utility_q24: i64,
    pub no_change_utility_q24: i64,
    pub ablated_utility_q24: i64,
    pub candidate_compute_units: u64,
    pub matched_baseline_compute_units: u64,
    pub candidate_latency_p95_us: u64,
    pub baseline_latency_p95_us: u64,
    pub candidate_rss_peak_bytes: u64,
    pub baseline_rss_peak_bytes: u64,
    pub candidate_throughput_q24: u64,
    pub baseline_throughput_q24: u64,
    pub negative_transfer_ppm: u32,
    pub retention_loss_ppm: u32,
    pub recovery_observation_digest: Digest32,
    pub rollback_observation_digest: Digest32,
    pub holdout_observation_digest: Digest32,
    pub rollback_verified: bool,
    pub recovery_verified: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedStructuralComparisonV1 {
    pub generator_plan: SignedLearningEvidenceV1,
    pub evaluator_observation: SignedLearningEvidenceV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StructuralComparisonDispositionV1 {
    EligibleForIndependentStatisticalReview,
    Rejected,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedStructuralComparisonDecisionV1 {
    pub candidate_id: StableId,
    pub disposition: StructuralComparisonDispositionV1,
    pub observation_digest: Digest32,
    pub authenticated_evaluator_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StructuralComparisonErrorV1 {
    InvalidDesign,
    InvalidObservation,
    Authentication(SignedEvidenceError),
}

impl From<SignedEvidenceError> for StructuralComparisonErrorV1 {
    fn from(error: SignedEvidenceError) -> Self {
        Self::Authentication(error)
    }
}

impl std::fmt::Display for StructuralComparisonErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for StructuralComparisonErrorV1 {}

fn validate(
    plan: &FrozenStructuralComparisonV1,
    result: &StructuralComparisonObservationV1,
) -> Result<(), StructuralComparisonErrorV1> {
    if plan.candidate_id == plan.predecessor_id
        || plan.candidate_id == plan.no_change_id
        || plan.predecessor_id == plan.no_change_id
        || plan.topology_admission_digest.is_zero()
        || plan.objective_digest.is_zero()
        || plan.rollback_plan_digest.is_zero()
        || plan.generation == 0
        || plan.frozen_plan_digest.is_zero()
        || plan.dataset_digest.is_zero()
        || plan.metric_policy_digest.is_zero()
        || plan.frozen_at_unix_ms == 0
        || plan.future_start_unix_ms <= plan.frozen_at_unix_ms
        || plan.future_end_unix_ms <= plan.future_start_unix_ms
        || plan.future_end_unix_ms - plan.future_start_unix_ms > 86_400_000 * 30
        || plan.maximum_compute_increase_ppm > 50_000
        || plan.maximum_latency_increase_ppm > 100_000
        || plan.maximum_rss_increase_ppm > 100_000
        || plan.maximum_negative_transfer_ppm > 1_000_000
        || plan.maximum_retention_loss_ppm > 1_000_000
        || plan.minimum_ablation_delta_q24 <= 0
    {
        return Err(StructuralComparisonErrorV1::InvalidDesign);
    }
    if result.candidate_compute_units == 0
        || result.matched_baseline_compute_units == 0
        || result.candidate_latency_p95_us == 0
        || result.baseline_latency_p95_us == 0
        || result.candidate_rss_peak_bytes == 0
        || result.baseline_rss_peak_bytes == 0
        || result.candidate_throughput_q24 == 0
        || result.baseline_throughput_q24 == 0
        || result.negative_transfer_ppm > 1_000_000
        || result.retention_loss_ppm > 1_000_000
        || result.recovery_observation_digest.is_zero()
        || result.rollback_observation_digest.is_zero()
        || result.holdout_observation_digest.is_zero()
    {
        return Err(StructuralComparisonErrorV1::InvalidObservation);
    }
    Ok(())
}

fn within_increase(candidate: u64, baseline: u64, extra_ppm: u32) -> bool {
    u128::from(candidate) * 1_000_000
        <= u128::from(baseline) * (1_000_000 + u128::from(extra_ppm))
}

fn passes(
    plan: &FrozenStructuralComparisonV1,
    result: &StructuralComparisonObservationV1,
) -> bool {
    let minimum_ablation = result
        .ablated_utility_q24
        .checked_add(plan.minimum_ablation_delta_q24);
    result.candidate_utility_q24 > result.predecessor_utility_q24
        && result.candidate_utility_q24 > result.no_change_utility_q24
        && minimum_ablation.is_some_and(|bound| result.candidate_utility_q24 >= bound)
        && within_increase(
            result.candidate_compute_units,
            result.matched_baseline_compute_units,
            plan.maximum_compute_increase_ppm,
        )
        && within_increase(
            result.candidate_latency_p95_us,
            result.baseline_latency_p95_us,
            plan.maximum_latency_increase_ppm,
        )
        && within_increase(
            result.candidate_rss_peak_bytes,
            result.baseline_rss_peak_bytes,
            plan.maximum_rss_increase_ppm,
        )
        && result.candidate_throughput_q24 >= result.baseline_throughput_q24
        && result.negative_transfer_ppm <= plan.maximum_negative_transfer_ppm
        && result.retention_loss_ppm <= plan.maximum_retention_loss_ppm
        && result.rollback_verified
        && result.recovery_verified
}

/// Stable, unambiguous signed data, including frozen policy and every metric.
pub fn structural_comparison_signing_payload_v1(
    plan: &FrozenStructuralComparisonV1,
    result: &StructuralComparisonObservationV1,
) -> Result<Vec<u8>, StructuralComparisonErrorV1> {
    validate(plan, result)?;
    let mut bytes = b"hepta.eval.structural-comparison.v1\0".to_vec();
    for id in [&plan.candidate_id, &plan.predecessor_id, &plan.no_change_id] {
        let data = id.as_str().as_bytes();
        let len = u32::try_from(data.len())
            .map_err(|_| StructuralComparisonErrorV1::InvalidDesign)?;
        bytes.extend_from_slice(&len.to_be_bytes());
        bytes.extend_from_slice(data);
    }
    bytes.push(plan.mutation.tag());
    for d in [
        plan.topology_admission_digest,
        plan.objective_digest,
        plan.rollback_plan_digest,
        plan.frozen_plan_digest,
        plan.dataset_digest,
        plan.metric_policy_digest,
        result.recovery_observation_digest,
        result.rollback_observation_digest,
        result.holdout_observation_digest,
    ] {
        bytes.extend_from_slice(d.as_array());
    }
    for v in [
        plan.generation,
        plan.frozen_at_unix_ms,
        plan.future_start_unix_ms,
        plan.future_end_unix_ms,
        result.candidate_compute_units,
        result.matched_baseline_compute_units,
        result.candidate_latency_p95_us,
        result.baseline_latency_p95_us,
        result.candidate_rss_peak_bytes,
        result.baseline_rss_peak_bytes,
        result.candidate_throughput_q24,
        result.baseline_throughput_q24,
    ] {
        bytes.extend_from_slice(&v.to_be_bytes());
    }
    for v in [
        plan.maximum_compute_increase_ppm,
        plan.maximum_latency_increase_ppm,
        plan.maximum_rss_increase_ppm,
        plan.maximum_negative_transfer_ppm,
        plan.maximum_retention_loss_ppm,
        result.negative_transfer_ppm,
        result.retention_loss_ppm,
    ] {
        bytes.extend_from_slice(&v.to_be_bytes());
    }
    for v in [
        plan.minimum_ablation_delta_q24,
        result.candidate_utility_q24,
        result.predecessor_utility_q24,
        result.no_change_utility_q24,
        result.ablated_utility_q24,
    ] {
        bytes.extend_from_slice(&v.to_be_bytes());
    }
    bytes.push(u8::from(result.rollback_verified));
    bytes.push(u8::from(result.recovery_verified));
    Ok(bytes)
}

/// Only signed, independently separated generator/evaluator roles can produce
/// a deterministic screening result. This is NOT statistical qualification.
/// Confidence-aware held-out signed evaluation, FinalUse, selection and cutover
/// remain external. Never promote solely on this comparator.
pub fn assess_signed_structural_comparison_v1(
    plan: &FrozenStructuralComparisonV1,
    result: &StructuralComparisonObservationV1,
    evidence: &SignedStructuralComparisonV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedStructuralComparisonDecisionV1, StructuralComparisonErrorV1> {
    let signed_payload = structural_comparison_signing_payload_v1(plan, result)?;
    let now_ms = now
        .checked_mul(1000)
        .ok_or(StructuralComparisonErrorV1::InvalidObservation)?;
    let generator_issued_ms = evidence
        .generator_plan
        .issued_at
        .checked_mul(1000)
        .ok_or(StructuralComparisonErrorV1::InvalidObservation)?;
    let evaluator_issued_ms = evidence
        .evaluator_observation
        .issued_at
        .checked_mul(1000)
        .ok_or(StructuralComparisonErrorV1::InvalidObservation)?;
    if verifier.objective_digest() != plan.objective_digest
        || now_ms < plan.future_end_unix_ms
        || generator_issued_ms > plan.frozen_at_unix_ms
        || evaluator_issued_ms < plan.future_end_unix_ms
    {
        return Err(StructuralComparisonErrorV1::InvalidObservation);
    }
    let generator = verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &evidence.generator_plan,
        plan.frozen_plan_digest.as_array(),
        now,
    )?;
    let evaluator = verifier.verify(
        LearningEvidenceRoleV1::Evaluator,
        &evidence.evaluator_observation,
        &signed_payload,
        now,
    )?;
    verify_signed_role_separation(&generator, &evaluator, now)?;
    let mut authenticated = b"hepta.eval.structural-comparison-auth.v1\0".to_vec();
    authenticated.extend_from_slice(verifier.trust_digest().as_array());
    authenticated.extend_from_slice(&evidence.generator_plan.signature);
    authenticated.extend_from_slice(&evidence.evaluator_observation.signature);
    Ok(SignedStructuralComparisonDecisionV1 {
        candidate_id: plan.candidate_id.clone(),
        disposition: if passes(plan, result) {
            StructuralComparisonDispositionV1::EligibleForIndependentStatisticalReview
        } else {
            StructuralComparisonDispositionV1::Rejected
        },
        observation_digest: Digest32::of_bytes(&signed_payload),
        authenticated_evaluator_digest: Digest32::of_bytes(&authenticated),
    })
}

#[cfg(test)]
#[path = "structural_comparison_tests.rs"]
mod tests;
