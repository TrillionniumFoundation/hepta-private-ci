    #![allow(clippy::expect_used)]
    use super::*;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    fn policy() -> NduFbsdeAcceptancePolicyV1 {
        NduFbsdeAcceptancePolicyV1::new(100, 10, 25_000, 1, 0)
            .expect("acceptance policy")
    }

    fn evidence() -> NduFbsdeIndependentEvidenceV1 {
        NduFbsdeIndependentEvidenceV1 {
            candidate_digest: digest(b"candidate"),
            registered_dataset_digest: digest(b"registered-dataset"),
            immutable_dataset_binding_digest: digest(b"dataset-binding"),
            filtration_audit_digest: digest(b"filtration"),
            leakage_audit_digest: digest(b"leakage"),
            independent_evaluator_identity_digest: digest(b"independent-evaluator"),
            independent_evaluator_receipt_digest: digest(b"independent-receipt"),
            trusted_time_receipt_digest: digest(b"trusted-time"),
            independent_oracle_digest: digest(b"oracle"),
            convergence_envelope_digest: digest(b"convergence"),
            calibration_receipt_digest: digest(b"calibration"),
            utility_improvement_receipt_digest: digest(b"utility"),
            regression_receipt_digest: digest(b"regression"),
            rollback_trigger_digest: digest(b"rollback"),
            runtime_receipt_digest: digest(b"runtime"),
            production_policy_digest: digest(b"production-policy"),
            shadow_sample_count: 120,
            maximum_convergence_residual_q24: 5,
            calibration_error_ppm: 10_000,
            utility_improvement_lower_bound_q24: 2,
            regression_failure_count: 0,
        }
    }

    #[test]
    fn promotion_is_monotone_and_never_grants_authority() {
        let policy = policy();
        let evidence = evidence();
        let shadow = evaluate_ndu_fbsde_acceptance_v1(
            NduFbsdeAcceptanceStageV1::Shadow,
            &policy,
            &evidence,
            None,
        )
        .expect("shadow");
        let advisory = evaluate_ndu_fbsde_acceptance_v1(
            NduFbsdeAcceptanceStageV1::Advisory,
            &policy,
            &evidence,
            Some(&shadow),
        )
        .expect("advisory");
        let restricted = evaluate_ndu_fbsde_acceptance_v1(
            NduFbsdeAcceptanceStageV1::RestrictedWrite,
            &policy,
            &evidence,
            Some(&advisory),
        )
        .expect("restricted");
        assert_eq!(restricted.authority(), AuthorityPosture::DENY_ALL);
    }
