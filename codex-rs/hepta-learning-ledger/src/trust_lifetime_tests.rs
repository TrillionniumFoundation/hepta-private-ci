use super::*;
use crate::SignedEvidenceError;
use crate::SignedLearningEvidenceV1;
use pretty_assertions::assert_eq;

#[test]
fn activated_trust_and_cloned_verifier_retain_expiry_revocation_and_clock_floor() {
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let signer = SigningKey::from_bytes(&[1; 32]);
    for (expires_at, revoked_at, rejected_at, expected) in [
        (60, None, 61, SignedEvidenceError::ValidityWindow),
        (90, Some(60), 60, SignedEvidenceError::Revoked),
        (90, None, 49, SignedEvidenceError::ValidityWindow),
    ] {
        let mut root = root(&root_key);
        root.revoked_at = revoked_at;
        let mut signed = signed_distribution(
            &root_key,
            LearningTrustDistributionV1 {
                distribution_id: id("windowed-trust"),
                generation: 1,
                effective_at: 20,
                trust: trust(/*epoch*/ 7, /*seed*/ 1),
            },
        );
        signed.expires_at = expires_at;
        signed.signature = root_key
            .sign(&signed.signing_bytes().unwrap())
            .to_bytes()
            .into();
        let activated =
            activate_learning_trust(&root, signed, /*previous*/ None, /*now*/ 50).unwrap();
        let verifier = activated.verifier().clone();
        let payload = b"actual generator evidence";
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id("evidence"),
            principal_id: id("generator"),
            role: LearningEvidenceRoleV1::Generator,
            trust_digest: verifier.trust_digest(),
            scope_digest: verifier.scope_digest(),
            objective_digest: verifier.objective_digest(),
            authority_epoch: verifier.authority_epoch(),
            payload_digest: Digest32::of_bytes(payload),
            issued_at: 20,
            expires_at: 100,
            signature: [0; 64].into(),
        };
        evidence.signature = signer.sign(&evidence.signing_bytes()).to_bytes().into();
        let admitted = verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                &evidence,
                payload,
                /*now*/ 50,
            )
            .unwrap();
        assert_eq!(admitted.principal_for_lifetime().authenticated_at, 50);
        assert_eq!(
            admitted.principal_for_lifetime().expires_at,
            revoked_at.map_or(expires_at, |at| expires_at.min(at - 1))
        );
        for retained in [activated.verifier(), &verifier] {
            assert_eq!(
                retained
                    .verify(
                        LearningEvidenceRoleV1::Generator,
                        &evidence,
                        payload,
                        rejected_at
                    )
                    .unwrap_err(),
                expected
            );
        }
        assert_eq!(
            crate::verify_signed_actor_separation(&admitted, &admitted, rejected_at),
            Err(expected)
        );
    }
}
