use super::CellSplitBudgetV1;
use super::CellSplitCandidateKindV1;
use super::CellSplitGuardrailsV1;
use super::CellSplitOperationV1;
use super::CellSplitPlannerErrorV1;
use super::CellSplitProposalSignalV1;
use super::CellSplitRiskV1;
use super::CellSplitRollbackV1;
use super::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub(super) fn digest_signal(
    signal: &CellSplitProposalSignalV1,
) -> Result<Digest32, CellSplitPlannerErrorV1> {
    let mut bytes = b"hepta.plasticity.cell-split.signal.v1\0".to_vec();
    push_id(&mut bytes, &signal.signal_id)?;
    push_id(&mut bytes, &signal.cell_id)?;
    bytes.push(operation_tag(signal.operation));
    bytes.extend_from_slice(&signal.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&signal.candidate_generation.get().to_be_bytes());
    push_optional_digest(&mut bytes, signal.predecessor_digest);
    push_optional_digest(&mut bytes, signal.candidate_digest);
    bytes.extend_from_slice(signal.evidence_digest.as_array());
    push_budget(&mut bytes, signal.budget);
    push_risk(&mut bytes, signal.risk);
    push_rollback(&mut bytes, signal.rollback);
    push_guardrails(&mut bytes, signal.guardrails);
    Ok(Digest32::of_bytes(&bytes))
}

pub(super) fn digest_plan(plan: &CellSplitV1) -> Result<Digest32, CellSplitPlannerErrorV1> {
    let mut bytes = b"hepta.plasticity.cell-split.plan.v1\0".to_vec();
    for id in [
        &plan.plan_id,
        &plan.generator_id,
        &plan.evaluator_id,
        &plan.reviewer_id,
        &plan.operator_id,
    ] {
        push_id(&mut bytes, id)?;
    }
    bytes.extend_from_slice(&plan.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&plan.candidate_generation.get().to_be_bytes());
    push_id(&mut bytes, &plan.signal_id)?;
    bytes.extend_from_slice(plan.signal_digest.as_array());
    push_optional_digest(&mut bytes, plan.predecessor_digest);
    push_optional_digest(&mut bytes, plan.candidate_digest);
    push_budget(&mut bytes, plan.budget);
    push_risk(&mut bytes, plan.risk);
    push_rollback(&mut bytes, plan.rollback);
    push_guardrails(&mut bytes, plan.guardrails);
    for candidate in &plan.candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.push(match candidate.kind {
            CellSplitCandidateKindV1::NoChange => 0,
            CellSplitCandidateKindV1::Change => 1,
        });
        bytes.push(candidate.operation.map(operation_tag).unwrap_or(u8::MAX));
        push_id(&mut bytes, &candidate.cell_id)?;
        bytes.extend_from_slice(candidate.evidence_digest.as_array());
    }
    bytes.push(0); // RequiresIndependentReview.
    bytes.push(0); // DENY_ALL authority profile.
    Ok(Digest32::of_bytes(&bytes))
}

pub(super) fn candidate_id(
    kind: &[u8],
    plan_id: &StableId,
    signal_id: &StableId,
    generation: Generation,
    operation: Option<CellSplitOperationV1>,
) -> Result<StableId, CellSplitPlannerErrorV1> {
    let mut bytes = b"hepta.plasticity.cell-split.candidate.v1\0".to_vec();
    bytes.extend_from_slice(kind);
    push_id(&mut bytes, plan_id)?;
    push_id(&mut bytes, signal_id)?;
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.push(operation.map(operation_tag).unwrap_or(u8::MAX));
    stable_id(&format!("cell-candidate:{}", Digest32::of_bytes(&bytes)))
}

fn operation_tag(operation: CellSplitOperationV1) -> u8 {
    match operation {
        CellSplitOperationV1::Add => 0,
        CellSplitOperationV1::Split => 1,
        CellSplitOperationV1::Merge => 2,
        CellSplitOperationV1::Rewire => 3,
        CellSplitOperationV1::Retire => 4,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), CellSplitPlannerErrorV1> {
    let length =
        u32::try_from(value.as_str().len()).map_err(|_| CellSplitPlannerErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
    Ok(())
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_budget(bytes: &mut Vec<u8>, budget: CellSplitBudgetV1) {
    for value in [
        budget.compute_micros,
        budget.memory_bytes,
        budget.storage_bytes,
        budget.network_bytes,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
}

fn push_risk(bytes: &mut Vec<u8>, risk: CellSplitRiskV1) {
    bytes.extend_from_slice(&risk.risk_ppm.to_be_bytes());
    bytes.extend_from_slice(&risk.maximum_risk_ppm.to_be_bytes());
    bytes.extend_from_slice(risk.risk_evidence_digest.as_array());
}

fn push_rollback(bytes: &mut Vec<u8>, rollback: CellSplitRollbackV1) {
    bytes.extend_from_slice(rollback.predecessor_digest.as_array());
    bytes.extend_from_slice(rollback.procedure_digest.as_array());
    bytes.extend_from_slice(&rollback.timeout_micros.to_be_bytes());
}

fn push_guardrails(bytes: &mut Vec<u8>, guardrails: CellSplitGuardrailsV1) {
    bytes.extend_from_slice(guardrails.canary.cohort_digest.as_array());
    bytes.extend_from_slice(&guardrails.canary.maximum_exposure_ppm.to_be_bytes());
    bytes.extend_from_slice(&guardrails.canary.duration_micros.to_be_bytes());
    bytes.extend_from_slice(guardrails.quarantine.trigger_digest.as_array());
    bytes.extend_from_slice(&guardrails.quarantine.duration_micros.to_be_bytes());
    bytes.extend_from_slice(guardrails.holdout.cohort_digest.as_array());
    bytes.extend_from_slice(guardrails.holdout.evaluation_digest.as_array());
    bytes.extend_from_slice(&guardrails.holdout.minimum_observations.to_be_bytes());
}

fn stable_id(value: &str) -> Result<StableId, CellSplitPlannerErrorV1> {
    StableId::new(value).map_err(|_| CellSplitPlannerErrorV1::Arithmetic)
}
