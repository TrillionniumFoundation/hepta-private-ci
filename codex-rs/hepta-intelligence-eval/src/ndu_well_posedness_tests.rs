use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::NduAssumptionEvidenceV1;
use super::NduConditionalMeanEvidenceV1;
use super::NduContinuityScopeV1;
use super::NduWellPosednessDecisionV1;
use super::NduWellPosednessError;
use super::NduWellPosednessEvidenceV1;
use super::decide_ndu_well_posedness_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn assumption(value: &str, satisfied: bool) -> NduAssumptionEvidenceV1 {
    NduAssumptionEvidenceV1 {
        evidence_digest: digest(value),
        satisfied,
    }
}

fn evidence() -> NduWellPosednessEvidenceV1 {
    NduWellPosednessEvidenceV1 {
        certificate_id: id("well-posedness-1"),
        manifest_digest: digest("coefficient-manifest"),
        operating_domain_digest: digest("operating-domain"),
        square_integrability: assumption("square-integrability", true),
        conditional_mean: NduConditionalMeanEvidenceV1 {
            evidence_digest: digest("conditional-mean"),
            standardized_absolute_mean_q32: (1_i64 * (1_i64 << 32)) / 100,
        },
        coefficient_bounds: assumption("coefficient-bounds", true),
        lipschitz: assumption("lipschitz", true),
        generator_monotonicity: assumption("generator-monotonicity", true),
        terminal_lipschitz: assumption("terminal-lipschitz", true),
        continuity_scope: NduContinuityScopeV1::DeclaredOperatingDomain,
        solver_stability: assumption("solver-stability", true),
        evaluator_identity: id("learning-eval-independent"),
        candidate_producer_identity: id("utility-ndu"),
        expires_unix_ms: 10_000,
    }
}

#[test]
fn complete_independent_well_posedness_evidence_can_be_accepted_without_authority() {
    let certificate =
        decide_ndu_well_posedness_v1(evidence(), 5_000).expect("valid independent decision");
    assert_eq!(certificate.decision, NduWellPosednessDecisionV1::Accepted);
    assert!(!certificate.certificate_digest.is_zero());
    assert!(!certificate.authority.grants_any());
}

#[test]
fn missing_support_is_unavailable_not_accepted() {
    let mut candidate = evidence();
    candidate.lipschitz.evidence_digest = Digest32::ZERO;
    let certificate =
        decide_ndu_well_posedness_v1(candidate, 5_000).expect("valid unavailable decision");
    assert_eq!(
        certificate.decision,
        NduWellPosednessDecisionV1::Unavailable
    );
}

#[test]
fn failed_assumption_or_conditional_mean_threshold_rejects() {
    let mut failed = evidence();
    failed.generator_monotonicity.satisfied = false;
    assert_eq!(
        decide_ndu_well_posedness_v1(failed, 5_000)
            .expect("valid rejected decision")
            .decision,
        NduWellPosednessDecisionV1::Rejected
    );

    let mut conditional_mean = evidence();
    conditional_mean
        .conditional_mean
        .standardized_absolute_mean_q32 = (2_i64 * (1_i64 << 32)) / 100;
    assert_eq!(
        decide_ndu_well_posedness_v1(conditional_mean, 5_000)
            .expect("threshold equality must reject")
            .decision,
        NduWellPosednessDecisionV1::Rejected
    );
}

#[test]
fn evaluator_cannot_self_certify_well_posedness() {
    let mut self_evaluation = evidence();
    self_evaluation.evaluator_identity = self_evaluation.candidate_producer_identity.clone();
    assert_eq!(
        decide_ndu_well_posedness_v1(self_evaluation, 5_000)
            .expect_err("self evaluation must fail"),
        NduWellPosednessError::SelfEvaluation
    );
}

#[test]
fn expired_certificate_input_rejects() {
    assert_eq!(
        decide_ndu_well_posedness_v1(evidence(), 10_000)
            .expect_err("expired evidence cannot be admitted"),
        NduWellPosednessError::Expired
    );
}

#[test]
fn certificate_digest_binds_assumption_evidence_and_producer() {
    let first =
        decide_ndu_well_posedness_v1(evidence(), 5_000).expect("first independent decision");

    let mut changed_support = evidence();
    changed_support.square_integrability.evidence_digest = digest("different-square-integrability");
    let second =
        decide_ndu_well_posedness_v1(changed_support, 5_000).expect("second independent decision");
    assert_ne!(first.certificate_digest, second.certificate_digest);

    let mut changed_producer = evidence();
    changed_producer.candidate_producer_identity = id("utility-ndu-other-producer");
    let third =
        decide_ndu_well_posedness_v1(changed_producer, 5_000).expect("third independent decision");
    assert_ne!(first.certificate_digest, third.certificate_digest);
}
