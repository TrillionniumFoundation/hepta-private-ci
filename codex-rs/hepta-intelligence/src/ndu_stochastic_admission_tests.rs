use codex_hepta_intelligence_eval::NduAssumptionEvidenceV1;
use codex_hepta_intelligence_eval::NduConditionalMeanEvidenceV1;
use codex_hepta_intelligence_eval::NduContinuityScopeV1;
use codex_hepta_intelligence_eval::NduConvergenceDecisionV1;
use codex_hepta_intelligence_eval::NduConvergenceEvidenceV1;
use codex_hepta_intelligence_eval::NduMultipleSolutionDispositionV1;
use codex_hepta_intelligence_eval::NduSubjectClassV1;
use codex_hepta_intelligence_eval::NduWellPosednessDecisionV1;
use codex_hepta_intelligence_eval::NduWellPosednessEvidenceV1;
use codex_hepta_intelligence_eval::decide_ndu_convergence_v1;
use codex_hepta_intelligence_eval::decide_ndu_well_posedness_v1;
use codex_hepta_ndu::CovarianceConventionV1;
use codex_hepta_ndu::NduCoefficientProfileV1;
use codex_hepta_ndu::NduCovarianceProfileV1;
use codex_hepta_ndu::ZEstimateV1;
use codex_hepta_ndu::admit_covariance_profile;
use codex_hepta_ndu::admit_ndu_coefficient_profile;
use codex_hepta_ndu::quantize_z_to_q24;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::NduStochasticAdmissionError;
use super::NduStochasticAdmissionRequestV1;
use super::admit_ndu_stochastic_candidate_v1;
use super::canonical_ndu_stochastic_solver_digest_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn coefficient_profile() -> codex_hepta_ndu::AdmittedNduCoefficientProfileV1 {
    let covariance = admit_covariance_profile(NduCovarianceProfileV1 {
        units_digest: digest("driver-units"),
        driver_dimension: 2,
        utility_dimension: 1,
        convention: CovarianceConventionV1::Increment,
        minimum_increment_eigenvalue: 1e-8,
        maximum_condition: 1e6,
        maximum_absolute_sample: 1e6,
        maximum_absolute_z: 100.0,
        maximum_relative_residual: 1e-10,
    })
    .expect("admitted covariance");
    admit_ndu_coefficient_profile(
        NduCoefficientProfileV1 {
            manifest_digest: digest("coefficient-manifest"),
            normalization_digest: digest("normalization"),
            runtime_tuple_digest: digest("runtime"),
            coordinate_digest: digest("original-coordinate-order"),
            covariance_profile_digest: covariance.digest(),
            units_digest: digest("driver-units"),
            driver_dimension: 2,
            utility_dimension: 1,
            expires_unix_ms: 20_000,
        },
        &covariance,
    )
    .expect("admitted coefficient profile")
}

fn z_projection(
    profile: &codex_hepta_ndu::AdmittedNduCoefficientProfileV1,
) -> codex_hepta_ndu::NduZQ24ProjectionV1 {
    quantize_z_to_q24(
        &ZEstimateV1 {
            z: vec![vec![3.0, -1.0]],
            condition_estimate: 1.0,
            increment_eigenvalue_lower_estimate: 1.0,
            maximum_relative_residual: 0.0,
            evidence_digest: digest("z-estimate"),
            authority: AuthorityPosture::DENY_ALL,
        },
        profile,
        5_000,
    )
    .expect("q24 projection")
}

fn assumption(name: &str, satisfied: bool) -> NduAssumptionEvidenceV1 {
    NduAssumptionEvidenceV1 {
        evidence_digest: digest(name),
        satisfied,
    }
}

