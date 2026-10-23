//! These tests exercise receipt propagation and binding, not signature
//! authentication or a live product request. Signed-host tests remain mandatory.

use codex_hepta_intelligence::AuthenticatedIntuitionDecisionV3;
use codex_hepta_intuition::AbstentionReasonV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::ProductionIntuitionReceiptV1;
use codex_hepta_intuition::ProductionSlowPathReasonV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use super::*;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn receipt(disposition: ProductionDispositionV1) -> AgentdIntuitionDecisionReceiptV2 {
    let is_abstain = matches!(disposition, ProductionDispositionV1::Abstained(_));
    AgentdIntuitionDecisionReceiptV2 {
        decision: AuthenticatedIntuitionDecisionV3 {
            decision: ProductionIntuitionReceiptV1 {
                decision_id: StableId::new("decision:admission-test").expect("decision id"),
                original_risk_class: RiskClass::Elevated,
                matched_risk_rule: CanonicalRiskRuleV1::ElevatedAndHighSlowPath,
                disposition,
                propensities: Vec::new(),
                abstain_probability: if is_abstain {
                    ProbabilityQ32::ONE
                } else {
                    ProbabilityQ32::ZERO
                },
                slow_path_probability: if is_abstain {
                    ProbabilityQ32::ZERO
                } else {
                    ProbabilityQ32::ONE
                },
                profile_digest: digest("profile"),
                legacy_receipt_digest: digest("legacy receipt"),
                receipt_digest: digest("policy receipt"),
                authority: AuthorityPosture::DENY_ALL,
            },
            profile_digest: digest("profile"),
            scoring_commitment_digest: digest("scoring"),
            assignment_commitment_digest: digest("assignment"),
            trust_digest: digest("trust"),
            completeness_payload_digest: digest("completeness"),
            profile_qualification_payload_digest: digest("qualification"),
            runtime_payload_digest: digest("runtime"),
            authentication_digest: digest("authentication"),
        },
        host_binding_digest: digest("host"),
        production_record_id: None,
        learning: None,
        service_receipt_digest: digest("service"),
    }
}

fn slow_path_receipt() -> AgentdIntuitionDecisionReceiptV2 {
    receipt(ProductionDispositionV1::SlowPath(
        ProductionSlowPathReasonV1::ProfileRiskRule,
    ))
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn intuition_policy_admission_preserves_complete_slow_path_receipt() {
    let expected = slow_path_receipt();
    let admitted = finish_canonical_admission(
        Ok(AgentdIntelligenceAdmittedOutcomeV1::SlowPath),
        Some(expected.clone()),
    )
    .expect("bound slow path");
    assert_eq!(admitted.disposition(), "canonical_slow_path");
    assert_eq!(admitted.policy_receipt(), Some(&expected));
    assert!(
        admitted
            .binding_digest()
            .is_some_and(|value| !value.is_zero())
    );
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn intuition_policy_admission_preserves_complete_abstention_receipt() {
    let expected = receipt(ProductionDispositionV1::Abstained(
        AbstentionReasonV1::NoLegalCandidate,
    ));
    let admitted = finish_canonical_admission(
        Ok(AgentdIntelligenceAdmittedOutcomeV1::Abstained),
        Some(expected.clone()),
    )
    .expect("bound abstention");
    assert_eq!(admitted.disposition(), "canonical_abstained");
    assert_eq!(admitted.policy_receipt(), Some(&expected));
}

#[test]
fn intuition_policy_admission_mismatch_keeps_policy_receipt_and_typed_cause() {
    let expected = slow_path_receipt();
    let error = finish_canonical_admission(
        Ok(AgentdIntelligenceAdmittedOutcomeV1::Abstained),
        Some(expected.clone()),
    )
    .expect_err("mismatched disposition");
    let AgentdError::IntuitionPolicy(service) = error else {
        panic!("lost typed policy error");
    };
    assert_eq!(service.acknowledged_policy_receipt(), Some(&expected));
    let AgentdIntuitionServiceErrorV1::AdmissionFailedAfterPolicy { receipt, source } = *service
    else {
        panic!("lost post-policy error classification");
    };
    assert_eq!(receipt, expected);
    assert!(matches!(*source, AgentdError::Protocol(_)));
}

#[test]
fn intuition_policy_admission_each_downstream_failure_keeps_the_original_receipt() {
    let expected = slow_path_receipt();
    let failures = [
        AgentdError::GenerationFenced("freshness changed".to_string()),
        AgentdError::Protocol("run start rejected".to_string()),
        AgentdError::Io(std::io::Error::other("context attachment unavailable")),
    ];
    for source in failures {
        let before = source.to_string();
        let error = finish_canonical_admission(Err(source), Some(expected.clone()))
            .expect_err("post-policy failure");
        let AgentdError::IntuitionPolicy(service) = error else {
            panic!("lost policy receipt");
        };
        assert_eq!(service.acknowledged_policy_receipt(), Some(&expected));
        let AgentdIntuitionServiceErrorV1::AdmissionFailedAfterPolicy { source, .. } = *service
        else {
            panic!("lost typed cause");
        };
        assert_eq!(source.to_string(), before);
    }
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn intuition_policy_admission_binding_changes_with_service_host_or_authentication() {
    let original = slow_path_receipt();
    let baseline = finish_canonical_admission(
        Ok(AgentdIntelligenceAdmittedOutcomeV1::SlowPath),
        Some(original.clone()),
    )
    .expect("baseline")
    .binding_digest();
    let mut variants = [original.clone(), original.clone(), original];
    variants[0].service_receipt_digest = digest("changed service");
    variants[1].host_binding_digest = digest("changed host");
    variants[2].decision.authentication_digest = digest("changed authentication");
    for variant in variants {
        let observed = finish_canonical_admission(
            Ok(AgentdIntelligenceAdmittedOutcomeV1::SlowPath),
            Some(variant),
        )
        .expect("changed binding")
        .binding_digest();
        assert_ne!(baseline, observed);
    }
}

#[test]
fn intuition_policy_admission_rejects_zero_binding_and_keeps_its_receipt() {
    let mut expected = slow_path_receipt();
    expected.service_receipt_digest = Digest32::ZERO;
    let error = finish_canonical_admission(
        Ok(AgentdIntelligenceAdmittedOutcomeV1::SlowPath),
        Some(expected.clone()),
    )
    .expect_err("zero binding");
    let AgentdError::IntuitionPolicy(service) = error else {
        panic!("lost zero-binding receipt");
    };
    assert_eq!(service.acknowledged_policy_receipt(), Some(&expected));
}

#[test]
#[allow(
    clippy::expect_used,
    reason = "Test setup and success assertions intentionally fail the test on unexpected errors."
)]
fn intuition_policy_admission_explicit_compatibility_does_not_fabricate_a_receipt() {
    let admitted = finish_canonical_admission(
        Ok(AgentdIntelligenceAdmittedOutcomeV1::SlowPath),
        /*policy_receipt*/ None,
    )
    .expect("explicit compatibility");
    assert_eq!(admitted.policy_receipt(), None);
    assert_eq!(admitted.binding_digest(), None);
    let error = finish_canonical_admission(
        Err(AgentdError::Protocol("compatibility rejected".to_string())),
        /*policy_receipt*/ None,
    )
    .expect_err("compatibility failure");
    assert!(matches!(error, AgentdError::Protocol(_)));
}
