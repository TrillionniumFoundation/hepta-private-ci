use super::*;
use crate::PromptAuthenticationErrorV1;
use crate::PromptCandidateBindingV1;
use crate::PromptCandidateRoleV1;
use crate::PromptCandidateEnumerationRequestV1;
use crate::PromptCandidateSetReceiptV1;
use crate::PromptCandidateSourceAuthenticatorV1;
use crate::PromptCandidateSourceV1;
use crate::PromptCostBreakdownV1;
use crate::PromptHardConstraintV1;
use crate::PromptModelProfileV1;
use crate::PromptPairInteractionV1;
use crate::PromptPricingEvidenceAuthenticatorV1;
use crate::PromptPricingEvidenceV1;
use crate::PromptPricingReceiptV1;
use crate::PromptRelationSourceAuthenticatorV1;
use crate::PromptRelationSourceV1;
use crate::enumerate_factors_v1;
use crate::price_factors_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

struct Accept;

impl PromptCandidateSourceAuthenticatorV1 for Accept {
    fn authenticate_candidate_source(
        &self,
        _source: &PromptCandidateSourceV1,
        _objective_digest: Digest32,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

impl PromptPricingEvidenceAuthenticatorV1 for Accept {
    fn authenticate_pricing_evidence(
        &self,
        _evidence: &PromptPricingEvidenceV1,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

impl PromptRelationSourceAuthenticatorV1 for Accept {
    fn authenticate_relation_source(
        &self,
        _source: &PromptRelationSourceV1,
        _objective_digest: Digest32,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

fn candidate_set(count: usize) -> PromptCandidateSetReceiptV1 {
    let mut bindings = (0..count)
        .map(|index| PromptCandidateBindingV1 {
            candidate_id: id(&format!("candidate:{index:03}")),
            factor_id: id(&format!("factor:{index:03}")),
            realization_id: id(&format!("realization:{index:03}")),
            role: PromptCandidateRoleV1::DeveloperInstruction,
            payload_digest: digest(&format!("payload:{index}")),
            admission_digest: digest(&format!("admission:{index}")),
            support_digest: digest(&format!("registry-support:{index}")),
            token_cost: 1,
            expires_unix_ms: Some(10_000),
            binding_digest: Digest32::ZERO,
        })
        .collect::<Vec<_>>();
    for binding in &mut bindings {
        binding.binding_digest = binding.compute_binding_digest();
    }
    let mut source = PromptCandidateSourceV1 {
        owner_id: id("prompt.registry"),
        registry_snapshot_digest: digest("registry"),
        registry_revision: 3,
        revocation_frontier: 2,
        generation_vector_digest: digest("generation"),
        model_profile: PromptModelProfileV1 {
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tools"),
            context_profile_digest: digest("context-profile"),
            locale_id: id("en-US"),
        },
        bindings,
        omitted_count: 0,
        source_digest: Digest32::ZERO,
    };
    source.source_digest = source.compute_source_digest();
    enumerate_factors_v1(
        PromptCandidateEnumerationRequestV1 {
            enumeration_id: id("enumeration:portfolio"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            maximum_candidates: count,
            now_unix_ms: 100,
            source,
        },
        &Accept,
    )
    .expect("candidate set")
}

fn pricing(set: &PromptCandidateSetReceiptV1, gains: &[i64]) -> PromptPricingReceiptV1 {
    let zero_cost = PromptCostBreakdownV1 {
        tokens: FixedQ32::ZERO,
        latency: FixedQ32::ZERO,
        context_crowding: FixedQ32::ZERO,
        instruction_interference: FixedQ32::ZERO,
        privacy: FixedQ32::ZERO,
        instability: FixedQ32::ZERO,
        future_context_option_value: FixedQ32::ZERO,
    };
    let evidence = set
        .candidates
        .iter()
        .zip(gains)
        .map(|(candidate, gain)| {
            let mut value = PromptPricingEvidenceV1 {
                candidate_id: candidate.candidate_id.clone(),
                candidate_binding_digest: candidate.binding_digest,
                objective_digest: set.objective_digest,
                state_digest: set.state_digest,
                model_profile_digest: set.model_profile_digest,
                causal_incremental_utility: q32(*gain),
                confidence: FixedQ32::ONE,
                costs: zero_cost,
                utility_unit_digest: digest("utility-unit"),
                cost_profile_digest: digest("cost-profile"),
                support_digest: digest(&format!("causal:{}", candidate.candidate_id)),
                valid_until_unix_ms: 1_000,
                evidence_digest: Digest32::ZERO,
            };
            value.evidence_digest = value.compute_evidence_digest();
            value
        })
        .collect();
    price_factors_v1(set, evidence, /*now_unix_ms*/ 100, &Accept).expect("pricing")
}

fn relation_source(set: &PromptCandidateSetReceiptV1) -> PromptRelationSourceV1 {
    PromptRelationSourceV1 {
        producer_id: id("knowledge.graph"),
        candidate_set_digest: set.candidate_set_digest,
        generation_vector_digest: set.generation_vector_digest,
        hard_constraint_completeness_digest: digest("hard-complete"),
        interactions: Vec::new(),
        hard_constraints: Vec::new(),
        source_digest: Digest32::ZERO,
    }
}

fn seal(mut source: PromptRelationSourceV1) -> PromptRelationSourceV1 {
    source.source_digest = source.compute_source_digest();
    source
}

fn request(relations: PromptRelationSourceV1) -> PromptPortfolioSelectionRequestV1 {
    PromptPortfolioSelectionRequestV1 {
        selection_id: id("selection:1"),
        token_budget: 10,
        maximum_selected_factors: 4,
        maximum_steps: 8,
        now_unix_ms: 100,
        relations,
    }
}

#[test]
fn prerequisite_closure_prices_the_bundle_instead_of_rejecting_negative_prerequisite() {
    let set = candidate_set(2);
    let pricing = pricing(&set, &[-1, 100]);
    let mut relations = relation_source(&set);
    relations.interactions.push(PromptPairInteractionV1 {
        left_candidate_id: id("candidate:000"),
        right_candidate_id: id("candidate:001"),
        marginal_net_utility: FixedQ32::ZERO,
        support_digest: digest("pair:0:1"),
    });
    relations
        .hard_constraints
        .push(PromptHardConstraintV1::Requires {
            candidate_id: id("candidate:001"),
            prerequisite_candidate_id: id("candidate:000"),
            support_digest: digest("requires:1:0"),
        });
    let relations = seal(relations);
    let receipt = select_portfolio_v1(&set, &pricing, request(relations.clone()), &Accept)
        .expect("bundle should be selected");
    assert_eq!(
        receipt.selected_candidate_ids,
        vec![id("candidate:000"), id("candidate:001")]
    );
    assert_eq!(receipt.total_net_utility, q32(99));
    receipt
        .validate_for(&set, &pricing, &relations, /*now_unix_ms*/ 100)
        .expect("receipt validates");
}

#[test]
fn absent_pair_support_is_not_silently_treated_as_zero() {
    let set = candidate_set(2);
    let pricing = pricing(&set, &[100, 90]);
    let relations = seal(relation_source(&set));
    let receipt = select_portfolio_v1(&set, &pricing, request(relations), &Accept)
        .expect("single-factor portfolio remains valid");
    assert_eq!(receipt.selected_candidate_ids, vec![id("candidate:000")]);
}

#[test]
fn hard_conflict_cannot_be_outweighed_by_pair_gain() {
    let set = candidate_set(2);
    let pricing = pricing(&set, &[100, 90]);
    let mut relations = relation_source(&set);
    relations.interactions.push(PromptPairInteractionV1 {
        left_candidate_id: id("candidate:000"),
        right_candidate_id: id("candidate:001"),
        marginal_net_utility: q32(1_000),
        support_digest: digest("pair:0:1"),
    });
    relations
        .hard_constraints
        .push(PromptHardConstraintV1::Conflict {
            left_candidate_id: id("candidate:000"),
            right_candidate_id: id("candidate:001"),
            support_digest: digest("conflict:0:1"),
        });
    let receipt = select_portfolio_v1(&set, &pricing, request(seal(relations)), &Accept)
        .expect("conflict should be enforced");
    assert_eq!(receipt.selected_candidate_ids, vec![id("candidate:000")]);
}
