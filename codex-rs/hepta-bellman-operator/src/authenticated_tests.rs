use super::*;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::FixedQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::ApplicabilityDecisionV1;
use crate::OperatorErrorComponentV1;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn trusted_signer(
    name: &str,
    controller: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    let verifying_key = SigningKey::from_bytes(&[seed; 32])
        .verifying_key()
        .to_bytes();
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(name),
            signing_key_digest: Digest32::of_bytes(&verifying_key),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(controller),
        verifying_key,
        roles: vec![role],
        revoked_at: None,
    }
}

fn verifier(evaluator_controller: &str) -> LearningEvidenceVerifierV1 {
    LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        signers: vec![
            trusted_signer(
                "generator",
                "generator-controller",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            trusted_signer(
                "evaluator",
                evaluator_controller,
                2,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ],
    })
    .expect("valid trust")
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &str,
    role: LearningEvidenceRoleV1,
    seed: u8,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{principal}-evidence")),
        principal_id: id(principal),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
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

fn evidence(
    verifier: &LearningEvidenceVerifierV1,
    payload: &[u8],
) -> SignedOperatorEvidenceV2 {
    SignedOperatorEvidenceV2 {
        generator: sign(
            verifier,
            "generator",
            LearningEvidenceRoleV1::Generator,
            1,
            payload,
        ),
        evaluator: sign(
            verifier,
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            2,
            payload,
        ),
    }
}

fn applicability() -> OperatorApplicabilityCertificateV1 {
    OperatorApplicabilityCertificateV1 {
        certificate_id: id("certificate"),
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
        expires_at: 90,
        decision: ApplicabilityDecisionV1::Pass,
    }
}

fn regularity() -> OperatorRegularityAssessmentV1 {
    OperatorRegularityAssessmentV1 {
        artifact_id: id("artifact"),
        measured_rank: 4,
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
fn op_02_signed_applicability_requires_authenticated_independent_evaluator() {
    let verifier = verifier("evaluator-controller");
    let certificate = applicability();
    let digest = validate_applicability_certificate(&certificate, 50).expect("structural");
    let signed = evidence(&verifier, digest.as_array());
    let admitted =
        validate_applicability_with_signed_evidence_v2(&certificate, &signed, &verifier, 50)
            .expect("authenticated applicability");
    assert_eq!(admitted.certificate_digest, digest);
    assert!(!admitted.authority.grants_any());

    let colliding = verifier("generator-controller");
    let collision_evidence = evidence(&colliding, digest.as_array());
    assert!(matches!(
        validate_applicability_with_signed_evidence_v2(
            &certificate,
            &collision_evidence,
            &colliding,
            50,
        ),
        Err(AuthenticatedOperatorError::Evidence(
            SignedEvidenceError::ControllerCollision
        ))
    ));
}

#[test]
fn op_02_signed_regularity_binds_evaluator_identity_and_exact_assessment() {
    let verifier = verifier("evaluator-controller");
    let assessment = regularity();
    let structural = admit_operator_regularity(assessment.clone()).expect("structural");
    let signed = evidence(&verifier, structural.assessment_digest.as_array());
    let authenticated = admit_operator_regularity_with_signed_evidence_v2(
        assessment.clone(),
        &signed,
        &verifier,
        50,
    )
    .expect("authenticated regularity");
    assert_eq!(
        authenticated.admission.assessment_digest,
        structural.assessment_digest
    );

    let mut wrong_identity = assessment;
    wrong_identity.evaluator_credential_digest = digest("asserted-other-credential");
    let changed =
        admit_operator_regularity(wrong_identity.clone()).expect("structural altered assessment");
    let changed_signed = evidence(&verifier, changed.assessment_digest.as_array());
    assert_eq!(
        admit_operator_regularity_with_signed_evidence_v2(
            wrong_identity,
            &changed_signed,
            &verifier,
            50,
        ),
        Err(AuthenticatedOperatorError::IdentityBinding)
    );
}
