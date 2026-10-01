use super::tests::current_view;
use super::tests::id;
use super::tests::manifest;
use super::tests::must;
use super::tests::owner_trust;
use super::tests::signed_selection;
use super::tests::trust;
use super::*;
use ed25519_dalek::SigningKey;

#[test]
fn verified_selection_preserves_selector_expiry_and_revocation_boundaries() {
    let key = SigningKey::from_bytes(&[44; 32]);
    let owner_key = SigningKey::from_bytes(&[13; 32]);
    let owner_trust = owner_trust(&owner_key);
    let producer = id("producer");
    let manifest = manifest(producer.clone());
    let current = current_view(&manifest, &owner_trust);
    for revoked_at in [None, Some(40)] {
        let mut trust = trust(&key, id("selector"));
        trust.selectors[0].expires_at = 40;
        trust.selectors[0].revoked_at = revoked_at;
        let verifier = must(ArtifactSelectionVerifierV1::new(trust, &owner_trust));
        let signed = signed_selection(&key, id("selector"), &manifest, &current);
        let verified = must(verifier.verify(&signed, &current, 30));
        let mut journal = ArtifactLifecycleJournalV2::new();
        assert!(matches!(
            record_verified_selection(
                &mut journal,
                Digest32::ZERO,
                &producer,
                &verified,
                id("selection-event"),
                if revoked_at.is_some() { 40 } else { 41 },
            ),
            Err(ArtifactSelectionError::SelectionContext)
        ));
        assert!(journal.records().is_empty());
    }
}

#[test]
fn verified_selection_cannot_be_recorded_with_a_substitute_producer() {
    let key = SigningKey::from_bytes(&[45; 32]);
    let owner_key = SigningKey::from_bytes(&[13; 32]);
    let owner_trust = owner_trust(&owner_key);
    let manifest = manifest(id("producer"));
    let current = current_view(&manifest, &owner_trust);
    let verifier = must(ArtifactSelectionVerifierV1::new(
        trust(&key, id("selector")),
        &owner_trust,
    ));
    let signed = signed_selection(&key, id("selector"), &manifest, &current);
    let verified = must(verifier.verify(&signed, &current, 30));
    let mut journal = ArtifactLifecycleJournalV2::new();
    assert!(matches!(
        record_verified_selection(
            &mut journal,
            Digest32::ZERO,
            &id("substitute-producer"),
            &verified,
            id("selection-event"),
            30,
        ),
        Err(ArtifactSelectionError::ManifestMismatch)
    ));
}
