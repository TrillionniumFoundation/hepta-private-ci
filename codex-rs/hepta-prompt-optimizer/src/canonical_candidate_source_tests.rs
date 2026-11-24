use super::*;

fn price_policy() -> PromptPricingPolicyV1 {
    PromptPricingPolicyV1 {
        policy_id: id("policy:temporal"),
        token_cost_per_token_q32: FixedQ32::ZERO,
        latency_cost_per_micro_q32: FixedQ32::ZERO,
        interference_cost_per_ppm_q32: FixedQ32::ZERO,
        downside_weight_q32: FixedQ32::ZERO,
        minimum_support_count: 1,
        maximum_interference_ppm: 0,
    }
}

fn authenticated_price_inputs(
    candidates: &EnumeratedPromptCandidatesV1,
    verifier: &LearningEvidenceVerifierV1,
) -> (
    CandidateSetCompletenessReceiptV1,
    SignedLearningEvidenceV1,
    Vec<PromptPricingEvidenceV1>,
) {
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: candidates.receipt.set_id.clone(),
        state_digest: candidates.receipt.state_digest,
        generator_id: id("prompt.optimizer"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: candidates.receipt.selection_grammar_digest,
        hard_filter_digest: digest("filters"),
        truncation_digest: digest("truncation"),
        candidates_digest: candidates.candidates_digest,
        candidate_count: u32::try_from(candidates.candidates.len()).expect("bounded candidates"),
        omitted_count_bound: candidates.omitted_count,
        canonical_order_digest: candidates.canonical_order_digest,
        complete_for_generator: true,
    };
    let proof = temporal::sign_temporal_evidence(
        verifier,
        "generator",
        LearningEvidenceRoleV1::Generator,
        7,
        &candidate_completeness_signing_payload_v1(&completeness).expect("complete signing bytes"),
    );
    let prices = candidates
        .candidates
        .iter()
        .map(|candidate| {
            let utility = FixedQ32::from_raw(100);
            let mut evidence = PromptPricingEvidenceV1 {
                factor_id: candidate.factor_id.clone(),
                state_digest: candidates.receipt.state_digest,
                model_tuple_digest: candidates.model_tuple.digest(),
                expected_incremental_utility_q32: utility,
                downside_q32: FixedQ32::ZERO,
                confidence_lower_q32: utility,
                confidence_upper_q32: utility,
                support_count: 1,
                latency_cost_micros: 0,
                interference_ppm: 0,
                context_crowding_cost_q32: FixedQ32::ZERO,
                privacy_cost_q32: FixedQ32::ZERO,
                instability_cost_q32: FixedQ32::ZERO,
                future_context_option_cost_q32: FixedQ32::ZERO,
                support_audit_digest: digest("support-audit"),
                evidence: proof.clone(),
            };
            evidence.evidence = temporal::sign_temporal_evidence(
                verifier,
                "evaluator",
                LearningEvidenceRoleV1::Evaluator,
                8,
                &pricing_evidence_signing_payload_v1(&evidence),
            );
            evidence
        })
        .collect();
    (completeness, proof, prices)
}

fn rehash_candidate_receipt(candidates: &mut EnumeratedPromptCandidatesV1) {
    candidates.receipt.receipt_digest = digest_candidate_receipt(
        &candidates.receipt.set_id,
        candidates.receipt.objective_digest,
        candidates.receipt.state_digest,
        candidates.registry_snapshot.registry_digest,
        candidates.registry_snapshot.snapshot_digest,
        candidates.model_tuple.digest(),
        candidates.receipt.selection_grammar_digest,
        &candidates.receipt.candidate_factor_ids,
        candidates.candidates_digest,
        candidates.canonical_order_digest,
        candidates.omitted_count,
    );
}

