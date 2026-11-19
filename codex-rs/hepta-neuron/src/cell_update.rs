//! Bounded immutable update proposals through the shared learning owner.
//! This interface never mutates live weights or adopts a candidate version.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::cell_types::*;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellUpdateBudgetV1 {
    pub maximum_dataset_bytes: u64,
    pub maximum_steps: u64,
    pub maximum_elapsed_micros: u64,
    pub maximum_working_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellUpdateRequestV1 {
    pub proposal_id: StableId,
    pub scope: CellScopeV1,
    pub base_bundle_digest: Digest32,
    pub source_frontier: Digest32,
    pub dataset_digest: Digest32,
    pub dataset_bytes: u64,
    pub credit_profile_digest: Digest32,
    pub trainable_mask_digest: Digest32,
    pub trainable_parameters: Vec<StableId>,
    pub from_generation: Generation,
    pub candidate_generation: Generation,
    pub budget: CellUpdateBudgetV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellUpdateCandidateV1 {
    pub proposal_id: StableId,
    pub base_bundle_digest: Digest32,
    pub dataset_digest: Digest32,
    pub credit_profile_digest: Digest32,
    pub trainable_mask_digest: Digest32,
    pub candidate_generation: Generation,
    pub candidate_artifact_digest: Digest32,
    pub changed_parameters: Vec<StableId>,
    pub executed_steps: u64,
    pub elapsed_micros: u64,
    pub peak_working_bytes: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellUpdateOutcomeV1 {
    NoUpdate,
    Candidate(Box<CellUpdateCandidateV1>),
}

/// The learning owner consumes admitted immutable datasets and training budgets.
/// It returns a bounded next-generation proposal, not a publication capability.
pub trait CellUpdatePortV1 {
    fn propose(
        &mut self,
        request: &CellUpdateRequestV1,
    ) -> Result<CellUpdateOutcomeV1, CellExecutionError>;
}

pub fn propose_cell_update(
    definition: &CellDefinitionV1,
    owner: &impl CellStateOwnerV1,
    learner: &mut impl CellUpdatePortV1,
    request: &CellUpdateRequestV1,
) -> Result<CellUpdateOutcomeV1, CellExecutionError> {
    let definition_digest = definition.semantic_digest()?;
    let before = owner.snapshot(&request.scope)?;
    if before.scope != request.scope || request.scope.cell_id != definition.cell_id {
        return Err(CellExecutionError::ScopeMismatch);
    }
    if before.definition_digest != definition_digest
        || request.base_bundle_digest != definition.bundle_digest
        || request.from_generation != definition.runtime.generation
        || request.from_generation.get().checked_add(1) != Some(request.candidate_generation.get())
    {
        return Err(CellExecutionError::IncompatibleBundle);
    }
    if request.source_frontier.is_zero() || before.source_frontier != request.source_frontier {
        return Err(CellExecutionError::StaleSource);
    }
    if request.dataset_digest.is_zero()
        || request.credit_profile_digest.is_zero()
        || request.trainable_mask_digest.is_zero()
        || request.dataset_bytes == 0
        || request.dataset_bytes > request.budget.maximum_dataset_bytes
        || request.budget.maximum_steps == 0
        || request.budget.maximum_elapsed_micros == 0
        || request.budget.maximum_working_bytes == 0
        || request.trainable_parameters.is_empty()
        || request.trainable_parameters.len() > 1024
    {
        return Err(CellExecutionError::InvalidInput);
    }
    let mut allowed = BTreeSet::new();
    let mut mask_bytes = b"hepta.cell.trainable-mask.v1".to_vec();
    for parameter in &request.trainable_parameters {
        if !allowed.insert(parameter) {
            return Err(CellExecutionError::InvalidInput);
        }
        mask_bytes.extend_from_slice(&(parameter.as_str().len() as u32).to_be_bytes());
        mask_bytes.extend_from_slice(parameter.as_str().as_bytes());
    }
    if Digest32::of_bytes(&mask_bytes) != request.trainable_mask_digest {
        return Err(CellExecutionError::InvalidInput);
    }
    let outcome = learner.propose(request)?;
    let after = owner.snapshot(&request.scope)?;
    if after.scope != before.scope
        || after.definition_digest != before.definition_digest
        || after.source_frontier != before.source_frontier
        || after.writer_epoch != before.writer_epoch
    {
        return Err(CellExecutionError::CommitConflict);
    }
    if let CellUpdateOutcomeV1::Candidate(candidate) = &outcome {
        let mut changed = BTreeSet::new();
        if candidate.proposal_id != request.proposal_id
            || candidate.base_bundle_digest != request.base_bundle_digest
            || candidate.dataset_digest != request.dataset_digest
            || candidate.credit_profile_digest != request.credit_profile_digest
            || candidate.trainable_mask_digest != request.trainable_mask_digest
            || candidate.candidate_generation != request.candidate_generation
            || candidate.candidate_artifact_digest.is_zero()
            || candidate.changed_parameters.is_empty()
            || candidate.changed_parameters.len() > request.trainable_parameters.len()
            || candidate
                .changed_parameters
                .iter()
                .any(|id| !allowed.contains(id) || !changed.insert(id))
            || candidate.executed_steps == 0
            || candidate.executed_steps > request.budget.maximum_steps
            || candidate.elapsed_micros > request.budget.maximum_elapsed_micros
            || candidate.peak_working_bytes > request.budget.maximum_working_bytes
            || candidate.authority.grants_any()
        {
            return Err(CellExecutionError::InvalidInput);
        }
    }
    Ok(outcome)
}
