use super::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

fn fixture(
    principal_expiry: u64,
    signed_expiry: u64,
    revoked_at: Option<u64>,
) -> (LearningEvidenceVerifierV1, SignedLearningEvidenceV1) {
    let id = |value: &str| StableId::new(value).expect("fixture ID");
    let digest = |value: &str| Digest32::of_bytes(value.as_bytes());
    let key = SigningKey::from_bytes(&[19; 32]);
    let public = key.verifying_key().to_bytes();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        signers: vec![TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id("evaluator"),
                credential_chain_digest: digest("credential"),
                signing_key_digest: Digest32::of_bytes(&public),
                scope_digest: digest("scope"),
                authority_epoch: 1,
                authenticated_at: 1,
                expires_at: principal_expiry,
            },
            controller_id: id("controller"),
            verifying_key: public,
            roles: vec![LearningEvidenceRoleV1::Evaluator],
            revoked_at,
        }],
    })
    .expect("trust");
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: id("evidence:horizon"),
        principal_id: id("evaluator"),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 1,
        issued_at: 1,
        expires_at: signed_expiry,
        payload_digest: Digest32::of_bytes(b"horizon"),
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    (verifier, signed)
}

#[test]
fn exclusive_horizon_preserves_inclusive_signed_and_principal_expiry() {
    for principal_expiry in [100, 200] {
        let (verifier, signed) = fixture(principal_expiry, /*signed_expiry*/ 100, None);
        let verified = verifier
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &signed,
                b"horizon",
                /*now*/ 100,
            )
            .expect("inclusive expiry");
        assert_eq!(verified.valid_until_unix_ms(), 101);
        assert!(
            verifier
                .verify(
                    LearningEvidenceRoleV1::Evaluator,
                    &signed,
                    b"horizon",
                    /*now*/ 101
                )
                .is_err()
        );
    }
}

#[test]
fn known_future_revocation_caps_exclusive_horizon() {
    let (verifier, signed) = fixture(
        /*principal_expiry*/ 200,
        /*signed_expiry*/ 100,
        Some(75),
    );
    let verified = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &signed,
            b"horizon",
            /*now*/ 74,
        )
        .expect("before revocation");
    assert_eq!(verified.valid_until_unix_ms(), 75);
    assert_eq!(
        verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &signed,
            b"horizon",
            /*now*/ 75
        ),
        Err(SignedEvidenceError::Revoked)
    );
}

#[test]
fn unrepresentable_exclusive_expiry_saturates_conservatively() {
    let (verifier, signed) = fixture(u64::MAX, u64::MAX, None);
    let verified = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &signed,
            b"horizon",
            u64::MAX - 1,
        )
        .expect("before maximum timestamp");
    assert_eq!(verified.valid_until_unix_ms(), u64::MAX);
}
