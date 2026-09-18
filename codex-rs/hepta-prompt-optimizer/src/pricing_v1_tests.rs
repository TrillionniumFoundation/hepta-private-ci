use super::*;
use crate::PromptCandidateBindingV1;
use crate::PromptCandidateEnumerationRequestV1;
use crate::PromptCandidateSourceAuthenticatorV1;
use crate::PromptCandidateSourceV1;
use crate::PromptModelProfileV1;
use crate::enumerate_factors_v1;

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

fn candidate_set() -> PromptCandidateSetReceiptV1 {
    let mut binding = PromptCandidateBindingV1 {
        candidate_id: id("candidate:1"),
        factor_id: id("factor:1"),
        realization_id: id("realization:1"),
        payload_digest: digest("payload"),
        admission_digest: digest("admission"),
        support_digest: digest("registry-support"),
        token_cost: 12,
        expires_unix_ms: Some(10_000),
        binding_digest: Digest32::ZERO,
    };
    binding.binding_digest = binding.compute_binding_digest();
    let profile = PromptModelProfileV1 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        locale_id: id("en-US"),
    };
    let mut source = PromptCandidateSourceV1 {
        owner_id: id("prompt.registry"),
        registry_snapshot_digest: digest("registry"),
        registry_revision: 3,
        revocation_frontier: 2,
        generation_vector_digest: digest("generation"),
        model_profile: profile,
        bindings: vec![binding],
        omitted_count: 0,
        source_digest: Digest32::ZERO,
    };
    source.source_digest = source.compute_source_digest();
    enumerate_factors_v1(
        PromptCandidateEnumerationRequestV1 {
            enumeration_id: id("enumeration:pricing"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            maximum_candidates: 1,
            now_unix_ms: 100,
            source,
        },
        &Accept,
    )
    .expect("candidate set")
}

fn costs() -> PromptCostBreakdownV1 {
    PromptCostBreakdownV1 {
        tokens: q32(1),
        latency: q32(2),
        context_crowding: q32(1),
        instruction_interference: q32(1),
        privacy: q32(1),
        instability: q32(1),
        future_context_option_value: q32(1),
    }
}

fn evidence(set: &PromptCandidateSetReceiptV1) -> PromptPricingEvidenceV1 {
    let mut value = PromptPricingEvidenceV1 {
        candidate_id: id("candidate:1"),
        candidate_binding_digest: set.candidates[0].binding_digest,
        objective_digest: set.objective_digest,
        state_digest: set.state_digest,
        model_profile_digest: set.model_profile_digest,
        causal_incremental_utility: q32(20),
        confidence: FixedQ32::ONE,
        costs: costs(),
        utility_unit_digest: digest("utility-unit"),
        cost_profile_digest: digest("cost-profile"),
        support_digest: digest("causal-support"),
        valid_until_unix_ms: 1_000,
        evidence_digest: Digest32::ZERO,
    };
    value.evidence_digest = value.compute_evidence_digest();
    value
}

#[test]
fn pricing_subtracts_all_registered_cost_classes() {
    let set = candidate_set();
    let evidence = evidence(&set);
    let evidence_digest = evidence.evidence_digest;
    let receipt =
        price_factors_v1(&set, vec![evidence], /*now_unix_ms*/ 100, &Accept)
            .expect("pricing should succeed");
    assert_eq!(
        receipt.prices,
        vec![PromptPriceV1 {
            candidate_id: id("candidate:1"),
            gross_utility: q32(20),
            total_cost: q32(8),
            net_utility: q32(12),
            confidence: FixedQ32::ONE,
            availability: PromptPriceAvailabilityV1::Available,
            evidence_digest: Some(evidence_digest),
        }]
    );
    assert!(!receipt.authority.grants_any());
    receipt
        .validate_for(&set, /*now_unix_ms*/ 100)
        .expect("receipt validates");
}

#[test]
fn missing_or_expired_evidence_is_unavailable_not_free_benefit() {
    let set = candidate_set();
    let missing = price_factors_v1(&set, Vec::new(), /*now_unix_ms*/ 100, &Accept)
        .expect("missing evidence should remain representable");
    assert_eq!(
        missing.prices[0].availability,
        PromptPriceAvailabilityV1::MissingEvidence
    );
    assert_eq!(missing.prices[0].net_utility, FixedQ32::ZERO);

    let mut expired = evidence(&set);
    expired.valid_until_unix_ms = 50;
    expired.evidence_digest = expired.compute_evidence_digest();
    let expired = price_factors_v1(&set, vec![expired], /*now_unix_ms*/ 100, &Accept)
        .expect("expired evidence should remain representable");
    assert_eq!(
        expired.prices[0].availability,
        PromptPriceAvailabilityV1::ExpiredEvidence
    );
    assert_eq!(expired.prices[0].net_utility, FixedQ32::ZERO);
}

#[test]
fn pricing_evidence_cannot_drift_across_objective_or_candidate_binding() {
    let set = candidate_set();
    let mut drifted = evidence(&set);
    drifted.objective_digest = digest("different-objective");
    drifted.evidence_digest = drifted.compute_evidence_digest();
    assert_eq!(
        price_factors_v1(&set, vec![drifted], /*now_unix_ms*/ 100, &Accept),
        Err(CanonicalPromptErrorV1::EvidenceContextMismatch(
            "candidate:1".to_string()
        ))
    );
}
