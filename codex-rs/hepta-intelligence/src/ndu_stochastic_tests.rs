use codex_hepta_intelligence_eval::NduAssumptionCheckV1;
use codex_hepta_intelligence_eval::NduConditionalIdentificationEvidenceV1;
use codex_hepta_intelligence_eval::NduConditionalMeanCheckV1;
use codex_hepta_intelligence_eval::NduContinuityScopeV1;
use codex_hepta_intelligence_eval::NduConvergenceEvidenceV1;
use codex_hepta_intelligence_eval::NduMultipleSolutionDispositionV1;
use codex_hepta_intelligence_eval::NduSubjectClassV1;
use codex_hepta_intelligence_eval::NduWellPosednessEvidenceV1;
use codex_hepta_intelligence_eval::evaluate_ndu_conditional_identification_v1;
use codex_hepta_intelligence_eval::evaluate_ndu_convergence_v1;
use codex_hepta_intelligence_eval::evaluate_ndu_well_posedness_v1;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::DatasetWithdrawalNoticeV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_artifacts::admit_manifest_at_withdrawal_head_v3;
use codex_hepta_ndu::CovarianceConventionV1;
use codex_hepta_ndu::NduCovarianceProfileV1;
use codex_hepta_ndu::NduZConversionProfileV1;
use codex_hepta_ndu::ZCoordinateConventionV1;
use codex_hepta_ndu::admit_covariance_profile;
use codex_hepta_ndu::admit_z_conversion_profile;
use codex_hepta_ndu::convert_z_to_original_q24;
use codex_hepta_types::Generation;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32_ratio(numerator: i64, denominator: i64) -> i64 {
    let raw = (i128::from(numerator) << 32) / i128::from(denominator);
    i64::try_from(raw).expect("fixture ratio fits")
}

fn manifest(
    dataset: Digest32,
    coefficient_manifest: Digest32,
    objective: Digest32,
    include_coefficient_lineage: bool,
) -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id("ndu-coefficient-artifact"),
        kind: ArtifactKind::Parameters,
        generation: Generation::new(1).expect("generation"),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![dataset],
        lineage_digests: vec![if include_coefficient_lineage {
            coefficient_manifest
        } else {
            digest("other-lineage")
        }],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: digest("artifact-bytes"),
        encoded_size_bytes: 512,
        training_code_digest: digest("training-code"),
        runtime_tuple_digest: digest("runtime-tuple"),
        device_profile_digest: digest("device-profile"),
        objective_class_digest: objective,
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema-profile"),
        normalization_digest: digest("normalization"),
        producer_id: id("candidate-producer"),
        created_at: 10,
        expires_at: 2_000,
    }
}

fn assumption(label: &str) -> NduAssumptionCheckV1 {
    NduAssumptionCheckV1 {
        support_digest: digest(label),
        satisfied: true,
    }
}

struct Fixture {
    registry: DatasetWithdrawalRegistry,
    admission: WithdrawalBoundArtifactAdmissionV3,
    covariance: AdmittedCovarianceProfileV1,
    z_profile: AdmittedZConversionProfileV1,
    z_receipt: ZQ24ConversionReceiptV1,
    identification: NduConditionalIdentificationReceiptV1,
    well_posedness: NduWellPosednessCertificateV1,
    convergence: NduConvergenceCertificateV1,
    coefficient_manifest: Digest32,
    objective: Digest32,
    dataset: Digest32,
}

