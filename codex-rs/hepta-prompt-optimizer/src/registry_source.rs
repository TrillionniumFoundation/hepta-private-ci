//! Read-only prompt-registry consumer for optimizer candidate construction.

use std::collections::BTreeMap;

use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_prompt_registry::PromptRegistrySnapshotV2;
use codex_hepta_prompt_registry::PromptRegistryV2Error;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::OptimizationRequest;
use crate::PromptCandidate;
use crate::PromptPortfolioReceipt;
use crate::optimize;

const MAX_REGISTRY_SCORES: usize = codex_hepta_prompt_registry::MAX_COMPATIBLE_REALIZATIONS_V2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegistryCandidateScore {
    pub factor_id: StableId,
    pub expected_gain: FixedQ32,
    pub legal: bool,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegistryOptimizationRequest {
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub now_unix_ms: u64,
    pub budget: u64,
    pub maximum_selected: usize,
    pub scores: Vec<RegistryCandidateScore>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RegistrySourceError {
    ScoreLimitExceeded,
    EmptyScores,
    DuplicateFactorScore(String),
    EmptySupportDigest(String),
    MissingScore(String),
    Registry(PromptRegistryV2Error),
    Optimizer(crate::Error),
}

impl std::fmt::Display for RegistrySourceError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for RegistrySourceError {}

pub fn candidates_from_registry(
    registry: &PromptRegistry,
    snapshot: &PromptRegistrySnapshotV2,
    generation_vector_digest: Digest32,
    model_tuple: &PromptModelTupleV2,
    now_unix_ms: u64,
    mut scores: Vec<RegistryCandidateScore>,
) -> Result<Vec<PromptCandidate>, RegistrySourceError> {
    if scores.is_empty() {
        return Err(RegistrySourceError::EmptyScores);
    }
    if scores.len() > MAX_REGISTRY_SCORES {
        return Err(RegistrySourceError::ScoreLimitExceeded);
    }
    scores.sort_by_key(|score| score.factor_id.clone());
    let mut by_factor = BTreeMap::new();
    for score in scores {
        if score.support_digest.is_zero() {
            return Err(RegistrySourceError::EmptySupportDigest(
                score.factor_id.to_string(),
            ));
        }
        let factor_id = score.factor_id.clone();
        if by_factor.insert(factor_id.clone(), score).is_some() {
            return Err(RegistrySourceError::DuplicateFactorScore(
                factor_id.to_string(),
            ));
        }
    }
    let required_factor_ids = by_factor.keys().cloned().collect::<Vec<_>>();
    let maximum_results = u32::try_from(required_factor_ids.len())
        .map_err(|_| RegistrySourceError::ScoreLimitExceeded)?;
    let compatible = registry
        .read_compatible_v2(
            snapshot,
            generation_vector_digest,
            model_tuple,
            now_unix_ms,
            required_factor_ids,
            maximum_results,
        )
        .map_err(RegistrySourceError::Registry)?;
    let mut candidates = Vec::with_capacity(compatible.bindings.len());
    for binding in compatible.bindings {
        let score = by_factor
            .get(&binding.factor_id)
            .ok_or_else(|| RegistrySourceError::MissingScore(binding.factor_id.to_string()))?;
        candidates.push(PromptCandidate {
            candidate_id: binding.realization_id.clone(),
            factor_id: binding.factor_id,
            realization_id: binding.realization_id,
            admitted: true,
            legal: score.legal,
            expected_gain: score.expected_gain,
            cost: u64::from(binding.token_cost),
            registry_digest: snapshot.snapshot_digest,
            support_digest: score.support_digest,
        });
    }
    candidates.sort_by_key(|candidate| candidate.candidate_id.clone());
    Ok(candidates)
}

pub fn optimize_registry_snapshot(
    registry: &PromptRegistry,
    snapshot: &PromptRegistrySnapshotV2,
    request: RegistryOptimizationRequest,
) -> Result<PromptPortfolioReceipt, RegistrySourceError> {
    let candidates = candidates_from_registry(
        registry,
        snapshot,
        request.generation_vector_digest,
        &request.model_tuple,
        request.now_unix_ms,
        request.scores,
    )?;
    optimize(OptimizationRequest {
        decision_id: request.decision_id,
        objective_digest: request.objective_digest,
        registry_snapshot_digest: snapshot.snapshot_digest,
        budget: request.budget,
        maximum_selected: request.maximum_selected,
        candidates,
    })
    .map_err(RegistrySourceError::Optimizer)
}

#[cfg(test)]
#[path = "registry_source_tests.rs"]
mod tests;
