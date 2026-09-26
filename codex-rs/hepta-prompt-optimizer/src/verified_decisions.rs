fn build_candidate_decisions(
    problem: &DensePromptProblem<'_>,
    selected: FactorMask,
) -> Result<Vec<PromptCandidateDecisionV2>, VerifiedPromptError> {
    let mut decisions = Vec::with_capacity(problem.rows.len());
    for index in 0..problem.rows.len() {
        let disposition = if selected.contains(index) {
            PromptCandidateDispositionV2::Selected
        } else if problem.dominated.contains(index) {
            PromptCandidateDispositionV2::Dominated
        } else if problem.rows[index].net_utility_q32 <= FixedQ32::ZERO {
            PromptCandidateDispositionV2::NonPositiveUtility
        } else if problem.tokens(problem.closures[index])? > problem.token_budget {
            PromptCandidateDispositionV2::TokenBudget
        } else if problem.closures[index].count() > problem.maximum_selected {
            PromptCandidateDispositionV2::SelectionLimit
        } else if problem.closures[index]
            .indices(problem.rows.len())
            .any(|member| problem.conflicts[member].intersects(selected))
        {
            PromptCandidateDispositionV2::HardConflict
        } else {
            PromptCandidateDispositionV2::HeuristicExcluded
        };
        decisions.push(PromptCandidateDecisionV2 {
            factor_id: problem.rows[index].binding.factor_id.clone(),
            disposition,
        });
    }
    Ok(decisions)
}