#[test]
fn authenticated_candidate_proofs_cannot_be_reused_for_mutated_public_inputs() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _tuple, authority, signing_key, now) =
        registry_fixture(&temp.path().join("registry"), &[1]);
    register_second_factor(&mut registry, &authority, &signing_key, now);
    let (priced, verifier) = temporal::authentic_temporal_prices(&registry);
    let (completeness, proof, prices) = authenticated_price_inputs(&priced.candidates, &verifier);
    price_factors_v1(
        priced.candidates.clone(),
        &completeness,
        &proof,
        prices.clone(),
        &verifier,
        &price_policy(),
        100,
    )
    .expect("unchanged real generator and evaluator proofs remain valid");
    let graph = graph(&["factor:a", "factor:b"], Vec::new());
    for tamper in [
        "snapshot-checksum",
        "snapshot-owner",
        "snapshot-revision",
        "lifecycle-frontier",
        "revocation-frontier",
        "model",
        "vector",
        "candidate-token",
        "candidate-binding",
        "candidate-order",
        "candidate-receipt",
        "candidate-factor-source",
        "candidate-id-list",
    ] {
        let mut candidates = priced.candidates.clone();
        match tamper {
            "snapshot-checksum" => {
                candidates.registry_snapshot.snapshot_digest = digest("wrong checksum")
            }
            "snapshot-owner" => {
                candidates.registry_snapshot.registry_digest = digest("other owner")
            }
            "snapshot-revision" => {
                candidates.registry_snapshot.revision = candidates
                    .registry_snapshot
                    .revision
                    .next()
                    .expect("revision")
            }
            "lifecycle-frontier" => candidates.registry_snapshot.lifecycle_frontier -= 1,
            "revocation-frontier" => candidates.registry_snapshot.revocation_frontier += 1,
            "model" => candidates.model_tuple.locale_id = id("locale:other"),
            "vector" => candidates.generation_vector_digest = digest("other vector"),
            "candidate-token" => {
                candidates.candidates[0].realization.token_cost += 1;
                candidates.candidates[0].binding_digest =
                    candidates.candidates[0].realization.digest();
            }
            "candidate-binding" => {
                candidates.candidates[0].binding_digest = digest("other binding")
            }
            "candidate-order" => candidates.candidates.reverse(),
            "candidate-receipt" => candidates.receipt.receipt_digest = digest("other receipt"),
            "candidate-factor-source" => {
                candidates.candidates[1].factor_id = id("factor:unregistered");
                candidates.candidates[1].realization.factor_id = id("factor:unregistered");
                candidates.candidates[1].binding_digest =
                    candidates.candidates[1].realization.digest();
            }
            "candidate-id-list" => candidates.receipt.candidate_factor_ids.reverse(),
            _ => unreachable!(),
        }
        let snapshot_tamper = matches!(
            tamper,
            "snapshot-owner" | "snapshot-revision" | "lifecycle-frontier" | "revocation-frontier"
        );
        if snapshot_tamper {
            // A valid public checksum still cannot replace the factory snapshot.
            candidates.registry_snapshot.snapshot_digest =
                candidates.registry_snapshot.compute_snapshot_digest();
            rehash_candidate_receipt(&mut candidates);
            candidates
                .registry_snapshot
                .validate()
                .expect("self-consistent forged snapshot");
        }
        let pricing_result = price_factors_v1(
            candidates.clone(),
            &completeness,
            &proof,
            prices.clone(),
            &verifier,
            &price_policy(),
            100,
        );
        let mut altered = priced.clone();
        altered.candidates = candidates;
        let selection_result = select_portfolio_v1(
            &altered,
            &graph,
            Vec::new(),
            &verifier,
            source::selection_request(),
            100,
        );
        for rejected in [pricing_result.map(|_| ()), selection_result.map(|_| ())] {
            let expected =
                if snapshot_tamper || matches!(tamper, "snapshot-checksum" | "model" | "vector") {
                    matches!(&rejected, Err(CanonicalPromptError::Registry(_)))
                } else {
                    rejected == Err(CanonicalPromptError::CandidateCompletenessBinding)
                };
            assert!(expected, "mutated authentic input: {tamper}: {rejected:?}");
        }
    }
}

fn rehash_prices(priced: &mut PricedPromptCandidatesV1) {
    for row in &mut priced.rows {
        let pricing = &row.pricing;
        row.pricing.receipt_digest = digest_pricing_receipt(
            &pricing.factor_id,
            pricing.state_digest,
            pricing.expected_utility_q32,
            pricing.downside_q32,
            pricing.token_cost,
            pricing.latency_cost_micros,
            pricing.interference_ppm,
            &pricing.confidence_interval,
            priced.pricing_policy_digest,
            row.binding.binding_digest,
        );
    }
    priced.pricing_set_digest = digest_pricing_set(&priced.rows, priced.pricing_policy_digest);
}

#[test]
fn public_priced_rows_must_still_match_the_sealed_enumeration() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _tuple, authority, signing_key, now) =
        registry_fixture(&temp.path().join("registry"), &[1]);
    register_second_factor(&mut registry, &authority, &signing_key, now);
    let (priced, verifier) = temporal::authentic_temporal_prices(&registry);
    let graph = graph(&["factor:a", "factor:b"], Vec::new());
    select_portfolio_v1(
        &priced,
        &graph,
        Vec::new(),
        &verifier,
        source::selection_request(),
        100,
    )
    .expect("unchanged authenticated priced table");
    for tamper in [
        "row-binding",
        "row-factor",
        "row-token",
        "row-utility",
        "row-order",
        "row-missing",
        "row-extra",
        "row-digest",
        "set-digest",
    ] {
        let mut altered = priced.clone();
        match tamper {
            "row-binding" => {
                altered.rows[0].binding.realization.token_cost += 1;
                altered.rows[0].binding.binding_digest =
                    altered.rows[0].binding.realization.digest();
            }
            "row-factor" => altered.rows[0].pricing.factor_id = id("factor:b"),
            "row-token" => altered.rows[0].pricing.token_cost += 1,
            "row-utility" => altered.rows[0].net_utility_q32 = FixedQ32::from_raw(999),
            "row-order" => altered.rows.reverse(),
            "row-missing" => {
                altered.rows.pop();
            }
            "row-extra" => altered.rows.push(altered.rows[0].clone()),
            "row-digest" => altered.rows[0].pricing.receipt_digest = digest("other price receipt"),
            "set-digest" => altered.pricing_set_digest = digest("other price set"),
            _ => unreachable!(),
        }
        if !matches!(tamper, "row-digest" | "set-digest") {
            rehash_prices(&mut altered);
        }
        assert_eq!(
            select_portfolio_v1(
                &altered,
                &graph,
                Vec::new(),
                &verifier,
                source::selection_request(),
                100
            ),
            Err(CanonicalPromptError::CandidateCompletenessBinding),
            "table tamper: {tamper}",
        );
    }
}
