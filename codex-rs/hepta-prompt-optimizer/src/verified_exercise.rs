#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptStaleReasonV2 {
    PortfolioExpired,
    EvidenceExpired,
    StateDrift,
    GenerationDrift,
    ModelDrift,
    GraphDrift,
    TrustRotation,
    ScopeDrift,
    ObjectiveDrift,
    RegistryRevisionOrRevocation,
    PortfolioIntegrity,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseContextV2 {
    pub request: PromptExerciseRequestV1,
    pub current_graph_generation_digest: Digest32,
    pub current_trust_digest: Digest32,
    pub current_scope_digest: Digest32,
    pub current_objective_digest: Digest32,
    pub current_authority_epoch: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedPromptExerciseDecisionV2 {
    inner: v1::PromptExerciseDecisionV1,
    stale_reason: Option<PromptStaleReasonV2>,
    portfolio_audit_digest: Digest32,
}

impl VerifiedPromptExerciseDecisionV2 {
    #[must_use]
    pub fn as_v1(&self) -> &v1::PromptExerciseDecisionV1 {
        &self.inner
    }

    #[must_use]
    pub fn stale_reason(&self) -> Option<PromptStaleReasonV2> {
        self.stale_reason
    }

    #[must_use]
    pub fn portfolio_audit_digest(&self) -> Digest32 {
        self.portfolio_audit_digest
    }
}

impl Deref for VerifiedPromptExerciseDecisionV2 {
    type Target = v1::PromptExerciseDecisionV1;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

/// Revalidate graph/trust/policy context before entering the registry-bound
/// delivery compiler. The compiler performs the final live registry check.
pub fn verify_exercise_context_v2(
    portfolio: &VerifiedSelectedPromptPortfolioV2,
    context: PromptExerciseContextV2,
) -> Result<VerifiedPromptExerciseDecisionV2, VerifiedPromptError> {
    validate_selected_shape(&portfolio.inner)?;
    let request = &context.request;
    for (name, digest) in [
        ("current_state", request.current_state_digest),
        ("generation_vector", request.generation_vector_digest),
        ("exercise_policy", request.policy_digest),
        ("graph_generation", context.current_graph_generation_digest),
        ("trust", context.current_trust_digest),
        ("scope", context.current_scope_digest),
        ("objective", context.current_objective_digest),
    ] {
        ensure_digest(name, digest)?;
    }
    if request.now_unix_ms == 0 {
        return Err(VerifiedPromptError::PortfolioExpired);
    }

    let stale_reason = if request.now_unix_ms >= portfolio.receipt.valid_until_unix_ms {
        Some(PromptStaleReasonV2::PortfolioExpired)
    } else if request.now_unix_ms >= portfolio.evidence_valid_until_unix_ms
        || request.now_unix_ms >= portfolio.graph_valid_until_unix_ms
    {
        Some(PromptStaleReasonV2::EvidenceExpired)
    } else if request.current_state_digest != portfolio.state_digest {
        Some(PromptStaleReasonV2::StateDrift)
    } else if request.generation_vector_digest != portfolio.generation_vector_digest {
        Some(PromptStaleReasonV2::GenerationDrift)
    } else if request.model_tuple != portfolio.model_tuple
        || request.model_tuple.digest() != portfolio.model_tuple_digest
    {
        Some(PromptStaleReasonV2::ModelDrift)
    } else if context.current_graph_generation_digest != portfolio.graph_generation_digest {
        Some(PromptStaleReasonV2::GraphDrift)
    } else if context.current_trust_digest != portfolio.trust_digest
        || context.current_authority_epoch != portfolio.authority_epoch
    {
        Some(PromptStaleReasonV2::TrustRotation)
    } else if context.current_scope_digest != portfolio.scope_digest {
        Some(PromptStaleReasonV2::ScopeDrift)
    } else if context.current_objective_digest != portfolio.objective_digest {
        Some(PromptStaleReasonV2::ObjectiveDrift)
    } else {
        None
    };

    let decision = if portfolio.selected.is_empty() {
        PromptExerciseActionV1::NoIntervention
    } else if stale_reason.is_some() {
        PromptExerciseActionV1::RejectStale
    } else if portfolio.receipt.expected_utility_q32 > request.wait_value_q32 {
        PromptExerciseActionV1::Exercise
    } else {
        PromptExerciseActionV1::Wait
    };
    let receipt_digest = digest_exercise_receipt_v2(
        &portfolio.receipt.portfolio_id,
        request.decision_boundary,
        portfolio.receipt.expected_utility_q32,
        request.wait_value_q32,
        decision,
        request.policy_digest,
        portfolio.receipt.receipt_digest,
        portfolio.audit.audit_digest,
        stale_reason,
    );
    Ok(VerifiedPromptExerciseDecisionV2 {
        inner: v1::PromptExerciseDecisionV1 {
            factor_or_portfolio_id: portfolio.receipt.portfolio_id.clone(),
            decision_boundary: request.decision_boundary,
            exercise_now_value_q32: portfolio.receipt.expected_utility_q32,
            wait_value_q32: request.wait_value_q32,
            decision,
            policy_digest: request.policy_digest,
            receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        },
        stale_reason,
        portfolio_audit_digest: portfolio.audit.audit_digest,
    })
}

/// Final registry-bound exercise. This preserves typed availability errors
/// rather than collapsing every owner failure into an undifferentiated stale bit.
pub fn exercise_verified_v2(
    registry: &PromptRegistry,
    portfolio: &VerifiedSelectedPromptPortfolioV2,
    context: PromptExerciseContextV2,
) -> Result<VerifiedPromptExerciseDecisionV2, VerifiedPromptError> {
    let preliminary = verify_exercise_context_v2(portfolio, context.clone())?;
    if preliminary.decision != PromptExerciseActionV1::Exercise {
        return Ok(preliminary);
    }

    let request = &context.request;
    let snapshot = registry
        .snapshot_v2(request.generation_vector_digest, &request.model_tuple)
        .map_err(map_registry_error)?;
    let selected_factor_ids = portfolio
        .selected
        .iter()
        .map(|binding| binding.factor_id.clone())
        .collect::<Vec<_>>();
    let current = registry
        .read_compatible_v2(
            &snapshot,
            request.generation_vector_digest,
            &request.model_tuple,
            request.now_unix_ms,
            selected_factor_ids,
            MAX_CANONICAL_PROMPT_FACTORS as u32,
        )
        .map_err(map_registry_error)?;
    let current_by_realization = current
        .bindings
        .into_iter()
        .map(|binding| (binding.realization_id.clone(), binding))
        .collect::<BTreeMap<_, _>>();
    let exact = portfolio.selected.iter().all(|selected| {
        current_by_realization
            .get(&selected.realization.realization_id)
            .is_some_and(|current| {
                current.realization_id == selected.realization.realization_id
                    && current.digest() == selected.binding_digest
            })
    });
    if exact {
        return Ok(preliminary);
    }

    let stale_reason = Some(PromptStaleReasonV2::RegistryRevisionOrRevocation);
    let decision = PromptExerciseActionV1::RejectStale;
    let receipt_digest = digest_exercise_receipt_v2(
        &portfolio.receipt.portfolio_id,
        request.decision_boundary,
        portfolio.receipt.expected_utility_q32,
        request.wait_value_q32,
        decision,
        request.policy_digest,
        portfolio.receipt.receipt_digest,
        portfolio.audit.audit_digest,
        stale_reason,
    );
    Ok(VerifiedPromptExerciseDecisionV2 {
        inner: v1::PromptExerciseDecisionV1 {
            factor_or_portfolio_id: portfolio.receipt.portfolio_id.clone(),
            decision_boundary: request.decision_boundary,
            exercise_now_value_q32: portfolio.receipt.expected_utility_q32,
            wait_value_q32: request.wait_value_q32,
            decision,
            policy_digest: request.policy_digest,
            receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        },
        stale_reason,
        portfolio_audit_digest: portfolio.audit.audit_digest,
    })
}
