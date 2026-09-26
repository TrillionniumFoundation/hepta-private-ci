#[derive(Clone, Copy)]
struct PromptEvaluation {
    valid: bool,
    tokens: u64,
    utility: FixedQ32,
}

struct PromptEvaluationCache<'problem, 'rows> {
    problem: &'problem DensePromptProblem<'rows>,
    values: BTreeMap<FactorMask, PromptEvaluation>,
}

impl<'problem, 'rows> PromptEvaluationCache<'problem, 'rows> {
    fn new(problem: &'problem DensePromptProblem<'rows>) -> Self {
        Self {
            problem,
            values: BTreeMap::new(),
        }
    }

    fn evaluate(&mut self, mask: FactorMask) -> Result<PromptEvaluation, VerifiedPromptError> {
        if let Some(value) = self.values.get(&mask) {
            return Ok(*value);
        }
        let tokens = self.problem.tokens(mask)?;
        let mut valid = mask.count() <= self.problem.maximum_selected
            && tokens <= self.problem.token_budget
            && !mask.intersects(self.problem.dominated);
        if valid {
            for index in mask.indices(self.problem.rows.len()) {
                if !self.problem.closures[index].is_subset(mask)
                    || self.problem.conflicts[index].intersects(mask)
                {
                    valid = false;
                    break;
                }
            }
        }
        let utility = if valid {
            self.problem.utility(mask)?
        } else {
            FixedQ32::ZERO
        };
        let value = PromptEvaluation {
            valid,
            tokens,
            utility,
        };
        self.values.insert(mask, value);
        Ok(value)
    }
}

#[derive(Clone, Copy)]
struct SolverOutcome {
    selected: FactorMask,
    rounds: u32,
    local_evaluations: u32,
    exact_nodes: u32,
    exact_complete: bool,
}

fn solve_prompt_problem(
    problem: &DensePromptProblem<'_>,
) -> Result<SolverOutcome, VerifiedPromptError> {
    let mut cache = PromptEvaluationCache::new(problem);
    let mut selected = FactorMask::default();
    let mut rounds = 0_u32;
    loop {
        let base = cache.evaluate(selected)?.utility;
        let mut best: Option<(FactorMask, FixedQ32, u64, usize)> = None;
        for root in 0..problem.rows.len() {
            if selected.contains(root) || problem.dominated.contains(root) {
                continue;
            }
            let proposed = selected.union(problem.closures[root]);
            let evaluation = cache.evaluate(proposed)?;
            if !evaluation.valid {
                continue;
            }
            let marginal = evaluation
                .utility
                .checked_sub(base)
                .map_err(|_| VerifiedPromptError::Arithmetic)?;
            if marginal <= FixedQ32::ZERO {
                continue;
            }
            let better = best.as_ref().is_none_or(
                |(_, best_gain, best_tokens, best_root)| {
                    marginal > *best_gain
                        || (marginal == *best_gain
                            && (evaluation.tokens < *best_tokens
                                || (evaluation.tokens == *best_tokens && root < *best_root)))
                },
            );
            if better {
                best = Some((proposed, marginal, evaluation.tokens, root));
            }
        }
        let Some((proposed, _, _, _)) = best else {
            break;
        };
        selected = proposed;
        rounds = rounds.saturating_add(1);
        if rounds >= MAX_LOCAL_SEARCH_ROUNDS {
            break;
        }
    }

    let mut local_evaluations = 0_u32;
    loop {
        let incumbent = cache.evaluate(selected)?.utility;
        let mut best_mask = selected;
        let mut best_utility = incumbent;
        let selected_indices = selected.indices(problem.rows.len()).collect::<Vec<_>>();
        'neighborhood: for first_pos in 0..=selected_indices.len() {
            for second_pos in first_pos..=selected_indices.len() {
                let mut base = selected;
                if first_pos < selected_indices.len() {
                    base.remove(selected_indices[first_pos]);
                }
                if second_pos < selected_indices.len() && second_pos != first_pos {
                    base.remove(selected_indices[second_pos]);
                }
                base = problem.repair_after_removal(base);
                for add_first in 0..=problem.rows.len() {
                    let mut one = base;
                    if add_first < problem.rows.len() {
                        one = one.union(problem.closures[add_first]);
                    }
                    for add_second in add_first..=problem.rows.len() {
                        local_evaluations = local_evaluations.saturating_add(1);
                        if local_evaluations >= MAX_LOCAL_SEARCH_EVALUATIONS {
                            break 'neighborhood;
                        }
                        let mut proposed = one;
                        if add_second < problem.rows.len() && add_second != add_first {
                            proposed = proposed.union(problem.closures[add_second]);
                        }
                        let evaluation = cache.evaluate(proposed)?;
                        if !evaluation.valid {
                            continue;
                        }
                        if evaluation.utility > best_utility
                            || (evaluation.utility == best_utility && proposed < best_mask)
                        {
                            best_utility = evaluation.utility;
                            best_mask = proposed;
                        }
                    }
                }
            }
        }
        if best_utility <= incumbent || best_mask == selected {
            break;
        }
        selected = best_mask;
        rounds = rounds.saturating_add(1);
        if rounds >= MAX_LOCAL_SEARCH_ROUNDS
            || local_evaluations >= MAX_LOCAL_SEARCH_EVALUATIONS
        {
            break;
        }
    }

    let mut exact_nodes = 0_u32;
    let mut exact_complete = false;
    if problem.rows.len() <= MAX_EXACT_FACTORS {
        let mut best_mask = selected;
        let mut best_utility = cache.evaluate(selected)?.utility;
        exact_complete = exact_search(
            problem,
            &mut cache,
            0,
            FactorMask::default(),
            FactorMask::default(),
            &mut best_mask,
            &mut best_utility,
            &mut exact_nodes,
        )?;
        if best_utility > cache.evaluate(selected)?.utility {
            selected = best_mask;
        }
    }

    Ok(SolverOutcome {
        selected,
        rounds,
        local_evaluations,
        exact_nodes,
        exact_complete,
    })
}

