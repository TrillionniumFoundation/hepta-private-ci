//! Original owner signatures, CURRENT snapshots and actual selected files.
//! These test signers grant no production enrollment, execution or efficacy.

use super::*;
use pretty_assertions::assert_eq;

fn signed_for(fixture: &Fixture) -> SignedArtifactSelectionV1 {
    let (current, _) = fixture.current();
    fixture.signed(&current)
}

fn load_initial(
    fixture: &Fixture,
    signed: &SignedArtifactSelectionV1,
    verified_at: u64,
    now: u64,
) -> Result<SelectedInitialSmolLmMaterialV1, ArtifactSelectionError> {
    let (current, snapshot) = fixture.current();
    let selected = fixture.selector.verify(signed, &current, verified_at)?;
    let (fresh_current, _) = fixture.current();
    selected.load_initial_smollm_material(
        File::open(snapshot).fixture("actual selected snapshot"),
        File::open(fixture.root.join("payload")).fixture("actual selected payload"),
        fresh_current,
        now,
    )
}

#[test]
fn opaque_material_reads_actual_bytes_and_cold_reopens_same_selected_files() {
    let bytes = material();
    let fixture = Fixture::new(&bytes, manifest(&bytes));
    let signed = signed_for(&fixture);
    let mut loaded = load_initial(&fixture, &signed, /*verified_at*/ 30, /*now*/ 30)
        .fixture("opaque selected material");
    let mut selection_bytes = signed.signing_bytes();
    selection_bytes.extend_from_slice(&signed.signature);
    assert_eq!(loaded.manifest(), &fixture.manifest);
    assert_eq!(
        loaded.selection_digest(),
        Digest32::of_bytes(&selection_bytes)
    );
    let (current, _) = fixture.current();
    assert_eq!(
        loaded
            .with_current(current, /*now*/ 31, Digest32::of_bytes)
            .fixture("actual byte consumer"),
        Digest32::of_bytes(&bytes)
    );
    drop(loaded);
    let mut recovered = load_initial(&fixture, &signed, /*verified_at*/ 32, /*now*/ 32)
        .fixture("cold reverify original selection and files");
    let (current, _) = fixture.current();
    assert_eq!(
        recovered
            .with_current(current, /*now*/ 32, Digest32::of_bytes)
            .fixture("cold actual byte consumer"),
        Digest32::of_bytes(&bytes)
    );
}

#[test]
fn original_signed_expiry_survives_load_and_cold_reverification() {
    let bytes = material();
    let fixture = Fixture::new(&bytes, manifest(&bytes));
    let mut signed = signed_for(&fixture);
    signed.expires_at = 35;
    signed.signature = fixture
        .selector_key
        .sign(&signed.signing_bytes())
        .to_bytes();
    let mut loaded = load_initial(&fixture, &signed, /*verified_at*/ 30, /*now*/ 34)
        .fixture("load inside original window");
    let (current, _) = fixture.current();
    loaded
        .with_current(current, /*now*/ 35, |_| ())
        .fixture("inclusive original expiry");
    let (current, _) = fixture.current();
    assert!(matches!(
        loaded.with_current(current, /*now*/ 36, |_| ()),
        Err(ArtifactSelectionError::SelectionContext)
    ));
    assert!(matches!(
        load_initial(&fixture, &signed, /*verified_at*/ 36, /*now*/ 36),
        Err(ArtifactSelectionError::SelectionContext)
    ));
    assert!(matches!(
        load_initial(&fixture, &signed, /*verified_at*/ 30, /*now*/ 36),
        Err(ArtifactSelectionError::SelectionContext)
    ));
}

#[test]
fn original_trusted_selector_expiry_and_known_revocation_are_not_lost() {
    for revoked_at in [None, Some(35)] {
        let bytes = material();
        let mut fixture = Fixture::new(&bytes, manifest(&bytes));
        let mut trust = fixture.selector.trust.clone();
        trust.selectors[0].expires_at = if revoked_at.is_some() { 100 } else { 35 };
        trust.selectors[0].revoked_at = revoked_at;
        fixture.selector = ArtifactSelectionVerifierV1::new(trust, &fixture.owner_trust)
            .fixture("original trusted selector window");
        let signed = signed_for(&fixture);
        let mut loaded = load_initial(&fixture, &signed, /*verified_at*/ 30, /*now*/ 30)
            .fixture("selection before original cutoff");
        let (current, _) = fixture.current();
        loaded
            .with_current(current, /*now*/ 34, |_| ())
            .fixture("pre-cutoff read");
        let (current, _) = fixture.current();
        let cutoff = if revoked_at.is_some() { 35 } else { 36 };
        let result = loaded.with_current(current, cutoff, |_| ());
        match revoked_at {
            Some(_) => assert!(matches!(
                result,
                Err(ArtifactSelectionError::SelectorRevoked)
            )),
            None => assert!(matches!(
                result,
                Err(ArtifactSelectionError::SelectionContext)
            )),
        }
    }
}

