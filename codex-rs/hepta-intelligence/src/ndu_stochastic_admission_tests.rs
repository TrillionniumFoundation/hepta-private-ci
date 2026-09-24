use std::fs::File;
use std::path::PathBuf;

use codex_hepta_intelligence_eval::NduAssumptionEvidenceV1;
use codex_hepta_intelligence_eval::NduConditionalMeanEvidenceV1;
use codex_hepta_intelligence_eval::NduContinuityScopeV1;
use codex_hepta_intelligence_eval::NduConvergenceEvidenceV1;
use codex_hepta_intelligence_eval::NduMultipleSolutionDispositionV1;
use codex_hepta_intelligence_eval::NduSubjectClassV1;
use codex_hepta_intelligence_eval::NduWellPosednessEvidenceV1;
use codex_hepta_intelligence_eval::decide_ndu_convergence_v1;
use codex_hepta_intelligence_eval::decide_ndu_well_posedness_v1;
use codex_hepta_intelligence_eval::ndu_convergence_evaluator_signing_payload_v1;
use codex_hepta_intelligence_eval::ndu_convergence_producer_signing_payload_v1;
use codex_hepta_intelligence_eval::ndu_well_posedness_evaluator_signing_payload_v1;
use codex_hepta_intelligence_eval::ndu_well_posedness_producer_signing_payload_v1;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::DatasetWithdrawalNoticeV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::PinnedCandidateSpec;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_artifacts::RegistryHeadRequirementV1;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::WithdrawalBoundArtifactAdmissionV3;
use codex_hepta_learning_artifacts::admit_manifest_at_withdrawal_head_v3;
use codex_hepta_learning_artifacts::load_pinned_candidate;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_ndu::AdmittedNduCoefficientProfileV1;
use codex_hepta_ndu::CovarianceConventionV1;
use codex_hepta_ndu::NduCoefficientProfileV1;
use codex_hepta_ndu::NduCoefficientProjectionV1;
use codex_hepta_ndu::NduCovarianceProfileV1;
use codex_hepta_ndu::NduZConversionProfileV1;
use codex_hepta_ndu::ZCoordinateConventionV1;
use codex_hepta_ndu::ZEstimateV1;
use codex_hepta_ndu::admit_covariance_profile;
use codex_hepta_ndu::admit_ndu_coefficient_profile;
use codex_hepta_ndu::admit_z_conversion_profile;
use codex_hepta_ndu::project_z_estimate_to_coefficient_q24;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("id: {error:?}"))
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn principal(name: &str, key: &SigningKey) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: digest("ndu-eval-scope"),
        authority_epoch: 9,
        authenticated_at: 1,
        expires_at: 100,
    }
}

fn evidence_verifier() -> (LearningEvidenceVerifierV1, SigningKey, SigningKey) {
    let producer_key = SigningKey::from_bytes(&[31; 32]);
    let evaluator_key = SigningKey::from_bytes(&[32; 32]);
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("ndu-eval-scope"),
        objective_digest: digest("objective-class"),
        authority_epoch: 9,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: principal("artifact-producer", &producer_key),
                controller_id: id("producer-controller"),
                verifying_key: producer_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: principal("independent-evaluator", &evaluator_key),
                controller_id: id("evaluator-controller"),
                verifying_key: evaluator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
        ],
    })
    .unwrap_or_else(|error| panic!("trust: {error:?}"));
    (verifier, producer_key, evaluator_key)
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    key: &SigningKey,
    principal: &str,
    role: LearningEvidenceRoleV1,
    evidence_id: &str,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id),
        principal_id: id(principal),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: 10,
        expires_at: 80,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    signed
}

struct Fixture {
    _dir: tempfile::TempDir,
    snapshot_path: PathBuf,
    snapshot_receipt: RegistrySnapshotReceipt,
    candidate: RevalidatingCandidate,
    withdrawal_registry: DatasetWithdrawalRegistry,
    dataset_digest: Digest32,
    artifact_admission: WithdrawalBoundArtifactAdmissionV3,
    coefficient_profile: AdmittedNduCoefficientProfileV1,
    projection: NduCoefficientProjectionV1,
    convergence: codex_hepta_intelligence_eval::NduConvergenceCertificateV1,
    well_posedness: codex_hepta_intelligence_eval::NduWellPosednessCertificateV1,
}

