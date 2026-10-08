//! Governed, proposal-only planning for decision-cell topology changes.
//!
//! `CellSplitProposalSignalV1` is an input observation.  This module expands
//! one signal into a complete, deterministic `CellSplitV1` candidate set.  It
//! does not select a candidate or perform acceptance, activation, promotion,
//! release, migration, or rollback.  Those actions remain owned by separate
//! independently authorized boundaries.

mod cell_split_codec;

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use cell_split_codec::candidate_id;
use cell_split_codec::digest_plan;
use cell_split_codec::digest_signal;

const MAX_SIGNAL_BYTES: usize = 64;
const MAX_CELL_ID_BYTES: usize = 128;
const MAX_CANDIDATES: usize = 2;
const PPM_DENOMINATOR: u32 = 1_000_000;

/// Structural operation proposed by a cell-plasticity signal.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CellSplitOperationV1 {
    Add,
    Split,
    Merge,
    Rewire,
    Retire,
}

/// Resource ceilings attached to a candidate plan.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitBudgetV1 {
    pub compute_micros: u64,
    pub memory_bytes: u64,
    pub storage_bytes: u64,
    pub network_bytes: u64,
}

/// Risk declaration and the independently checked ceiling for the plan.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitRiskV1 {
    pub risk_ppm: u32,
    pub maximum_risk_ppm: u32,
    pub risk_evidence_digest: Digest32,
}

/// A concrete, reversible predecessor and procedure binding.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitRollbackV1 {
    pub predecessor_digest: Digest32,
    pub procedure_digest: Digest32,
    pub timeout_micros: u64,
}

/// Bounded canary cohort and exposure window.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitCanaryV1 {
    pub cohort_digest: Digest32,
    pub maximum_exposure_ppm: u32,
    pub duration_micros: u64,
}

/// A quarantine rule that is evaluated before any external activation gate.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitQuarantineV1 {
    pub trigger_digest: Digest32,
    pub duration_micros: u64,
}

/// Independent holdout cohort and minimum observation requirement.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitHoldoutV1 {
    pub cohort_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub minimum_observations: u64,
}

/// Safety controls that must be complete before a plan is emitted.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellSplitGuardrailsV1 {
    pub canary: CellSplitCanaryV1,
    pub quarantine: CellSplitQuarantineV1,
    pub holdout: CellSplitHoldoutV1,
}

/// An observation from the learning/evaluation boundary.
///
/// The signal is intentionally not a plan.  It contains no actor selection or
/// acceptance decision and cannot carry runtime authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitProposalSignalV1 {
    pub signal_id: StableId,
    pub cell_id: StableId,
    pub operation: CellSplitOperationV1,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub predecessor_digest: Option<Digest32>,
    pub candidate_digest: Option<Digest32>,
    pub evidence_digest: Digest32,
    pub budget: CellSplitBudgetV1,
    pub risk: CellSplitRiskV1,
    pub rollback: CellSplitRollbackV1,
    pub guardrails: CellSplitGuardrailsV1,
}

/// Inputs to the governed planner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitPlannerRequestV1 {
    pub plan_id: StableId,
    pub generator_id: StableId,
    pub evaluator_id: StableId,
    pub reviewer_id: StableId,
    pub operator_id: StableId,
    pub current_generation: Generation,
    /// `None` is an explicit missing-signal input and is rejected fail-closed.
    pub signal: Option<CellSplitProposalSignalV1>,
    /// A generator may enumerate candidates but may never submit a selection.
    pub generator_selected_candidate_id: Option<StableId>,
    /// Untrusted ingress posture.  Only `DENY_ALL` can be admitted.
    pub authority: AuthorityPosture,
}

impl CellSplitPlannerRequestV1 {
    /// Construct a request with no generator-side selection or authority.
    #[must_use]
    pub fn new(
        plan_id: StableId,
        generator_id: StableId,
        evaluator_id: StableId,
        reviewer_id: StableId,
        operator_id: StableId,
        current_generation: Generation,
        signal: Option<CellSplitProposalSignalV1>,
    ) -> Self {
        Self {
            plan_id,
            generator_id,
            evaluator_id,
            reviewer_id,
            operator_id,
            current_generation,
            signal,
            generator_selected_candidate_id: None,
            authority: AuthorityPosture::DENY_ALL,
        }
    }
}

/// Candidate kind.  Both candidates are emitted; no candidate is selected.
#[derive(Clone, Copy, Debug, Eq, PartialOrd, Ord, PartialEq)]
pub enum CellSplitCandidateKindV1 {
    NoChange,
    Change,
}