#[test]
fn failed_time_or_withdrawal_cannot_be_revived_by_an_old_current() {
    let bytes = material();
    let mut fixture = Fixture::new(&bytes, manifest(&bytes));
    let signed = signed_for(&fixture);
    let mut loaded =
        load_initial(&fixture, &signed, /*verified_at*/ 30, /*now*/ 30).fixture("initial");
    let (old_current, _) = fixture.current();
    fixture
        .registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("opaque-initial-withdrawal"),
            artifact_id: fixture.manifest.artifact_id.clone(),
            evaluator_id: id("independent-withdrawal-owner"),
            reason_digest: digest("withdrawn selected initial material"),
        }))
        .fixture("original registry withdrawal");
    let (withdrawn, _) = fixture.current();
    assert!(matches!(
        loaded.with_current(withdrawn, /*now*/ 31, |_| ()),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Ineligible
        ))
    ));
    assert!(matches!(
        loaded.with_current(old_current, /*now*/ 31, |_| ()),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Unavailable
        ))
    ));
    assert!(matches!(
        load_initial(&fixture, &signed, /*verified_at*/ 31, /*now*/ 31),
        Err(ArtifactSelectionError::CurrentHeadMismatch)
    ));
}

#[test]
fn current_expiry_and_clock_rollback_fail_closed_without_invoking_consumer() {
    let bytes = material();
    let fixture = Fixture::new(&bytes, manifest(&bytes));
    let signed = signed_for(&fixture);
    let mut loaded =
        load_initial(&fixture, &signed, /*verified_at*/ 30, /*now*/ 30).fixture("initial");
    let (current, _) = fixture.current();
    loaded
        .with_current(current, /*now*/ 40, |_| ())
        .fixture("forward clock");
    let (current, _) = fixture.current();
    assert!(matches!(
        loaded.with_current(
            current,
            /*now*/ 39,
            |_| panic!("rollback consumer reached")
        ),
        Err(ArtifactSelectionError::SelectionContext)
    ));
    let (current, _) = fixture.current();
    assert!(matches!(
        loaded.with_current(
            current,
            /*now*/ 40,
            |_| panic!("sticky consumer reached")
        ),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Unavailable
        ))
    ));

    let mut fresh = load_initial(&fixture, &signed, /*verified_at*/ 30, /*now*/ 30)
        .fixture("new verified consumer");
    let (current, _) = fixture.current();
    assert!(matches!(
        fresh.with_current(
            current,
            /*now*/ 29,
            |_| panic!("pre-verification consumer reached")
        ),
        Err(ArtifactSelectionError::SelectionContext)
    ));
    let mut longer_signed = signed;
    longer_signed.expires_at = 90;
    longer_signed.signature = fixture
        .selector_key
        .sign(&longer_signed.signing_bytes())
        .to_bytes();
    let mut fresh = load_initial(
        &fixture,
        &longer_signed,
        /*verified_at*/ 30,
        /*now*/ 30,
    )
    .fixture("selection outlives CURRENT");
    let (current, _) = fixture.current();
    assert!(matches!(
        fresh.with_current(
            current,
            /*now*/ 81,
            |_| panic!("expired CURRENT consumer reached")
        ),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::CurrentValidity
        ))
    ));
}

