use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::error::CanonicalPromptError;
use super::raw;
use super::selection::PromptSolverMethodV2;
use super::selection::PromptSolverTerminationV1;

const EXACT_ORACLE_LIMIT: usize = 18;
const LOCAL_SEARCH_EVALUATION_LIMIT: u32 = 8_192;

#[derive(Clone, Debug)]
pub(super) struct SolverOutcome {
    pub(super) mask: u128,
    pub(super) utility_raw: i64,
    pub(super) upper_bound_raw: i64,
    pub(super) rounds: u32,
    pub(super) evaluations: u32,
    pub(super) method: PromptSolverMethodV2,
    pub(super) termination: PromptSolverTerminationV1,
}

#[derive(Clone, Debug)]
pub(super) struct SolverModel {
    ids: Vec<StableId>,
    utilities: Vec<i64>,
    tokens: Vec<u64>,
    requires: Vec<u128>,
    conflicts: Vec<u128>,
    pair: Vec<Vec<i64>>,
    maximum_selected: usize,
    token_budget: u64,
}

impl SolverModel {
    pub(super) fn build(
        priced: &raw::PricedPromptCandidatesV1,
        requires: &BTreeMap<StableId, BTreeSet<StableId>>,
        conflicts: &BTreeSet<(StableId, StableId)>,
        pair_values: &BTreeMap<(StableId, StableId), i64>,
        maximum_selected: usize,
        token_budget: u64,
    ) -> Result<Self, CanonicalPromptError> {
        if priced.rows.len() > 128 {
            return Err(CanonicalPromptError::CandidateLimit);
        }
        let ids = priced
            .rows
            .iter()
            .map(|row| row.binding.factor_id.clone())
            .collect::<Vec<_>>();
        let index = ids
            .iter()
            .enumerate()
            .map(|(position, id)| (id.clone(), position))
            .collect::<BTreeMap<_, _>>();
        let utilities = priced
            .rows
            .iter()
            .map(|row| row.net_utility_q32.raw())
            .collect::<Vec<_>>();
        let tokens = priced
            .rows
            .iter()
            .map(|row| u64::from(row.pricing.token_cost))
            .collect::<Vec<_>>();
        let mut closure = vec![0_u128; ids.len()];
        for (position, id) in ids.iter().enumerate() {
            closure[position] |= 1_u128 << position;
            let mut stack = requires
                .get(id)
                .into_iter()
                .flatten()
                .cloned()
                .collect::<Vec<_>>();
            let mut seen = BTreeSet::new();
            while let Some(required) = stack.pop() {
                if !seen.insert(required.clone()) {
                    continue;
                }
                let required_position = index.get(&required).ok_or_else(|| {
                    CanonicalPromptError::UnsatisfiableConstraintGraph(format!(
                        "{id} requires unavailable {required}"
                    ))
                })?;
                closure[position] |= 1_u128 << required_position;
                if let Some(next) = requires.get(&required) {
                    stack.extend(next.iter().cloned());
                }
            }
        }
        let mut conflict_masks = vec![0_u128; ids.len()];
        for (left, right) in conflicts {
            if let (Some(left_index), Some(right_index)) = (index.get(left), index.get(right)) {
                conflict_masks[*left_index] |= 1_u128 << right_index;
                conflict_masks[*right_index] |= 1_u128 << left_index;
            }
        }
        let mut pair = vec![vec![0_i64; ids.len()]; ids.len()];
        for ((left, right), value) in pair_values {
            if let (Some(left_index), Some(right_index)) = (index.get(left), index.get(right)) {
                pair[*left_index][*right_index] = *value;
                pair[*right_index][*left_index] = *value;
            }
        }
        Ok(Self {
            ids,
            utilities,
            tokens,
            requires: closure,
            conflicts: conflict_masks,
            pair,
            maximum_selected,
            token_budget,
        })
    }

    pub(super) fn mask_for_ids(&self, ids: &[StableId]) -> Result<u128, CanonicalPromptError> {
        let index = self
            .ids
            .iter()
            .enumerate()
            .map(|(position, id)| (id, position))
            .collect::<BTreeMap<_, _>>();
        ids.iter().try_fold(0_u128, |mask, id| {
            let position = index
                .get(id)
                .ok_or_else(|| CanonicalPromptError::Corrupt(format!("unknown selected {id}")))?;
            Ok(mask | (1_u128 << position))
        })
    }

