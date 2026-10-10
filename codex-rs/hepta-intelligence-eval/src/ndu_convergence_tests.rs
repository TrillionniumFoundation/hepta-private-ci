use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn evidence() -> NduConvergenceEvidenceV1 {
    NduConvergenceEvidenceV1 {
        certificate_id: id("convergence-1"),
        subject_class: NduSubjectClassV1::Agent,
        objective_class_digest: digest("objective-class"),
        solver_digest: digest("solver"),
        initialization_digest: digest("initialization"),
        iterations: 16,
        maximum_residual_q32: 1 << 10,
        spectral_radius_upper95_q32: (90_i64 * (1_i64 << 32)) / 100,
        conservation_residual_q32: 1,
        multiple_solution_disposition: NduMultipleSolutionDispositionV1::Unique,
        perturbation_evidence_digest: digest("perturbation"),
        stability_evidence_digest: digest("stability"),
        conservation_evidence_digest: digest("conservation"),
    }
}

fn principal(name: &str, key: &SigningKey) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: digest("scope"),
        authority_epoch: 7,
        authenticated_at: 1,
        expires_at: 100,
    }
}

fn fixture() -> (LearningEvidenceVerifierV1, SigningKey, SigningKey) {
    let producer_key = SigningKey::from_bytes(&[11; 32]);
    let evaluator_key = SigningKey::from_bytes(&[12; 32]);
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective-class"),
        authority_epoch: 7,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: principal("producer", &producer_key),
                controller_id: id("producer-controller"),
                verifying_key: producer_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: principal("evaluator", &evaluator_key),
                controller_id: id("evaluator-controller"),
                verifying_key: evaluator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
        ],
    })
    .expect("trust");
    (verifier, producer_key, evaluator_key)
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    key: &SigningKey,
    principal: &str,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{principal}-evidence")),
        principal_id: id(principal),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at: 10,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    signed
}

fn signed_pair(
    evidence: &NduConvergenceEvidenceV1,
) -> (
    LearningEvidenceVerifierV1,
    SignedLearningEvidenceV1,
    SignedLearningEvidenceV1,
) {
    let (verifier, producer_key, evaluator_key) = fixture();
    let producer = sign(
        &verifier,
        &producer_key,
        "producer",
        LearningEvidenceRoleV1::Generator,
        &super::ndu_convergence_producer_signing_payload_v1(evidence),
    );
    let evaluator = sign(
        &verifier,
        &evaluator_key,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &super::ndu_convergence_evaluator_signing_payload_v1(evidence),
    );
    (verifier, producer, evaluator)
}

#[test]
fn independent_signed_evidence_can_issue_accepted_deny_all_certificate() {
    let evidence = evidence();
    let (verifier, producer, evaluator) = signed_pair(&evidence);
    let certificate = decide_ndu_convergence_v1(evidence, &producer, &evaluator, &verifier, 50)
        .expect("decision");
    assert_eq!(certificate.decision(), NduConvergenceDecisionV1::Accepted);
    assert_eq!(certificate.candidate_producer_identity(), &id("producer"));
    assert_eq!(certificate.evaluator_identity(), &id("evaluator"));
    assert!(!certificate.certificate_digest().is_zero());
    assert!(!certificate.authority().grants_any());
}

#[test]
fn spectral_or_residual_failure_rejects_but_missing_support_is_unavailable() {
    let mut spectral = evidence();
    spectral.spectral_radius_upper95_q32 = (95_i64 * (1_i64 << 32)) / 100;
    let (verifier, producer, evaluator) = signed_pair(&spectral);
    assert_eq!(
        decide_ndu_convergence_v1(spectral, &producer, &evaluator, &verifier, 50)
            .expect("decision")
            .decision(),
        NduConvergenceDecisionV1::Rejected
    );

    let mut missing = evidence();
    missing.perturbation_evidence_digest = Digest32::ZERO;
    let (verifier, producer, evaluator) = signed_pair(&missing);
    assert_eq!(
        decide_ndu_convergence_v1(missing, &producer, &evaluator, &verifier, 50)
            .expect("decision")
            .decision(),
        NduConvergenceDecisionV1::Unavailable
    );
}

#[test]
fn tampered_evaluator_payload_cannot_self_certify() {
    let evidence = evidence();
    let (verifier, producer, mut evaluator) = signed_pair(&evidence);
    evaluator.payload_digest = digest("tampered");
    assert!(matches!(
        decide_ndu_convergence_v1(evidence, &producer, &evaluator, &verifier, 50),
        Err(NduConvergenceError::SignedEvidence(
            SignedEvidenceError::PayloadMismatch | SignedEvidenceError::InvalidSignature
        ))
    ));
}