#[test]
fn newly_authenticated_current_cannot_substitute_the_original_owner_trust() {
    let bytes = material();
    let mut fixture = Fixture::new(&bytes, manifest(&bytes));
    let signed = signed_for(&fixture);
    let mut loaded =
        load_initial(&fixture, &signed, /*verified_at*/ 30, /*now*/ 30).fixture("initial");
    let (original_current, snapshot) = fixture.current();
    let selected = fixture
        .selector
        .verify(&signed, &original_current, /*now*/ 30)
        .fixture("original selection");
    fixture.owner_trust.head_signers[0].expires_at = 99;
    let (other_trust, _) = fixture.current();
    assert!(matches!(
        loaded.with_current(
            other_trust,
            /*now*/ 31,
            |_| panic!("substituted owner reached")
        ),
        Err(ArtifactSelectionError::OwnerTrustMismatch)
    ));
    let (other_trust, _) = fixture.current();
    assert!(matches!(
        selected.load_initial_smollm_material(
            File::open(snapshot).fixture("original snapshot"),
            File::open(fixture.root.join("payload")).fixture("original payload"),
            other_trust,
            /*now*/ 30,
        ),
        Err(ArtifactSelectionError::OwnerTrustMismatch)
    ));
}

#[test]
fn old_trained_profile_null_bytes_and_null_signature_cannot_make_typed_material() {
    let bytes = b"old trained bytes";
    let mut old_manifest = manifest(bytes);
    old_manifest.compatibility_digest = digest("existing trained profile");
    old_manifest.generation = Generation::new(2).fixture("trained generation");
    let fixture = Fixture::new(bytes, old_manifest);
    fixture
        .load()
        .fixture("original generic trained behavior remains");
    assert!(matches!(
        load_initial(
            &fixture,
            &signed_for(&fixture),
            /*verified_at*/ 30,
            /*now*/ 30
        ),
        Err(ArtifactSelectionError::InitialGenesisMaterial)
    ));

    let fixture = Fixture::new(b"null", manifest(b"null"));
    assert!(matches!(
        load_initial(
            &fixture,
            &signed_for(&fixture),
            /*verified_at*/ 30,
            /*now*/ 30
        ),
        Err(ArtifactSelectionError::InitialGenesisMaterial)
    ));
    let bytes = material();
    let fixture = Fixture::new(&bytes, manifest(&bytes));
    let mut signed = signed_for(&fixture);
    signed.signature = [0; 64];
    assert!(matches!(
        load_initial(&fixture, &signed, /*verified_at*/ 30, /*now*/ 30),
        Err(ArtifactSelectionError::InvalidSignature)
    ));
}

#[test]
fn original_files_are_checked_again_and_cached_panic_is_sticky() {
    let bytes = material();
    let fixture = Fixture::new(&bytes, manifest(&bytes));
    let signed = signed_for(&fixture);
    let mut loaded =
        load_initial(&fixture, &signed, /*verified_at*/ 30, /*now*/ 30).fixture("initial");
    let (current, _) = fixture.current();
    let unwind = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _ = loaded.with_current(
            current,
            /*now*/ 31,
            |_| panic!("bounded consumer panic"),
        );
    }));
    assert!(unwind.is_err());
    let (current, _) = fixture.current();
    assert!(matches!(
        loaded.with_current(current, /*now*/ 31, |_| ()),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Unavailable
        ))
    ));
    fs::write(fixture.root.join("payload"), b"null")
        .fixture("replace stored payload with null control");
    assert!(matches!(
        load_initial(&fixture, &signed, /*verified_at*/ 31, /*now*/ 31),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Storage(_)
        ))
    ));
}

#[test]
fn typed_material_cannot_bypass_actual_positive_zero_or_snapshot_bytes() {
    let mut bytes = material();
    let start = 8 + HEADER.len();
    bytes[start..start + 4].copy_from_slice(&(-0_f32).to_le_bytes());
    let fixture = Fixture::new(&bytes, manifest(&bytes));
    assert!(matches!(
        load_initial(
            &fixture,
            &signed_for(&fixture),
            /*verified_at*/ 30,
            /*now*/ 30
        ),
        Err(ArtifactSelectionError::InitialGenesisMaterial)
    ));

    let bytes = material();
    let fixture = Fixture::new(&bytes, manifest(&bytes));
    let (current, snapshot) = fixture.current();
    let selected = fixture
        .selector
        .verify(&fixture.signed(&current), &current, /*now*/ 30)
        .fixture("actual original selection");
    fs::write(&snapshot, b"null").fixture("null actual CURRENT snapshot control");
    let (fresh_current, _) = fixture.current();
    assert!(matches!(
        selected.load_initial_smollm_material(
            File::open(snapshot).fixture("null original snapshot"),
            File::open(fixture.root.join("payload")).fixture("actual original payload"),
            fresh_current,
            /*now*/ 30,
        ),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Storage(_)
        ))
    ));
}