    pub(super) fn solve(&self, seed: u128) -> Result<SolverOutcome, CanonicalPromptError> {
        let upper = self.upper_bound()?;
        if self.ids.len() <= EXACT_ORACLE_LIMIT {
            let mut best_mask = 0_u128;
            let mut best_utility = 0_i64;
            let mut evaluations = 0_u32;
            let limit = 1_u128 << self.ids.len();
            for mask in 0..limit {
                if !self.feasible(mask) {
                    continue;
                }
                evaluations = evaluations.saturating_add(1);
                let utility = self.utility(mask)?;
                if utility > best_utility
                    || (utility == best_utility && self.tie_break(mask, best_mask))
                {
                    best_mask = mask;
                    best_utility = utility;
                }
            }
            return Ok(SolverOutcome {
                mask: best_mask,
                utility_raw: best_utility,
                upper_bound_raw: best_utility,
                rounds: 1,
                evaluations,
                method: PromptSolverMethodV2::ExactOracleEnumerationV1,
                termination: if best_mask == 0 {
                    PromptSolverTerminationV1::NoPositivePortfolio
                } else {
                    PromptSolverTerminationV1::ExactSearchComplete
                },
            });
        }

        let mut best_mask = if self.feasible(seed) { seed } else { 0 };
        let mut best_utility = self.utility(best_mask)?;
        let mut evaluations = 1_u32;
        let mut rounds = 0_u32;
        let mut exhausted = false;
        loop {
            rounds = rounds.saturating_add(1);
            let mut improved = false;
            let selected = bit_positions(best_mask, self.ids.len());
            for remove in std::iter::once(None).chain(selected.iter().copied().map(Some)) {
                let mut base = best_mask;
                if let Some(position) = remove {
                    base &= !(1_u128 << position);
                    base = self.repair_requirements(base);
                }
                for first in 0..self.ids.len() {
                    let first_mask = base | self.requires[first];
                    let candidates = std::iter::once(first_mask).chain(
                        (first + 1..self.ids.len())
                            .map(|second| first_mask | self.requires[second]),
                    );
                    for candidate in candidates {
                        if evaluations >= LOCAL_SEARCH_EVALUATION_LIMIT {
                            exhausted = true;
                            break;
                        }
                        evaluations = evaluations.saturating_add(1);
                        if !self.feasible(candidate) {
                            continue;
                        }
                        let utility = self.utility(candidate)?;
                        if utility > best_utility
                            || (utility == best_utility
                                && self.tie_break(candidate, best_mask))
                        {
                            best_mask = candidate;
                            best_utility = utility;
                            improved = true;
                        }
                    }
                    if exhausted {
                        break;
                    }
                }
                if exhausted {
                    break;
                }
            }
            if exhausted || !improved || rounds >= 32 {
                break;
            }
        }
        Ok(SolverOutcome {
            mask: best_mask,
            utility_raw: best_utility.max(0),
            upper_bound_raw: upper.max(best_utility.max(0)),
            rounds,
            evaluations,
            method: PromptSolverMethodV2::GreedyWithOneTwoSwapV1,
            termination: if exhausted {
                PromptSolverTerminationV1::EvaluationBudgetExhausted
            } else if best_mask == 0 {
                PromptSolverTerminationV1::NoPositivePortfolio
            } else if usize::try_from(best_mask.count_ones()).unwrap_or(usize::MAX)
                >= self.maximum_selected
            {
                PromptSolverTerminationV1::SelectionLimit
            } else {
                PromptSolverTerminationV1::NoImprovingMove
            },
        })
    }

    fn repair_requirements(&self, mut mask: u128) -> u128 {
        loop {
            let mut changed = false;
            for position in bit_positions(mask, self.ids.len()) {
                if self.requires[position] & mask != self.requires[position] {
                    mask &= !(1_u128 << position);
                    changed = true;
                }
            }
            if !changed {
                return mask;
            }
        }
    }

