//! Runtime use of an activated distribution, not only its activation ceremony.
use super::*;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::AuthenticatedPrincipalV1;
use crate::LearningEvidenceRoleV1;
use crate::SignedLearningEvidenceV1;
use crate::TrustedLearningSignerV1;
use crate::verify_signed_actor_separation;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn activated(root_revoked_at: Option<u64>) -> ActivatedLearningTrustV1 {
    let signer = SigningKey::from_bytes(&[1; 32]);
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("root"),
        scope_digest: digest("scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: root_revoked_at,
    };
    let mut distribution = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("live-use-distribution"),
            generation: 1,
            effective_at: 20,
            trust: LearningEvidenceTrustV1 {
                scope_digest: digest("scope"),
                objective_digest: digest("objective"),
                authority_epoch: 7,
                signers: vec![TrustedLearningSignerV1 {
                    principal: AuthenticatedPrincipalV1 {
                        principal_id: id("generator"),
                        credential_chain_digest: digest("credential"),
                        signing_key_digest: Digest32::of_bytes(&signer.verifying_key().to_bytes()),
                        scope_digest: digest("scope"),
                        authority_epoch: 7,
                        authenticated_at: 10,
                        expires_at: 100,
                    },
                    controller_id: id("controller"),
                    verifying_key: signer.verifying_key().to_bytes(),
                    roles: vec![LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                }],
            },
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    distribution.signature = root_key
        .sign(&distribution.signing_bytes().unwrap())
        .to_bytes();
    activate_learning_trust(&root, distribution, None, 50).unwrap()
}

fn signed(
    verifier: &LearningEvidenceVerifierV1,
    issued_at: u64,
    expires_at: u64,
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id("live-use-evidence"),
        principal_id: id("generator"),
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: verifier.authority_epoch(),
        issued_at,
        expires_at,
        payload_digest: digest("payload"),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[1; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

#[test]
fn fresh_evidence_cannot_extend_an_expired_distribution() {
    let trust = activated(None);
    let evidence = signed(trust.verifier(), 91, 99);
    assert_eq!(
        trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Generator, &evidence, b"payload", 95),
        Err(SignedEvidenceError::ValidityWindow)
    );
}

#[test]
fn valid_window_boundaries_and_cloned_verifier_keep_the_same_limit() {
    let trust = activated(None);
    let verifier = trust.verifier().clone();
    let evidence = signed(&verifier, 15, 99);
    for time in [20, 50, 90] {
        assert!(
            verifier
                .verify(
                    LearningEvidenceRoleV1::Generator,
                    &evidence,
                    b"payload",
                    time
                )
                .is_ok()
        );
    }
    for time in [19, 91] {
        assert_eq!(
            verifier.verify(
                LearningEvidenceRoleV1::Generator,
                &evidence,
                b"payload",
                time
            ),
            Err(SignedEvidenceError::ValidityWindow)
        );
    }
}

#[test]
fn scheduled_root_revocation_is_checked_at_actual_use() {
    let trust = activated(Some(70));
    let evidence = signed(trust.verifier(), 20, 99);
    assert!(
        trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Generator, &evidence, b"payload", 69)
            .is_ok()
    );
    assert_eq!(
        trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Generator, &evidence, b"payload", 70),
        Err(SignedEvidenceError::Revoked)
    );
}

#[test]
fn cached_verification_cannot_outlive_the_distribution() {
    let trust = activated(None);
    let evidence = signed(trust.verifier(), 20, 99);
    let verified = trust
        .verifier()
        .verify(LearningEvidenceRoleV1::Generator, &evidence, b"payload", 50)
        .unwrap();
    // The validity check must fail before actor-collision checks. A previously
    // verified object is evidence, not a perpetual authorization capability.
    assert_eq!(
        verify_signed_actor_separation(&verified, &verified, 95),
        Err(SignedEvidenceError::ValidityWindow)
    );
}

#[test]
fn cached_verification_retains_scheduled_root_revocation() {
    let trust = activated(Some(70));
    let evidence = signed(trust.verifier(), 20, 99);
    let verified = trust
        .verifier()
        .verify(LearningEvidenceRoleV1::Generator, &evidence, b"payload", 50)
        .unwrap();
    assert_eq!(
        verify_signed_actor_separation(&verified, &verified, 70),
        Err(SignedEvidenceError::Revoked)
    );
}
