//! Real signature and file-boundary tests; fixture clocks/keys are not production evidence.
use std::fs::File;
use std::fs::{self};
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::test_support::FixtureValue;
use crate::*;

static NEXT: AtomicU64 = AtomicU64::new(0);
fn id(s: &str) -> StableId {
    StableId::new(s).fixture("id")
}
fn d(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}
struct Fixture {
    root: PathBuf,
    registry: ArtifactRegistry,
    receipt: RegistrySnapshotReceipt,
    owner: ArtifactOwnerTrustV1,
    trust: ArtifactSelectionTrustV1,
    verifier: ArtifactSelectionVerifierV1,
    signed: SignedArtifactSelectionV1,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
impl Fixture {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "hepta-selected-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).fixture("directory");
        let writer = SigningKey::from_bytes(&[12; 32]);
        let selector = SigningKey::from_bytes(&[41; 32]);
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("owner"),
            verifying_key: writer.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 9,
            valid_from: 1,
            expires_at: 100,
            revoked_at: None,
        };
        let owner = ArtifactOwnerTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: d("scope"),
            minimum_registry_generation: Generation::new(1).fixture("generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        };
        let trust = ArtifactSelectionTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: d("scope"),
            minimum_authority_epoch: 4,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id: id("selector"),
                verifying_key: selector.verifying_key().to_bytes(),
                minimum_authority_epoch: 4,
                maximum_authority_epoch: 9,
                valid_from: 10,
                expires_at: 100,
                revoked_at: None,
            }],
        };
        let verifier =
            ArtifactSelectionVerifierV1::new(trust.clone(), &owner).fixture("selector trust");
        let manifest = ArtifactManifest {
            artifact_id: id("parameters"),
            kind: ArtifactKind::Parameters,
            generation: Generation::new(1).fixture("generation"),
            predecessor_id: None,
            content_digest: d("payload"),
            objective_digest: d("objective"),
            support_digest: d("support"),
            producer_id: id("trainer"),
            compatibility_digest: d("base"),
            encoded_size_bytes: 7,
        };
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("register"),
                manifest: manifest.clone(),
            })
            .fixture("register");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(root.join("snapshot")).fixture("snapshot file"),
            &registry,
            d("binding"),
        )
        .fixture("snapshot");
        write_candidate_payload(
            CreateOnlyArtifactFile::create(root.join("payload")).fixture("payload file"),
            &registry,
            &manifest.artifact_id,
            b"payload",
        )
        .fixture("payload");
        let mut signed = SignedArtifactSelectionV1 {
            selection_id: id("selection"),
            artifact_id: manifest.artifact_id.clone(),
            registry_id: id("registry"),
            withdrawal_scope_digest: d("scope"),
            registry_head_digest: receipt.head_digest,
            current_witness_digest: d("witness"),
            current_trust_digest: ArtifactOwnerVerifierV1::new(owner.clone())
                .fixture("owner trust")
                .trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: None,
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: 7,
            selector_id: id("selector"),
            selector_credential_digest: d("selector-credential"),
            signing_key_digest: Digest32::of_bytes(&selector.verifying_key().to_bytes()),
            authority_epoch: 4,
            issued_at: 20,
            expires_at: 80,
            signature: [0; 64],
        };
        signed.signature = selector.sign(&signed.signing_bytes()).to_bytes();
        Self {
            root,
            registry,
            receipt,
            owner,
            trust,
            verifier,
            signed,
        }
    }
    fn current(&self) -> VerifiedCurrentRegistryViewV1 {
        let mut receipt = self.receipt;
        receipt.records = self.registry.records().len();
        receipt.head_digest = self.registry.snapshot().head_digest;
        VerifiedCurrentRegistryViewV1::new(
            receipt,
            self.registry.clone(),
            d("witness"),
            ArtifactOwnerVerifierV1::new(self.owner.clone())
                .fixture("owner")
                .trust_digest(),
        )
    }
    fn load(&self) -> GuardedSelectedCandidateV1 {
        let selected = self
            .verifier
            .verify(&self.signed, &self.current(), 30)
            .fixture("signed selection");
        load_guarded_selected_candidate_v1(
            File::open(self.root.join("snapshot")).fixture("snapshot"),
            File::open(self.root.join("payload")).fixture("payload"),
            selected,
            &self.verifier,
            30,
        )
        .fixture("guarded load")
    }
}

