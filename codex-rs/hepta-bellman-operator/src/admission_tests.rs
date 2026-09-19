use super::*;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DatasetFreezeRequestV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::freeze_dataset_receipt_v3;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::ApplicabilityDecisionV1;
use crate::OperatorErrorComponentV1;
use crate::TabularOperatorSampleV1;
use crate::WorldModelSampleV1;
use crate::admit_operator_regularity;
use crate::validate_applicability_certificate;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid fixture id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn dataset_receipt() -> DatasetSnapshotReceiptV3 {
    freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("operator-dataset"),
            producer: AuthenticatedPrincipalV1 {
                principal_id: id("dataset-owner"),
                credential_chain_digest: digest("dataset-owner-credential"),
                signing_key_digest: digest("dataset-owner-key"),
                scope_digest: digest("scope"),
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            },
            ledger_head_digest: digest("ledger-head"),
            objective_digest: digest("objective"),
            eligible_frontier: 7,
            outcome_watermark: 40,
            correction_cut_digest: digest("correction-cut"),
            revocation_cut_digest: digest("revocation-cut"),
            inclusion_policy_digest: digest("inclusion-policy"),
            source_record_digests: vec![digest("record-b"), digest("record-a")],
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        50,
    )
    .expect("valid frozen dataset")
}

fn operator_plan(receipt: &DatasetSnapshotReceiptV3) -> TabularOperatorPlanV1 {
    TabularOperatorPlanV1 {
        artifact_id: id("operator-artifact"),
        producer_id: id("operator-trainer"),
        generation: Generation::new(1).expect("generation"),
        objective_digest: receipt.snapshot.objective_digest,
        dataset_digest: receipt.snapshot.dataset_digest,
        sensor_core_digest: digest("sensor-core"),
        training_profile_digest: digest("receipt-bound-tabular"),
        minimum_samples_per_cell: 2,
        sensor_ids: vec![id("sensor")],
        action_ids: vec![id("action")],
        samples: vec![
            TabularOperatorSampleV1 {
                sample_id: id("sample-a"),
                sensor_id: id("sensor"),
                action_id: id("action"),
                target: FixedQ32::from_raw(10),
                evidence_digest: digest("record-a"),
            },
            TabularOperatorSampleV1 {
                sample_id: id("sample-b"),
                sensor_id: id("sensor"),
                action_id: id("action"),
                target: FixedQ32::from_raw(20),
                evidence_digest: digest("record-b"),
            },
        ],
    }
}

fn world_samples() -> Vec<WorldModelSampleV1> {
    vec![
        WorldModelSampleV1 {
            sample_id: id("world-a"),
            state_id: id("state"),
            action_id: id("action"),
            next_state_id: id("next-a"),
            outcome: FixedQ32::from_raw(10),
            evidence_digest: digest("record-a"),
        },
        WorldModelSampleV1 {
            sample_id: id("world-b"),
            state_id: id("state"),
            action_id: id("action"),
            next_state_id: id("next-b"),
            outcome: FixedQ32::from_raw(20),
            evidence_digest: digest("record-b"),
        },
    ]
}

#[test]
fn op_07_tabular_fit_binds_verified_dataset_receipt_and_rows() {
    let receipt = dataset_receipt();
    let artifact = fit_tabular_operator_from_dataset_receipt(operator_plan(&receipt), &receipt, 50)
        .expect("receipt-bound fit");
    assert_eq!(artifact.dataset_digest, receipt.snapshot.dataset_digest);

    let mut wrong_dataset = operator_plan(&receipt);
    wrong_dataset.dataset_digest = digest("caller-claimed-other-dataset");
    assert_eq!(
        fit_tabular_operator_from_dataset_receipt(wrong_dataset, &receipt, 50),
        Err(OperatorAdmissionError::DatasetBinding)
    );

    let mut outside = operator_plan(&receipt);
    outside.samples[1].evidence_digest = digest("not-in-frozen-dataset");
    assert_eq!(
        fit_tabular_operator_from_dataset_receipt(outside, &receipt, 50),
        Err(OperatorAdmissionError::EvidenceOutsideDataset)
    );
}

#[test]
fn op_07_world_model_takes_dataset_identity_from_verified_receipt() {
    let receipt = dataset_receipt();
    let model =
        fit_transition_model_from_dataset_receipt(id("world-model"), &receipt, world_samples(), 50)
            .expect("receipt-bound world model");
    assert_eq!(model.dataset_digest, receipt.snapshot.dataset_digest);

    let mut outside = world_samples();
    outside[1].evidence_digest = digest("outside");
    assert_eq!(
        fit_transition_model_from_dataset_receipt(id("world-model-2"), &receipt, outside, 50),
        Err(OperatorAdmissionError::EvidenceOutsideDataset)
    );
}

