use codex_hepta_kg::KnowledgeNodeV2;
use codex_hepta_kg::KnowledgeProjectionInputV2;
use codex_hepta_kg::KnowledgeSupportV2;
use codex_hepta_kg::build_complete_generation;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_prompt_optimizer::canonical::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture ID")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

/// Exercise the real signed pricing and canonical selection boundaries.
pub(super) fn select_candidates(
    candidates: EnumeratedPromptCandidatesV1,
    now: u64,
    valid_until: u64,
) -> SelectedPromptPortfolioV1 {
    let scope = digest("scope:prompt-selection-fixture");
    let generator = SigningKey::from_bytes(&[71; 32]);
    let evaluator = SigningKey::from_bytes(&[72; 32]);
    let objective = candidates.receipt.objective_digest;
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 1,
        signers: [
            (
                "generator:fixture",
                &generator,
                LearningEvidenceRoleV1::Generator,
            ),
            (
                "evaluator:fixture",
                &evaluator,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ]
        .into_iter()
        .map(|(principal, signing, role)| {
            let public = signing.verifying_key().to_bytes();
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(principal),
                    credential_chain_digest: digest(principal),
                    signing_key_digest: Digest32::of_bytes(&public),
                    scope_digest: scope,
                    authority_epoch: 1,
                    authenticated_at: now,
                    expires_at: valid_until,
                },
                controller_id: id(principal),
                verifying_key: public,
                roles: vec![role],
                revoked_at: None,
            }
        })
        .collect(),
    })
    .expect("fixture trust");
    let sign = |role: LearningEvidenceRoleV1, label: &str, payload: &[u8]| {
        let (principal, signing) = match role {
            LearningEvidenceRoleV1::Generator => ("generator:fixture", &generator),
            LearningEvidenceRoleV1::Evaluator => ("evaluator:fixture", &evaluator),
            _ => panic!("unsupported fixture evidence role"),
        };
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(label),
            principal_id: id(principal),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 1,
            issued_at: now,
            expires_at: valid_until,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
        evidence
    };
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: candidates.receipt.set_id.clone(),
        state_digest: candidates.receipt.state_digest,
        generator_id: id("prompt.optimizer"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: candidates.receipt.selection_grammar_digest,
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        candidates_digest: candidates.candidates_digest,
        candidate_count: u32::try_from(candidates.candidates.len()).expect("fixture count"),
        omitted_count_bound: candidates.omitted_count,
        canonical_order_digest: candidates.canonical_order_digest,
        complete_for_generator: true,
    };
    let signed_completeness = sign(
        LearningEvidenceRoleV1::Generator,
        "evidence:completeness",
        &candidate_completeness_signing_payload_v1(&completeness).expect("completeness payload"),
    );
    let pricing = candidates
        .candidates
        .iter()
        .map(|candidate| {
            let label = format!("evidence:pricing:{}", candidate.factor_id);
            let mut evidence = PromptPricingEvidenceV1 {
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
                support_audit_digest: digest("pricing-audit"),
                evidence: sign(LearningEvidenceRoleV1::Evaluator, &label, b"pending"),
            };
            evidence.evidence = sign(
                LearningEvidenceRoleV1::Evaluator,
                &label,
                &pricing_evidence_signing_payload_v1(&evidence),
            );
            evidence
        })
        .collect();
    let graph = build_complete_generation(
        Generation::new(1).expect("fixture generation"),
        KnowledgeProjectionInputV2 {
            source_snapshot_digest: candidates.registry_snapshot.registry_digest,
            generation_vector_digest: candidates.generation_vector_digest,
            graph_profile_digest: digest("graph-profile"),
            complete_source_cut: true,
            nodes: candidates
                .candidates
                .iter()
                .map(|candidate| KnowledgeNodeV2 {
                    node_id: candidate.factor_id.clone(),
                    node_kind_id: id("kind:prompt-factor"),
                    payload_digest: candidate.binding_digest,
                    supports: vec![KnowledgeSupportV2 {
                        source_id: candidate.factor_id.clone(),
                        source_revision: Revision::new(1).expect("fixture revision"),
                        source_fact_digest: candidate.binding_digest,
                        validity_digest: digest("graph-support-validity"),
                        valid_from_unix_seconds: None,
                        valid_to_unix_seconds: None,
                        tombstoned: false,
                    }],
                })
                .collect(),
            edges: Vec::new(),
        },
    )
    .expect("fixture graph");
    let priced = price_factors_v1(
        candidates,
        &completeness,
        &signed_completeness,
        pricing,
        &verifier,
        &PromptPricingPolicyV1 {
            policy_id: id("pricing-policy:fixture"),
            token_cost_per_token_q32: FixedQ32::ZERO,
            latency_cost_per_micro_q32: FixedQ32::ZERO,
            interference_cost_per_ppm_q32: FixedQ32::ZERO,
            downside_weight_q32: FixedQ32::ZERO,
            minimum_support_count: 1,
            maximum_interference_ppm: 1_000_000,
        },
        now,
    )
    .expect("signed fixture pricing");
    select_portfolio_v1(
        &priced,
        &graph,
        Vec::new(),
        &verifier,
        PromptPortfolioRequestV1 {
            portfolio_id: id("portfolio:fixture"),
            graph_query_id: id("query:fixture"),
            token_budget: MAX_CANONICAL_TOKEN_BUDGET,
            maximum_selected_factors: MAX_CANONICAL_SELECTED_FACTORS,
            requested_valid_until_unix_ms: valid_until,
        },
        now,
    )
    .expect("canonical fixture selection")
}
