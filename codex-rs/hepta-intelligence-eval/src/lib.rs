//! Independent deterministic candidate evaluation. Eligibility is not promotion.
#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

mod ope;
mod sequential;
mod temporal_evaluation;
mod temporal_fold;

pub use ope::ClusterAssignment;
pub use ope::ClusterConfidenceError;
pub use ope::ClusterConfidencePlan;
pub use ope::ClusterOpeEstimate;
pub use ope::OpeAction;
pub use ope::OpeError;
pub use ope::OpeEstimate;
pub use ope::OpeInterval;
pub use ope::OpePlan;
pub use ope::OpeRow;
pub use ope::estimate_cluster_intervals;
pub use ope::estimate_ope;
pub use sequential::DepthSupport;
pub use sequential::FiniteHorizonEstimand;
pub use sequential::SequentialError;
pub use sequential::SequentialEstimate;
pub use sequential::SequentialEvidenceGap;
pub use sequential::SequentialPlan;
pub use sequential::TerminalRewardConvention;
pub use sequential::Trajectory;
pub use sequential::TrajectoryAction;
pub use sequential::TrajectoryBoundary;
pub use sequential::TrajectoryClaimScope;
pub use sequential::TrajectoryEstimate;
pub use sequential::TrajectoryStep;
pub use sequential::estimate_sequential;
pub use temporal_evaluation::TemporalEvaluationError;
pub use temporal_evaluation::TemporalEvaluationPlan;
pub use temporal_evaluation::TemporalEvaluationReceipt;
pub use temporal_evaluation::evaluate_temporal_holdout;
pub use temporal_fold::HeldOutPrediction;
pub use temporal_fold::HeldOutTarget;
pub use temporal_fold::OutcomeTrainingSample;
pub use temporal_fold::TemporalFoldError;
pub use temporal_fold::TemporalFoldPlan;
pub use temporal_fold::TemporalFoldReceipt;
pub use temporal_fold::fit_temporal_fold;

const MAX_METRICS: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Direction {
    Maximize,
    Minimize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricComparison {
    pub metric_id: StableId,
    pub direction: Direction,
    pub candidate: FixedQ32,
    pub baseline: FixedQ32,
    pub minimum_delta: FixedQ32,
    pub hard: bool,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluationRequest {
    pub evaluation_id: StableId,
    pub evaluator_id: StableId,
    pub candidate_id: StableId,
    pub candidate_producer_id: StableId,
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub comparisons: Vec<MetricComparison>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Disposition {
    EligibleForFurtherReview,
    Ineligible,
    InsufficientEvidence,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvaluationReceipt {
    pub evaluation_id: StableId,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub disposition: Disposition,
    pub failed_metrics: Vec<StableId>,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    SelfEvaluation,
    EmptyDigest(&'static str),
    MetricLimitExceeded,
    DuplicateMetric(String),
    Arithmetic,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for Error {}

pub fn evaluate(mut request: EvaluationRequest) -> Result<EvaluationReceipt, Error> {
    if request.evaluator_id == request.candidate_producer_id {
        return Err(Error::SelfEvaluation);
    }
    if request.objective_digest.is_zero() {
        return Err(Error::EmptyDigest("objective"));
    }
    if request.comparisons.len() > MAX_METRICS {
        return Err(Error::MetricLimitExceeded);
    }

    request
        .comparisons
        .sort_by(|left, right| left.metric_id.cmp(&right.metric_id));
    let mut seen = BTreeSet::new();
    let mut failed_metrics = Vec::new();
    let mut insufficient = request.comparisons.is_empty();
    for metric in &request.comparisons {
        if !seen.insert(metric.metric_id.clone()) {
            return Err(Error::DuplicateMetric(metric.metric_id.to_string()));
        }
        if metric.support_digest.is_zero() {
            insufficient = true;
            continue;
        }
        let delta = match metric.direction {
            Direction::Maximize => subtract(metric.candidate, metric.baseline)?,
            Direction::Minimize => subtract(metric.baseline, metric.candidate)?,
        };
        if metric.hard && delta.raw() < metric.minimum_delta.raw() {
            failed_metrics.push(metric.metric_id.clone());
        }
    }

    let disposition = if !failed_metrics.is_empty() {
        Disposition::Ineligible
    } else if insufficient {
        Disposition::InsufficientEvidence
    } else {
        Disposition::EligibleForFurtherReview
    };
    let evidence_digest = digest(&request, disposition, &failed_metrics);
    Ok(EvaluationReceipt {
        evaluation_id: request.evaluation_id,
        candidate_id: request.candidate_id,
        baseline_id: request.baseline_id,
        disposition,
        failed_metrics,
        evidence_digest,
    })
}

fn subtract(left: FixedQ32, right: FixedQ32) -> Result<FixedQ32, Error> {
    let raw = i128::from(left.raw()) - i128::from(right.raw());
    Ok(FixedQ32::from_raw(
        i64::try_from(raw).map_err(|_| Error::Arithmetic)?,
    ))
}

fn digest(request: &EvaluationRequest, disposition: Disposition, failed: &[StableId]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.intelligence-eval.v1");
    for id in [
        &request.evaluation_id,
        &request.evaluator_id,
        &request.candidate_id,
        &request.candidate_producer_id,
        &request.baseline_id,
    ] {
        push_id(&mut bytes, id);
    }
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.push(match disposition {
        Disposition::EligibleForFurtherReview => 0,
        Disposition::Ineligible => 1,
        Disposition::InsufficientEvidence => 2,
    });
    for metric in &request.comparisons {
        push_id(&mut bytes, &metric.metric_id);
        bytes.push(match metric.direction {
            Direction::Maximize => 0,
            Direction::Minimize => 1,
        });
        bytes.extend_from_slice(&metric.candidate.raw().to_be_bytes());
        bytes.extend_from_slice(&metric.baseline.raw().to_be_bytes());
        bytes.extend_from_slice(&metric.minimum_delta.raw().to_be_bytes());
        bytes.push(u8::from(metric.hard));
        bytes.extend_from_slice(metric.support_digest.as_array());
    }
    for id in failed {
        push_id(&mut bytes, id);
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
