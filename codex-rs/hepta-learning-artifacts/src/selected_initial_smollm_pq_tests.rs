//! Real ML-DSA CURRENT and selector signatures around the original initial bytes.
//! Test keys and local temporary files do not qualify a deployed trust service.
use super::*;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use pretty_assertions::assert_eq;

pub(super) fn pq_key(seed: u8) -> PqNativeSigningKey {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
    PqNativeSigningKey::from_owned_seed(
        [seed; 32].into(),
        ml_dsa_65_key_id_from_spki(&spki).fixture("PQ key identity"),
    )
    .fixture("PQ initial-material test signer")
}

pub(super) fn pq_current(
    fixture: &Fixture,
    key: &PqNativeSigningKey,
) -> (VerifiedCurrentRegistryViewV1, PathBuf) {
    let path = fixture.root.join(format!(
        "pq-snapshot-{}",
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    let receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&path).fixture("PQ snapshot create"),
        &fixture.registry,
        digest("storage binding"),
    )
    .fixture("PQ actual snapshot");
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: fixture.owner_trust.withdrawal_scope_digest,
        binding: receipt.binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: fixture.owner_trust.registry_id.clone(),
            generation: Generation::new(receipt.records as u64).fixture("PQ generation"),
            head_digest: receipt.head_digest,
            predecessor_head_digest: Digest32::ZERO,
            authority_epoch: 1,
            signer_id: id("original-owner"),
            signing_key_digest: Digest32::of_bytes(key.public_spki()),
            issued_at: 20,
            expires_at: 80,
        },
        signature: LearningSignature::MlDsa65V2(Vec::new()),
    };
    signed.signature = LearningSignature::MlDsa65V2(
        key.sign_exact_message(&signed.signing_bytes())
            .fixture("PQ CURRENT signature")
            .to_vec(),
    );
    let current = ArtifactOwnerVerifierV1::new(fixture.owner_trust.clone())
        .fixture("PQ CURRENT owner")
        .verify_current_registry_view(
            File::open(&path).fixture("PQ snapshot FD"),
            receipt,
            &signed,
            &RegistryHeadRequirementV1 {
                registry_id: fixture.owner_trust.registry_id.clone(),
                minimum_generation: Generation::new(1).fixture("PQ floor"),
                expected_predecessor_head_digest: Digest32::ZERO,
                minimum_authority_epoch: 1,
                now: 30,
            },
        )
        .fixture("authenticate original PQ CURRENT");
    (current, path)
}

#[test]
fn pq_initial_material_keeps_selector_current_and_final_use_profile_bound() {
    for public in [false, true] {
        let bytes = material();
        let mut declared = manifest(&bytes);
        if public {
            declared.compatibility_digest = Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2);
        }
        let mut fixture = Fixture::new(&bytes, declared);
        let owner = pq_key(/*seed*/ 93);
        let selector = pq_key(/*seed*/ 94);
        for trusted in fixture
            .owner_trust
            .writer_signers
            .iter_mut()
            .chain(fixture.owner_trust.head_signers.iter_mut())
        {
            trusted.verifying_key =
                LearningVerificationKey::MlDsa65V2(owner.public_spki().to_vec());
        }
        let mut trust = fixture.selector.trust.clone();
        trust.selectors[0].verifying_key =
            LearningVerificationKey::MlDsa65V2(selector.public_spki().to_vec());
        fixture.selector = ArtifactSelectionVerifierV1::new(trust, &fixture.owner_trust)
            .fixture("PQ selector owner");
        let (current, snapshot) = pq_current(&fixture, &owner);
        let mut signed = fixture.signed(&current);
        // CURRENT remains valid until 80; only the immutable selector lease ends at 40.
        signed.expires_at = 40;
        signed.signing_key_digest = Digest32::of_bytes(selector.public_spki());
        signed.signature = LearningSignature::MlDsa65V2(Vec::new());
        signed.signature = LearningSignature::MlDsa65V2(
            selector
                .sign_exact_message(&signed.signing_bytes())
                .fixture("PQ selection signature")
                .to_vec(),
        );
        // An actual classical proof cannot satisfy this independently pinned
        // PQ selection. Rejection does not poison the later valid selection.
        let mut classical = signed.clone();
        classical.signature = [0; 64].into();
        classical.signature = fixture
            .selector_key
            .sign(&classical.signing_bytes())
            .to_bytes()
            .into();
        assert!(
            fixture
                .selector
                .verify(&classical, &current, /*now*/ 30)
                .is_err()
        );
        let selected = fixture
            .selector
            .verify(&signed, &current, /*now*/ 30)
            .fixture("valid PQ selection after refusal");
        let payload = File::open(fixture.root.join("payload")).fixture("selected PQ payload");
        let snapshot = File::open(snapshot).fixture("selected PQ snapshot");
        if public {
            let mut loaded = selected
                .load_public_initial_smollm_material_v2(snapshot, payload, current, /*now*/ 30)
                .fixture("public initial material under PQ owners");
            assert_eq!(
                loaded.authentication_profile(),
                LearningAuthenticationProfile::MlDsa65V2
            );
            let (current, _) = pq_current(&fixture, &owner);
            assert_eq!(
                loaded
                    .with_current(current, /*now*/ 39, Digest32::of_bytes)
                    .unwrap(),
                Digest32::of_bytes(&bytes)
            );
            let (current, _) = pq_current(&fixture, &owner);
            assert!(
                loaded
                    .with_current(
                        current,
                        /*now*/ 40,
                        |_| panic!("expired PQ material read")
                    )
                    .is_err()
            );
            let (current, _) = pq_current(&fixture, &owner);
            assert!(
                loaded
                    .with_current(
                        current,
                        /*now*/ 39,
                        |_| panic!("closed PQ material revived")
                    )
                    .is_err()
            );
        } else {
            let mut loaded = selected
                .load_initial_smollm_material(snapshot, payload, current, /*now*/ 30)
                .fixture("historical initial material under PQ owners");
            assert_eq!(
                loaded.authentication_profile(),
                LearningAuthenticationProfile::MlDsa65V2
            );
            let (current, _) = pq_current(&fixture, &owner);
            assert_eq!(
                loaded
                    .with_current(current, /*now*/ 39, Digest32::of_bytes)
                    .unwrap(),
                Digest32::of_bytes(&bytes)
            );
            let (current, _) = pq_current(&fixture, &owner);
            assert!(
                loaded
                    .with_current(
                        current,
                        /*now*/ 40,
                        |_| panic!("expired PQ material read")
                    )
                    .is_err()
            );
            let (current, _) = pq_current(&fixture, &owner);
            assert!(
                loaded
                    .with_current(
                        current,
                        /*now*/ 39,
                        |_| panic!("closed PQ material revived")
                    )
                    .is_err()
            );
        }
    }
}
