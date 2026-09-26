fn direct_priced(rows: &[(u32, i64)]) -> VerifiedPricedPromptCandidatesV2 {
    let tokens = rows.iter().map(|(tokens, _)| *tokens).collect::<Vec<_>>();
    let candidates = verified_candidates(&tokens);
    let policy_digest = digest("direct-policy");
    let priced_rows = rows
        .iter()
        .zip(&candidates.candidates)
        .map(|((token_cost, utility), binding)| {
            let confidence = v1::PromptConfidenceIntervalV1 {
                lower_q32: FixedQ32::from_raw(*utility),
                upper_q32: FixedQ32::from_raw(*utility),
                support_count: 1,
                support_audit_digest: digest("direct-support"),
            };
            let receipt_digest = digest_pricing_receipt(
                &binding.factor_id,
                candidates.receipt.state_digest,
                FixedQ32::from_raw(*utility),
                FixedQ32::ZERO,
                *token_cost,
                0,
                0,
                &confidence,
                policy_digest,
                binding.binding_digest,
            );
            v1::PricedPromptCandidateV1 {
                binding: (*binding).clone(),
                pricing: v1::PromptPricingReceiptV1 {
                    factor_id: binding.factor_id.clone(),
                    state_digest: candidates.receipt.state_digest,
                    expected_utility_q32: FixedQ32::from_raw(*utility),
                    downside_q32: FixedQ32::ZERO,
                    token_cost: *token_cost,
                    latency_cost_micros: 0,
                    interference_ppm: 0,
                    confidence_interval: confidence,
                    receipt_digest,
                    authority: AuthorityPosture::DENY_ALL,
                },
                net_utility_q32: FixedQ32::from_raw(*utility),
            }
        })
        .collect::<Vec<_>>();
    let pricing_set_digest = digest_pricing_set(&priced_rows, policy_digest);
    let inner = v1::PricedPromptCandidatesV1 {
        candidates: candidates.inner,
        completeness_digest: digest("direct-completeness"),
        pricing_policy_digest: policy_digest,
        rows: priced_rows,
        pricing_set_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    validate_priced(&inner).unwrap_or_else(|error| panic!("direct pricing: {error}"));
    VerifiedPricedPromptCandidatesV2 {
        inner,
        context: PromptEvidenceContextV2 {
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            candidate_set_digest: digest("candidate-context"),
            registry_snapshot_digest: digest("snapshot-context"),
            generation_vector_digest: digest("generation"),
            model_tuple_digest: tuple().digest(),
            selection_grammar_digest: digest("grammar"),
            generator_code_digest: digest("generator-code"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("truncation"),
            pricing_policy_digest: policy_digest,
        },
        generator_principal_id: id("principal:generator"),
        generator_controller_id: id("controller:generator"),
        evaluator_principal_ids: vec![id("principal:evaluator")],
        evaluator_controller_ids: vec![id("controller:evaluator")],
        oldest_evidence_issued_at: 1,
        evidence_valid_until_unix_ms: 10_000,
        evidence_binding_digest: digest("evidence-binding"),
    }
}