fn well_posedness(
    manifest_digest: Digest32,
    domain_digest: Digest32,
    monotonicity: bool,
) -> codex_hepta_intelligence_eval::NduWellPosednessCertificateV1 {
    decide_ndu_well_posedness_v1(
        NduWellPosednessEvidenceV1 {
            certificate_id: id("well-posedness"),
            manifest_digest,
            operating_domain_digest: domain_digest,
            square_integrability: assumption("square-integrability", true),
            conditional_mean: NduConditionalMeanEvidenceV1 {
                evidence_digest: digest("conditional-mean"),
                standardized_absolute_mean_q32: (1_i64 << 32) / 100,
            },
            coefficient_bounds: assumption("coefficient-bounds", true),
            lipschitz: assumption("lipschitz", true),
            generator_monotonicity: assumption("generator-monotonicity", monotonicity),
            terminal_lipschitz: assumption("terminal-lipschitz", true),
            continuity_scope: NduContinuityScopeV1::DeclaredOperatingDomain,
            solver_stability: assumption("solver-stability", true),
            evaluator_identity: id("learning-eval-well-posedness"),
            candidate_producer_identity: id("utility-ndu"),
            expires_unix_ms: 15_000,
        },
        5_000,
    )
    .expect("well-posedness decision")
}

fn convergence(
    solver_digest: Digest32,
    objective_class_digest: Digest32,
    spectral_percent: i64,
    perturbation: &str,
) -> codex_hepta_intelligence_eval::NduConvergenceCertificateV1 {
    decide_ndu_convergence_v1(NduConvergenceEvidenceV1 {
        certificate_id: id("convergence"),
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest,
        solver_digest,
        initialization_digest: digest("initialization"),
        iterations: 16,
        maximum_residual_q32: 1 << 10,
        spectral_radius_upper95_q32: (spectral_percent * (1_i64 << 32)) / 100,
        conservation_residual_q32: 1,
        multiple_solution_disposition: NduMultipleSolutionDispositionV1::Unique,
        evaluator_identity: id("learning-eval-convergence"),
        candidate_producer_identity: id("utility-ndu"),
        perturbation_evidence_digest: digest(perturbation),
        stability_evidence_digest: digest("stability"),
        conservation_evidence_digest: digest("conservation"),
    })
    .expect("convergence decision")
}

