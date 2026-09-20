use super::*;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::AuthenticatedPrincipalV1;
use crate::LearningEvidenceRoleV1;
use crate::TrustedLearningSignerV1;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn trust(epoch: u64, seed: u8) -> LearningEvidenceTrustV1 {
    let key = SigningKey::from_bytes(&[seed; 32]);
    LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: epoch,
        signers: vec![TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id("generator"),
                credential_chain_digest: digest(&format!("credential-{epoch}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: digest("scope"),
                authority_epoch: epoch,
                authenticated_at: 10,
                expires_at: 100,
            },
            controller_id: id("controller"),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Generator],
            revoked_at: None,
        }],
    }
}

fn root(key: &SigningKey) -> LearningTrustRootV1 {
    LearningTrustRootV1 {
        root_id: id("root"),
        scope_digest: digest("scope"),
        verifying_key: key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    }
}

fn signed_distribution(
    root_key: &SigningKey,
    distribution: LearningTrustDistributionV1,
) -> SignedLearningTrustDistributionV1 {
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution,
        root_id: id("root"),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = root_key
        .sign(&signed.signing_bytes().unwrap())
        .to_bytes();
    signed
}

#[test]
fn trust_distribution_rotation_is_root_authenticated_monotonic_and_content_addressed() {
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = root(&root_key);
    let first = activate_learning_trust(
        &root,
        signed_distribution(
            &root_key,
            LearningTrustDistributionV1 {
                distribution_id: id("trust-v1"),
                generation: 1,
                effective_at: 20,
                trust: trust(7, 1),
            },
        ),
        None,
        50,
    )
    .unwrap();
    let second = activate_learning_trust(
        &root,
        signed_distribution(
            &root_key,
            LearningTrustDistributionV1 {
                distribution_id: id("trust-v2"),
                generation: 2,
                effective_at: 30,
                trust: trust(8, 2),
            },
        ),
        Some(&first),
        50,
    )
    .unwrap();

    assert_eq!(first.generation(), 1);
    assert_eq!(second.generation(), 2);
    assert_eq!(first.root_id(), &id("root"));
    assert_ne!(first.root_digest(), Digest32::ZERO);
    assert_ne!(first.distribution_digest(), second.distribution_digest());
    assert_eq!(second.verifier().authority_epoch(), 8);
}

#[test]
fn trust_distribution_rejects_bad_signature_generation_skips_and_epoch_rollback() {
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = root(&root_key);
    let first = activate_learning_trust(
        &root,
        signed_distribution(
            &root_key,
            LearningTrustDistributionV1 {
                distribution_id: id("trust-v1"),
                generation: 1,
                effective_at: 20,
                trust: trust(7, 1),
            },
        ),
        None,
        50,
    )
    .unwrap();

    let mut bad_signature = signed_distribution(
        &root_key,
        LearningTrustDistributionV1 {
            distribution_id: id("trust-bad"),
            generation: 2,
            effective_at: 30,
            trust: trust(8, 2),
        },
    );
    bad_signature.signature[0] ^= 1;
    assert_eq!(
        activate_learning_trust(&root, bad_signature, Some(&first), 50).unwrap_err(),
        LearningTrustDistributionError::InvalidSignature
    );

    assert_eq!(
        activate_learning_trust(
            &root,
            signed_distribution(
                &root_key,
                LearningTrustDistributionV1 {
                    distribution_id: id("trust-v3"),
                    generation: 3,
                    effective_at: 30,
                    trust: trust(8, 2),
                },
            ),
            Some(&first),
            50,
        )
        .unwrap_err(),
        LearningTrustDistributionError::NonMonotonicRotation
    );
    assert_eq!(
        activate_learning_trust(
            &root,
            signed_distribution(
                &root_key,
                LearningTrustDistributionV1 {
                    distribution_id: id("trust-v2"),
                    generation: 2,
                    effective_at: 30,
                    trust: trust(6, 3),
                },
            ),
            Some(&first),
            50,
        )
        .unwrap_err(),
        LearningTrustDistributionError::NonMonotonicRotation
    );
}

#[test]
fn trust_distribution_rejects_root_substitution_and_revocation() {
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = root(&root_key);
    let signed = signed_distribution(
        &root_key,
        LearningTrustDistributionV1 {
            distribution_id: id("trust-v1"),
            generation: 1,
            effective_at: 20,
            trust: trust(7, 1),
        },
    );

    let other_key = SigningKey::from_bytes(&[100; 32]);
    let other_root = LearningTrustRootV1 {
        root_id: id("other-root"),
        scope_digest: digest("scope"),
        verifying_key: other_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    assert_eq!(
        activate_learning_trust(&other_root, signed.clone(), None, 50).unwrap_err(),
        LearningTrustDistributionError::RootMismatch
    );

    let mut revoked = root;
    revoked.revoked_at = Some(40);
    assert_eq!(
        activate_learning_trust(&revoked, signed, None, 50).unwrap_err(),
        LearningTrustDistributionError::InvalidRoot
    );
}
