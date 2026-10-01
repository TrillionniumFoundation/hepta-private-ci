//! Real owner-cut regressions for realization-bound evaluator attestations.

use super::*;
use super::tests::*;
use codex_hepta_prompt_registry::final_use_realization_binding;

fn signed_pair(
    priced: &PricedPromptCandidatesV1,
    projection: &PromptFactorProjectionV1,
    left_binding_digest: Digest32,
) -> PromptPairUtilityEvidenceV2 {
    let mut evidence = PromptPairUtilityEvidenceV2 {
        pair: PromptPairUtilityEvidenceV1 {
            left_factor_id: priced.rows[0].binding.factor_id.clone(),
            right_factor_id: priced.rows[1].binding.factor_id.clone(),
            state_digest: priced.candidates.receipt.state_digest,
            graph_generation_digest: projection.generation().generation_digest,
            edge_validity_digest: projection.generation().edges[0].validity_digest,
            marginal_utility_q32: FixedQ32::from_raw(2),
            confidence_lower_q32: FixedQ32::from_raw(2),
            confidence_upper_q32: FixedQ32::from_raw(2),
            support_audit_digest: digest("pair-calibration-support"),
            evidence: priced.admission_proofs[0].evidence.clone(),
        },
        model_tuple_digest: priced.candidates.model_tuple.digest(),
        left_binding_digest,
        right_binding_digest: priced.rows[1].binding.binding_digest,
    };
    evidence.pair.evidence = sign_learning_evidence(
        &verifier(), 7, "evaluator", LearningEvidenceRoleV1::Evaluator,
        "evidence:pair-calibration", &pair_utility_evidence_signing_payload_v2(&evidence),
    );
    evidence
}

#[test]
fn fresh_completeness_cannot_reuse_prices_for_a_superseded_realization() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _, authority, key, now) = registry_fixture(&temp.path().join("registry"), &[4]);
    let original = current_enumeration(registry.registry().expect("registry"), vec![id("factor:a")]);
    let old_price = authenticated_pricing_inputs(&original, verifier()).evidence[0].clone();
    verifier().verify(LearningEvidenceRoleV1::Evaluator, &old_price.pricing.evidence, &pricing_evidence_signing_payload_v2(&old_price), 100).expect("authentic original realization price");
    let predecessor = original.candidates[0].realization.realization_id.clone();
    let mut replacement = original.candidates[0].realization.clone();
    replacement.realization_id = id("realization:replacement");
    let payload = b"replacement payload";
    replacement.payload_digest = Digest32::of_bytes(payload);
    let factor = registry.registry().expect("registry").factor(&id("factor:a")).expect("factor").clone();
    let actor = id("publisher:replacement");
    let scope = digest("scope:replacement");
    let grant = relation_grant(final_use_realization_binding(&factor, &actor, scope, &replacement, Some(&predecessor)).expect("exact supersession binding"), &key, now, "realization:replacement:grant");
    registry.register_realization_payload_final_use_v2(&authority, &grant, &actor, scope, replacement, payload.to_vec(), Some(predecessor.clone())).expect("governed actual supersession");
    let owner = registry.registry().expect("registry");
    assert!(!owner.realization(&predecessor).expect("immutable predecessor").active);
    let current = current_enumeration(owner, vec![id("factor:a")]);
    assert_eq!(current.candidates[0].realization.realization_id, id("realization:replacement"));
    let mut fixture = authenticated_pricing_inputs(&current, verifier());
    fixture.evidence[0] = old_price.clone();
    assert_eq!(fixture.price(current.clone()).expect_err("fresh generator completeness cannot bless an old evaluator binding"), CanonicalPromptError::InvalidPricingEvidence("factor:a".to_owned()));
    let mut rebound = old_price;
    rebound.candidate_set_digest = current.receipt.receipt_digest;
    rebound.binding_digest = current.candidates[0].binding_digest;
    let mut historical = rebound.clone();
    historical.pricing.evidence = sign_learning_evidence(&verifier(), 7, "evaluator", LearningEvidenceRoleV1::Evaluator, "evidence:historical-v1", &pricing_evidence_signing_payload_v1(&historical.pricing));
    verifier().verify(LearningEvidenceRoleV1::Evaluator, &historical.pricing.evidence, &pricing_evidence_signing_payload_v1(&historical.pricing), 100).expect("historical V1 signatures remain interpretable");
    for evidence in [rebound, historical] {
        let mut fixture = authenticated_pricing_inputs(&current, verifier());
        fixture.evidence[0] = evidence;
        assert_eq!(fixture.price(current.clone()).expect_err("public binding rewrite or historical payload cannot mint V2 admission"), CanonicalPromptError::LearningEvidence("PayloadMismatch".to_owned()));
    }
    let priced = authenticated_pricing_inputs(&current, verifier()).price(current).expect("fresh V2 realization pricing");
    let selected = select_portfolio_v1(&priced, &owner_projection(owner), &[], &verifier(), selection_request(), 100).expect("select exact replacement");
    assert_eq!(selected.selected[0].realization.realization_id, id("realization:replacement"));
}

