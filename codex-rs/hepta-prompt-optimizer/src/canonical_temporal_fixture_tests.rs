use super::*;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_realization_binding;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub(super) struct Fixture {
    _temporary: tempfile::TempDir,
    pub(super) registry: DurablePromptRegistry,
    pub(super) priced: PricedPromptCandidatesV1,
    pub(super) verifier: LearningEvidenceVerifierV1,
    evaluator: SigningKey,
}

pub(super) fn fixture() -> Fixture {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error:?}"));
    let (mut registry, tuple, authority, key, wall_now) =
        tests::registry_fixture(&temporary.path().join("registry"), &[1]);
    let mut factor = registry
        .registry()
        .unwrap_or_else(|error| panic!("registry: {error:?}"))
        .factor(&id("factor:a"))
        .unwrap_or_else(|| panic!("missing factor a"))
        .clone();
    factor.factor_id = id("factor:b");
    factor.content_digest = digest("factor:b");
    factor.lifecycle = Lifecycle::Draft;
    registry
        .register_factor(factor.clone())
        .unwrap_or_else(|error| panic!("factor b: {error:?}"));
    let sign_grant = |binding, grant_id: &str, nonce| {
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "review-authority:prompt".to_owned(),
            authority_epoch: 1,
            grant_id: grant_id.to_owned(),
            nonce: [nonce; 32],
            binding,
            not_before_unix_ms: wall_now.saturating_sub(1_000),
            expires_at_unix_ms: wall_now + 30_000,
        };
        SignedFinalUseGrant {
            signature: key
                .sign(
                    &grant
                        .signing_bytes()
                        .unwrap_or_else(|error| panic!("grant bytes: {error:?}")),
                )
                .to_bytes()
                .to_vec(),
            grant,
        }
    };
    let scope = digest("scope:prompt");
    let admission_evidence = digest("evidence:prompt");
    let admission =
        final_use_admission_binding(&factor, &id("reviewer:1"), scope, admission_evidence)
            .unwrap_or_else(|error| panic!("admission binding: {error:?}"));
    registry
        .admit_factor_final_use(
            &authority,
            &sign_grant(admission, "admission:temporal:b", /*nonce*/ 91),
            &factor.factor_id,
            scope,
            admission_evidence,
        )
        .unwrap_or_else(|error| panic!("admit b: {error:?}"));
    let enumeration_request = PromptEnumerationRequestV1 {
        set_id: id("set:temporal"),
        objective_digest: digest("objective"),
        state_digest: digest("state"),
        generation_vector_digest: digest("generation-vector"),
        model_tuple: tuple,
        now_unix_ms: 1_000,
        required_factor_ids: vec![id("factor:a")],
        maximum_candidates: 8,
        selection_grammar_digest: digest("grammar"),
    };
    let initial = enumerate_factors_v1(
        registry
            .registry()
            .unwrap_or_else(|error| panic!("registry: {error:?}")),
        enumeration_request.clone(),
    )
    .unwrap_or_else(|error| panic!("enumerate a: {error:?}"));
    let mut realization = initial.candidates[0].realization.clone();
    realization.realization_id = id("realization:b");
    realization.factor_id = factor.factor_id.clone();
    let admitted_factor = registry
        .registry()
        .unwrap_or_else(|error| panic!("registry: {error:?}"))
        .factor(&factor.factor_id)
        .unwrap_or_else(|| panic!("missing admitted b"));
    let actor = id("publisher:prompt");
    let realization_scope = digest("scope:realization:prompt");
    let realization_binding = final_use_realization_binding(
        admitted_factor,
        &actor,
        realization_scope,
        &realization,
        None,
    )
    .unwrap_or_else(|error| panic!("realization binding: {error:?}"));
    registry
        .register_realization_payload_final_use_v2(
            &authority,
            &sign_grant(
                realization_binding,
                "realization:temporal:b",
                /*nonce*/ 92,
            ),
            &actor,
            realization_scope,
            realization,
            b"payload".to_vec(),
            None,
        )
        .unwrap_or_else(|error| panic!("register b payload: {error:?}"));
    let candidates = enumerate_factors_v1(
        registry
            .registry()
            .unwrap_or_else(|error| panic!("registry: {error:?}")),
        PromptEnumerationRequestV1 {
            required_factor_ids: vec![id("factor:a"), id("factor:b")],
            ..enumeration_request
        },
    )
    .unwrap_or_else(|error| panic!("actual two-factor enumeration: {error:?}"));
    let generator = SigningKey::from_bytes(&[81; 32]);
    let evaluator = SigningKey::from_bytes(&[82; 32]);
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        signers: [
            ("generator", &generator, LearningEvidenceRoleV1::Generator),
            ("evaluator", &evaluator, LearningEvidenceRoleV1::Evaluator),
        ]
        .into_iter()
        .map(|(principal, key, role)| {
            let public = key.verifying_key().to_bytes();
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(principal),
                    credential_chain_digest: digest(principal),
                    signing_key_digest: Digest32::of_bytes(&public),
                    scope_digest: digest("scope"),
                    authority_epoch: 1,
                    authenticated_at: 1,
                    expires_at: 10_000,
                },
                controller_id: id(principal),
                verifying_key: public,
                roles: vec![role],
                revoked_at: None,
            }
        })
        .collect(),
    })
    .unwrap_or_else(|error| panic!("trust: {error:?}"));
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: candidates.receipt.set_id.clone(),
        state_digest: candidates.receipt.state_digest,
        generator_id: id("prompt.optimizer"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: candidates.receipt.selection_grammar_digest,
        hard_filter_digest: digest("filters"),
        truncation_digest: digest("truncation"),
        candidates_digest: candidates.candidates_digest,
        candidate_count: 2,
        omitted_count_bound: 0,
        canonical_order_digest: candidates.canonical_order_digest,
        complete_for_generator: true,
    };
    let completeness_evidence = sign(
        &verifier,
        &generator,
        LearningEvidenceRoleV1::Generator,
        &candidate_completeness_signing_payload_v1(&completeness)
            .unwrap_or_else(|error| panic!("completeness: {error:?}")),
    );
    let rows = candidates
        .candidates
        .iter()
        .map(|candidate| {
            let mut row = PromptPricingEvidenceV1 {
                factor_id: candidate.factor_id.clone(),
                state_digest: candidates.receipt.state_digest,
                model_tuple_digest: candidates.model_tuple.digest(),
                expected_incremental_utility_q32: FixedQ32::ONE,
                downside_q32: FixedQ32::ZERO,
                confidence_lower_q32: FixedQ32::ONE,
                confidence_upper_q32: FixedQ32::ONE,
                support_count: 1,
                latency_cost_micros: 0,
                interference_ppm: 0,
                context_crowding_cost_q32: FixedQ32::ZERO,
                privacy_cost_q32: FixedQ32::ZERO,
                instability_cost_q32: FixedQ32::ZERO,
                future_context_option_cost_q32: FixedQ32::ZERO,
                support_audit_digest: digest("audit"),
                evidence: sign(
                    &verifier,
                    &evaluator,
                    LearningEvidenceRoleV1::Evaluator,
                    b"pending",
                ),
            };
            row.evidence = sign(
                &verifier,
                &evaluator,
                LearningEvidenceRoleV1::Evaluator,
                &pricing_evidence_signing_payload_v1(&row),
            );
            row
        })
        .collect();
    let priced = price_factors_v1(
        candidates,
        &completeness,
        &completeness_evidence,
        rows,
        &verifier,
        &PromptPricingPolicyV1 {
            policy_id: id("policy:temporal"),
            token_cost_per_token_q32: FixedQ32::ZERO,
            latency_cost_per_micro_q32: FixedQ32::ZERO,
            interference_cost_per_ppm_q32: FixedQ32::ZERO,
            downside_weight_q32: FixedQ32::ZERO,
            minimum_support_count: 1,
            maximum_interference_ppm: 1_000_000,
        },
        1_000,
    )
    .unwrap_or_else(|error| panic!("actual signed pricing: {error:?}"));
    Fixture {
        _temporary: temporary,
        registry,
        priced,
        verifier,
        evaluator,
    }
}

