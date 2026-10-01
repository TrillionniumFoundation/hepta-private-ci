use super::tests::*;
use super::*;
use crate::ArtifactSelectionError;
use crate::ArtifactSelectionTrustV1;
use crate::ArtifactSelectionVerifierV1;
use crate::SignedArtifactSelectionV1;
use crate::TrustedArtifactSelectorV1;
use crate::test_support::FixtureValue;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

#[test]
fn real_current_view_retains_exact_head_actor_expiry_and_revocation_windows() {
    for case in 0..3 {
        let directory = TestDir::new();
        let key = key();
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
        let scope_digest = withdrawals.scope_digest().fixture("scope");
        let mut owner_trust = trust(&key, scope_digest);
        if case == 1 {
            owner_trust.head_signers[0].expires_at = 60;
        }
        if case == 2 {
            owner_trust.head_signers[0].revoked_at = Some(60);
        }
        let mut service =
            LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                root: directory.0.clone(),
                trust: owner_trust.clone(),
                writer_lease: lease(&key, scope_digest),
                required_current_head: None,
                withdrawal_registry: withdrawals.clone(),
                storage_binding: digest("binding"),
                now: 20,
            })
            .fixture("open");
        let predecessor = service.registry().snapshot().head_digest;
        let admission = crate::admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            manifest(),
            20,
        )
        .fixture("admission");
        let mut staged = service.registry().clone();
        let preview = ArtifactPublicationTransactionV1::begin(
            id("operation"),
            admission,
            &withdrawals,
            &staged,
            predecessor,
            20,
        )
        .fixture("preview");
        service
            .host
            .stage_compatibility_registration(&preview, &mut staged, 20)
            .fixture("preview register");
        let request = publish_request(
            &key,
            &withdrawals,
            predecessor,
            staged.snapshot().head_digest,
        );
        service
            .publish(request)
            .fixture("actual signed publication");
        let view = service
            .current_registry_view(40)
            .fixture("actual CURRENT authentication");
        assert!(matches!(
            view.revalidate_at(39),
            Err(ArtifactOwnerHostError::SignerContext)
        ));
        let window = view.use_window();
        match case {
            0 => {
                window.revalidate_at(1_000).fixture("inclusive head expiry");
                assert!(matches!(
                    window.revalidate_at(1_001),
                    Err(ArtifactOwnerHostError::CurrentHeadExpired)
                ));
            }
            1 => {
                window.revalidate_at(60).fixture("inclusive signer expiry");
                assert!(matches!(
                    window.revalidate_at(61),
                    Err(ArtifactOwnerHostError::SignerRevoked)
                ));
            }
            2 => {
                window.revalidate_at(59).fixture("before known revocation");
                assert!(matches!(
                    window.revalidate_at(60),
                    Err(ArtifactOwnerHostError::SignerRevoked)
                ));
            }
            _ => unreachable!(),
        }
        let selector_key = SigningKey::from_bytes(&[55; 32]);
        let selector_trust = ArtifactSelectionTrustV1 {
            registry_id: owner_trust.registry_id.clone(),
            withdrawal_scope_digest: scope_digest,
            minimum_authority_epoch: 1,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id: id("independent-selector"),
                verifying_key: selector_key.verifying_key().to_bytes(),
                minimum_authority_epoch: 1,
                maximum_authority_epoch: 10,
                valid_from: 1,
                expires_at: 2_000,
                revoked_at: None,
            }],
        };
        let verifier = ArtifactSelectionVerifierV1::new(selector_trust, &owner_trust)
            .fixture("selector trust");
        let manifest = service
            .registry()
            .manifest(&id("candidate"))
            .fixture("published manifest");
        let mut signed = SignedArtifactSelectionV1 {
            selection_id: id("selection"),
            artifact_id: manifest.artifact_id.clone(),
            registry_id: owner_trust.registry_id.clone(),
            withdrawal_scope_digest: scope_digest,
            registry_head_digest: view.receipt().head_digest,
            current_witness_digest: view.witness_digest(),
            current_trust_digest: view.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: manifest.predecessor_id.clone(),
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: id("independent-selector"),
            selector_credential_digest: digest("selector-credential"),
            signing_key_digest: Digest32::of_bytes(&selector_key.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: 40,
            expires_at: 2_000,
            signature: [0; 64],
        };
        signed.signature = selector_key.sign(&signed.signing_bytes()).to_bytes();
        let selected = verifier
            .verify(&signed, &view, 40)
            .fixture("real independent signed selection");
        let (last_valid, expired) = match case {
            0 => (1_000, 1_001),
            1 => (60, 61),
            2 => (59, 60),
            _ => unreachable!(),
        };
        verifier
            .verify(&signed, &view, last_valid)
            .fixture("inclusive CURRENT boundary");
        verifier
            .revalidate_for_use(&selected, &view, last_valid)
            .fixture("retained boundary use");
        verifier
            .revalidate_window_for_use(&selected, expired)
            .fixture("selection remains current");
        assert!(matches!(
            verifier.verify(&signed, &view, expired),
            Err(ArtifactSelectionError::CurrentHeadMismatch)
        ));
        assert!(matches!(
            verifier.revalidate_for_use(&selected, &view, expired),
            Err(ArtifactSelectionError::CurrentHeadMismatch)
        ));
    }
}
