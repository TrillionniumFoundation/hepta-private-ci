//! Bounded independence check for the actual two frozen source sets.
use codex_hepta_agent_components::types::Digest32;

// Matches the real LedgerWriter materialization entry's per-dataset bound.
const MAX_FROZEN_SOURCES: usize = 4096;

pub(crate) fn validate_disjoint_frozen_sources(
    training: &[Digest32],
    evaluation: &[Digest32],
) -> Result<(), &'static str> {
    if training.is_empty()
        || evaluation.is_empty()
        || training.len() > MAX_FROZEN_SOURCES
        || evaluation.len() > MAX_FROZEN_SOURCES
    {
        return Err("frozen source bounds");
    }
    // Receipts retain ledger sequence order, so hash order cannot be assumed.
    let mut training = training.to_vec();
    let mut evaluation = evaluation.to_vec();
    training.sort_unstable();
    evaluation.sort_unstable();
    if training.windows(2).any(|pair| pair[0] == pair[1])
        || evaluation.windows(2).any(|pair| pair[0] == pair[1])
    {
        return Err("duplicate frozen sources");
    }
    let (mut left, mut right) = (0, 0);
    while left < training.len() && right < evaluation.len() {
        match training[left].cmp(&evaluation[right]) {
            std::cmp::Ordering::Less => left += 1,
            std::cmp::Ordering::Greater => right += 1,
            std::cmp::Ordering::Equal => return Err("training/evaluation source overlap"),
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "learning_operator_source_binding_tests.rs"]
mod tests;