/// One member of the complete, deterministic candidate set.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitCandidateV1 {
    pub candidate_id: StableId,
    pub kind: CellSplitCandidateKindV1,
    pub operation: Option<CellSplitOperationV1>,
    pub cell_id: StableId,
    pub evidence_digest: Digest32,
}

/// Complete proposal-only cell plan.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitV1 {
    pub plan_id: StableId,
    pub generator_id: StableId,
    pub evaluator_id: StableId,
    pub reviewer_id: StableId,
    pub operator_id: StableId,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub signal_id: StableId,
    pub signal_digest: Digest32,
    pub predecessor_digest: Option<Digest32>,
    pub candidate_digest: Option<Digest32>,
    pub budget: CellSplitBudgetV1,
    pub risk: CellSplitRiskV1,
    pub rollback: CellSplitRollbackV1,
    pub guardrails: CellSplitGuardrailsV1,
    pub candidates: Vec<CellSplitCandidateV1>,
    pub plan_digest: Digest32,
    pub status: CellSplitPlanStatusV1,
    pub authority: AuthorityPosture,
}

impl CellSplitV1 {
    #[must_use]
    pub fn no_change_candidate(&self) -> Option<&CellSplitCandidateV1> {
        self.candidates
            .iter()
            .find(|candidate| candidate.kind == CellSplitCandidateKindV1::NoChange)
    }

    #[must_use]
    pub fn change_candidate(&self) -> Option<&CellSplitCandidateV1> {
        self.candidates
            .iter()
            .find(|candidate| candidate.kind == CellSplitCandidateKindV1::Change)
    }
}

/// A generated plan is waiting for independent review and operator acceptance.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellSplitPlanStatusV1 {
    RequiresIndependentReview,
}

/// Fail-closed validation failures.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitPlannerErrorV1 {
    MissingSignal,
    MissingEvidence(&'static str),
    InvalidIdentity(&'static str),
    IndependentIdentityRequired,
    StaleGeneration,
    GenerationNotExactSuccessor,
    UnsupportedOperation,
    InvalidLineage,
    InvalidBudget,
    InvalidRisk,
    MissingRollback,
    MissingHoldout,
    InvalidCanary,
    InvalidQuarantine,
    GeneratorSelectionForbidden,
    AuthorityGranted,
    CandidateSetMismatch,
    DigestMismatch,
    Arithmetic,
}

impl fmt::Display for CellSplitPlannerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellSplitPlannerErrorV1 {}

/// Expand one signal into a complete, deterministic and unselected plan.
pub fn plan_cell_split_v1(
    request: CellSplitPlannerRequestV1,
) -> Result<CellSplitV1, CellSplitPlannerErrorV1> {
    validate_request(&request)?;
    let plan = build_unverified_plan(&request)?;
    verify_cell_split_v1(&plan)?;
    Ok(plan)
}

fn build_unverified_plan(
    request: &CellSplitPlannerRequestV1,
) -> Result<CellSplitV1, CellSplitPlannerErrorV1> {
    let signal = request
        .signal
        .as_ref()
        .ok_or(CellSplitPlannerErrorV1::MissingSignal)?;
    let no_change_id = candidate_id(
        b"no-change",
        &request.plan_id,
        &signal.signal_id,
        signal.candidate_generation,
        None,
    )?;
    let change_id = candidate_id(
        b"change",
        &request.plan_id,
        &signal.signal_id,
        signal.candidate_generation,
        Some(signal.operation),
    )?;
    let mut candidates = vec![
        CellSplitCandidateV1 {
            candidate_id: no_change_id,
            kind: CellSplitCandidateKindV1::NoChange,
            operation: None,
            cell_id: signal.cell_id.clone(),
            evidence_digest: signal.evidence_digest,
        },
        CellSplitCandidateV1 {
            candidate_id: change_id,
            kind: CellSplitCandidateKindV1::Change,
            operation: Some(signal.operation),
            cell_id: signal.cell_id.clone(),
            evidence_digest: signal.evidence_digest,
        },
    ];
    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));

    let mut plan = CellSplitV1 {
        plan_id: request.plan_id.clone(),
        generator_id: request.generator_id.clone(),
        evaluator_id: request.evaluator_id.clone(),
        reviewer_id: request.reviewer_id.clone(),
        operator_id: request.operator_id.clone(),
        baseline_generation: signal.baseline_generation,
        candidate_generation: signal.candidate_generation,
        signal_id: signal.signal_id.clone(),
        signal_digest: digest_signal(signal)?,
        predecessor_digest: signal.predecessor_digest,
        candidate_digest: signal.candidate_digest,
        budget: signal.budget,
        risk: signal.risk,
        rollback: signal.rollback,
        guardrails: signal.guardrails,
        candidates,
        plan_digest: Digest32::ZERO,
        status: CellSplitPlanStatusV1::RequiresIndependentReview,
        authority: AuthorityPosture::DENY_ALL,
    };
    plan.plan_digest = digest_plan(&plan)?;
    Ok(plan)
}