#[allow(clippy::too_many_arguments)]
fn exact_search(
    problem: &DensePromptProblem<'_>,
    cache: &mut PromptEvaluationCache<'_, '_>,
    index: usize,
    selected: FactorMask,
    excluded: FactorMask,
    best_mask: &mut FactorMask,
    best_utility: &mut FixedQ32,
    nodes: &mut u32,
) -> Result<bool, VerifiedPromptError> {
    *nodes = nodes.saturating_add(1);
    if *nodes > MAX_EXACT_NODES {
        return Ok(false);
    }
    let branch_bound = problem.relaxed_upper_bound_from(selected, excluded, index)?;
    if branch_bound < *best_utility {
        return Ok(true);
    }
    if index >= problem.rows.len() {
        let evaluation = cache.evaluate(selected)?;
        if evaluation.valid
            && (evaluation.utility > *best_utility
                || (evaluation.utility == *best_utility && selected < *best_mask))
        {
            *best_utility = evaluation.utility;
            *best_mask = selected;
        }
        return Ok(true);
    }
    if selected.contains(index) || excluded.contains(index) {
        return exact_search(
            problem,
            cache,
            index + 1,
            selected,
            excluded,
            best_mask,
            best_utility,
            nodes,
        );
    }

    let mut complete = true;
    let mut without = excluded;
    without.insert(index);
    complete &= exact_search(
        problem,
        cache,
        index + 1,
        selected,
        without,
        best_mask,
        best_utility,
        nodes,
    )?;

    let closure = problem.closures[index];
    if !closure.intersects(excluded) {
        let with = selected.union(closure);
        if cache.evaluate(with)?.valid {
            complete &= exact_search(
                problem,
                cache,
                index + 1,
                with,
                excluded,
                best_mask,
                best_utility,
                nodes,
            )?;
        }
    }
    Ok(complete)
}