impl Fixture {
    fn new(include_coefficient_lineage: bool) -> Self {
        let coefficient_manifest = digest("coefficient-manifest");
        let objective = digest("objective-class");
        let dataset = digest("dataset");
        let registry = DatasetWithdrawalRegistry::new();
        let admission = admit_manifest_at_withdrawal_head_v3(
            &registry,
            registry.snapshot().head_digest,
            manifest(
                dataset,
                coefficient_manifest,
                objective,
                include_coefficient_lineage,
            ),
            50,
        )
        .expect("artifact admission");

        let units = digest("driver-units");
        let covariance = admit_covariance_profile(NduCovarianceProfileV1 {
            units_digest: units,
            driver_dimension: 1,
            utility_dimension: 1,
            convention: CovarianceConventionV1::Increment,
            minimum_increment_eigenvalue: 1e-9,
            maximum_condition: 1e6,
            maximum_absolute_sample: 1e6,
            maximum_absolute_z: 100.0,
            maximum_relative_residual: 1e-8,
        })
        .expect("covariance profile");
        let z_profile = admit_z_conversion_profile(NduZConversionProfileV1 {
            units_digest: units,
            driver_dimension: 1,
            utility_dimension: 1,
            source_coordinates: ZCoordinateConventionV1::OriginalIncrement,
            whitening_lower: Vec::new(),
            maximum_absolute_z: 100.0,
        })
        .expect("z profile");
        let z_receipt = convert_z_to_original_q24(
            &[vec![3.0]],
            digest("source-z"),
            &z_profile,
        )
        .expect("z conversion");

        let identification = evaluate_ndu_conditional_identification_v1(
            &NduConditionalIdentificationEvidenceV1 {
                receipt_id: id("identification"),
                coefficient_manifest_digest: coefficient_manifest,
                objective_class_digest: objective,
                conditioning_spec_digest: digest("conditioning"),
                training_fold_digest: digest("train-fold"),
                holdout_fold_digest: digest("holdout-fold"),
                pre_boundary_feature_digest: digest("pre-boundary"),
                outcome_time_policy_digest: digest("outcome-time"),
                overlap_support_digest: digest("overlap"),
                leakage_audit_digest: digest("leakage-audit"),
                sample_count: 512,
                minimum_sample_count: 128,
                maximum_abs_standardized_conditional_mean_q32: q32_ratio(1, 100),
                evaluator_identity: id("independent-evaluator"),
                candidate_producer_identity: id("candidate-producer"),
                expires_unix_ms: 2_000,
            },
            50,
        )
        .expect("identification");

        let well_posedness = evaluate_ndu_well_posedness_v1(
            &NduWellPosednessEvidenceV1 {
                certificate_id: id("well-posedness"),
                manifest_digest: coefficient_manifest,
                operating_domain_digest: digest("operating-domain"),
                square_integrability: assumption("square-integrability"),
                conditional_mean: NduConditionalMeanCheckV1 {
                    support_digest: digest("conditional-mean"),
                    maximum_abs_standardized_q32: q32_ratio(1, 100),
                },
                coefficient_bounds: assumption("coefficient-bounds"),
                lipschitz: assumption("lipschitz"),
                generator_monotonicity: assumption("generator-monotonicity"),
                terminal_lipschitz: assumption("terminal-lipschitz"),
                continuity_scope: NduContinuityScopeV1::QualifiedOperatingRegion,
                solver_stability: assumption("solver-stability"),
                evaluator_identity: id("independent-evaluator"),
                candidate_producer_identity: id("candidate-producer"),
                expires_unix_ms: 2_000,
            },
            50,
        )
        .expect("well posedness");

        let convergence = evaluate_ndu_convergence_v1(&NduConvergenceEvidenceV1 {
            certificate_id: id("convergence"),
            subject_class: NduSubjectClassV1::Agent,
            objective_class_digest: objective,
            current_objective_class_digest: objective,
            solver_digest: digest("solver"),
            initialization_digest: digest("initialization"),
            iterations: 12,
            maximum_residual_q32: 1_i64 << 12,
            spectral_radius_upper95_q32: q32_ratio(94, 100),
            conservation_residual_q32: 1,
            multiple_solution_disposition: NduMultipleSolutionDispositionV1::Unique,
            evaluator_identity: id("independent-evaluator"),
            candidate_producer_identity: id("candidate-producer"),
            operating_region_digest: digest("operating-region"),
            perturbation_support_digest: digest("perturbations"),
            stability_support_digest: digest("stability"),
            conservation_support_digest: digest("conservation"),
        })
        .expect("convergence");

        Self {
            registry,
            admission,
            covariance,
            z_profile,
            z_receipt,
            identification,
            well_posedness,
            convergence,
            coefficient_manifest,
            objective,
            dataset,
        }
    }