fn trusted_signer(
    name: &str,
    controller: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32])
        .verifying_key()
        .to_bytes();
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(name),
            signing_key_digest: Digest32::of_bytes(&key),
            scope_digest: digest("scope"),
            authority_epoch: 9,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(controller),
        verifying_key: key,
        roles: vec![role],
        revoked_at: None,
    }
}

fn verifier() -> LearningEvidenceVerifierV1 {
    LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 9,
        signers: vec![
            trusted_signer(
                "generator",
                "controller-generator",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            trusted_signer(
                "evaluator",
                "controller-evaluator",
                2,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ],
    })
    .expect("host-owned trust")
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    name: &str,
    role: LearningEvidenceRoleV1,
    seed: u8,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{name}-evidence")),
        principal_id: id(name),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 9,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

fn admitted_generator(verifier: &LearningEvidenceVerifierV1) -> VerifiedLearningEvidenceV1 {
    let evidence = sign(
        verifier,
        "generator",
        LearningEvidenceRoleV1::Generator,
        1,
        b"generator-plan",
    );
    verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &evidence,
            b"generator-plan",
            50,
        )
        .expect("authenticated generator")
}

fn applicability() -> OperatorApplicabilityCertificateV1 {
    OperatorApplicabilityCertificateV1 {
        certificate_id: id("applicability"),
        axis_partition_digest: digest("axis"),
        domain_digest: digest("domain"),
        action_space_digest: digest("actions"),
        holder_exponents_digest: digest("holder-exponents"),
        holder_constants_digest: digest("holder-constants"),
        state_lipschitz_digest: digest("state-lipschitz"),
        action_lipschitz_digest: digest("action-lipschitz"),
        ellipticity_nu_lcb: FixedQ32::from_raw(1),
        control_interval_millis: 100,
        evaluator_id: id("evaluator"),
        evaluator_credential_digest: digest("evaluator"),
        fallback_digest: digest("fallback"),
        expires_at: 80,
        decision: ApplicabilityDecisionV1::Pass,
    }
}

fn regularity() -> OperatorRegularityAssessmentV1 {
    OperatorRegularityAssessmentV1 {
        artifact_id: id("operator-artifact"),
        measured_rank: 2,
        reconstruction_gain_q32: FixedQ32::ONE,
        monotonicity_violations: 0,
        positivity_violations: 0,
        holder_residual_q32: FixedQ32::from_raw(10),
        action_lipschitz_residual_q32: FixedQ32::from_raw(10),
        ood_false_acceptance_q32: FixedQ32::from_raw(10),
        error_components: vec![
            OperatorErrorComponentV1 {
                component_id: id("model"),
                normalized_error: FixedQ32::from_raw(10),
                evidence_digest: digest("model-error"),
            },
            OperatorErrorComponentV1 {
                component_id: id("sensor"),
                normalized_error: FixedQ32::from_raw(10),
                evidence_digest: digest("sensor-error"),
            },
        ],
        dominant_component_approved: false,
        evaluator_id: id("evaluator"),
        evaluator_credential_digest: digest("evaluator"),
    }
}

#[test]
fn op_08_applicability_requires_authenticated_independent_evaluator_binding() {
    let verifier = verifier();
    let generator = admitted_generator(&verifier);
    let certificate = applicability();
    let structural = validate_applicability_certificate(&certificate, 50)
        .expect("structurally valid applicability");
    let payload = structural.as_array();
    let signed = sign(
        &verifier,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        2,
        payload,
    );
    let evaluator = verifier
        .verify(LearningEvidenceRoleV1::Evaluator, &signed, payload, 50)
        .expect("authenticated evaluator");
    assert_eq!(
        validate_applicability_certificate_authenticated(&certificate, &generator, &evaluator, 50,)
            .expect("authenticated admission"),
        structural
    );

    let wrong_signed = sign(
        &verifier,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        2,
        b"different-applicability",
    );
    let wrong = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &wrong_signed,
            b"different-applicability",
            50,
        )
        .expect("authentic but wrong payload");
    assert_eq!(
        validate_applicability_certificate_authenticated(&certificate, &generator, &wrong, 50,),
        Err(OperatorAdmissionError::EvidencePayload)
    );
}

#[test]
fn op_08_regularity_requires_authenticated_evaluator_binding() {
    let verifier = verifier();
    let generator = admitted_generator(&verifier);
    let assessment = regularity();
    let structural = admit_operator_regularity(assessment.clone())
        .expect("structurally valid regularity")
        .assessment_digest;
    let payload = structural.as_array();
    let signed = sign(
        &verifier,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        2,
        payload,
    );
    let evaluator = verifier
        .verify(LearningEvidenceRoleV1::Evaluator, &signed, payload, 50)
        .expect("authenticated evaluator");
    let admission = admit_operator_regularity_authenticated(assessment, &generator, &evaluator, 50)
        .expect("authenticated regularity admission");
    assert_eq!(admission.assessment_digest, structural);
}
