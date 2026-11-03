use super::*;
use pretty_assertions::assert_eq;

#[test]
fn delayed_selection_recording_preserves_all_original_authorization_windows() {
    let key = SigningKey::from_bytes(&[43; 32]);
    let producer = id("producer");
    let selector = id("selector");
    let manifest = manifest(producer.clone());
    let owner_key = SigningKey::from_bytes(&[13; 32]);
    let owner_trust = owner_trust(&owner_key);
    for (selector_expiry, selector_revoked, current_expiry, current_revoked, rejected_at) in [
        (40, None, 1_000, None, 41),
        (100, Some(40), 1_000, None, 40),
        (100, None, 40, None, 41),
        (100, None, 1_000, Some(40), 40),
        (100, None, 1_000, None, 29),
    ] {
        let original = current_view(&manifest, &owner_trust);
        let current = VerifiedCurrentRegistryViewV1::new(
            original.receipt(),
            original.registry().clone(),
            original.witness_digest(),
            original.trust_digest(),
            crate::CurrentRegistryValidityV1::new(
                /*verified_at*/ 20,
                current_expiry,
                current_revoked,
            ),
            original.authentication_profile(),
        );
        let mut selector_trust = trust(&key, selector.clone());
        selector_trust.selectors[0].expires_at = selector_expiry;
        selector_trust.selectors[0].revoked_at = selector_revoked;
        let verifier = must(ArtifactSelectionVerifierV1::new(
            selector_trust,
            &owner_trust,
        ));
        let signed = signed_selection(&key, selector.clone(), &manifest, &current);
        let verified = must(verifier.verify(&signed, &current, /*now*/ 30));
        let mut journal = ArtifactLifecycleJournalV2::new();
        let expected_head = journal.head_digest();
        let result = record_verified_selection(
            &mut journal,
            expected_head,
            &producer,
            &verified,
            id("late-selection"),
            rejected_at,
        );
        // The lifetime refusal precedes lifecycle validation or any journal write.
        assert!(matches!(
            result,
            Err(ArtifactSelectionError::SelectorRevoked
                | ArtifactSelectionError::SelectionContext
                | ArtifactSelectionError::Load(PinnedCandidateLoadError::CurrentValidity))
        ));
        assert_eq!(journal.head_digest(), expected_head);
        assert!(journal.records().is_empty());
    }
}
