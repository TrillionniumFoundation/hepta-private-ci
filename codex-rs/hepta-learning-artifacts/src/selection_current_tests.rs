use std::fs;
use std::fs::File;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactOwnerVerifierV1;
use crate::ArtifactRegistry;
use crate::ArtifactSelectionTrustV1;
use crate::CreateOnlyArtifactFile;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessV1;
use crate::RegistrySnapshotReceipt;
use crate::SignedCurrentArtifactHeadV1;
use crate::StateChange;
use crate::TrustedArtifactSelectorV1;
use crate::TrustedArtifactSignerV1;
use crate::test_support::FixtureValue;
use crate::write_candidate_payload;
use crate::write_registry_snapshot;

static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(/*v*/ 0);

fn id(value: &str) -> StableId {
    StableId::new(value).fixture("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct Fixture {
    root: PathBuf,
    registry: ArtifactRegistry,
    receipt: RegistrySnapshotReceipt,
    owner_trust: ArtifactOwnerTrustV1,
    selection_trust: ArtifactSelectionTrustV1,
    signed: SignedArtifactSelectionV1,
}

impl Fixture {
    fn new(revoked_at: Option<u64>) -> Self {
        let sequence = NEXT_DIRECTORY.fetch_add(/*val*/ 1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-selected-current-{}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&root).fixture("create fixture directory");
        let owner_key = SigningKey::from_bytes(&[12; 32]);
        let selector_key = SigningKey::from_bytes(&[13; 32]);
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("owner"),
            verifying_key: owner_key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 9,
            valid_from: 1,
            expires_at: 1_000,
            revoked_at: None,
        };
        let owner_trust = ArtifactOwnerTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: digest("scope"),
            minimum_registry_generation: Generation::new(/*value*/ 1).fixture("generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        };
        let selection_trust = ArtifactSelectionTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: digest("scope"),
            minimum_authority_epoch: 1,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id: id("selector"),
                verifying_key: selector_key.verifying_key().to_bytes(),
                minimum_authority_epoch: 1,
                maximum_authority_epoch: 9,
                valid_from: 1,
                expires_at: 1_000,
                revoked_at,
            }],
        };
        let manifest = ArtifactManifest {
            artifact_id: id("rule-checkpoint"),
            kind: ArtifactKind::Policy,
            generation: Generation::new(/*value*/ 1).fixture("generation"),
            predecessor_id: None,
            content_digest: digest("checkpoint"),
            objective_digest: digest("objective"),
            support_digest: digest("support"),
            producer_id: id("producer"),
            compatibility_digest: digest("compatibility"),
            encoded_size_bytes: 10,
        };
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("register"),
                manifest: manifest.clone(),
            })
            .fixture("register candidate");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(root.join("snapshot")).fixture("create snapshot"),
            &registry,
            digest("binding"),
        )
        .fixture("write snapshot");
        write_candidate_payload(
            CreateOnlyArtifactFile::create(root.join("payload")).fixture("create payload"),
            &registry,
            &manifest.artifact_id,
            b"checkpoint",
        )
        .fixture("write payload");
        let current = Self::authenticate(&root, receipt, &owner_trust);
        let mut signed = SignedArtifactSelectionV1 {
            selection_id: id("selection"),
            artifact_id: manifest.artifact_id,
            registry_id: id("registry"),
            withdrawal_scope_digest: digest("scope"),
            registry_head_digest: receipt.head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: None,
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: id("selector"),
            selector_credential_digest: digest("selector-credential"),
            signing_key_digest: Digest32::of_bytes(&selector_key.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: 20,
            expires_at: 80,
            signature: [0; 64],
        };
        signed.signature = selector_key.sign(&signed.signing_bytes()).to_bytes();
        Self {
            root,
            registry,
            receipt,
            owner_trust,
            selection_trust,
            signed,
        }
    }

    fn authenticate(
        root: &std::path::Path,
        receipt: RegistrySnapshotReceipt,
        trust: &ArtifactOwnerTrustV1,
    ) -> VerifiedCurrentRegistryViewV1 {
        let key = SigningKey::from_bytes(&[12; 32]);
        let mut signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: trust.withdrawal_scope_digest,
            binding: receipt.binding,
            witness: RegistryHeadWitnessV1 {
                registry_id: trust.registry_id.clone(),
                generation: Generation::new(receipt.records as u64).fixture("generation"),
                head_digest: receipt.head_digest,
                predecessor_head_digest: Digest32::ZERO,
                authority_epoch: trust.minimum_authority_epoch,
                signer_id: id("owner"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: 1_000,
            },
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        ArtifactOwnerVerifierV1::new(trust.clone())
            .fixture("owner verifier")
            .verify_current_registry_view(
                File::open(root.join("snapshot")).fixture("open snapshot"),
                receipt,
                &signed,
                &RegistryHeadRequirementV1 {
                    registry_id: trust.registry_id.clone(),
                    minimum_generation: signed.witness.generation,
                    expected_predecessor_head_digest: Digest32::ZERO,
                    minimum_authority_epoch: trust.minimum_authority_epoch,
                    now: 20,
                },
            )
            .fixture("authenticate CURRENT")
    }

    fn current(&self) -> VerifiedCurrentRegistryViewV1 {
        Self::authenticate(&self.root, self.receipt, &self.owner_trust)
    }

    fn load(&self) -> RevalidatingSelectedCandidateV1 {
        RevalidatingSelectedCandidateV1::load(
            ArtifactSelectionVerifierV1::new(self.selection_trust.clone(), &self.owner_trust)
                .fixture("selection verifier"),
            self.signed.clone(),
            self.current(),
            /*now*/ 20,
            File::open(self.root.join("snapshot")).fixture("open snapshot"),
            File::open(self.root.join("payload")).fixture("open payload"),
        )
        .fixture("load selected candidate")
    }

    fn revoked_current(&mut self) -> VerifiedCurrentRegistryViewV1 {
        self.registry
            .append(ArtifactEvent::Revoke(StateChange {
                event_id: id("revoke"),
                artifact_id: id("rule-checkpoint"),
                evaluator_id: id("withdrawal-owner"),
                reason_digest: digest("withdrawal"),
            }))
            .fixture("revoke candidate");
        fs::remove_file(self.root.join("snapshot")).fixture("replace fixture snapshot");
        self.receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(self.root.join("snapshot")).fixture("create snapshot"),
            &self.registry,
            digest("binding"),
        )
        .fixture("write revoked snapshot");
        self.current()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn selected_current_revalidates_and_consumes_exact_payload() {
    let fixture = Fixture::new(/*revoked_at*/ None);
    let mut candidate = fixture.load();
    assert_eq!(candidate.artifact_id(), &fixture.signed.artifact_id);
    assert_eq!(
        candidate.spec().manifest.content_digest,
        digest("checkpoint")
    );
    for now in [20, 21] {
        assert_eq!(
            candidate
                .with_current(fixture.current(), now, <[u8]>::to_vec)
                .fixture("use candidate"),
            b"checkpoint"
        );
    }
}

#[test]
fn selected_current_expiry_permanently_closes_consumer() {
    let fixture = Fixture::new(/*revoked_at*/ None);
    let mut candidate = fixture.load();
    assert!(matches!(
        candidate.with_current(
            fixture.current(),
            /*now*/ 81,
            |_| panic!("expired selection used")
        ),
        Err(ArtifactSelectionError::SelectionContext)
    ));
    assert!(matches!(
        candidate.with_current(
            fixture.current(),
            /*now*/ 21,
            |_| panic!("old selection revived")
        ),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Unavailable
        ))
    ));
}

