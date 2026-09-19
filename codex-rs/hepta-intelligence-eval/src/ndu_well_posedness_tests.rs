use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32_ratio(numerator: i64, denominator: i64) -> i64 {
    let raw = (i128::from(numerator) << 32) / i128::from(denominator);
    i64::try_from(raw).expect("fixture ratio fits")
}

fn check(label: &str) -> NduAssumptionCheckV1 {
    NduAssumptionCheckV1 {
        support_digest: digest(label),
        satisfied: true,
    }
}

fn evidence() -> NduWellPosednessEvidenceV1 {
    NduWellPosednessEvidenceV1 {
        certificate_id: id("well-posedness-1"),
        manifest_digest: digest("coefficient-manifest"),
        operating_domain_digest: digest("operating-domain"),
        square_integrability: check("square-integrability"),
        conditional_mean: NduConditionalMeanCheckV1 {
            support_digest: digest("conditional-mean"),
            maximum_abs_standardized_q32: q32_ratio(1, 100),
        },
        coefficient_bounds: check("coefficient-bounds"),
        lipschitz: check("lipschitz"),
        generator_monotonicity: check("generator-monotonicity"),
        terminal_lipschitz: check("terminal-lipschitz"),
        continuity_scope: NduContinuityScopeV1::QualifiedOperatingRegion,
        solver_stability: check("solver-stability"),
        evaluator_identity: id("independent-evaluator"),
        candidate_producer_identity: id("candidate-producer"),
        expires_unix_ms: 2_000,
    }
}

#[test]
fn supported_independent_assumptions_can_be_accepted() {
    let certificate =
        evaluate_ndu_well_posedness_v1(&evidence(), 1_000).expect("valid evidence");
    assert_eq!(certificate.decision, NduWellPosednessDecisionV1::Accepted);
    assert!(!canonical_ndu_well_posedness_certificate_digest_v1(&certificate).is_zero());
}

#[test]
fn missing_support_is_unavailable() {
    let mut input = evidence();
    input.solver_stability.support_digest = Digest32::ZERO;
    assert_eq!(
        evaluate_ndu_well_posedness_v1(&input, 1_000)
            .expect("structurally valid")
            .decision,
        NduWellPosednessDecisionV1::Unavailable
    );
}

#[test]
fn failed_assumption_or_conditional_mean_rejects() {
    let mut failed = evidence();
    failed.lipschitz.satisfied = false;
    assert_eq!(
        evaluate_ndu_well_posedness_v1(&failed, 1_000)
            .expect("structurally valid")
            .decision,
        NduWellPosednessDecisionV1::Rejected
    );

    let mut mean = evidence();
    mean.conditional_mean.maximum_abs_standardized_q32 = q32_ratio(2, 100);
    assert_eq!(
        evaluate_ndu_well_posedness_v1(&mean, 1_000)
            .expect("structurally valid")
            .decision,
        NduWellPosednessDecisionV1::Rejected
    );
}

#[test]
fn self_evaluation_and_expiry_fail_closed() {
    let mut self_eval = evidence();
    self_eval.evaluator_identity = self_eval.candidate_producer_identity.clone();
    assert_eq!(
        evaluate_ndu_well_posedness_v1(&self_eval, 1_000)
            .expect_err("self evaluation rejects"),
        NduWellPosednessError::SelfEvaluation
    );
    assert_eq!(
        evaluate_ndu_well_posedness_v1(&evidence(), 2_000)
            .expect_err("expiry rejects"),
        NduWellPosednessError::Expired
    );
}