#[test]
fn pair_prices_cannot_cross_models_or_realizations_within_one_owner_cut() {
    use codex_hepta_prompt_registry::PromptFactorRelation;
    use codex_hepta_prompt_registry::PromptFactorRelationKind;
    use codex_hepta_prompt_registry::final_use_factor_relation_binding;

    let temp = tempfile::tempdir().expect("tempdir");
    let (mut registry, _, authority, key, now) = registry_fixture(&temp.path().join("registry"), &[4, 5]);
    let (actor, scope) = register_second_realized_factor(&mut registry, &authority, &key, now);
    let templates = current_enumeration(registry.registry().expect("registry"), vec![id("factor:a"), id("factor:b")]);
    let mut model_b = model_tuple();
    model_b.model_id = id("model:b");
    model_b.model_digest = digest("model:b");
    for candidate in &templates.candidates {
        let mut binding = candidate.realization.clone();
        binding.realization_id = id(&format!("{}:model:b", binding.realization_id));
        binding.model_id = model_b.model_id.clone();
        binding.model_digest = model_b.model_digest;
        let factor = registry.registry().expect("registry").factor(&binding.factor_id).expect("factor").clone();
        let grant = relation_grant(final_use_realization_binding(&factor, &actor, scope, &binding, None).expect("model B realization binding"), &key, now, &format!("grant:{}", binding.realization_id));
        registry.register_realization_payload_final_use_v2(&authority, &grant, &actor, scope, binding, b"payload".to_vec(), None).expect("genuine model B payload");
    }
    let relation = PromptFactorRelation {
        relation_id: id("relation:pair-complement"), left_factor_id: id("factor:a"), right_factor_id: id("factor:b"),
        kind: PromptFactorRelationKind::Complements, evidence_digest: digest("complement-evidence"),
    };
    let grant = relation_grant(final_use_factor_relation_binding(registry.registry().expect("registry"), &actor, scope, &relation).expect("relation binding"), &key, now, "insert:pair-complement");
    registry.register_factor_relation_final_use(&authority, &grant, &actor, scope, relation).expect("genuine shared relation");
    let owner = registry.registry().expect("registry");
    let projection = owner_projection(owner);
    let priced_a = current_pair_pricing(owner);
    let mut request_b = enumeration_request();
    request_b.required_factor_ids = vec![id("factor:a"), id("factor:b")];
    request_b.model_tuple = model_b;
    let candidates_b = enumerate_factors_v1(owner, request_b).expect("genuine same-cut model B enumeration");
    let priced_b = authenticated_pricing_inputs(&candidates_b, verifier()).price(candidates_b).expect("genuine model B individual prices");
    assert_eq!(priced_a.candidates.registry_snapshot.registry_digest, priced_b.candidates.registry_snapshot.registry_digest);
    let pair_a = signed_pair(&priced_a, &projection, priced_a.rows[0].binding.binding_digest);
    verifier().verify(LearningEvidenceRoleV1::Evaluator, &pair_a.pair.evidence, &pair_utility_evidence_signing_payload_v2(&pair_a), 100).expect("genuine model A pair signature");
    assert_eq!(select_portfolio_v1(&priced_a, &projection, &[pair_a.clone()], &verifier(), selection_request(), 100).expect("calibrated model A pair").receipt.factor_ids, vec![id("factor:a"), id("factor:b")]);
    assert_eq!(select_portfolio_v1(&priced_b, &projection, &[pair_a.clone()], &verifier(), selection_request(), 100).expect_err("same owner graph cannot make model A pair valid for B"), CanonicalPromptError::InvalidPairEvidence);
    let mut rebound = pair_a;
    rebound.model_tuple_digest = priced_b.candidates.model_tuple.digest();
    rebound.left_binding_digest = priced_b.rows[0].binding.binding_digest;
    rebound.right_binding_digest = priced_b.rows[1].binding.binding_digest;
    assert_eq!(select_portfolio_v1(&priced_b, &projection, &[rebound], &verifier(), selection_request(), 100).expect_err("rewritten pair context still needs a new authenticated payload"), CanonicalPromptError::LearningEvidence("PayloadMismatch".to_owned()));
    let alternative = owner.read_compatible_v2(&priced_a.candidates.registry_snapshot, digest("generation-vector"), &model_tuple(), 100, vec![id("factor:a")], 8).expect("actual same-model alternatives").bindings.into_iter().find(|binding| binding.realization_id == id("realization:1")).expect("system-role alternative");
    let alternative_pair = signed_pair(&priced_a, &projection, alternative.digest());
    assert_eq!(select_portfolio_v1(&priced_a, &projection, &[alternative_pair], &verifier(), selection_request(), 100).expect_err("a genuine other realization calibration cannot price the selected realization"), CanonicalPromptError::InvalidPairEvidence);
    let pair_b = signed_pair(&priced_b, &projection, priced_b.rows[0].binding.binding_digest);
    select_portfolio_v1(&priced_b, &projection, &[pair_b], &verifier(), selection_request(), 100).expect("fresh model B pair calibration succeeds");
}

