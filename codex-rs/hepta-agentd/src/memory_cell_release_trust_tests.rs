use std::fs::File;
use std::sync::Arc;

use codex_hepta_learning_artifacts::ArtifactOwnerVerifierV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::RegistryHeadRequirementV1;
use codex_hepta_learning_artifacts::RegistrySnapshotReceipt;
use codex_hepta_learning_artifacts::VerifiedArtifactSelectionV1;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::MemoryCellReleaseHostV1;
use super::test_support::ReleaseFixture;
use super::test_support::selection_trust;
use super::tests::owner_fixture;

fn install(
    fixture: &ReleaseFixture,
    host: &MemoryCellReleaseHostV1,
    selection: VerifiedArtifactSelectionV1,
    receipt: RegistrySnapshotReceipt,
) -> Result<(), String> {
    host.install_selected(
        File::open(fixture.registry_file(receipt)).expect("real registry file"),
        File::open(fixture.payload_path(&fixture.initial_request)).expect("real payload file"),
        selection,
        fixture.initial_request.admission.clone(),
    )
}

#[tokio::test]
async fn signed_selection_expires_with_its_actual_credential_and_cannot_revive_after_failure() {
    let (_directory, store, access, scope) = owner_fixture().await;
    let snapshot = store
        .memory_cell_snapshot(&access, &scope, super::now().expect("time") as i64)
        .await
        .expect("owner snapshot");
    let fixture = ReleaseFixture::new(&snapshot);
    let now = super::now().expect("time");
    let current = fixture
        .service
        .lock()
        .expect("service")
        .current_registry_view(now)
        .expect("signed current");
    let receipt = current.receipt();
    let signed = fixture.signed_selection(&fixture.initial_request, &current);
    let mut trust = selection_trust(&fixture.config);
    trust.selectors[0].expires_at = now + 10;
    let verifier = ArtifactSelectionVerifierV1::new(trust.clone(), &fixture.config.trust)
        .expect("short credential trust");
    let verified = verifier
        .verify(&signed, &current, now)
        .expect("real signature and current verification");
    assert_eq!(verified.expires_at(), now + 10);
    assert!(verified.valid_at(now + 10));
    assert!(!verified.valid_at(now + 11));
    assert!(!verified.valid_at(signed.issued_at.saturating_sub(1)));
    let short_host = MemoryCellReleaseHostV1::new(Arc::clone(&fixture.service), verifier);
    install(&fixture, &short_host, verified, receipt).expect("current credential installation");
    short_host.load_current().expect("live selected reader");
    {
        let service = fixture.service.lock().expect("service");
        let mut selected = short_host.inner.selected.lock().expect("selected state");
        assert!(
            super::revalidate_state(
                &service,
                &short_host.inner.selection_verifier,
                selected.as_mut().expect("installed"),
                now + 11
            )
            .is_err()
        );
    }
    assert!(
        short_host.load_current().is_err(),
        "a failed validity check permanently closes this cached selection"
    );

    trust.selectors[0].expires_at = now + 20;
    trust.selectors[0].revoked_at = Some(now + 7);
    let verifier = ArtifactSelectionVerifierV1::new(trust, &fixture.config.trust)
        .expect("revocation-bounded trust");
    let verified = verifier
        .verify(&signed, &current, now)
        .expect("credential valid before revocation");
    assert_eq!(verified.expires_at(), now + 6);
    assert!(verified.valid_at(now + 6));
    assert!(!verified.valid_at(now + 7));
    assert!(verifier.verify(&signed, &current, now + 7).is_err());
}

#[tokio::test]
async fn opaque_proofs_from_other_selector_or_owner_trust_cannot_replay_identical_registry_bytes() {
    let (_directory, store, access, scope) = owner_fixture().await;
    let snapshot = store
        .memory_cell_snapshot(&access, &scope, super::now().expect("time") as i64)
        .await
        .expect("owner snapshot");
    let fixture = ReleaseFixture::new(&snapshot);
    let now = super::now().expect("time");
    let current = fixture
        .service
        .lock()
        .expect("service")
        .current_registry_view(now)
        .expect("real current");
    let receipt = current.receipt();
    let foreign_selector = SigningKey::from_bytes(&[61; 32]);
    let mut foreign_selector_trust = selection_trust(&fixture.config);
    foreign_selector_trust.selectors[0].verifying_key = foreign_selector.verifying_key().to_bytes();
    let verifier = ArtifactSelectionVerifierV1::new(foreign_selector_trust, &fixture.config.trust)
        .expect("internally valid alternate selector trust");
    let mut signed = fixture.signed_selection(&fixture.initial_request, &current);
    signed.signing_key_digest = Digest32::of_bytes(&foreign_selector.verifying_key().to_bytes());
    signed.signature = foreign_selector.sign(&signed.signing_bytes()).to_bytes();
    let foreign_proof = verifier
        .verify(&signed, &current, now)
        .expect("proof verified under other selector policy");
    assert!(install(&fixture, &fixture.host, foreign_proof, receipt).is_err());

    // Even identical payload/snapshot bytes can be signed in another authority
    // domain. The opaque proof must retain and bind the actual owner trust.
    let foreign_owner = SigningKey::from_bytes(&[73; 32]);
    let mut foreign_owner_trust = fixture.config.trust.clone();
    for signer in foreign_owner_trust
        .writer_signers
        .iter_mut()
        .chain(foreign_owner_trust.head_signers.iter_mut())
    {
        signer.verifying_key = foreign_owner.verifying_key().to_bytes();
    }
    let owner_verifier =
        ArtifactOwnerVerifierV1::new(foreign_owner_trust.clone()).expect("alternate owner policy");
    let mut foreign_head = fixture.initial_request.signed_current_head.clone();
    foreign_head.witness.signing_key_digest =
        Digest32::of_bytes(&foreign_owner.verifying_key().to_bytes());
    foreign_head.signature = foreign_owner.sign(&foreign_head.signing_bytes()).to_bytes();
    let requirement = RegistryHeadRequirementV1 {
        registry_id: foreign_head.witness.registry_id.clone(),
        minimum_generation: foreign_head.witness.generation,
        expected_predecessor_head_digest: foreign_head.witness.predecessor_head_digest,
        minimum_authority_epoch: 1,
        now,
    };
    let foreign_current = owner_verifier
        .verify_current_registry_view(
            File::open(fixture.registry_file(receipt)).expect("same exact registry bytes"),
            receipt,
            &foreign_head,
            &requirement,
        )
        .expect("current proof under another owner trust");
    assert_ne!(foreign_current.trust_digest(), current.trust_digest());
    let verifier =
        ArtifactSelectionVerifierV1::new(selection_trust(&fixture.config), &foreign_owner_trust)
            .expect("same selector, other owner");
    let signed = fixture.signed_selection(&fixture.initial_request, &foreign_current);
    let foreign_proof = verifier
        .verify(&signed, &foreign_current, now)
        .expect("other-owner selection proof");
    assert_eq!(
        foreign_proof.trust_digest(),
        fixture.host.selection_verifier.trust_digest()
    );
    assert_ne!(
        foreign_proof.current_owner_trust_digest(),
        fixture.host.selection_verifier.owner_trust_digest()
    );
    assert!(install(&fixture, &fixture.host, foreign_proof, receipt).is_err());
    fixture
        .host
        .load_current()
        .expect("rejected foreign proofs leave configured selected reader intact");
}
