#![allow(clippy::expect_used, clippy::unwrap_used)]
use super::*;
use crate::AuthenticatedPrincipalV1;
use crate::LearningEvidenceRoleV1;
use crate::activate_learning_trust;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub(super) fn fixture(count: usize) -> (LearningTrustRootV1, SignedLearningTrustDistributionV1) {
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("fixture-root"),
        scope_digest: digest("scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 1000,
        revoked_at: None,
    };
    let signers = (0..count)
        .map(|index| {
            let key = SigningKey::from_bytes(&[71 + index as u8; 32]);
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(&format!("principal-{index}")),
                    credential_chain_digest: digest(&format!("credential-{index}")),
                    signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
                    scope_digest: root.scope_digest,
                    authority_epoch: 1,
                    authenticated_at: 1,
                    expires_at: 1000,
                },
                controller_id: id(&format!("controller-{index}")),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![match index {
                    0 => LearningEvidenceRoleV1::Generator,
                    1 => LearningEvidenceRoleV1::Observer,
                    2 | 3 => LearningEvidenceRoleV1::Evaluator,
                    _ => LearningEvidenceRoleV1::UnlearningAuthority,
                }],
                revoked_at: None,
            }
        })
        .collect();
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("fixture-distribution"),
            generation: 1,
            effective_at: 10,
            trust: LearningEvidenceTrustV1 {
                scope_digest: root.scope_digest,
                objective_digest: digest("objective"),
                authority_epoch: 1,
                signers,
            },
        },
        root_id: root.root_id.clone(),
        issued_at: 10,
        expires_at: 900,
        signature: [0; 64],
    };
    signed.signature = root_key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    (root, signed)
}

#[test]
fn review_wire_retains_original_roster_and_dedicated_unlearning_root_signature() {
    for count in [4, 5] {
        let (root, signed) = fixture(count);
        let wire = ReviewTrustWireV1::from_native(&root, &signed);
        let (decoded_root, decoded_signed) = wire.native().unwrap();
        assert_eq!(decoded_root, root);
        assert_eq!(decoded_signed, signed);
        let trust = activate_learning_trust(&decoded_root, decoded_signed, None, 50).unwrap();
        let key = SigningKey::from_bytes(&[75; 32]);
        let payload = b"original typed fixture payload";
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id("withdrawal-evidence"),
            principal_id: id("principal-4"),
            role: LearningEvidenceRoleV1::UnlearningAuthority,
            trust_digest: trust.verifier().trust_digest(),
            scope_digest: root.scope_digest,
            objective_digest: digest("objective"),
            authority_epoch: 1,
            issued_at: 50,
            expires_at: 100,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
        assert_eq!(
            ReviewEvidenceWireV1::from_native(&evidence)
                .native()
                .unwrap(),
            evidence
        );
        assert_eq!(
            trust
                .verifier()
                .verify(
                    LearningEvidenceRoleV1::UnlearningAuthority,
                    &evidence,
                    payload,
                    50
                )
                .is_ok(),
            count == 5
        );
    }
    let (root, signed) = fixture(5);
    let mut wire = ReviewTrustWireV1::from_native(&root, &signed);
    wire.signers[4].role = "evaluator".into();
    assert!(wire.native().is_err());
    wire.signers[4].role = "unlearning_authority".into();
    wire.signers.remove(3);
    assert!(wire.native().is_err());
}
