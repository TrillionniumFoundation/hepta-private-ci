use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid test id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn signer(
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
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(controller),
        verifying_key: key,
        roles: vec![role],
        revoked_at: None,
    }
}
fn trust() -> LearningEvidenceTrustV1 {
    LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        signers: vec![
            signer(
                "generator",
                "controller-a",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            signer(
                "evaluator",
                "controller-b",
                2,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ],
    }
}
fn sign(
    verifier: &LearningEvidenceVerifierV1,
    name: &str,
    role: LearningEvidenceRoleV1,
    seed: u8,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id("evidence"),
        principal_id: id(name),
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

#[test]
fn signed_evidence_binds_actual_bytes_and_credential_not_digest_claims() {
    let verifier = LearningEvidenceVerifierV1::new(trust()).expect("host trust");
    let signed = sign(
        &verifier,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        2,
        b"observed metrics",
    );
    let admitted = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &signed,
            b"observed metrics",
            50,
        )
        .expect("authentic evidence");
    assert_eq!(admitted.principal(), &trust().signers[1].principal);
    assert_eq!(
        verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &signed,
            b"edited metrics",
            50
        ),
        Err(SignedEvidenceError::PayloadMismatch)
    );
    let forged = sign(
        &verifier,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        1,
        b"observed metrics",
    );
    assert_eq!(
        verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &forged,
            b"observed metrics",
            50
        ),
        Err(SignedEvidenceError::InvalidSignature)
    );
    let mut edited = signed;
    edited.evidence_id = id("relabelled");
    assert_eq!(
        verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &edited,
            b"observed metrics",
            50
        ),
        Err(SignedEvidenceError::InvalidSignature)
    );
}

#[test]
fn trust_epoch_revocation_scope_and_expiry_fail_closed() {
    let verifier = LearningEvidenceVerifierV1::new(trust()).expect("host trust");
    let signed = sign(
        &verifier,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        2,
        b"metrics",
    );
    let mut new_trust = trust();
    new_trust.authority_epoch = 8;
    for signer in &mut new_trust.signers {
        signer.principal.authority_epoch = 8;
    }
    let rotated = LearningEvidenceVerifierV1::new(new_trust).expect("rotated trust");
    assert_eq!(
        rotated.verify(LearningEvidenceRoleV1::Evaluator, &signed, b"metrics", 50),
        Err(SignedEvidenceError::ContextMismatch)
    );
    let mut revoked_trust = trust();
    revoked_trust.signers[1].revoked_at = Some(40);
    let revoked = LearningEvidenceVerifierV1::new(revoked_trust).expect("revoked trust");
    let resigned = sign(
        &revoked,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        2,
        b"metrics",
    );
    assert_eq!(
        revoked.verify(LearningEvidenceRoleV1::Evaluator, &resigned, b"metrics", 50),
        Err(SignedEvidenceError::Revoked)
    );
    let observer_before_revocation = revoked
        .verify(LearningEvidenceRoleV1::Evaluator, &resigned, b"metrics", 30)
        .expect("not yet revoked");
    let generator_before_revocation = revoked
        .verify(
            LearningEvidenceRoleV1::Generator,
            &sign(
                &revoked,
                "generator",
                LearningEvidenceRoleV1::Generator,
                1,
                b"plan",
            ),
            b"plan",
            30,
        )
        .expect("generator");
    assert_eq!(
        verify_signed_role_separation(
            &generator_before_revocation,
            &observer_before_revocation,
            50
        ),
        Err(SignedEvidenceError::Revoked)
    );
    assert_eq!(
        verify_signed_role_separation(
            &generator_before_revocation,
            &observer_before_revocation,
            15
        ),
        Err(SignedEvidenceError::ValidityWindow)
    );
    assert_eq!(
        verifier.verify(LearningEvidenceRoleV1::Evaluator, &signed, b"metrics", 91),
        Err(SignedEvidenceError::ValidityWindow)
    );
    let mut wrong_scope = signed.clone();
    wrong_scope.scope_digest = digest("other-scope");
    assert_eq!(
        verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &wrong_scope,
            b"metrics",
            50
        ),
        Err(SignedEvidenceError::ContextMismatch)
    );
    assert_eq!(
        verifier.verify(LearningEvidenceRoleV1::Observer, &signed, b"metrics", 50),
        Err(SignedEvidenceError::RoleMismatch)
    );
}

#[test]
fn distinct_keys_do_not_make_one_controller_independent() {
    let mut shared = trust();
    shared.signers[1].controller_id = shared.signers[0].controller_id.clone();
    let verifier = LearningEvidenceVerifierV1::new(shared).expect("host trust");
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &sign(
                &verifier,
                "generator",
                LearningEvidenceRoleV1::Generator,
                1,
                b"plan",
            ),
            b"plan",
            50,
        )
        .expect("generator");
    let evaluator = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &sign(
                &verifier,
                "evaluator",
                LearningEvidenceRoleV1::Evaluator,
                2,
                b"metrics",
            ),
            b"metrics",
            50,
        )
        .expect("evaluator");
    assert_eq!(
        verify_signed_role_separation(&generator, &evaluator, 50),
        Err(SignedEvidenceError::ControllerCollision)
    );
    let verifier = LearningEvidenceVerifierV1::new(trust()).expect("independent trust");
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &sign(
                &verifier,
                "generator",
                LearningEvidenceRoleV1::Generator,
                1,
                b"plan",
            ),
            b"plan",
            50,
        )
        .expect("generator");
    let evaluator = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &sign(
                &verifier,
                "evaluator",
                LearningEvidenceRoleV1::Evaluator,
                2,
                b"metrics",
            ),
            b"metrics",
            50,
        )
        .expect("evaluator");
    assert_eq!(
        verify_signed_role_separation(&generator, &evaluator, 50),
        Ok(())
    );
}
