use super::*;
use crate::*;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

pub(super) fn must<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture: {error:?}"),
    }
}
pub(super) fn id(value: &str) -> StableId {
    must(StableId::new(value))
}
pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub(super) fn decode(bytes: &[u8], _: &ArtifactManifest) -> Result<u64, std::io::Error> {
    Ok(u64::from_be_bytes(
        bytes
            .try_into()
            .map_err(|_| std::io::ErrorKind::InvalidData)?,
    ))
}

pub(super) struct Snapshot {
    pub registry: ArtifactRegistry,
    pub receipt: RegistrySnapshotReceipt,
    pub path: PathBuf,
}
pub(super) struct Fixture {
    pub root: PathBuf,
    owner_key: SigningKey,
    owner_trust: ArtifactOwnerTrustV1,
    selector_key: SigningKey,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
impl Fixture {
    pub fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(1);
        let root = std::env::temp_dir().join(format!(
            "hepta-typed-v5-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        must(fs::create_dir(&root));
        let owner_key = SigningKey::from_bytes(&[71; 32]);
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("owner"),
            verifying_key: owner_key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: 1,
            expires_at: 100,
            revoked_at: None,
        };
        let owner_trust = ArtifactOwnerTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: digest("scope"),
            minimum_registry_generation: must(Generation::new(1)),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        };
        Self {
            root,
            owner_key,
            owner_trust,
            selector_key: SigningKey::from_bytes(&[72; 32]),
        }
    }
    pub fn add(
        &self,
        registry: &mut ArtifactRegistry,
        name: &str,
        previous: Option<&str>,
        value: u64,
    ) {
        let payload = value.to_be_bytes();
        let manifest = ArtifactManifest {
            artifact_id: id(name),
            kind: ArtifactKind::Parameters,
            generation: must(Generation::new(if previous.is_some() { 2 } else { 1 })),
            predecessor_id: previous.map(id),
            content_digest: Digest32::of_bytes(&payload),
            objective_digest: digest("objective"),
            support_digest: digest(name),
            producer_id: id("trainer"),
            compatibility_digest: digest("typed-u64"),
            encoded_size_bytes: 8,
        };
        must(registry.append(ArtifactEvent::Register {
            event_id: id(&format!("register-{name}")),
            manifest,
        }));
        must(write_candidate_payload_beneath(
            &self.root,
            format!("{name}.bin"),
            registry,
            &id(name),
            &payload,
        ));
    }
    pub fn save(&self, registry: &ArtifactRegistry, name: &str) -> Snapshot {
        let path = self.root.join(name);
        let receipt = must(write_registry_snapshot_beneath(
            &self.root,
            name,
            registry,
            digest("storage"),
        ));
        Snapshot {
            registry: registry.clone(),
            receipt,
            path,
        }
    }
    pub fn view(&self, snapshot: &Snapshot) -> VerifiedCurrentRegistryViewV1 {
        let previous = snapshot
            .registry
            .records()
            .last()
            .map_or(Digest32::ZERO, |row| row.predecessor_chain_digest);
        let generation = must(Generation::new(snapshot.receipt.records as u64));
        let mut signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: digest("scope"),
            binding: digest("storage"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("registry"),
                generation,
                head_digest: snapshot.receipt.head_digest,
                predecessor_head_digest: previous,
                authority_epoch: 1,
                signer_id: id("owner"),
                signing_key_digest: Digest32::of_bytes(&self.owner_key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: 100,
            },
            signature: [0; 64],
        };
        signed.signature = self.owner_key.sign(&signed.signing_bytes()).to_bytes();
        let verifier = must(ArtifactOwnerVerifierV1::new(self.owner_trust.clone()));
        must(verifier.verify_current_registry_view(
            must(File::open(&snapshot.path)),
            snapshot.receipt,
            &signed,
            &RegistryHeadRequirementV1 {
                registry_id: id("registry"),
                minimum_generation: generation,
                expected_predecessor_head_digest: previous,
                minimum_authority_epoch: 1,
                now: 20,
            },
        ))
    }
    pub fn selection(&self, snapshot: &Snapshot, name: &str) -> VerifiedArtifactSelectionV1 {
        let current = self.view(snapshot);
        let manifest = match snapshot.registry.manifest(&id(name)) {
            Some(value) => value,
            None => panic!("fixture manifest"),
        };
        let mut signed = SignedArtifactSelectionV1 {
            selection_id: id(&format!("select-{name}")),
            artifact_id: manifest.artifact_id.clone(),
            registry_id: id("registry"),
            withdrawal_scope_digest: digest("scope"),
            registry_head_digest: current.receipt().head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: manifest.predecessor_id.clone(),
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: id("selector"),
            selector_credential_digest: digest("selector-credential"),
            signing_key_digest: Digest32::of_bytes(&self.selector_key.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: 20,
            expires_at: 80,
            signature: [0; 64],
        };
        signed.signature = self.selector_key.sign(&signed.signing_bytes()).to_bytes();
        let verifier = must(ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: id("registry"),
                withdrawal_scope_digest: digest("scope"),
                minimum_authority_epoch: 1,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id("selector"),
                    verifying_key: self.selector_key.verifying_key().to_bytes(),
                    minimum_authority_epoch: 1,
                    maximum_authority_epoch: 1,
                    valid_from: 1,
                    expires_at: 100,
                    revoked_at: None,
                }],
            },
            &self.owner_trust,
        ));
        must(verifier.verify(&signed, &current, 20))
    }
    pub fn payload(&self, name: &str) -> File {
        must(File::open(self.root.join(format!("{name}.bin"))))
    }
    pub fn load(&self, snapshot: &Snapshot, name: &str) -> TypedSelectedCandidateV5<u64> {
        must(TypedSelectedCandidateV5::load(
            must(File::open(&snapshot.path)),
            self.payload(name),
            self.selection(snapshot, name),
            self.view(snapshot),
            digest("typed-u64"),
            decode,
        ))
    }
}
