//! Real selection/CURRENT byte checks; no model or product qualification.
use super::pq_initial_tests::pq_current;
use super::pq_initial_tests::pq_key;
use super::*;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use pretty_assertions::assert_eq;

struct PublicFixture {
    original: Fixture,
    owner: PqNativeSigningKey,
    selector: PqNativeSigningKey,
}

impl PublicFixture {
    fn new(bytes: &[u8], manifest: ArtifactManifest) -> Self {
        let mut original = Fixture::new(bytes, manifest);
        let owner = pq_key(/*seed*/ 93);
        let selector = pq_key(/*seed*/ 94);
        for trusted in original
            .owner_trust
            .writer_signers
            .iter_mut()
            .chain(original.owner_trust.head_signers.iter_mut())
        {
            trusted.verifying_key =
                LearningVerificationKey::MlDsa65V2(owner.public_spki().to_vec());
        }
        let mut trust = original.selector.trust.clone();
        trust.selectors[0].verifying_key =
            LearningVerificationKey::MlDsa65V2(selector.public_spki().to_vec());
        original.selector = ArtifactSelectionVerifierV1::new(trust, &original.owner_trust)
            .fixture("ordinary public selector trust");
        Self {
            original,
            owner,
            selector,
        }
    }

    fn current(&self) -> (VerifiedCurrentRegistryViewV1, PathBuf) {
        pq_current(&self.original, &self.owner)
    }

    fn signed(&self, current: &VerifiedCurrentRegistryViewV1) -> SignedArtifactSelectionV1 {
        let mut signed = self.original.signed(current);
        signed.signing_key_digest = Digest32::of_bytes(self.selector.public_spki());
        signed.signature = LearningSignature::MlDsa65V2(Vec::new());
        signed.signature = LearningSignature::MlDsa65V2(
            self.selector
                .sign_exact_message(&signed.signing_bytes())
                .fixture("ordinary public selector signature")
                .to_vec(),
        );
        signed
    }
}

#[test]
fn public_initial_admission_rejects_profile_crossing_and_changed_factors() {
    let original = material();
    for public in [false, true] {
        for changed in [false, true] {
            let mut bytes = original.clone();
            if changed {
                *bytes.last_mut().unwrap() = 1;
            }
            let mut declared = manifest(&bytes);
            if public {
                declared.compatibility_digest =
                    Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2);
            }
            let fixture = PublicFixture::new(&bytes, declared);
            for v2 in [false, true] {
                let (current, snapshot) = fixture.current();
                let selected = fixture
                    .original
                    .selector
                    .verify(&fixture.signed(&current), &current, /*now*/ 30)
                    .unwrap();
                let result = if v2 {
                    selected
                        .load_public_initial_smollm_material_v2(
                            File::open(snapshot).unwrap(),
                            File::open(fixture.original.root.join("payload")).unwrap(),
                            current,
                            /*now*/ 30,
                        )
                        .map(|mut value| {
                            let (current, _) = fixture.current();
                            value
                                .with_current(current, /*now*/ 30, Digest32::of_bytes)
                                .unwrap()
                        })
                } else {
                    selected
                        .load_initial_smollm_material(
                            File::open(snapshot).unwrap(),
                            File::open(fixture.original.root.join("payload")).unwrap(),
                            current,
                            /*now*/ 30,
                        )
                        .map(|mut value| {
                            let (current, _) = fixture.current();
                            value
                                .with_current(current, /*now*/ 30, Digest32::of_bytes)
                                .unwrap()
                        })
                };
                assert_eq!(result.is_ok(), public == v2 && !changed);
                if let Ok(actual) = result {
                    assert_eq!(actual, Digest32::of_bytes(&original));
                }
            }
        }
    }
}

#[test]
fn public_initial_expired_current_is_sticky_and_cannot_be_revived() {
    let bytes = material();
    let mut declared = manifest(&bytes);
    declared.compatibility_digest = Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2);
    let fixture = PublicFixture::new(&bytes, declared);
    let (current, snapshot) = fixture.current();
    let selected = fixture
        .original
        .selector
        .verify(&fixture.signed(&current), &current, /*now*/ 30)
        .unwrap();
    let mut value = selected
        .load_public_initial_smollm_material_v2(
            File::open(snapshot).unwrap(),
            File::open(fixture.original.root.join("payload")).unwrap(),
            current,
            /*now*/ 30,
        )
        .unwrap();
    let (current, _) = fixture.current();
    assert!(value.with_current(current, /*now*/ 81, |_| ()).is_err());
    let (current, _) = fixture.current();
    assert!(value.with_current(current, /*now*/ 30, |_| ()).is_err());
}

#[test]
fn classical_public_history_does_not_authorize_new_runtime_material() {
    let bytes = material();
    let mut declared = manifest(&bytes);
    declared.compatibility_digest = Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2);
    let fixture = Fixture::new(&bytes, declared);
    let (current, snapshot) = fixture.current();
    let selected = fixture
        .selector
        .verify(&fixture.signed(&current), &current, /*now*/ 30)
        .fixture("valid historical classical signature");
    assert!(matches!(
        selected.load_public_initial_smollm_material_v2(
            File::open(snapshot).fixture("historical snapshot"),
            File::open(fixture.root.join("payload")).fixture("historical payload"),
            current,
            /*now*/ 30,
        ),
        Err(ArtifactSelectionError::AuthenticationProfile)
    ));
    // Rejecting new execution material neither rewrites nor destroys history.
    let mut history = fixture.load().fixture("original historical read API");
    let (current, _) = fixture.current();
    assert_eq!(
        history
            .with_current(current, /*now*/ 30, Digest32::of_bytes)
            .fixture("historical bytes remain readable"),
        Digest32::of_bytes(&bytes)
    );
}
