#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedEnumeratedPromptCandidatesV2 {
    inner: v1::EnumeratedPromptCandidatesV1,
    verification_digest: Digest32,
}

impl VerifiedEnumeratedPromptCandidatesV2 {
    pub fn try_from_v1(
        inner: v1::EnumeratedPromptCandidatesV1,
    ) -> Result<Self, VerifiedPromptError> {
        validate_enumerated(&inner)?;
        let verification_digest = digest_verified_enumerated(&inner);
        Ok(Self {
            inner,
            verification_digest,
        })
    }

    #[must_use]
    pub fn as_v1(&self) -> &v1::EnumeratedPromptCandidatesV1 {
        &self.inner
    }

    #[must_use]
    pub fn verification_digest(&self) -> Digest32 {
        self.verification_digest
    }
}

impl Deref for VerifiedEnumeratedPromptCandidatesV2 {
    type Target = v1::EnumeratedPromptCandidatesV1;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub fn enumerate_factors_verified_v2(
    registry: &PromptRegistry,
    request: PromptEnumerationRequestV1,
) -> Result<VerifiedEnumeratedPromptCandidatesV2, VerifiedPromptError> {
    VerifiedEnumeratedPromptCandidatesV2::try_from_v1(v1::enumerate_factors_v1(
        registry, request,
    )?)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedPricedPromptCandidatesV2 {
    inner: v1::PricedPromptCandidatesV1,
    context: PromptEvidenceContextV2,
    generator_principal_id: StableId,
    generator_controller_id: StableId,
    evaluator_principal_ids: Vec<StableId>,
    evaluator_controller_ids: Vec<StableId>,
    oldest_evidence_issued_at: u64,
    evidence_valid_until_unix_ms: u64,
    evidence_binding_digest: Digest32,
}

impl VerifiedPricedPromptCandidatesV2 {
    #[must_use]
    pub fn as_v1(&self) -> &v1::PricedPromptCandidatesV1 {
        &self.inner
    }

    #[must_use]
    pub fn context(&self) -> &PromptEvidenceContextV2 {
        &self.context
    }

    #[must_use]
    pub fn evidence_valid_until_unix_ms(&self) -> u64 {
        self.evidence_valid_until_unix_ms
    }

    #[must_use]
    pub fn evidence_binding_digest(&self) -> Digest32 {
        self.evidence_binding_digest
    }

    #[must_use]
    pub fn generator_principal_id(&self) -> &StableId {
        &self.generator_principal_id
    }

    #[must_use]
    pub fn generator_controller_id(&self) -> &StableId {
        &self.generator_controller_id
    }

    #[must_use]
    pub fn evaluator_principal_ids(&self) -> &[StableId] {
        &self.evaluator_principal_ids
    }

    #[must_use]
    pub fn evaluator_controller_ids(&self) -> &[StableId] {
        &self.evaluator_controller_ids
    }
}

impl Deref for VerifiedPricedPromptCandidatesV2 {
    type Target = v1::PricedPromptCandidatesV1;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

pub fn price_factors_verified_v2(
    candidates: VerifiedEnumeratedPromptCandidatesV2,
    completeness: PromptCompletenessEvidenceV2,
    pricing_evidence: Vec<PromptPricingEvidenceV2>,
    verifier: &LearningEvidenceVerifierV1,
    policy: &PromptPricingPolicyV1,
    now_unix_ms: u64,
) -> Result<VerifiedPricedPromptCandidatesV2, VerifiedPromptError> {
    if now_unix_ms == 0 {
        return Err(VerifiedPromptError::EvidenceExpired);
    }
    candidates
        .inner
        .registry_snapshot
        .validate()
        .map_err(map_registry_error)?;
    let policy_digest = policy.digest().map_err(VerifiedPromptError::Legacy)?;
    validate_evidence_context(
        &completeness.context,
        &candidates,
        verifier,
        policy_digest,
    )?;
    let completeness_digest = validate_completeness_binding(
        &candidates,
        &completeness.context,
        &completeness.receipt,
    )?;
    let completeness_payload = completeness_evidence_signing_payload_v2(&completeness);
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &completeness.evidence,
            &completeness_payload,
            now_unix_ms,
        )
        .map_err(|error| VerifiedPromptError::Evidence(format!("{error:?}")))?;

    let mut evidence_by_factor = BTreeMap::new();
    for evidence in pricing_evidence {
        let factor_id = evidence.factor_id.clone();
        if evidence_by_factor.insert(factor_id.clone(), evidence).is_some() {
            return Err(VerifiedPromptError::DuplicateEvidence(
                factor_id.to_string(),
            ));
        }
    }

    let mut rows = Vec::with_capacity(candidates.candidates.len());
    let mut evaluator_principals = BTreeSet::new();
    let mut evaluator_controllers = BTreeSet::new();
    let mut oldest_issued_at = completeness.evidence.issued_at;
    let mut valid_until = completeness.evidence.expires_at;
    let mut evidence_payload_digests = vec![completeness.evidence.payload_digest];

    for candidate in &candidates.candidates {
        let evidence = evidence_by_factor.remove(&candidate.factor_id).ok_or_else(|| {
            VerifiedPromptError::MissingEvidence(candidate.factor_id.to_string())
        })?;
        validate_pricing_evidence_v2(
            &candidates,
            candidate,
            &completeness.context,
            &evidence,
            policy,
        )?;
        let payload = pricing_evidence_signing_payload_v2(&evidence);
        let evaluator = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &evidence.evidence,
                &payload,
                now_unix_ms,
            )
            .map_err(|error| VerifiedPromptError::Evidence(format!("{error:?}")))?;
        verify_signed_independent_roles_v1(&generator, &evaluator, now_unix_ms)
            .map_err(|error| VerifiedPromptError::EvidenceIndependence(format!("{error:?}")))?;

        evaluator_principals.insert(evaluator.principal().principal_id.clone());
        evaluator_controllers.insert(evaluator.controller_id().clone());
        oldest_issued_at = oldest_issued_at.min(evidence.evidence.issued_at);
        valid_until = valid_until.min(evidence.evidence.expires_at);
        if let Some(expires) = candidate.realization.expires_unix_ms {
            valid_until = valid_until.min(expires);
        }
        evidence_payload_digests.push(evaluator.payload_digest());

        let token_cost = candidate.realization.token_cost;
        let mut net = evidence.expected_incremental_utility_q32;
        let downside_penalty = policy
            .downside_weight_q32
            .checked_mul(evidence.downside_q32)
            .map_err(|_| VerifiedPromptError::Arithmetic)?;
        for cost in [
            downside_penalty,
            scale_rate(policy.token_cost_per_token_q32, u64::from(token_cost))?,
            scale_rate(
                policy.latency_cost_per_micro_q32,
                evidence.latency_cost_micros,
            )?,
            scale_rate(
                policy.interference_cost_per_ppm_q32,
                u64::from(evidence.interference_ppm),
            )?,
            evidence.context_crowding_cost_q32,
            evidence.privacy_cost_q32,
            evidence.instability_cost_q32,
            evidence.future_context_option_cost_q32,
        ] {
            net = net
                .checked_sub(cost)
                .map_err(|_| VerifiedPromptError::Arithmetic)?;
        }
        let confidence_interval = v1::PromptConfidenceIntervalV1 {
            lower_q32: evidence.confidence_lower_q32,
            upper_q32: evidence.confidence_upper_q32,
            support_count: evidence.support_count,
            support_audit_digest: evidence.support_audit_digest,
        };
        let receipt_digest = digest_pricing_receipt(
            &candidate.factor_id,
            candidates.receipt.state_digest,
            net,
            evidence.downside_q32,
            token_cost,
            evidence.latency_cost_micros,
            evidence.interference_ppm,
            &confidence_interval,
            policy_digest,
            candidate.binding_digest,
        );
        rows.push(v1::PricedPromptCandidateV1 {
            binding: candidate.clone(),
            pricing: v1::PromptPricingReceiptV1 {
                factor_id: candidate.factor_id.clone(),
                state_digest: candidates.receipt.state_digest,
                expected_utility_q32: net,
                downside_q32: evidence.downside_q32,
                token_cost,
                latency_cost_micros: evidence.latency_cost_micros,
                interference_ppm: evidence.interference_ppm,
                confidence_interval,
                receipt_digest,
                authority: AuthorityPosture::DENY_ALL,
            },
            net_utility_q32: net,
        });
    }
    if let Some(extra) = evidence_by_factor.keys().next() {
        return Err(VerifiedPromptError::MissingEvidence(format!(
            "unknown factor {extra}"
        )));
    }
    if valid_until <= now_unix_ms {
        return Err(VerifiedPromptError::EvidenceExpired);
    }

    let pricing_set_digest = digest_pricing_set(&rows, policy_digest);
    let inner = v1::PricedPromptCandidatesV1 {
        candidates: candidates.inner,
        completeness_digest,
        pricing_policy_digest: policy_digest,
        rows,
        pricing_set_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    validate_priced(&inner)?;
    evidence_payload_digests.sort();
    let generator_principal_id = generator.principal().principal_id.clone();
    let generator_controller_id = generator.controller_id().clone();
    let evaluator_principal_ids = evaluator_principals.into_iter().collect::<Vec<_>>();
    let evaluator_controller_ids = evaluator_controllers.into_iter().collect::<Vec<_>>();
    let evidence_binding_digest = digest_evidence_binding(
        &completeness.context,
        &generator_principal_id,
        &generator_controller_id,
        &evaluator_principal_ids,
        &evaluator_controller_ids,
        generator.payload_digest(),
        &evidence_payload_digests,
        valid_until,
    );
    Ok(VerifiedPricedPromptCandidatesV2 {
        inner,
        context: completeness.context,
        generator_principal_id,
        generator_controller_id,
        evaluator_principal_ids,
        evaluator_controller_ids,
        oldest_evidence_issued_at: oldest_issued_at,
        evidence_valid_until_unix_ms: valid_until,
        evidence_binding_digest,
    })
}
