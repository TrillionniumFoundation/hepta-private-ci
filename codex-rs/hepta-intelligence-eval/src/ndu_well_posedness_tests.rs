use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
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
fn assumption(value: &str, satisfied: bool) -> NduAssumptionEvidenceV1 {
    NduAssumptionEvidenceV1 {
        evidence_digest: digest(value),
        satisfied,
    }
}

fn evidence() -> NduWellPosednessEvidenceV1 {
    NduWellPosednessEvidenceV1 {
        certificate_id: id("well-posedness-1"),
        artifact_manifest_digest: digest("artifact-manifest"),
        objective_class_digest: digest("objective-class"),
        operating_domain_digest: digest("operating-domain"),
        square_integrability: assumption("square-integrability", true),
        conditional_mean: NduConditionalMeanEvidenceV1 {
            evidence_digest: digest("conditional-mean"),
            standardized_absolute_mean_q32: (1_i64 << 32) / 100,
        },
        coefficient_bounds: assumption("coefficient-bounds", true),
        lipschitz: assumption("lipschitz", true),
        generator_monotonicity: assumption("generator-monotonicity", true),
        terminal_lipschitz: assumption("terminal-lipschitz", true),
        continuity_scope: NduContinuityScopeV1::DeclaredOperatingDomain,
        solver_stability: assumption("solver-stability", true),
        expires_unix_ms: 90,
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
    let producer_key = SigningKey::from_bytes(&[21; 32]);
    let evaluator_key = SigningKey::from_bytes(&[22; 32]);
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
        evidence_id: id(&format!("{principal}-well-posedness")),
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

fn signed_pair(
    evidence: &NduWellPosednessEvidenceV1,
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
        &super::ndu_well_posedness_producer_signing_payload_v1(evidence),
    );
    let evaluator = sign(
        &verifier,
        &evaluator_key,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &super::ndu_well_posedness_evaluator_signing_payload_v1(evidence),
    );
    (verifier, producer, evaluator)
}

#[test]
fn complete_signed_independent_evidence_is_accepted_without_authority() {
    let evidence = evidence();
    let (verifier, producer, evaluator) = signed_pair(&evidence);
    let certificate =
        decide_ndu_well_posedness_v1(evidence, &producer, &evaluator, &verifier, 50)
            .expect("decision");
    assert_eq!(certificate.decision(), NduWellPosednessDecisionV1::Accepted);
    assert_eq!(certificate.candidate_producer_identity(), &id("producer"));
    assert_eq!(certificate.evaluator_identity(), &id("evaluator"));
    assert!(!certificate.certificate_digest().is_zero());
    assert!(!certificate.authority().grants_any());
}

#[test]
fn missing_support_is_unavailable_and_failed_assumption_rejects() {
    let mut missing = evidence();
    missing.lipschitz.evidence_digest = Digest32::ZERO;
    let (verifier, producer, evaluator) = signed_pair(&missing);
    assert_eq!(
        decide_ndu_well_posedness_v1(missing, &producer, &evaluator, &verifier, 50)
            .expect("decision")
            .decision(),
        NduWellPosednessDecisionV1::Unavailable
    );

    let mut failed = evidence();
    failed.generator_monotonicity.satisfied = false;
    let (verifier, producer, evaluator) = signed_pair(&failed);
    assert_eq!(
        decide_ndu_well_posedness_v1(failed, &producer, &evaluator, &verifier, 50)
            .expect("decision")
            .decision(),
        NduWellPosednessDecisionV1::Rejected
    );
}

#[test]
fn conditional_mean_threshold_and_expiry_fail_closed() {
    let mut threshold = evidence();
    threshold.conditional_mean.standardized_absolute_mean_q32 =
        (2_i64 * (1_i64 << 32)) / 100;
    let (verifier, producer, evaluator) = signed_pair(&threshold);
    assert_eq!(
        decide_ndu_well_posedness_v1(threshold, &producer, &evaluator, &verifier, 50)
            .expect("decision")
            .decision(),
        NduWellPosednessDecisionV1::Rejected
    );

    let expired = evidence();
    let (verifier, producer, evaluator) = signed_pair(&expired);
    assert_eq!(
        decide_ndu_well_posedness_v1(expired, &producer, &evaluator, &verifier, 90)
            .expect_err("expired"),
        NduWellPosednessError::Expired
    );
}
