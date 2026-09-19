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

fn evidence() -> NduConditionalIdentificationEvidenceV1 {
    NduConditionalIdentificationEvidenceV1 {
        receipt_id: id("conditional-identification-1"),
        coefficient_manifest_digest: digest("coefficient-manifest"),
        objective_class_digest: digest("objective-class"),
        conditioning_spec_digest: digest("conditioning"),
        training_fold_digest: digest("training-fold"),
        holdout_fold_digest: digest("holdout-fold"),
        pre_boundary_feature_digest: digest("pre-boundary-features"),
        outcome_time_policy_digest: digest("outcome-time-policy"),
        overlap_support_digest: digest("overlap-support"),
        leakage_audit_digest: digest("leakage-audit"),
        sample_count: 512,
        minimum_sample_count: 128,
        maximum_abs_standardized_conditional_mean_q32: q32_ratio(1, 100),
        evaluator_identity: id("independent-evaluator"),
        candidate_producer_identity: id("candidate-producer"),
        expires_unix_ms: 2_000,
    }
}

#[test]
fn independent_supported_identification_can_be_accepted() {
    let receipt = evaluate_ndu_conditional_identification_v1(&evidence(), 1_000)
        .expect("valid evidence");
    assert_eq!(
        receipt.decision,
        NduConditionalIdentificationDecisionV1::Accepted
    );
    assert!(
        !canonical_ndu_conditional_identification_receipt_digest_v1(&receipt).is_zero()
    );
}

#[test]
fn missing_overlap_or_too_few_samples_is_unavailable() {
    let mut missing = evidence();
    missing.overlap_support_digest = Digest32::ZERO;
    assert_eq!(
        evaluate_ndu_conditional_identification_v1(&missing, 1_000)
            .expect("structurally valid")
            .decision,
        NduConditionalIdentificationDecisionV1::Unavailable
    );

    let mut sparse = evidence();
    sparse.sample_count = 127;
    assert_eq!(
        evaluate_ndu_conditional_identification_v1(&sparse, 1_000)
            .expect("structurally valid")
            .decision,
        NduConditionalIdentificationDecisionV1::Unavailable
    );
}

#[test]
fn leakage_or_conditional_mean_failure_rejects() {
    let mut leaked = evidence();
    leaked.holdout_fold_digest = leaked.training_fold_digest;
    assert_eq!(
        evaluate_ndu_conditional_identification_v1(&leaked, 1_000)
            .expect("structurally valid")
            .decision,
        NduConditionalIdentificationDecisionV1::Rejected
    );

    let mut mean = evidence();
    mean.maximum_abs_standardized_conditional_mean_q32 = q32_ratio(2, 100);
    assert_eq!(
        evaluate_ndu_conditional_identification_v1(&mean, 1_000)
            .expect("structurally valid")
            .decision,
        NduConditionalIdentificationDecisionV1::Rejected
    );
}

#[test]
fn self_evaluation_and_expiry_fail_before_decision() {
    let mut self_eval = evidence();
    self_eval.evaluator_identity = self_eval.candidate_producer_identity.clone();
    assert_eq!(
        evaluate_ndu_conditional_identification_v1(&self_eval, 1_000)
            .expect_err("self evaluation rejects"),
        NduConditionalIdentificationError::SelfEvaluation
    );
    assert_eq!(
        evaluate_ndu_conditional_identification_v1(&evidence(), 2_000)
            .expect_err("expired evidence rejects"),
        NduConditionalIdentificationError::Expired
    );
}