fn fixture() -> Fixture {
    let dir = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error:?}"));
    let snapshot_path = dir.path().join("registry.snapshot");
    let payload_path = dir.path().join("candidate.payload");
    let payload = b"ndu-coefficient-bytes-v1";
    let artifact_id = id("ndu-coefficients");

    let v1_manifest = ArtifactManifest {
        artifact_id: artifact_id.clone(),
        kind: ArtifactKind::Parameters,
        generation: Generation::new(1).unwrap_or_else(|error| panic!("generation: {error:?}")),
        predecessor_id: None,
        content_digest: Digest32::of_bytes(payload),
        objective_digest: digest("objective-exact"),
        support_digest: digest("artifact-support"),
        producer_id: id("artifact-producer"),
        compatibility_digest: digest("ndu-runtime-compatibility"),
        encoded_size_bytes: payload.len() as u64,
    };
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register-ndu-coefficients"),
            manifest: v1_manifest.clone(),
        })
        .unwrap_or_else(|error| panic!("register: {error:?}"));
    let snapshot_receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&snapshot_path)
            .unwrap_or_else(|error| panic!("snapshot create: {error:?}")),
        &registry,
        digest("artifact-registry-binding"),
    )
    .unwrap_or_else(|error| panic!("snapshot: {error:?}"));
    write_candidate_payload(
        CreateOnlyArtifactFile::create(&payload_path)
            .unwrap_or_else(|error| panic!("payload create: {error:?}")),
        &registry,
        &artifact_id,
        payload,
    )
    .unwrap_or_else(|error| panic!("payload: {error:?}"));
    let loaded = load_pinned_candidate(
        File::open(&snapshot_path).unwrap_or_else(|error| panic!("snapshot open: {error:?}")),
        File::open(&payload_path).unwrap_or_else(|error| panic!("payload open: {error:?}")),
        PinnedCandidateSpec {
            registry_receipt: snapshot_receipt,
            manifest: v1_manifest,
        },
    )
    .unwrap_or_else(|error| panic!("pinned candidate: {error:?}"));
    let candidate = RevalidatingCandidate::new(loaded);

    let dataset_digest = digest("training-dataset");
    let withdrawal_registry = DatasetWithdrawalRegistry::new_scoped(
        codex_hepta_learning_artifacts::DatasetWithdrawalScopeV1 {
            authority_domain_id: id("dataset-authority"),
            registry_id: id("ndu-withdrawals"),
            scope_id: id("ndu-training"),
        },
    );
    let v2_manifest = LearningArtifactManifestV2 {
        artifact_id,
        kind: ArtifactKind::Parameters,
        generation: Generation::new(1).unwrap_or_else(|error| panic!("generation: {error:?}")),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![dataset_digest],
        lineage_digests: vec![digest("dataset-lineage")],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: Digest32::of_bytes(payload),
        encoded_size_bytes: payload.len() as u64,
        training_code_digest: digest("training-code"),
        runtime_tuple_digest: digest("runtime-tuple"),
        device_profile_digest: digest("device-profile"),
        objective_class_digest: digest("objective-class"),
        compatibility_digest: digest("ndu-runtime-compatibility"),
        schema_profile_digest: digest("ndu-coefficient-schema"),
        normalization_digest: digest("normalization"),
        producer_id: id("artifact-producer"),
        created_at: 10,
        expires_at: 100,
    };
    let artifact_admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawal_registry,
        withdrawal_registry.snapshot().head_digest,
        v2_manifest,
        50,
    )
    .unwrap_or_else(|error| panic!("artifact admission: {error:?}"));

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
    .unwrap_or_else(|error| panic!("covariance: {error:?}"));
    let z_conversion = admit_z_conversion_profile(NduZConversionProfileV1 {
        units_digest: digest("driver-units"),
        driver_dimension: 2,
        utility_dimension: 1,
        source_coordinates: ZCoordinateConventionV1::OriginalIncrement,
        whitening_lower: Vec::new(),
        maximum_absolute_z: 100.0,
    })
    .unwrap_or_else(|error| panic!("z conversion: {error:?}"));
    let coefficient_profile = admit_ndu_coefficient_profile(
        NduCoefficientProfileV1 {
            artifact_manifest_digest: artifact_admission.validated_manifest.manifest_digest,
            normalization_digest: digest("normalization"),
            runtime_tuple_digest: digest("runtime-tuple"),
            covariance_profile_digest: covariance.digest(),
            z_conversion_profile_digest: z_conversion.digest(),
            units_digest: digest("driver-units"),
            driver_dimension: 2,
            utility_dimension: 1,
            expires_unix_ms: 80,
        },
        &covariance,
        &z_conversion,
    )
    .unwrap_or_else(|error| panic!("coefficient profile: {error:?}"));
    let estimate = ZEstimateV1 {
        z: vec![vec![3.0, -1.0]],
        covariance_profile_digest: covariance.digest(),
        condition_estimate: 1.0,
        increment_eigenvalue_lower_estimate: 1.0,
        maximum_relative_residual: 0.0,
        evidence_digest: digest("z-estimate"),
        authority: AuthorityPosture::DENY_ALL,
    };
    let projection =
        project_z_estimate_to_coefficient_q24(&estimate, &coefficient_profile, &z_conversion, 50)
            .unwrap_or_else(|error| panic!("q24 projection: {error:?}"));
    let solver_digest =
        canonical_ndu_stochastic_solver_digest_v1(&coefficient_profile, &projection)
            .unwrap_or_else(|error| panic!("solver digest: {error:?}"));

    let convergence_evidence = NduConvergenceEvidenceV1 {
        certificate_id: id("convergence"),
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest: digest("objective-class"),
        solver_digest,
        initialization_digest: digest("initialization"),
        iterations: 16,
        maximum_residual_q32: 1 << 10,
        spectral_radius_upper95_q32: (90_i64 * (1_i64 << 32)) / 100,
        conservation_residual_q32: 1,
        multiple_solution_disposition: NduMultipleSolutionDispositionV1::Unique,
        perturbation_evidence_digest: digest("perturbation"),
        stability_evidence_digest: digest("stability"),
        conservation_evidence_digest: digest("conservation"),
    };
    let well_evidence = NduWellPosednessEvidenceV1 {
        certificate_id: id("well-posedness"),
        artifact_manifest_digest: artifact_admission.validated_manifest.manifest_digest,
        objective_class_digest: digest("objective-class"),
        operating_domain_digest: digest("operating-domain"),
        square_integrability: NduAssumptionEvidenceV1 {
            evidence_digest: digest("square-integrability"),
            satisfied: true,
        },
        conditional_mean: NduConditionalMeanEvidenceV1 {
            evidence_digest: digest("conditional-mean"),
            standardized_absolute_mean_q32: (1_i64 << 32) / 100,
        },
        coefficient_bounds: NduAssumptionEvidenceV1 {
            evidence_digest: digest("coefficient-bounds"),
            satisfied: true,
        },
        lipschitz: NduAssumptionEvidenceV1 {
            evidence_digest: digest("lipschitz"),
            satisfied: true,
        },
        generator_monotonicity: NduAssumptionEvidenceV1 {
            evidence_digest: digest("monotonicity"),
            satisfied: true,
        },
        terminal_lipschitz: NduAssumptionEvidenceV1 {
            evidence_digest: digest("terminal-lipschitz"),
            satisfied: true,
        },
        continuity_scope: NduContinuityScopeV1::DeclaredOperatingDomain,
        solver_stability: NduAssumptionEvidenceV1 {
            evidence_digest: digest("solver-stability"),
            satisfied: true,
        },
        expires_unix_ms: 80,
    };

    let (verifier, producer_key, evaluator_key) = evidence_verifier();
    let convergence_producer = sign(
        &verifier,
        &producer_key,
        "artifact-producer",
        LearningEvidenceRoleV1::Generator,
        "convergence-producer",
        &ndu_convergence_producer_signing_payload_v1(&convergence_evidence),
    );
    let convergence_evaluator = sign(
        &verifier,
        &evaluator_key,
        "independent-evaluator",
        LearningEvidenceRoleV1::Evaluator,
        "convergence-evaluator",
        &ndu_convergence_evaluator_signing_payload_v1(&convergence_evidence),
    );
    let convergence = decide_ndu_convergence_v1(
        convergence_evidence,
        &convergence_producer,
        &convergence_evaluator,
        &verifier,
        50,
    )
    .unwrap_or_else(|error| panic!("convergence: {error:?}"));

    let well_producer = sign(
        &verifier,
        &producer_key,
        "artifact-producer",
        LearningEvidenceRoleV1::Generator,
        "well-producer",
        &ndu_well_posedness_producer_signing_payload_v1(&well_evidence),
    );
    let well_evaluator = sign(
        &verifier,
        &evaluator_key,
        "independent-evaluator",
        LearningEvidenceRoleV1::Evaluator,
        "well-evaluator",
        &ndu_well_posedness_evaluator_signing_payload_v1(&well_evidence),
    );
    let well_posedness = decide_ndu_well_posedness_v1(
        well_evidence,
        &well_producer,
        &well_evaluator,
        &verifier,
        50,
    )
    .unwrap_or_else(|error| panic!("well posedness: {error:?}"));

    Fixture {
        _dir: dir,
        snapshot_path,
        snapshot_receipt,
        candidate,
        withdrawal_registry,
        dataset_digest,
        artifact_admission,
        coefficient_profile,
        projection,
        convergence,
        well_posedness,
    }
}

