use super::*;

use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRegistrySnapshotV2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;

use crate::canonical::PricedPromptCandidateV1;
use crate::canonical::PromptCandidateBindingV1;
use crate::canonical::PromptCandidateSetReceiptV1;
use crate::canonical::PromptConfidenceIntervalV1;
use crate::canonical::PromptOptimalityDisclosureV1;
use crate::canonical::PromptPortfolioReceiptV1;
use crate::canonical::PromptPricingReceiptV1;
use crate::canonical::PromptSelectionMethodV1;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn model_tuple() -> PromptModelTupleV2 {
    PromptModelTupleV2 {
        model_id: id("model:test"),
        model_version: "v1".to_owned(),
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        context_profile_digest: digest("context"),
        locale_id: id("locale:en-US"),
    }
}

fn candidate(index: usize) -> PromptCandidateBindingV1 {
    let tuple = model_tuple();
    let realization = PromptRealizationBindingV2 {
        realization_id: id(&format!("realization:{index:03}")),
        factor_id: id(&format!("factor:{index:03}")),
        model_id: tuple.model_id,
        model_version: tuple.model_version,
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        context_profile_digest: tuple.context_profile_digest,
        locale_id: tuple.locale_id,
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: digest(&format!("payload:{index:03}")),
        token_cost: u32::try_from(index + 1).unwrap_or(u32::MAX),
        expires_unix_ms: Some(20_000),
    };
    PromptCandidateBindingV1 {
        factor_id: realization.factor_id.clone(),
        binding_digest: realization.digest(),
        realization,
    }
}

