// ---------------------------------------------------------------------------
// Target operation 4: exercise.
// ---------------------------------------------------------------------------

/// Evaluate the portfolio at one owner-registered decision boundary.
///
/// The returned decision remains authority-free; a separate owner-bound adapter
/// must consume it if an intervention is ever activated.
pub fn exercise(
    portfolio: &PromptPortfolioReceiptV1,
    registered_boundary: &RegisteredPromptBoundaryV1,
    state: &PromptExerciseStateV1,
) -> Result<PromptExerciseDecisionV1, PolicyError> {
    Ok(exercise_audited(portfolio, registered_boundary, state)?.receipt)
}

pub fn exercise_audited(
    portfolio: &PromptPortfolioReceiptV1,
    registered_boundary: &RegisteredPromptBoundaryV1,
    state: &PromptExerciseStateV1,
) -> Result<PromptExerciseDecisionBundleV1, PolicyError> {
    validate_nonzero_digest(registered_boundary.portfolio_digest, "registered portfolio")?;
    validate_nonzero_digest(registered_boundary.candidate_set_digest, "registered candidate set")?;
    validate_nonzero_digest(registered_boundary.registry_digest, "registered registry")?;
    validate_nonzero_digest(registered_boundary.model_profile_digest, "registered model profile")?;
    validate_nonzero_digest(registered_boundary.registered_state_digest, "registered state")?;
    validate_nonzero_digest(registered_boundary.policy_digest, "exercise policy")?;
    validate_nonzero_digest(registered_boundary.boundary_support_digest, "boundary support")?;

    let portfolio_digest = digest_portfolio_receipt(portfolio);
    if portfolio_digest != registered_boundary.portfolio_digest
        || portfolio.candidate_set_digest != registered_boundary.candidate_set_digest
    {
        return Err(PolicyError::PortfolioDigestMismatch);
    }
    if state.state_digest != registered_boundary.registered_state_digest {
        return Err(PolicyError::StateDrift);
    }
    if state.registry_digest != registered_boundary.registry_digest {
        return Err(PolicyError::RegistryDrift);
    }
    if state.model_profile_digest != registered_boundary.model_profile_digest {
        return Err(PolicyError::ModelProfileDrift);
    }
    if state.observed_at_unix_ms > portfolio.valid_until_unix_ms {
        return Err(PolicyError::PortfolioExpired);
    }

    let choice = if portfolio.factor_ids.is_empty() {
        PromptExerciseChoiceV1::NoChange
    } else if portfolio.expected_utility_q32 > state.wait_value_q32 {
        PromptExerciseChoiceV1::Exercise
    } else {
        PromptExerciseChoiceV1::Wait
    };
    let receipt = PromptExerciseDecisionV1 {
        factor_or_portfolio_id: portfolio.portfolio_id.clone(),
        decision_boundary: registered_boundary.decision_boundary,
        exercise_now_value_q32: portfolio.expected_utility_q32,
        wait_value_q32: state.wait_value_q32,
        decision: choice,
        policy_digest: registered_boundary.policy_digest,
    };
    let boundary_digest = digest_registered_boundary(registered_boundary);
    let audit_digest = digest_exercise_audit(&receipt, portfolio_digest, boundary_digest, state);
    Ok(PromptExerciseDecisionBundleV1 {
        receipt,
        audit: PromptExerciseAuditV1 {
            portfolio_digest,
            boundary_digest,
            state_compatible: true,
            registry_compatible: true,
            model_profile_compatible: true,
            before_expiry: true,
            audit_digest,
        },
    })
}