impl Fixture {
    pub(super) fn pair_evidence(
        &self,
        graph: &KnowledgeGenerationV2,
    ) -> PromptPairUtilityEvidenceV1 {
        let mut pair = PromptPairUtilityEvidenceV1 {
            left_factor_id: id("factor:a"),
            right_factor_id: id("factor:b"),
            state_digest: self.priced.candidates.receipt.state_digest,
            graph_generation_digest: graph.generation_digest,
            edge_validity_digest: graph.edges[0].validity_digest,
            marginal_utility_q32: FixedQ32::ONE,
            confidence_lower_q32: FixedQ32::ONE,
            confidence_upper_q32: FixedQ32::ONE,
            support_audit_digest: digest("pair-audit"),
            evidence: sign(
                &self.verifier,
                &self.evaluator,
                LearningEvidenceRoleV1::Evaluator,
                b"pending",
            ),
        };
        pair.evidence = sign(
            &self.verifier,
            &self.evaluator,
            LearningEvidenceRoleV1::Evaluator,
            &pair_utility_evidence_signing_payload_v1(&pair),
        );
        pair
    }
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let principal = match role {
        LearningEvidenceRoleV1::Generator => "generator",
        LearningEvidenceRoleV1::Evaluator => "evaluator",
        _ => panic!("unsupported fixture role"),
    };
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(principal),
        principal_id: id(principal),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        issued_at: 75,
        expires_at: 10_000,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}
