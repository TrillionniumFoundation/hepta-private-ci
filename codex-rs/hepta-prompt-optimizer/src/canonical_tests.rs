use std::fmt::Debug;

use super::*;
use codex_hepta_prompt_registry::{
    FactorSource, Lifecycle, PromptFactor, PromptRealizationBindingV2, PromptRoleV2,
};

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("test fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn fixture_registry() -> (PromptRegistry, PromptModelTupleV2, Digest32, PromptRegistrySnapshotV2) {
    let mut registry = must(PromptRegistry::new(64));
    let model = PromptModelTupleV2 {
        model_digest: digest(b"model"),
        tokenizer_digest: digest(b"tokenizer"),
        template_digest: digest(b"template"),
        tool_schema_digest: digest(b"tools"),
        locale_id: id("en-US"),
    };
    for index in 0..2 {
        let factor_id = id(&format!("factor:{index}"));
        must(registry.register_factor(PromptFactor {
            factor_id: factor_id.clone(),
            proposer_id: id(&format!("proposer:{index}")),
            semantic_version: id("v1"),
            content_digest: digest(format!("factor-body:{index}").as_bytes()),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        }));
        must(registry.admit_factor(
            &factor_id,
            &id(&format!("reviewer:{index}")),
            digest(format!("review:{index}").as_bytes()),
        ));
        must(registry.register_realization_v2(PromptRealizationBindingV2 {
            realization_id: id(&format!("realization:{index}")),
            factor_id,
            model_digest: model.model_digest,
            tokenizer_digest: model.tokenizer_digest,
            template_digest: model.template_digest,
            tool_schema_digest: model.tool_schema_digest,
            locale_id: model.locale_id.clone(),
            role: PromptRoleV2::DeveloperInstruction,
            payload_digest: digest(format!("payload:{index}").as_bytes()),
            token_cost: 1,
            expires_unix_ms: None,
        }));
    }
    let generation = digest(b"generation");
    let snapshot = must(registry.snapshot_v2(generation, &model));
    (registry, model, generation, snapshot)
}

fn candidate_receipt(
    registry: &PromptRegistry,
    model: &PromptModelTupleV2,
    generation: Digest32,
    snapshot: &PromptRegistrySnapshotV2,
) -> PromptCandidateSetReceiptV1 {
    let compatible = must(registry.read_compatible_v2(
        snapshot,
        generation,
        model,
        10,
        Vec::new(),
        128,
    ));
    must(enumerate_factors(
        id("decision:1"),
        digest(b"objective"),
        snapshot,
        &compatible,
        digest(b"generator"),
        digest(b"hard-filter"),
        digest(b"truncation"),
    ))
}

fn evidence(candidate_id: StableId, utility: i64) -> CandidateEvidenceV1 {
    CandidateEvidenceV1 {
        candidate_id,
        causal_utility: FixedQ32::from_raw(utility),
        token_shadow_cost: FixedQ32::ZERO,
        latency_cost: FixedQ32::ZERO,
        crowding_cost: FixedQ32::ZERO,
        interference_cost: FixedQ32::ZERO,
        privacy_cost: FixedQ32::ZERO,
        instability_cost: FixedQ32::ZERO,
        future_option_cost: FixedQ32::ZERO,
        resource_cost: FixedQ32::ZERO,
        support_digest: digest(b"support"),
        confidence_digest: digest(b"confidence"),
        applicability_digest: digest(b"applicability"),
    }
}

#[test]
fn pricing_fails_closed_when_any_candidate_lacks_evidence() {
    let (registry, model, generation, snapshot) = fixture_registry();
    let candidates = candidate_receipt(&registry, &model, generation, &snapshot);
    let only_one = evidence(candidates.candidates[0].candidate_id.clone(), 10);
    assert!(matches!(
        price_factors(&candidates, vec![only_one]),
        Err(CanonicalError::MissingEvidence(_))
    ));
}

#[test]
fn prerequisite_bundle_is_evaluated_as_one_marginal_choice() {
    let (registry, model, generation, snapshot) = fixture_registry();
    let candidates = candidate_receipt(&registry, &model, generation, &snapshot);
    let prerequisite = candidates.candidates[0].candidate_id.clone();
    let dependent = candidates.candidates[1].candidate_id.clone();
    let pricing = must(price_factors(
        &candidates,
        vec![
            evidence(prerequisite.clone(), -1),
            evidence(dependent.clone(), 100),
        ],
    ));

    let portfolio = must(select_portfolio(
        &pricing,
        vec![PortfolioRelationV1::Requires {
            candidate_id: dependent,
            prerequisite_candidate_id: prerequisite,
            support_digest: digest(b"requires"),
        }],
        PortfolioBudgetV1 {
            token_budget: 2,
            maximum_selected: 2,
        },
    ));

    assert_eq!(portfolio.selected_candidate_ids.len(), 2);
    assert_eq!(portfolio.total_net_utility, FixedQ32::from_raw(99));
    assert!(!portfolio.authority.grants_any());
}