    fn feasible(&self, mask: u128) -> bool {
        if usize::try_from(mask.count_ones()).unwrap_or(usize::MAX) > self.maximum_selected {
            return false;
        }
        let mut token_total = 0_u64;
        for position in bit_positions(mask, self.ids.len()) {
            if self.requires[position] & mask != self.requires[position]
                || self.conflicts[position] & mask != 0
            {
                return false;
            }
            let Some(next) = token_total.checked_add(self.tokens[position]) else {
                return false;
            };
            token_total = next;
        }
        token_total <= self.token_budget
    }

    fn utility(&self, mask: u128) -> Result<i64, CanonicalPromptError> {
        let positions = bit_positions(mask, self.ids.len());
        let mut total = 0_i128;
        for (offset, left) in positions.iter().enumerate() {
            total = total
                .checked_add(i128::from(self.utilities[*left]))
                .ok_or(CanonicalPromptError::Arithmetic)?;
            for right in positions.iter().skip(offset + 1) {
                total = total
                    .checked_add(i128::from(self.pair[*left][*right]))
                    .ok_or(CanonicalPromptError::Arithmetic)?;
            }
        }
        i64::try_from(total).map_err(|_| CanonicalPromptError::Arithmetic)
    }

    fn upper_bound(&self) -> Result<i64, CanonicalPromptError> {
        let mut total = 0_i128;
        for utility in &self.utilities {
            total = total
                .checked_add(i128::from((*utility).max(0)))
                .ok_or(CanonicalPromptError::Arithmetic)?;
        }
        for left in 0..self.ids.len() {
            for right in left + 1..self.ids.len() {
                total = total
                    .checked_add(i128::from(self.pair[left][right].max(0)))
                    .ok_or(CanonicalPromptError::Arithmetic)?;
            }
        }
        Ok(i64::try_from(total).unwrap_or(i64::MAX))
    }

    fn tie_break(&self, candidate: u128, current: u128) -> bool {
        let candidate_tokens = self.token_cost(candidate);
        let current_tokens = self.token_cost(current);
        candidate_tokens < current_tokens
            || (candidate_tokens == current_tokens
                && self.ids_for_mask(candidate) < self.ids_for_mask(current))
    }

    fn token_cost(&self, mask: u128) -> u64 {
        bit_positions(mask, self.ids.len())
            .into_iter()
            .fold(0_u64, |sum, position| sum.saturating_add(self.tokens[position]))
    }

    fn ids_for_mask(&self, mask: u128) -> Vec<&StableId> {
        bit_positions(mask, self.ids.len())
            .into_iter()
            .map(|position| &self.ids[position])
            .collect()
    }
}

pub(super) fn apply_solver_outcome(
    selected: &mut raw::SelectedPromptPortfolioV1,
    priced: &raw::PricedPromptCandidatesV1,
    outcome: &SolverOutcome,
    graph_generation_digest: Digest32,
) -> Result<(), CanonicalPromptError> {
    let positions = bit_positions(outcome.mask, priced.rows.len());
    let mut selected_bindings = positions
        .iter()
        .map(|position| priced.rows[*position].binding.clone())
        .collect::<Vec<_>>();
    selected_bindings.sort_by(|left, right| left.factor_id.cmp(&right.factor_id));
    let factor_ids = selected_bindings
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<Vec<_>>();
    let token_total = positions.iter().try_fold(0_u64, |sum, position| {
        sum.checked_add(u64::from(priced.rows[*position].pricing.token_cost))
            .ok_or(CanonicalPromptError::Arithmetic)
    })?;
    selected.selected = selected_bindings;
    selected.receipt.factor_ids = factor_ids;
    selected.receipt.expected_utility_q32 = FixedQ32::from_raw(outcome.utility_raw);
    selected.receipt.total_token_upper_bound =
        u32::try_from(token_total).map_err(|_| CanonicalPromptError::TokenBudgetLimit)?;
    selected.graph_generation_digest = graph_generation_digest;
    Ok(())
}

fn bit_positions(mask: u128, limit: usize) -> Vec<usize> {
    (0..limit)
        .filter(|position| mask & (1_u128 << position) != 0)
        .collect()
}