/// Compatibility name for callers that describe planning as building.
pub fn build_cell_split_plan_v1(
    request: CellSplitPlannerRequestV1,
) -> Result<CellSplitV1, CellSplitPlannerErrorV1> {
    plan_cell_split_v1(request)
}

/// Validate a generated plan without changing it or granting authority.
pub fn verify_cell_split_v1(plan: &CellSplitV1) -> Result<(), CellSplitPlannerErrorV1> {
    if plan.authority.grants_any() {
        return Err(CellSplitPlannerErrorV1::AuthorityGranted);
    }
    if plan.generator_id == plan.evaluator_id
        || plan.generator_id == plan.reviewer_id
        || plan.generator_id == plan.operator_id
        || plan.evaluator_id == plan.reviewer_id
        || plan.evaluator_id == plan.operator_id
        || plan.reviewer_id == plan.operator_id
    {
        return Err(CellSplitPlannerErrorV1::IndependentIdentityRequired);
    }
    let signal = CellSplitProposalSignalV1 {
        signal_id: plan.signal_id.clone(),
        cell_id: plan
            .change_candidate()
            .ok_or(CellSplitPlannerErrorV1::CandidateSetMismatch)?
            .cell_id
            .clone(),
        operation: plan
            .change_candidate()
            .and_then(|candidate| candidate.operation)
            .ok_or(CellSplitPlannerErrorV1::CandidateSetMismatch)?,
        baseline_generation: plan.baseline_generation,
        candidate_generation: plan.candidate_generation,
        predecessor_digest: plan.predecessor_digest,
        candidate_digest: plan.candidate_digest,
        evidence_digest: plan
            .change_candidate()
            .ok_or(CellSplitPlannerErrorV1::CandidateSetMismatch)?
            .evidence_digest,
        budget: plan.budget,
        risk: plan.risk,
        rollback: plan.rollback,
        guardrails: plan.guardrails,
    };
    validate_signal(&signal, plan.baseline_generation)?;
    if plan.candidates.len() != MAX_CANDIDATES {
        return Err(CellSplitPlannerErrorV1::CandidateSetMismatch);
    }
    let mut kinds = BTreeSet::new();
    for candidate in &plan.candidates {
        if !kinds.insert(candidate.kind)
            || candidate.cell_id != signal.cell_id
            || candidate.evidence_digest != signal.evidence_digest
        {
            return Err(CellSplitPlannerErrorV1::CandidateSetMismatch);
        }
        match (candidate.kind, candidate.operation) {
            (CellSplitCandidateKindV1::NoChange, None) => {}
            (CellSplitCandidateKindV1::Change, Some(operation)) if operation == signal.operation => {}
            _ => return Err(CellSplitPlannerErrorV1::CandidateSetMismatch),
        }
    }
    if plan.candidates.windows(2).any(|pair| pair[0].candidate_id >= pair[1].candidate_id) {
        return Err(CellSplitPlannerErrorV1::CandidateSetMismatch);
    }
    let expected = build_unverified_plan(&CellSplitPlannerRequestV1 {
        plan_id: plan.plan_id.clone(),
        generator_id: plan.generator_id.clone(),
        evaluator_id: plan.evaluator_id.clone(),
        reviewer_id: plan.reviewer_id.clone(),
        operator_id: plan.operator_id.clone(),
        current_generation: plan.baseline_generation,
        signal: Some(signal),
        generator_selected_candidate_id: None,
        authority: AuthorityPosture::DENY_ALL,
    })?;
    if expected.candidates != plan.candidates
        || expected.signal_id != plan.signal_id
        || expected.signal_digest != plan.signal_digest
        || expected.plan_digest != plan.plan_digest
        || plan.status != CellSplitPlanStatusV1::RequiresIndependentReview
    {
        return Err(CellSplitPlannerErrorV1::DigestMismatch);
    }
    Ok(())
}

/// Bytes for an external generator authentication envelope.
#[must_use]
pub fn cell_split_generator_signing_payload_v1(plan: &CellSplitV1) -> Vec<u8> {
    let mut bytes = b"hepta.plasticity.cell-split.generator.v1\0".to_vec();
    bytes.extend_from_slice(plan.plan_digest.as_array());
    bytes
}

