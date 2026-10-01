use super::*;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture ID")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn actual_signed_pricing_preserves_expiry_and_known_revocation_through_selection() {
    for revoked_at in [None, Some(150)] {
        let temporary = tempfile::tempdir().expect("tempdir");
        let (registry, tuple, _authority, _key, _wall_now) =
            tests::registry_fixture(&temporary.path().join("registry"), &[1]);
        let candidates = enumerate_factors_v1(
            registry.registry().expect("registry view"),
            PromptEnumerationRequestV1 {
                set_id: id("set:signed-horizon"),
                objective_digest: digest("objective"),
                state_digest: digest("state"),
                generation_vector_digest: digest("generation-vector"),
                model_tuple: tuple,
                now_unix_ms: 100,
                required_factor_ids: vec![id("factor:a")],
                maximum_candidates: 8,
                selection_grammar_digest: digest("grammar"),
            },
        )
        .expect("actual registry enumeration");
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
                        expires_at: 5_000,
                    },
                    controller_id: id(principal),
                    verifying_key: public,
                    roles: vec![role],
                    revoked_at,
                }
            })
            .collect(),
        })
        .expect("trust");
        let sign = |role: LearningEvidenceRoleV1, payload: &[u8]| {
            let (principal, key) = match role {
                LearningEvidenceRoleV1::Generator => ("generator", &generator),
                LearningEvidenceRoleV1::Evaluator => ("evaluator", &evaluator),
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
                expires_at: 200,
                payload_digest: Digest32::of_bytes(payload),
                signature: [0; 64],
            };
            evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
            evidence
        };
        let completeness = CandidateSetCompletenessReceiptV1 {
            set_id: candidates.receipt.set_id.clone(),
            state_digest: candidates.receipt.state_digest,
            generator_id: id("prompt.optimizer"),
            generator_code_digest: digest("generator-code"),
            grammar_digest: candidates.receipt.selection_grammar_digest,
            hard_filter_digest: digest("filters"),
            truncation_digest: digest("truncation"),
            candidates_digest: candidates.candidates_digest,
            candidate_count: 1,
            omitted_count_bound: 0,
            canonical_order_digest: candidates.canonical_order_digest,
            complete_for_generator: true,
        };
        let signed_completeness = sign(
            LearningEvidenceRoleV1::Generator,
            &candidate_completeness_signing_payload_v1(&completeness)
                .expect("completeness payload"),
        );
        let mut pricing = PromptPricingEvidenceV1 {
            factor_id: id("factor:a"),
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
            evidence: sign(LearningEvidenceRoleV1::Evaluator, b"pending"),
        };
        pricing.evidence = sign(
            LearningEvidenceRoleV1::Evaluator,
            &pricing_evidence_signing_payload_v1(&pricing),
        );
        let priced = price_factors_v1(
            candidates,
            &completeness,
            &signed_completeness,
            vec![pricing],
            &verifier,
            &PromptPricingPolicyV1 {
                policy_id: id("policy"),
                token_cost_per_token_q32: FixedQ32::ZERO,
                latency_cost_per_micro_q32: FixedQ32::ZERO,
                interference_cost_per_ppm_q32: FixedQ32::ZERO,
                downside_weight_q32: FixedQ32::ZERO,
                minimum_support_count: 1,
                maximum_interference_ppm: 1_000_000,
            },
            100,
        )
        .expect("actual signed pricing");
        let horizon = revoked_at.unwrap_or(201);
        let request = PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:signed-horizon"),
            graph_query_id: id("query:signed-horizon"),
            token_budget: 8,
            maximum_selected_factors: 1,
            requested_valid_until_unix_ms: 5_000,
        };
        let graph = tests::graph(&["factor:a"], Vec::new());
        let selected = select_portfolio_v1(
            &priced,
            &graph,
            Vec::new(),
            &verifier,
            request.clone(),
            horizon - 1,
        )
        .expect("last valid selection millisecond");
        assert_eq!(selected.receipt.valid_until_unix_ms, horizon);
        assert_eq!(
            select_portfolio_v1(
                &priced,
                &graph,
                Vec::new(),
                &verifier,
                request.clone(),
                horizon
            ),
            Err(CanonicalPromptError::PortfolioExpired)
        );
        assert_eq!(
            select_portfolio_v1(
                &priced,
                &graph,
                Vec::new(),
                &verifier,
                request,
                /*now_unix_ms*/ 99
            ),
            Err(CanonicalPromptError::InvalidTime)
        );
    }
}