#[test]
fn exercise_accepts_exact_snapshot_then_rejects_after_revocation() {
    let (mut registry, model, generation, snapshot) = fixture_registry();
    let candidates = candidate_receipt(&registry, &model, generation, &snapshot);
    let evidence = candidates
        .candidates
        .iter()
        .map(|candidate| evidence(candidate.candidate_id.clone(), 10))
        .collect();
    let pricing = must(price_factors(&candidates, evidence));
    let portfolio = must(select_portfolio(
        &pricing,
        Vec::new(),
        PortfolioBudgetV1 {
            token_budget: 2,
            maximum_selected: 2,
        },
    ));

    let accepted = must(exercise(
        &portfolio,
        &registry,
        &snapshot,
        generation,
        &model,
        10,
        ExerciseBoundaryV1::BeforeModelOrToolDispatch,
    ));
    assert_eq!(accepted.disposition, ExerciseDispositionV1::Exercise);

    must(registry.revoke_factor(&portfolio.selected_factor_ids[0]));
    let rejected = must(exercise(
        &portfolio,
        &registry,
        &snapshot,
        generation,
        &model,
        10,
        ExerciseBoundaryV1::BeforeModelOrToolDispatch,
    ));
    assert_eq!(rejected.disposition, ExerciseDispositionV1::RejectStale);
}

#[test]
fn pricing_preserves_and_subtracts_all_utility_cost_dimensions() {
    let (registry, model, generation, snapshot) = fixture_registry();
    let candidates = candidate_receipt(&registry, &model, generation, &snapshot);
    let mut row = evidence(candidates.candidates[0].candidate_id.clone(), 30);
    row.token_shadow_cost = FixedQ32::from_raw(5);
    row.latency_cost = FixedQ32::from_raw(1);
    row.crowding_cost = FixedQ32::from_raw(2);
    row.interference_cost = FixedQ32::from_raw(3);
    row.privacy_cost = FixedQ32::from_raw(4);
    row.instability_cost = FixedQ32::from_raw(1);
    row.future_option_cost = FixedQ32::from_raw(2);
    row.resource_cost = FixedQ32::from_raw(2);
    let other = evidence(candidates.candidates[1].candidate_id.clone(), 1);
    let pricing = must(price_factors(&candidates, vec![row, other]));
    assert_eq!(pricing.prices[0].token_shadow_cost, FixedQ32::from_raw(5));
    assert_eq!(pricing.prices[0].resource_cost, FixedQ32::from_raw(2));
    assert_eq!(pricing.prices[0].total_utility_cost, FixedQ32::from_raw(20));
    assert_eq!(pricing.prices[0].net_utility, FixedQ32::from_raw(10));
}

#[test]
fn portfolio_never_selects_two_realizations_of_one_factor() {
    let (mut registry, model, generation, _) = fixture_registry();
    must(registry.register_realization_v2(PromptRealizationBindingV2 {
        realization_id: id("realization:0:alternate"),
        factor_id: id("factor:0"),
        model_digest: model.model_digest,
        tokenizer_digest: model.tokenizer_digest,
        template_digest: model.template_digest,
        tool_schema_digest: model.tool_schema_digest,
        locale_id: model.locale_id.clone(),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: digest(b"payload:0:alternate"),
        token_cost: 1,
        expires_unix_ms: None,
    }));
    let snapshot = must(registry.snapshot_v2(generation, &model));
    let candidates = candidate_receipt(&registry, &model, generation, &snapshot);
    let evidence = candidates
        .candidates
        .iter()
        .map(|candidate| evidence(candidate.candidate_id.clone(), 10))
        .collect();
    let pricing = must(price_factors(&candidates, evidence));
    let portfolio = must(select_portfolio(
        &pricing,
        Vec::new(),
        PortfolioBudgetV1 {
            token_budget: 3,
            maximum_selected: 3,
        },
    ));
    let unique_factors = portfolio
        .selected_factor_ids
        .iter()
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(portfolio.selected_factor_ids.len(), 2);
    assert_eq!(unique_factors.len(), 2);
}