#[test]
fn selection_expiry_closes_a_previously_loaded_payload() {
    let f = Fixture::new();
    let mut cache = f.load();
    assert_eq!(
        cache
            .with_current(&f.verifier, f.current(), 31, <[u8]>::to_vec)
            .fixture("read"),
        b"payload"
    );
    assert!(matches!(
        cache.with_current(&f.verifier, f.current(), 80, |_| panic!("expired read")),
        Err(ArtifactSelectionError::SelectionContext)
    ));
    assert!(matches!(
        cache.with_current(&f.verifier, f.current(), 31, |_| panic!("revived read")),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Unavailable
        ))
    ));
}

#[test]
fn trust_rotation_cannot_reuse_the_old_selected_cache() {
    let f = Fixture::new();
    let mut cache = f.load();
    let mut trust = f.trust.clone();
    trust.selectors[0].revoked_at = Some(32);
    let current = ArtifactSelectionVerifierV1::new(trust, &f.owner).fixture("rotated trust");
    assert!(
        cache
            .with_current(&current, f.current(), 33, |_| panic!("rotated read"))
            .is_err()
    );
    assert!(
        cache
            .with_current(&f.verifier, f.current(), 31, |_| panic!("old trust retry"))
            .is_err()
    );
}

#[test]
fn source_revocation_rejects_the_cached_candidate_and_old_restore() {
    let mut f = Fixture::new();
    let mut cache = f.load();
    let old = f.current();
    f.registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoke"),
            artifact_id: id("parameters"),
            evaluator_id: id("source-owner"),
            reason_digest: d("source withdrawn"),
        }))
        .fixture("revocation");
    assert!(matches!(
        cache.with_current(&f.verifier, f.current(), 32, |_| panic!("revoked read")),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Ineligible
        ))
    ));
    assert!(
        cache
            .with_current(&f.verifier, old, 33, |_| panic!("restored old view"))
            .is_err()
    );
}

#[test]
fn a_panicking_consumer_requires_fresh_selection_and_load() {
    let f = Fixture::new();
    let mut cache = f.load();
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        cache.with_current(&f.verifier, f.current(), 31, |_| panic!("consumer failed"))
    }));
    assert!(outcome.is_err());
    assert!(
        cache
            .with_current(&f.verifier, f.current(), 32, |_| ())
            .is_err()
    );
}

#[test]
fn tampered_signature_and_payload_never_enter_the_consumer() {
    let mut f = Fixture::new();
    f.signed.signature[0] ^= 1;
    assert!(matches!(
        f.verifier.verify(&f.signed, &f.current(), 30),
        Err(ArtifactSelectionError::InvalidSignature)
    ));
    f.signed.signature[0] ^= 1;
    let selected = f
        .verifier
        .verify(&f.signed, &f.current(), 30)
        .fixture("selected");
    fs::write(f.root.join("payload"), b"changed").fixture("tamper");
    assert!(
        load_guarded_selected_candidate_v1(
            File::open(f.root.join("snapshot")).fixture("snapshot"),
            File::open(f.root.join("payload")).fixture("payload"),
            selected,
            &f.verifier,
            30
        )
        .is_err()
    );
}

#[test]
fn a_clock_rollback_cannot_reopen_a_selected_candidate() {
    let f = Fixture::new();
    let mut cache = f.load();
    cache
        .with_current(&f.verifier, f.current(), 60, |_| ())
        .fixture("live read");
    assert!(
        cache
            .with_current(&f.verifier, f.current(), 59, |_| panic!(
                "rolled back clock"
            ))
            .is_err()
    );
    assert!(
        cache
            .with_current(&f.verifier, f.current(), 61, |_| panic!("reopened clock"))
            .is_err()
    );
}