fn validate_request(
    request: &CellSplitPlannerRequestV1,
) -> Result<(), CellSplitPlannerErrorV1> {
    if request.plan_id.as_str().len() > MAX_CELL_ID_BYTES {
        return Err(CellSplitPlannerErrorV1::InvalidIdentity("plan"));
    }
    if request.generator_selected_candidate_id.is_some() {
        return Err(CellSplitPlannerErrorV1::GeneratorSelectionForbidden);
    }
    if request.authority.grants_any() {
        return Err(CellSplitPlannerErrorV1::AuthorityGranted);
    }
    if request.generator_id == request.evaluator_id
        || request.generator_id == request.reviewer_id
        || request.generator_id == request.operator_id
        || request.evaluator_id == request.reviewer_id
        || request.evaluator_id == request.operator_id
        || request.reviewer_id == request.operator_id
    {
        return Err(CellSplitPlannerErrorV1::IndependentIdentityRequired);
    }
    let signal = request
        .signal
        .as_ref()
        .ok_or(CellSplitPlannerErrorV1::MissingSignal)?;
    validate_signal(signal, request.current_generation)
}

fn validate_signal(
    signal: &CellSplitProposalSignalV1,
    current_generation: Generation,
) -> Result<(), CellSplitPlannerErrorV1> {
    if signal.signal_id.as_str().len() > MAX_SIGNAL_BYTES
        || signal.cell_id.as_str().len() > MAX_CELL_ID_BYTES
    {
        return Err(CellSplitPlannerErrorV1::InvalidIdentity("signal"));
    }
    if signal.baseline_generation != current_generation {
        return Err(CellSplitPlannerErrorV1::StaleGeneration);
    }
    if signal.baseline_generation.next() != Ok(signal.candidate_generation) {
        return Err(CellSplitPlannerErrorV1::GenerationNotExactSuccessor);
    }
    if signal.evidence_digest.is_zero() {
        return Err(CellSplitPlannerErrorV1::MissingEvidence("signal"));
    }
    let shape_ok = match signal.operation {
        CellSplitOperationV1::Add => {
            signal.predecessor_digest.is_none() && signal.candidate_digest.is_some()
        }
        CellSplitOperationV1::Split
        | CellSplitOperationV1::Merge
        | CellSplitOperationV1::Rewire => {
            signal.predecessor_digest.is_some() && signal.candidate_digest.is_some()
        }
        CellSplitOperationV1::Retire => {
            signal.predecessor_digest.is_some() && signal.candidate_digest.is_none()
        }
    };
    if !shape_ok {
        return Err(CellSplitPlannerErrorV1::InvalidLineage);
    }
    for digest in [signal.predecessor_digest, signal.candidate_digest]
        .into_iter()
        .flatten()
    {
        if digest.is_zero() {
            return Err(CellSplitPlannerErrorV1::MissingEvidence("lineage"));
        }
    }
    if signal.predecessor_digest.is_some()
        && signal.predecessor_digest == signal.candidate_digest
    {
        return Err(CellSplitPlannerErrorV1::InvalidLineage);
    }
    if signal.budget.compute_micros == 0
        || signal.budget.memory_bytes == 0
        || signal.budget.storage_bytes == 0
        || signal.budget.network_bytes == 0
    {
        return Err(CellSplitPlannerErrorV1::InvalidBudget);
    }
    if signal.risk.risk_ppm > signal.risk.maximum_risk_ppm
        || signal.risk.maximum_risk_ppm > PPM_DENOMINATOR
        || signal.risk.risk_evidence_digest.is_zero()
    {
        return Err(CellSplitPlannerErrorV1::InvalidRisk);
    }
    if signal.rollback.predecessor_digest.is_zero()
        || signal.rollback.procedure_digest.is_zero()
        || signal.rollback.timeout_micros == 0
    {
        return Err(CellSplitPlannerErrorV1::MissingRollback);
    }
    if signal.guardrails.holdout.cohort_digest.is_zero()
        || signal.guardrails.holdout.evaluation_digest.is_zero()
        || signal.guardrails.holdout.minimum_observations == 0
    {
        return Err(CellSplitPlannerErrorV1::MissingHoldout);
    }
    if signal.guardrails.canary.cohort_digest.is_zero()
        || !(1..=PPM_DENOMINATOR).contains(&signal.guardrails.canary.maximum_exposure_ppm)
        || signal.guardrails.canary.duration_micros == 0
    {
        return Err(CellSplitPlannerErrorV1::InvalidCanary);
    }
    if signal.guardrails.quarantine.trigger_digest.is_zero()
        || signal.guardrails.quarantine.duration_micros == 0
    {
        return Err(CellSplitPlannerErrorV1::InvalidQuarantine);
    }
    Ok(())
}

#[cfg(test)]
#[path = "cell_split_tests.rs"]
mod tests;
