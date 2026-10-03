//! Make intrinsic abstention explicit in a fresh qualification ledger decision.
//!
//! The evaluation signature has already been verified over the policy's action
//! candidates. This checked representation projection does not rewrite those
//! signed candidates or their bindings: calibrated intuition separately commits
//! intrinsic abstention. Prepared runs and persisted or pending events retain
//! their original representation.

use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_types::StableId;

const MAX_LEARNING_CANDIDATES: usize = 128;

pub(crate) fn learning_candidate_ids_v1(
    actions: &[StableId],
) -> Result<Vec<StableId>, CanonicalIntelligenceError> {
    if actions.is_empty() || actions.len() >= MAX_LEARNING_CANDIDATES {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "learning candidate capacity including abstain",
        ));
    }
    if actions.iter().any(|value| value.as_str() == "abstain") {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "reserved intrinsic abstain action",
        ));
    }
    let mut candidates = actions.to_vec();
    candidates.sort();
    if candidates.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "duplicate learning action",
        ));
    }
    candidates.push(StableId::new("abstain").map_err(|_| CanonicalIntelligenceError::Arithmetic)?);
    candidates.sort();
    Ok(candidates)
}

#[cfg(test)]
#[path = "intelligence_learning_candidates_tests.rs"]
mod tests;