    fn request(&self) -> NduStochasticCompositionRequestV1<'_> {
        NduStochasticCompositionRequestV1 {
            artifact_admission: &self.admission,
            withdrawal_registry: &self.registry,
            coefficient_manifest_digest: self.coefficient_manifest,
            expected_objective_class_digest: self.objective,
            covariance_profile: &self.covariance,
            z_conversion_profile: &self.z_profile,
            z_conversion_receipt: &self.z_receipt,
            conditional_identification: &self.identification,
            well_posedness: &self.well_posedness,
            convergence: &self.convergence,
            now_unix_ms: 50,
        }
    }
}

#[test]
fn typed_cross_owner_evidence_admits_only_authority_free_candidate() {
    let fixture = Fixture::new(true);
    let receipt =
        admit_ndu_stochastic_product_candidate_v1(fixture.request()).expect("composition");
    assert!(!receipt.authority.grants_any());
    assert!(!receipt.composition_digest.is_zero());
    assert!(!receipt.stochastic_admission.admission_digest().is_zero());
    assert_eq!(
        receipt.stochastic_admission.binding().coefficient_manifest_digest,
        fixture.coefficient_manifest
    );
}

#[test]
fn current_dataset_withdrawal_invalidates_prior_artifact_admission() {
    let mut fixture = Fixture::new(true);
    fixture
        .registry
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdrawal"),
            dataset_digest: fixture.dataset,
            source_tombstone_digest: digest("tombstone"),
            authority_id: id("data-authority"),
            credential_chain_digest: digest("credential"),
            signing_key_digest: digest("signing-key"),
            authority_epoch: 1,
            issued_at: 60,
        })
        .expect("withdrawal");
    assert!(matches!(
        admit_ndu_stochastic_product_candidate_v1(fixture.request()),
        Err(NduStochasticCompositionError::Artifact(
            ArtifactAdmissionError::WithdrawalHeadChanged
        ))
    ));
}

#[test]
fn coefficient_manifest_must_be_bound_by_artifact_lineage() {
    let fixture = Fixture::new(false);
    assert_eq!(
        admit_ndu_stochastic_product_candidate_v1(fixture.request())
            .expect_err("unbound coefficient manifest rejects"),
        NduStochasticCompositionError::Binding("coefficient manifest lineage")
    );
}

#[test]
fn incompatible_numeric_profiles_reject_before_ndu_admission() {
    let mut fixture = Fixture::new(true);
    fixture.z_profile = admit_z_conversion_profile(NduZConversionProfileV1 {
        units_digest: digest("different-units"),
        driver_dimension: 1,
        utility_dimension: 1,
        source_coordinates: ZCoordinateConventionV1::OriginalIncrement,
        whitening_lower: Vec::new(),
        maximum_absolute_z: 100.0,
    })
    .expect("alternate z profile");
    assert_eq!(
        admit_ndu_stochastic_product_candidate_v1(fixture.request())
            .expect_err("profile mismatch rejects"),
        NduStochasticCompositionError::Binding("numeric profile compatibility")
    );
}

#[test]
fn nonaccepted_independent_identification_never_reaches_ndu_admission() {
    let mut fixture = Fixture::new(true);
    fixture.identification = evaluate_ndu_conditional_identification_v1(
        &NduConditionalIdentificationEvidenceV1 {
            receipt_id: id("identification-rejected"),
            coefficient_manifest_digest: fixture.coefficient_manifest,
            objective_class_digest: fixture.objective,
            conditioning_spec_digest: digest("conditioning"),
            training_fold_digest: digest("train-fold"),
            holdout_fold_digest: digest("holdout-fold"),
            pre_boundary_feature_digest: digest("pre-boundary"),
            outcome_time_policy_digest: digest("outcome-time"),
            overlap_support_digest: digest("overlap"),
            leakage_audit_digest: digest("leakage"),
            sample_count: 512,
            minimum_sample_count: 128,
            maximum_abs_standardized_conditional_mean_q32: q32_ratio(2, 100),
            evaluator_identity: id("independent-evaluator"),
            candidate_producer_identity: id("candidate-producer"),
            expires_unix_ms: 2_000,
        },
        50,
    )
    .expect("rejected decision is still a receipt");
    assert_eq!(
        admit_ndu_stochastic_product_candidate_v1(fixture.request())
            .expect_err("rejected identification blocks composition"),
        NduStochasticCompositionError::Binding("conditional identification")
    );
}