#[test]
fn net_confidence_interval_follows_all_deterministic_costs_without_sum_overflow() {
    let temp = tempfile::tempdir().expect("tempdir");
    let (registry, _, _, _, _) = registry_fixture(&temp.path().join("registry"), &[4]);
    let candidates = current_enumeration(registry.registry().expect("registry"), vec![id("factor:a")]);
    for wide_penalty in [false, true] {
        let mut fixture = authenticated_pricing_inputs(&candidates, verifier());
        let raw = &mut fixture.evidence[0].pricing;
        let (utility, lower, upper, expected_net, net_lower, net_upper) = if wide_penalty {
            (8_000_000_000_000_000_000, 8_000_000_000_000_000_000, 8_000_000_000_000_000_000, -8_000_000_000_000_000_000, -8_000_000_000_000_000_000, -8_000_000_000_000_000_000)
        } else { (10, 8, 12, 1, -1, 3) };
        raw.expected_incremental_utility_q32 = FixedQ32::from_raw(utility);
        raw.confidence_lower_q32 = FixedQ32::from_raw(lower);
        raw.confidence_upper_q32 = FixedQ32::from_raw(upper);
        if wide_penalty {
            raw.context_crowding_cost_q32 = FixedQ32::from_raw(utility);
            raw.privacy_cost_q32 = FixedQ32::from_raw(utility);
        } else {
            raw.downside_q32 = FixedQ32::from_raw(2);
            raw.latency_cost_micros = 1;
            raw.context_crowding_cost_q32 = FixedQ32::from_raw(2);
            fixture.policy.downside_weight_q32 = FixedQ32::ONE;
            fixture.policy.token_cost_per_token_q32 = FixedQ32::from_raw(1);
            fixture.policy.latency_cost_per_micro_q32 = FixedQ32::from_raw(1);
        }
        let audit = raw.support_audit_digest;
        fixture.evidence[0].pricing.evidence = sign_learning_evidence(&fixture.verifier, 7, "evaluator", LearningEvidenceRoleV1::Evaluator, "evidence:net-confidence", &pricing_evidence_signing_payload_v2(&fixture.evidence[0]));
        let priced = fixture.price(candidates.clone()).expect("authenticated raw intervals and legal final bounds");
        assert_eq!(priced.rows[0].net_utility_q32, FixedQ32::from_raw(expected_net));
        assert_eq!(priced.rows[0].pricing.confidence_interval, PromptConfidenceIntervalV1 {
            lower_q32: FixedQ32::from_raw(net_lower), upper_q32: FixedQ32::from_raw(net_upper),
            support_count: 10, support_audit_digest: audit,
        });
        priced.validate().expect("translated interval and accounting remain sealed");
    }
}
