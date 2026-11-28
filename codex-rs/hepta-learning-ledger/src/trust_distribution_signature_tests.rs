use super::*;

use pretty_assertions::assert_eq;

#[test]
fn signature_only_validation_keeps_full_content_and_validity_checks()
-> Result<(), Box<dyn std::error::Error>> {
    let key = SigningKey::from_bytes(&[99; 32]);
    let pinned = root(&key);
    let original = signed_distribution(
        &key,
        LearningTrustDistributionV1 {
            distribution_id: id("external-trust-v1"),
            generation: 1,
            effective_at: 20,
            trust: trust(/*epoch*/ 7, /*seed*/ 1),
        },
    );
    verify_learning_trust_distribution_signature(&pinned, &original, /*now*/ 50)?;
    let mut mutations = Vec::new();
    let mut changed = original.clone();
    changed.signature[0] ^= 1;
    mutations.push(changed);
    let mut changed = original.clone();
    changed.distribution.generation = 2;
    mutations.push(changed);
    let mut changed = original.clone();
    changed.distribution.trust.objective_digest = digest("other-objective");
    mutations.push(changed);
    let mut changed = original.clone();
    changed.distribution.trust.signers[0].roles = vec![LearningEvidenceRoleV1::Observer];
    mutations.push(changed);
    for changed in mutations {
        assert_eq!(
            verify_learning_trust_distribution_signature(&pinned, &changed, /*now*/ 50).err(),
            Some(LearningTrustDistributionError::InvalidSignature)
        );
    }
    assert_eq!(
        verify_learning_trust_distribution_signature(&pinned, &original, /*now*/ 91).err(),
        Some(LearningTrustDistributionError::DistributionWindow)
    );
    let mut revoked = pinned.clone();
    revoked.revoked_at = Some(50);
    assert_eq!(
        verify_learning_trust_distribution_signature(&revoked, &original, /*now*/ 50).err(),
        Some(LearningTrustDistributionError::InvalidRoot)
    );
    let mut other_scope = pinned;
    other_scope.scope_digest = digest("other-scope");
    assert_eq!(
        verify_learning_trust_distribution_signature(&other_scope, &original, /*now*/ 50).err(),
        Some(LearningTrustDistributionError::InvalidGeneration)
    );
    Ok(())
}

#[test]
fn independent_signatures_do_not_assert_current_generation()
-> Result<(), Box<dyn std::error::Error>> {
    let key = SigningKey::from_bytes(&[99; 32]);
    let pinned = root(&key);
    let mut observed = Vec::new();
    for generation in [3, 1] {
        let signed = signed_distribution(
            &key,
            LearningTrustDistributionV1 {
                distribution_id: id(&format!("external-trust-{generation}")),
                generation,
                effective_at: 20,
                trust: trust(/*epoch*/ 7, /*seed*/ 1),
            },
        );
        let verified =
            verify_learning_trust_distribution_signature(&pinned, &signed, /*now*/ 50)?;
        let identity = verified.learning_trust_signature_identity();
        observed.push((
            identity.root_id.clone(),
            identity.generation,
            identity.authority_epoch,
        ));
        assert_eq!(identity.scope_digest, digest("scope"));
        assert_eq!(
            (
                identity.issued_at,
                identity.effective_at,
                identity.expires_at
            ),
            (15, 20, 90)
        );
        assert!(!identity.distribution_digest.is_zero());
    }
    assert_eq!(observed, vec![(id("root"), 3, 7), (id("root"), 1, 7)]);
    Ok(())
}
