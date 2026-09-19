//! Independent admission of NDU local solver evidence.
//!
//! This owner belongs to learning.eval. It can classify supplied evidence as
//! accepted/rejected/unavailable for further governed use, but grants no
//! selection, activation, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_ndu::NduSolverTerminationReceipt;
use codex_hepta_ndu::SolveDisposition;
use codex_hepta_ndu::SubjectClass;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

const MAX_ITERATIONS: u32 = 64;
const MAX_SOLVER_RESIDUAL_RAW: i64 = 1_i64 << 12;
const MAX_CONSERVATION_RESIDUAL_RAW: i64 = 1;
const MAX_RESOURCE_RESIDUAL_RAW: i64 = 1;
const MAX_RISK_RESIDUAL_PPM: u32 = 10;
const MAX_BOUNDARY_RESIDUAL_PPM: u32 = 10_000;
const MAX_STANDARDIZED_MARTINGALE_MEAN_PPM: u32 = 20_000;
const SPECTRAL_RADIUS_95_Q32_RAW: i64 =
    (((1_i128 << 32) * 95_i128) / 100_i128) as i64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduMultipleSolutionDispositionV1 {
    Unique,
    PredecessorNearestCertified,
    MultipleSolutionUnresolved,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduConvergenceDecisionV1 {
    Accepted,
    Rejected,
    Unavailable,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceEvaluationV1 {
    pub certificate_id: StableId,
    pub subject_class: SubjectClass,
    pub objective_class_digest: Digest32,
    pub solver_digest: Digest32,
    pub initialization_digest: Digest32,
    pub operating_region_digest: Digest32,
    pub perturbation_evidence_digest: Digest32,
    pub conservation_evidence_digest: Digest32,
    pub support_digest: Digest32,
    pub evaluator_identity: StableId,
    pub candidate_producer_identity: StableId,
    pub termination: NduSolverTerminationReceipt,
    pub spectral_radius_upper_95_q32: FixedQ32,
    pub conservation_residual_q32: FixedQ32,
    pub resource_residual_q32: FixedQ32,
    pub risk_residual_ppm: u32,
    pub boundary_residual_p99_ppm: u32,
    pub standardized_martingale_mean_abs_ppm: u32,
    pub multiple_solution_disposition: NduMultipleSolutionDispositionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConvergenceCertificateV1 {
    pub certificate_id: StableId,
    pub subject_class: SubjectClass,
    pub objective_class_digest: Digest32,
    pub solver_digest: Digest32,
    pub initialization_digest: Digest32,
    pub iterations: u32,
    pub maximum_residual_q32: i64,
    pub spectral_radius_upper_95_q32: i64,
    pub conservation_residual_q32: i64,
    pub multiple_solution_disposition: NduMultipleSolutionDispositionV1,
    pub evaluator_identity: StableId,
    pub decision: NduConvergenceDecisionV1,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduConvergenceError {
    SelfEvaluation,
    MissingDigest(&'static str),
    InvalidSolverEvidence,
    InvalidMetric(&'static str),
}

impl fmt::Display for NduConvergenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduConvergenceError {}

/// Independently classify one complete NDU convergence evidence bundle.
///
/// The acceptance thresholds are the bounded pilot values from the NDU FBSDE
/// specification. Passing them is evidence eligibility only, never artifact
/// selection or runtime activation.
pub fn evaluate_ndu_convergence_v1(
    evaluation: NduConvergenceEvaluationV1,
) -> Result<NduConvergenceCertificateV1, NduConvergenceError> {
    if evaluation.evaluator_identity == evaluation.candidate_producer_identity {
        return Err(NduConvergenceError::SelfEvaluation);
    }
    for (name, digest) in [
        ("objective_class", evaluation.objective_class_digest),
        ("solver", evaluation.solver_digest),
        ("initialization", evaluation.initialization_digest),
        ("operating_region", evaluation.operating_region_digest),
        ("perturbation", evaluation.perturbation_evidence_digest),
        ("conservation", evaluation.conservation_evidence_digest),
        ("support", evaluation.support_digest),
    ] {
        if digest.is_zero() {
            return Err(NduConvergenceError::MissingDigest(name));
        }
    }
    validate_termination(&evaluation.termination)?;
    validate_metrics(&evaluation)?;

    let decision = if evaluation.termination.disposition != SolveDisposition::Converged
        || evaluation.multiple_solution_disposition
            == NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved
    {
        NduConvergenceDecisionV1::Unavailable
    } else if evaluation.termination.maximum_residual_raw > MAX_SOLVER_RESIDUAL_RAW
        || !spectral_radius_below_threshold(evaluation.spectral_radius_upper_95_q32)
        || absolute_raw(evaluation.conservation_residual_q32)?
            > MAX_CONSERVATION_RESIDUAL_RAW as u64
        || absolute_raw(evaluation.resource_residual_q32)? > MAX_RESOURCE_RESIDUAL_RAW as u64
        || evaluation.risk_residual_ppm > MAX_RISK_RESIDUAL_PPM
        || evaluation.boundary_residual_p99_ppm > MAX_BOUNDARY_RESIDUAL_PPM
        || evaluation.standardized_martingale_mean_abs_ppm
            >= MAX_STANDARDIZED_MARTINGALE_MEAN_PPM
    {
        NduConvergenceDecisionV1::Rejected
    } else {
        NduConvergenceDecisionV1::Accepted
    };

    let evidence_digest = digest_evaluation(&evaluation, decision);
    Ok(NduConvergenceCertificateV1 {
        certificate_id: evaluation.certificate_id,
        subject_class: evaluation.subject_class,
        objective_class_digest: evaluation.objective_class_digest,
        solver_digest: evaluation.solver_digest,
        initialization_digest: evaluation.initialization_digest,
        iterations: evaluation.termination.iterations,
        maximum_residual_q32: evaluation.termination.maximum_residual_raw,
        spectral_radius_upper_95_q32: evaluation.spectral_radius_upper_95_q32.raw(),
        conservation_residual_q32: evaluation.conservation_residual_q32.raw(),
        multiple_solution_disposition: evaluation.multiple_solution_disposition,
        evaluator_identity: evaluation.evaluator_identity,
        decision,
        evidence_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_termination(
    termination: &NduSolverTerminationReceipt,
) -> Result<(), NduConvergenceError> {
    if termination.iterations > MAX_ITERATIONS
        || termination.terminal_residual_raw < 0
        || termination.maximum_residual_raw < termination.terminal_residual_raw
        || termination.predecessor_digest.is_zero()
        || termination.terminal_state_digest.is_zero()
    {
        return Err(NduConvergenceError::InvalidSolverEvidence);
    }
    Ok(())
}

fn validate_metrics(
    evaluation: &NduConvergenceEvaluationV1,
) -> Result<(), NduConvergenceError> {
    if evaluation.spectral_radius_upper_95_q32.raw() < 0 {
        return Err(NduConvergenceError::InvalidMetric("spectral_radius"));
    }
    absolute_raw(evaluation.conservation_residual_q32)?;
    absolute_raw(evaluation.resource_residual_q32)?;
    Ok(())
}

fn absolute_raw(value: FixedQ32) -> Result<u64, NduConvergenceError> {
    value
        .raw()
        .checked_abs()
        .and_then(|raw| u64::try_from(raw).ok())
        .ok_or(NduConvergenceError::InvalidMetric("signed_residual"))
}

fn spectral_radius_below_threshold(value: FixedQ32) -> bool {
    value.raw() < SPECTRAL_RADIUS_95_Q32_RAW
}

fn digest_evaluation(
    evaluation: &NduConvergenceEvaluationV1,
    decision: NduConvergenceDecisionV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning.eval.ndu-convergence.v1".to_vec();
    push_id(&mut bytes, &evaluation.certificate_id);
    bytes.push(subject_class_tag(evaluation.subject_class));
    for digest in [
        evaluation.objective_class_digest,
        evaluation.solver_digest,
        evaluation.initialization_digest,
        evaluation.operating_region_digest,
        evaluation.perturbation_evidence_digest,
        evaluation.conservation_evidence_digest,
        evaluation.support_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &evaluation.evaluator_identity);
    push_id(&mut bytes, &evaluation.candidate_producer_identity);
    bytes.push(match evaluation.termination.disposition {
        SolveDisposition::Converged => 0,
        SolveDisposition::IterationBoundReached => 1,
    });
    bytes.extend_from_slice(&evaluation.termination.iterations.to_be_bytes());
    bytes.extend_from_slice(&evaluation.termination.terminal_residual_raw.to_be_bytes());
    bytes.extend_from_slice(&evaluation.termination.maximum_residual_raw.to_be_bytes());
    bytes.extend_from_slice(&evaluation.termination.projection_count.to_be_bytes());
    bytes.extend_from_slice(evaluation.termination.predecessor_digest.as_array());
    bytes.extend_from_slice(evaluation.termination.terminal_state_digest.as_array());
    bytes.extend_from_slice(&evaluation.spectral_radius_upper_95_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&evaluation.conservation_residual_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&evaluation.resource_residual_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&evaluation.risk_residual_ppm.to_be_bytes());
    bytes.extend_from_slice(&evaluation.boundary_residual_p99_ppm.to_be_bytes());
    bytes.extend_from_slice(
        &evaluation
            .standardized_martingale_mean_abs_ppm
            .to_be_bytes(),
    );
    bytes.push(match evaluation.multiple_solution_disposition {
        NduMultipleSolutionDispositionV1::Unique => 0,
        NduMultipleSolutionDispositionV1::PredecessorNearestCertified => 1,
        NduMultipleSolutionDispositionV1::MultipleSolutionUnresolved => 2,
    });
    bytes.push(match decision {
        NduConvergenceDecisionV1::Accepted => 0,
        NduConvergenceDecisionV1::Rejected => 1,
        NduConvergenceDecisionV1::Unavailable => 2,
    });
    Digest32::of_bytes(&bytes)
}

const fn subject_class_tag(value: SubjectClass) -> u8 {
    match value {
        SubjectClass::System => 0,
        SubjectClass::Domain => 1,
        SubjectClass::Agent => 2,
        SubjectClass::Episode => 3,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "ndu_convergence_tests.rs"]
mod tests;