#[test]
fn selected_current_rechecks_selector_revocation_before_use() {
    let fixture = Fixture::new(Some(25));
    let mut candidate = fixture.load();
    assert_eq!(candidate.valid_until(), 24);
    assert!(matches!(
        candidate.with_current(
            fixture.current(),
            /*now*/ 25,
            |_| panic!("revoked selector used")
        ),
        Err(ArtifactSelectionError::SelectorRevoked)
    ));
}

#[test]
fn selected_current_validity_is_bounded_by_trusted_head_key() {
    let mut fixture = Fixture::new(/*revoked_at*/ None);
    fixture.owner_trust.head_signers[0].expires_at = 30;
    fixture.signed.current_trust_digest = fixture.current().trust_digest();
    fixture.signed.signature = SigningKey::from_bytes(&[13; 32])
        .sign(&fixture.signed.signing_bytes())
        .to_bytes();
    let mut candidate = fixture.load();
    assert_eq!(
        (fixture.current().valid_until(), candidate.valid_until()),
        (30, 30)
    );
    assert_eq!(
        candidate
            .with_current(fixture.current(), /*now*/ 30, <[u8]>::to_vec)
            .fixture("inclusive key expiry boundary"),
        b"checkpoint"
    );
    assert!(matches!(
        candidate.with_current(
            fixture.current(),
            /*now*/ 31,
            |_| panic!("expired head key used")
        ),
        Err(ArtifactSelectionError::SelectionContext)
    ));
}

#[test]
fn selected_current_validity_includes_trusted_selector_expiry() {
    let mut fixture = Fixture::new(/*revoked_at*/ None);
    fixture.selection_trust.selectors[0].expires_at = 30;
    let mut candidate = fixture.load();
    assert_eq!(candidate.valid_until(), 30);
    assert!(matches!(
        candidate.with_current(fixture.current(), /*now*/ 31, |_| panic!(
            "expired selector key used"
        )),
        Err(ArtifactSelectionError::SelectorRevoked)
    ));
}

#[test]
fn selected_current_rejects_owner_trust_substitution() {
    let fixture = Fixture::new(/*revoked_at*/ None);
    let mut candidate = fixture.load();
    let mut trust = fixture.owner_trust.clone();
    trust.minimum_authority_epoch = 2;
    let changed = Fixture::authenticate(&fixture.root, fixture.receipt, &trust);
    assert!(matches!(
        candidate.with_current(
            changed,
            /*now*/ 21,
            |_| panic!("substituted trust used")
        ),
        Err(ArtifactSelectionError::OwnerTrustMismatch)
    ));
}

#[test]
fn selected_current_revocation_requires_fresh_independent_selection() {
    let mut fixture = Fixture::new(/*revoked_at*/ None);
    let mut candidate = fixture.load();
    assert!(matches!(
        candidate.with_current(fixture.revoked_current(), /*now*/ 21, |_| panic!(
            "revoked artifact used"
        )),
        Err(ArtifactSelectionError::CurrentHeadMismatch)
    ));
}

#[test]
fn selected_current_panicking_consumer_cannot_revive_cache() {
    let fixture = Fixture::new(/*revoked_at*/ None);
    let mut candidate = fixture.load();
    assert!(
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _ = candidate.with_current(
                fixture.current(),
                /*now*/ 21,
                |_| panic!("consumer failure"),
            );
        }))
        .is_err()
    );
    assert!(matches!(
        candidate.with_current(
            fixture.current(),
            /*now*/ 21,
            |_| panic!("panicked cache revived")
        ),
        Err(ArtifactSelectionError::Load(
            PinnedCandidateLoadError::Unavailable
        ))
    ));
}