// These fixtures exercise the genuine Artifact Registry and its opaque current
// view TYPE, but Fixture::current is deliberately a test-only constructor.
// Only the real ArtifactOwnerHost's verified signed-head path may create a
// production-current view. No selected-model or runtime grant is produced.
#[cfg(feature = "amcn-epoch-shadow")]
#[test]
fn amcn_artifact_epoch_signed_view_projection_binds_exact_current_head_and_trust() {
    let fixture = Fixture::new();
    let view = fixture.current();
    let first = project_verified_amcn_artifact_epoch_v1(
        &view, view.receipt().head_digest, view.witness_digest(),
        view.trust_digest(),
    ).fixture("read-only current registry projection");
    assert_eq!(first.enrolled_model_and_head_manifests().len(), 1);
    assert!(first.quarantined_model_and_head_manifest_digests().is_empty());
    assert!(!first.production_accepted());
    assert!(!AMCN_OWNER_EPOCH_PRODUCTION_ACCEPTED);
    assert_ne!(first.enrolled_manifest_set_digest(), Digest32::ZERO);
    assert_ne!(first.quarantined_manifest_set_digest(), Digest32::ZERO);

    for (head, witness, trust) in [
        (d("old-registry"), view.witness_digest(), view.trust_digest()),
        (view.receipt().head_digest, d("forged-witness"), view.trust_digest()),
        (view.receipt().head_digest, view.witness_digest(), d("other-trust-root")),
    ] {
        assert!(matches!(
            project_verified_amcn_artifact_epoch_v1(&view, head, witness, trust),
            Err(AmcnOwnerEpochError::CurrentHeadMismatch),
        ));
    }
}

#[cfg(feature = "amcn-epoch-shadow")]
#[test]
fn amcn_artifact_epoch_original_registry_ancestor_quarantine_propagates_to_child() {
    let mut fixture = Fixture::new();
    let ancestor = fixture.registry.manifest(&id("parameters"))
        .expect("registered Head ancestor").clone();
    let derived = ArtifactManifest {
        artifact_id: id("cell-derived-head"),
        predecessor_id: Some(ancestor.artifact_id.clone()),
        generation: Generation::new(2).fixture("derived generation"),
        content_digest: d("derived-parameter-bytes"),
        ..ancestor
    };
    fixture.registry.append(ArtifactEvent::Register {
        event_id: id("derived-registration"),
        manifest: derived.clone(),
    }).fixture("original Registry derived Head registration");
    let before = fixture.current();
    let registered = project_verified_amcn_artifact_epoch_v1(
        &before, before.receipt().head_digest, before.witness_digest(),
        before.trust_digest(),
    ).fixture("two original registered Heads");
    assert_eq!(registered.enrolled_model_and_head_manifests().len(), 2);
    assert!(registered.quarantined_model_and_head_manifest_digests().is_empty());

    fixture.registry.append(ArtifactEvent::Revoke(StateChange {
        event_id: id("withdrawn-source-revoke"),
        artifact_id: id("parameters"),
        evaluator_id: id("independent-source-owner"),
        reason_digest: d("authoritative-dataset-withdrawal"),
    })).fixture("original registry revocation");
    let after = fixture.current();
    let updated = project_verified_amcn_artifact_epoch_v1(
        &after, after.receipt().head_digest, after.witness_digest(),
        after.trust_digest(),
    ).fixture("read original lineage-aware quarantine");
    assert_eq!(registered.enrolled_manifest_set_digest(), updated.enrolled_manifest_set_digest());
    assert_ne!(registered.quarantined_manifest_set_digest(),
               updated.quarantined_manifest_set_digest());
    assert_eq!(updated.quarantined_model_and_head_manifest_digests().len(), 2);
    assert!(!updated.production_accepted());
    // Old view is NOT proof of the newer current head. A required newer
    // external head rejects that stale snapshot without resurrecting a Head.
    assert_eq!(
        project_verified_amcn_artifact_epoch_v1(
            &before, after.receipt().head_digest,
            after.witness_digest(), after.trust_digest(),
        ),
        Err(AmcnOwnerEpochError::CurrentHeadMismatch),
    );
}

#[cfg(feature = "amcn-epoch-shadow")]
#[test]
fn amcn_artifact_epoch_excludes_non_cell_artifact_kinds_from_shared_stem_index() {
    let mut fixture = Fixture::new();
    let mut unrelated = fixture.registry.manifest(&id("parameters"))
        .expect("registered fixture").clone();
    unrelated.artifact_id = id("research-workflow-not-a-Head");
    unrelated.kind = ArtifactKind::Workflow;
    unrelated.predecessor_id = None;
    fixture.registry.append(ArtifactEvent::Register {
        event_id: id("register-unrelated-workflow"),
        manifest: unrelated,
    }).fixture("original registry accepts non-Head artifact");
    let view = fixture.current();
    let projected = project_verified_amcn_artifact_epoch_v1(
        &view, view.receipt().head_digest, view.witness_digest(),
        view.trust_digest(),
    ).fixture("filter by original Artifact kind");
    assert_eq!(projected.enrolled_model_and_head_manifests().len(), 1);
    assert_eq!(projected.enrolled_model_and_head_manifests()[0].0,
               id("parameters"));
}