fn enumerated() -> EnumeratedPromptCandidatesV1 {
    let tuple = model_tuple();
    let generation_vector = digest("generation-vector");
    let candidates = vec![candidate(0), candidate(1)];
    let factor_ids = candidates
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<Vec<_>>();
    let mut value = EnumeratedPromptCandidatesV1 {
        registry_snapshot: PromptRegistrySnapshotV2 {
            revision: Revision::new(1).unwrap_or_else(|error| panic!("revision: {error}")),
            registry_digest: digest("registry"),
            lifecycle_frontier: 1,
            revocation_frontier: 0,
            generation_vector_digest: generation_vector,
            model_tuple_digest: tuple.digest(),
            snapshot_digest: digest("registry-snapshot"),
            authority: AuthorityPosture::DENY_ALL,
        },
        model_tuple: tuple,
        generation_vector_digest: generation_vector,
        candidates_digest: Digest32::ZERO,
        canonical_order_digest: Digest32::ZERO,
        omitted_count: 0,
        receipt: PromptCandidateSetReceiptV1 {
            set_id: id("candidate-set:test"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            registry_digest: digest("registry"),
            candidate_factor_ids: factor_ids,
            selection_grammar_digest: digest("grammar"),
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        },
        candidates,
    };
    value.candidates_digest = digest_candidates(value);
    value.canonical_order_digest = digest_candidate_order(&value);
    value.receipt.receipt_digest = digest_candidate_receipt(
        &value,
        value.candidates_digest,
        value.canonical_order_digest,
    );
    value
}

fn priced() -> PricedPromptCandidatesV1 {
    let candidates = enumerated();
    let state_digest = candidates.receipt.state_digest;
    let rows = candidates
        .candidates
        .iter()
        .enumerate()
        .map(|(index, binding)| {
            let utility = FixedQ32::from_raw(100 - i64::try_from(index).unwrap_or(i64::MAX));
            PricedPromptCandidateV1 {
                binding: binding.clone(),
                pricing: PromptPricingReceiptV1 {
                    factor_id: binding.factor_id.clone(),
                    state_digest,
                    expected_utility_q32: utility,
                    downside_q32: FixedQ32::ZERO,
                    token_cost: binding.realization.token_cost,
                    latency_cost_micros: 1,
                    interference_ppm: 0,
                    confidence_interval: PromptConfidenceIntervalV1 {
                        lower_q32: utility,
                        upper_q32: utility,
                        support_count: 10,
                        support_audit_digest: digest(&ormat!("support:{index}")),
                    },
                    receipt_digest: Digest32::ZERO,
                    authority: AuthorityPosture::DENY_ALL,
                },
                net_utility_q32: utility,
            }
        })
        .collect::<Vec<_>>();
    let mut value = PricedPromptCandidatesV1 {
        candidates,
        completeness_digest: digest("completeness"),
        pricing_policy_digest: digest("pricing-policy"),
        rows,
        pricing_set_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    for index in 0..value.rows.len() {
        let row_digest = digest_pricing_receipt(&value, &value.rows[index]);
        value.rows[index].pricing.receipt_digest = row_digest;
    }
    value.pricing_set_digest = digest_pricing_set(&value);
    value
}

fn selected() -> (SelectedPromptPortfolioV1, PromptPortfolioVerificationContextV2) {
    let priced = priced();
    let binding = priced.rows[0].binding.clone();
    let model_tuple = priced.candidates.model_tuple.clone();
    let generation_vector_digest = priced.candidates.generation_vector_digest;
    let state_digest = priced.candidates.receipt.state_digest;
    let objective_digest = priced.candidates.receipt.objective_digest;
    let mut value = SelectedPromptPortfolioV1 {
        receipt: PromptPortfolioReceiptV1 {
            portfolio_id: id("portfolio:test"),
            candidate_set_digest: priced.candidates.candidates_digest,
            factor_ids: vec![binding.factor_id.clone()],
            interaction_digest: digest("interactions"),
            expected_utility_q32: priced.rows[0].net_utility_q32,
            total_token_upper_bound: binding.realization.token_cost,
            valid_until_unix_ms: 10_000,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        },
        selected: vec![binding],
        objective_digest,
        state_digest,
        model_tuple_digest: model_tuple.digest(),
        model_tuple,
        generation_vector_digest,
        pricing_set_digest: priced.pricing_set_digest,
        graph_generation_digest: digest("graph-generation"),
        selection_method: PromptSelectionMethodV1::GreedyPrerequisiteBundleV1,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
    };
    value.receipt.receipt_digest = digest_portfolio_receipt(&value);
    let context = PromptPortfolioVerificationContextV2 {
        candidate_set_digest: value.receipt.candidate_set_digest,
        pricing_set_digest: value.pricing_set_digest,
        registry_snapshot_digest: priced.candidates.registry_snapshot.snapshot_digest,
        generation_vector_digest,
        model_tuple_digest: value.model_tuple_digest,
        graph_generation_digest: value.graph_generation_digest,
        objective_digest,
        state_digest,
        scope_digest: digest("scope"),
        trust_digest: digest("trust"),
        authority_epoch: 1,
        valid_until_unix_ms: 9_000,
        evidence_lineage_digest: digest("lineage"),
    };
    (value, context)
}

#[test]
fn verified_enumeration_recomputes_every_binding_and_digest() {
    let value = enumerated();
    let verified = verify_enumerated_prompt_candidates_v2(value.clone())
        .unwrap_or_else(|error| panic!("verified enumeration: {error}"));
    assert_eq!(verified.canonical(), &value);
    assert!(!verified.scope_digest().is_zero());
}

#[test]
fn forged_realization_binding_is_rejected() {
    let mut value = enumerated();
    value.candidates[0].realization.token_cost += 1;
    assert!(matches!(
        verify_enumerated_prompt_candidates_v2(value),
        Err(VerifiedPromptErrorV2:IdentityMismatch(
            "candidate realization binding"
        ))
    ));
}

#[test]
fn candidate_order_tamper_is_rejected() {
    let mut value = enumerated();
    value.candidates.swap(0, 1);
    assert!(matches!(
        verify_enumerated_prompt_candidates_v2(value),
        Err(VerifiedPromptErrorV2::NonCanonicalOrder(
            "candidate factor order"
        ))
    ));
}

#[test]
fn forged_pricing_utility_is_rejected() {
    let mut value = priced();
    value.rows[0].pricing.expected_utility_q32 = FixedQ32::from_raw(9_999);
    value.rows[0].net_utility_q32 = FixedQ32::from_raw(9_999);
    assert!(matches!(
        validate_priced(&value),
        Err(VerifiedPromptErrorV2::DigestMismatch("pricing receipt"))
    ));
}

#[test]
fn forged_portfolio_utility_is_rejected() {
    let (mut value, context) = selected();
    value.receipt.expected_utility_q32 = FixedQ32::from_raw(9_999);
    assert!(matches!(
        verify_selected_prompt_portfolio_v2(value, context),
        Err(VerifiedPromptErrorV2::DigestMismatch("portfolio receipt"))
    ));
}

#[test]
fn portfolio_state_drift_is_rejected_before_exercise() {
    let (value, mut context) = selected();
    context.state_digest = digest("different-state");
    assert!(matches!(
        verify_selected_prompt_portfolio_v2(value, context),
        Err(VerifiedPromptErrorV2::IdentityMismatch(
            "portfolio verification context"
        ))
    ));
}

#[test]
fn solver_disclosure_tamper_is_rejected() {
    let (mut value, context) = selected();
    value.optimality = PromptOptimalityDisclosureV1::HeuristicNoCertificate;
    value.selection_method = PromptSelectionMethodV1::GreedyPrerequisiteBundleV1;
    let verified = verify_selected_prompt_portfolio_v2(value, context)
        .unwrap_or_else(|error| panic!("valid disclosure: {error}"));
    assert_eq!(
        verified.canonical().selection_method,
        PromptSelectionMethodV1::GreedyPrerequisiteBundleV1
    );
}