fn verified_current_view(fixture: &Fixture, now: u64) -> VerifiedCurrentRegistryViewV1 {
    let key = SigningKey::from_bytes(&[41; 32]);
    let signer_id = id("artifact-current-head-signer");
    let scope = fixture
        .withdrawal_registry
        .scope_digest()
        .unwrap_or_else(|| panic!("scoped registry"));
    let signer = TrustedArtifactSignerV1 {
        signer_id: signer_id.clone(),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 10,
        valid_from: 1,
        expires_at: 100,
        revoked_at: None,
    };
    let verifier = ArtifactOwnerVerifierV1::new(ArtifactOwnerTrustV1 {
        registry_id: id("artifact-registry"),
        withdrawal_scope_digest: scope,
        minimum_registry_generation: Generation::new(1)
            .unwrap_or_else(|error| panic!("generation: {error:?}")),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    })
    .unwrap_or_else(|error| panic!("artifact owner verifier: {error:?}"));
    let witness = RegistryHeadWitnessV1 {
        registry_id: id("artifact-registry"),
        generation: Generation::new(1).unwrap_or_else(|error| panic!("generation: {error:?}")),
        head_digest: fixture.snapshot_receipt.head_digest,
        predecessor_head_digest: Digest32::ZERO,
        authority_epoch: 1,
        signer_id,
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        issued_at: 1,
        expires_at: 100,
    };
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: scope,
        binding: fixture.snapshot_receipt.binding,
        witness,
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    verifier
        .verify_current_registry_view(
            File::open(&fixture.snapshot_path)
                .unwrap_or_else(|error| panic!("current snapshot: {error:?}")),
            fixture.snapshot_receipt,
            &signed,
            &RegistryHeadRequirementV1 {
                registry_id: id("artifact-registry"),
                minimum_generation: Generation::new(1)
                    .unwrap_or_else(|error| panic!("generation: {error:?}")),
                expected_predecessor_head_digest: Digest32::ZERO,
                minimum_authority_epoch: 1,
                now,
            },
        )
        .unwrap_or_else(|error| panic!("verified current registry view: {error:?}"))
}