#[test]
fn independently_accepted_fbsde_evidence_composes_to_deny_all_admission() {
    let profile = coefficient_profile();
    let projection = z_projection(&profile);
    let objective = digest("objective-class");
    let domain = digest("operating-domain");
    let solver = canonical_ndu_stochastic_solver_digest_v1(&profile, &projection)
        .expect("canonical solver identity");
    let convergence = convergence(solver, objective, 90, "perturbation");
    let well_posedness = well_posedness(profile.manifest_digest(), domain, true);

    assert_eq!(convergence.decision(), NduConvergenceDecisionV1::Accepted);
    assert_eq!(
        well_posedness.decision(),
        NduWellPosednessDecisionV1::Accepted
    );
    let receipt = admit_ndu_stochastic_candidate_v1(
        NduStochasticAdmissionRequestV1 {
            coefficient_profile: &profile,
            z_projection: &projection,
            convergence: &convergence,
            well_posedness: &well_posedness,
            objective_class_digest: objective,
            operating_domain_digest: domain,
        },
        5_000,
    )
    .expect("independently qualified source admission");

    assert_eq!(receipt.solver_digest, solver);
    assert_eq!(receipt.z_output_digest, projection.output_digest);
    assert!(!receipt.admission_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}

#[test]
fn solver_identity_mismatch_rejects_even_when_certificate_is_accepted() {
    let profile = coefficient_profile();
    let projection = z_projection(&profile);
    let objective = digest("objective-class");
    let domain = digest("operating-domain");
    let convergence = convergence(digest("different-solver"), objective, 90, "perturbation");
    let well_posedness = well_posedness(profile.manifest_digest(), domain, true);

    assert_eq!(
        admit_ndu_stochastic_candidate_v1(
            NduStochasticAdmissionRequestV1 {
                coefficient_profile: &profile,
                z_projection: &projection,
                convergence: &convergence,
                well_posedness: &well_posedness,
                objective_class_digest: objective,
                operating_domain_digest: domain,
            },
            5_000,
        )
        .expect_err("accepted evidence for another solver must not compose"),
        NduStochasticAdmissionError::SolverMismatch
    );
}

#[test]
fn independent_rejection_or_manifest_drift_blocks_admission() {
    let profile = coefficient_profile();
    let projection = z_projection(&profile);
    let objective = digest("objective-class");
    let domain = digest("operating-domain");
    let solver = canonical_ndu_stochastic_solver_digest_v1(&profile, &projection)
        .expect("canonical solver identity");

    let rejected_convergence = convergence(solver, objective, 95, "perturbation");
    let valid_well_posedness = well_posedness(profile.manifest_digest(), domain, true);
    assert_eq!(
        admit_ndu_stochastic_candidate_v1(
            NduStochasticAdmissionRequestV1 {
                coefficient_profile: &profile,
                z_projection: &projection,
                convergence: &rejected_convergence,
                well_posedness: &valid_well_posedness,
                objective_class_digest: objective,
                operating_domain_digest: domain,
            },
            5_000,
        )
        .expect_err("rejected convergence cannot compose"),
        NduStochasticAdmissionError::ConvergenceNotAccepted
    );

    let accepted_convergence = convergence(solver, objective, 90, "perturbation");
    let wrong_manifest = well_posedness(digest("other-manifest"), domain, true);
    assert_eq!(
        admit_ndu_stochastic_candidate_v1(
            NduStochasticAdmissionRequestV1 {
                coefficient_profile: &profile,
                z_projection: &projection,
                convergence: &accepted_convergence,
                well_posedness: &wrong_manifest,
                objective_class_digest: objective,
                operating_domain_digest: domain,
            },
            5_000,
        )
        .expect_err("well-posedness must bind the same coefficient manifest"),
        NduStochasticAdmissionError::CoefficientProfileMismatch
    );

    let rejected_well_posedness = well_posedness(profile.manifest_digest(), domain, false);
    assert_eq!(
        admit_ndu_stochastic_candidate_v1(
            NduStochasticAdmissionRequestV1 {
                coefficient_profile: &profile,
                z_projection: &projection,
                convergence: &accepted_convergence,
                well_posedness: &rejected_well_posedness,
                objective_class_digest: objective,
                operating_domain_digest: domain,
            },
            5_000,
        )
        .expect_err("failed well-posedness assumption cannot compose"),
        NduStochasticAdmissionError::WellPosednessNotAccepted
    );
}

#[test]
fn admission_digest_binds_independent_certificate_evidence() {
    let profile = coefficient_profile();
    let projection = z_projection(&profile);
    let objective = digest("objective-class");
    let domain = digest("operating-domain");
    let solver = canonical_ndu_stochastic_solver_digest_v1(&profile, &projection)
        .expect("canonical solver identity");
    let well_posedness = well_posedness(profile.manifest_digest(), domain, true);

    let first_convergence = convergence(solver, objective, 90, "perturbation-a");
    let first = admit_ndu_stochastic_candidate_v1(
        NduStochasticAdmissionRequestV1 {
            coefficient_profile: &profile,
            z_projection: &projection,
            convergence: &first_convergence,
            well_posedness: &well_posedness,
            objective_class_digest: objective,
            operating_domain_digest: domain,
        },
        5_000,
    )
    .expect("first admission");

    let second_convergence = convergence(solver, objective, 90, "perturbation-b");
    let second = admit_ndu_stochastic_candidate_v1(
        NduStochasticAdmissionRequestV1 {
            coefficient_profile: &profile,
            z_projection: &projection,
            convergence: &second_convergence,
            well_posedness: &well_posedness,
            objective_class_digest: objective,
            operating_domain_digest: domain,
        },
        5_000,
    )
    .expect("second admission");

    assert_ne!(first.convergence_certificate_digest, second.convergence_certificate_digest);
    assert_ne!(first.admission_digest, second.admission_digest);
}
