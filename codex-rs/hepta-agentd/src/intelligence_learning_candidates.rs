//! Project policy actions into the ledger's intrinsic-complete candidate set.
//!
//! Use only when constructing a fresh learning request, before completeness and
//! signature verification. Canonical policy bindings and persisted payloads
//! retain their original candidate universe.

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