#[test]
fn current_artifact_and_independent_evidence_compose_to_deny_all_admission() {
    let mut fixture = fixture();
    let current_view = verified_current_view(&fixture, 50);
    let request = NduStochasticAdmissionRequestV1 {
        artifact_admission: &fixture.artifact_admission,
        current_withdrawal_head: fixture.withdrawal_registry.snapshot().head_digest,
        coefficient_profile: &fixture.coefficient_profile,
        projection: &fixture.projection,
        convergence: &fixture.convergence,
        well_posedness: &fixture.well_posedness,
        objective_class_digest: digest("objective-class"),
        operating_domain_digest: digest("operating-domain"),
        expected_compatibility_digest: digest("ndu-runtime-compatibility"),
    };
    let candidate = &mut fixture.candidate;
    let receipt = admit_ndu_stochastic_candidate_v1(candidate, current_view, request, 50)
        .unwrap_or_else(|error| panic!("stochastic admission: {error:?}"));

    assert_eq!(
        receipt.artifact_manifest_digest,
        fixture
            .artifact_admission
            .validated_manifest
            .manifest_digest
    );
    assert_eq!(
        receipt.registry_head_digest,
        fixture.snapshot_receipt.head_digest
    );
    assert!(!receipt.solver_digest.is_zero());
    assert!(!receipt.admission_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}

#[test]
fn withdrawal_frontier_change_invalidates_previously_admitted_artifact() {
    let mut fixture = fixture();
    fixture
        .withdrawal_registry
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdrawal"),
            dataset_digest: fixture.dataset_digest,
            source_tombstone_digest: digest("dataset-tombstone"),
            authority_id: id("dataset-authority"),
            credential_chain_digest: digest("withdrawal-credential"),
            signing_key_digest: digest("withdrawal-key"),
            authority_epoch: 2,
            issued_at: 51,
        })
        .unwrap_or_else(|error| panic!("withdrawal: {error:?}"));

    let current_view = verified_current_view(&fixture, 52);
    let request = NduStochasticAdmissionRequestV1 {
        artifact_admission: &fixture.artifact_admission,
        current_withdrawal_head: fixture.withdrawal_registry.snapshot().head_digest,
        coefficient_profile: &fixture.coefficient_profile,
        projection: &fixture.projection,
        convergence: &fixture.convergence,
        well_posedness: &fixture.well_posedness,
        objective_class_digest: digest("objective-class"),
        operating_domain_digest: digest("operating-domain"),
        expected_compatibility_digest: digest("ndu-runtime-compatibility"),
    };
    let candidate = &mut fixture.candidate;
    assert!(matches!(
        admit_ndu_stochastic_candidate_v1(candidate, current_view, request, 52),
        Err(NduStochasticAdmissionError::ArtifactAdmission(
            codex_hepta_learning_artifacts::ArtifactAdmissionError::WithdrawalHeadChanged
        ))
    ));
}
