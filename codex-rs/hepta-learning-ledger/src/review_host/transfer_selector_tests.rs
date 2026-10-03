#![allow(clippy::expect_used, clippy::unwrap_used)]
use super::*;
use crate::AuthenticatedPrincipalV1;
use crate::activate_learning_trust;
use crate::verify_signed_independent_roles_v1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn fixture(unlearning: bool) -> (LearningTrustRootV1, SignedLearningTrustDistributionV1) {
    let (root, mut signed) = super::unlearning_tests::fixture(if unlearning { 5 } else { 4 });
    let key = SigningKey::from_bytes(&[87; 32]);
    signed
        .distribution
        .trust
        .signers
        .push(TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: StableId::new("fixture-selector").unwrap(),
                credential_chain_digest: Digest32::of_bytes(b"selector-credential"),
                signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
                scope_digest: root.scope_digest,
                authority_epoch: 1,
                authenticated_at: 1,
                expires_at: 1000,
            },
            controller_id: StableId::new("fixture-selector-controller").unwrap(),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Selector],
            revoked_at: None,
        });
    resign(&mut signed);
    (root, signed)
}

fn resign(signed: &mut SignedLearningTrustDistributionV1) {
    signed.signature = SigningKey::from_bytes(&[99; 32])
        .sign(&signed.signing_bytes().unwrap())
        .to_bytes();
}

fn evidence(
    trust: Digest32,
    scope: Digest32,
    role: LearningEvidenceRoleV1,
    key: u8,
    principal: &str,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!("{principal}-evidence")).unwrap(),
        principal_id: StableId::new(principal).unwrap(),
        role,
        trust_digest: trust,
        scope_digest: scope,
        objective_digest: Digest32::of_bytes(b"objective"),
        authority_epoch: 1,
        issued_at: 50,
        expires_at: 100,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = SigningKey::from_bytes(&[key; 32])
        .sign(&signed.signing_bytes())
        .to_bytes();
    signed
}

#[test]
fn original_signed_distribution_retains_optional_selector_and_old_rosters() {
    for unlearning in [false, true] {
        let (root, original) = super::unlearning_tests::fixture(if unlearning { 5 } else { 4 });
        let old_bytes =
            serde_json::to_vec(&ReviewTrustWireV1::from_native(&root, &original)).unwrap();
        let (decoded_root, decoded) = ReviewTrustWireV1::from_native(&root, &original)
            .native()
            .unwrap();
        assert_eq!(
            serde_json::to_vec(&ReviewTrustWireV1::from_native(&decoded_root, &decoded)).unwrap(),
            old_bytes
        );
        let (root, signed) = fixture(unlearning);
        let wire = ReviewTrustWireV1::from_native(&root, &signed);
        assert_eq!(wire.signers.last().unwrap().role, "selector");
        let (decoded_root, decoded) = wire.native().unwrap();
        assert_eq!(decoded, signed);
        let active = activate_learning_trust(&decoded_root, decoded, None, 50).unwrap();
        let verifier = active.verifier();
        let payload = b"original learning-stage selection payload";
        let selector = evidence(
            verifier.trust_digest(),
            root.scope_digest,
            LearningEvidenceRoleV1::Selector,
            87,
            "fixture-selector",
            payload,
        );
        let native = ReviewEvidenceWireV1::from_native(&selector)
            .native()
            .unwrap();
        assert_eq!(selector, native);
        let selector = verifier
            .verify(LearningEvidenceRoleV1::Selector, &native, payload, 50)
            .unwrap();
        let observer = evidence(
            verifier.trust_digest(),
            root.scope_digest,
            LearningEvidenceRoleV1::Observer,
            72,
            "principal-1",
            payload,
        );
        let observer = verifier
            .verify(LearningEvidenceRoleV1::Observer, &observer, payload, 50)
            .unwrap();
        verify_signed_independent_roles_v1(&selector, &observer, 50).unwrap();
        assert!(
            verifier
                .verify(LearningEvidenceRoleV1::Observer, &native, payload, 50)
                .is_err()
        );
        assert!(
            verifier
                .verify(LearningEvidenceRoleV1::Selector, &native, payload, 101)
                .is_err()
        );
    }
}

#[test]
fn selector_transport_keeps_original_roster_and_root_authentication_mandatory() {
    let (root, signed) = fixture(true);
    let mut duplicate = signed.clone();
    duplicate
        .distribution
        .trust
        .signers
        .push(duplicate.distribution.trust.signers.last().unwrap().clone());
    assert!(
        ReviewTrustWireV1::from_native(&root, &duplicate)
            .native()
            .is_err()
    );
    let mut missing_evaluator = signed.clone();
    missing_evaluator.distribution.trust.signers.remove(3);
    assert!(
        ReviewTrustWireV1::from_native(&root, &missing_evaluator)
            .native()
            .is_err()
    );
    let mut forged = ReviewTrustWireV1::from_native(&root, &signed);
    forged.signers.last_mut().unwrap().controller_id = "unapproved-controller".into();
    let (root, decoded) = forged.native().unwrap();
    assert!(activate_learning_trust(&root, decoded, None, 50).is_err());
}
