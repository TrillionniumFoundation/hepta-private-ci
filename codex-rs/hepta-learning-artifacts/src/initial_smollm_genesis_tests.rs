//! Real original CURRENT/selector factories and durable temporary bytes.
//! Fixed test signers establish no production identity, efficacy or loading.

use super::*;
use crate::test_support::FixtureError;
use crate::test_support::FixtureValue;
use crate::*;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::File;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(1);

fn id(value: &str) -> StableId {
    StableId::new(value).fixture("test ID")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn material() -> Vec<u8> {
    let mut bytes = (HEADER.len() as u64).to_le_bytes().to_vec();
    bytes.extend_from_slice(HEADER);
    bytes.resize(bytes.len() + FACTOR_BYTES, 0);
    bytes
}

fn manifest(bytes: &[u8]) -> ArtifactManifest {
    ArtifactManifest {
        artifact_id: id("initial-neural-material"),
        kind: ArtifactKind::Parameters,
        generation: Generation::new(1).fixture("generation"),
        predecessor_id: None,
        content_digest: Digest32::of_bytes(bytes),
        objective_digest: digest("declared-initial-objective"),
        support_digest: digest("non-authorizing-initial-material"),
        producer_id: id("material-producer"),
        compatibility_digest: Digest32::of_bytes(PROFILE),
        encoded_size_bytes: bytes.len() as u64,
    }
}

struct Fixture {
    root: PathBuf,
    registry: ArtifactRegistry,
    manifest: ArtifactManifest,
    owner_key: SigningKey,
    selector_key: SigningKey,
    owner_trust: ArtifactOwnerTrustV1,
    selector: ArtifactSelectionVerifierV1,
}

impl Fixture {
    fn new(bytes: &[u8], manifest: ArtifactManifest) -> Self {
        let root = std::env::temp_dir().join(format!(
            "hepta-initial-genesis-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).fixture("create private test directory");
        let owner_key = SigningKey::from_bytes(&[71; 32]);
        let selector_key = SigningKey::from_bytes(&[72; 32]);
        let owner = TrustedArtifactSignerV1 {
            signer_id: id("original-owner"),
            verifying_key: owner_key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 9,
            valid_from: 1,
            expires_at: 100,
            revoked_at: None,
        };
        let owner_trust = ArtifactOwnerTrustV1 {
            registry_id: id("initial-registry"),
            withdrawal_scope_digest: digest("scope"),
            minimum_registry_generation: Generation::new(1).fixture("registry generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![owner.clone()],
            head_signers: vec![owner],
        };
        let selector = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: owner_trust.registry_id.clone(),
                withdrawal_scope_digest: owner_trust.withdrawal_scope_digest,
                minimum_authority_epoch: 1,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id("independent-selector"),
                    verifying_key: selector_key.verifying_key().to_bytes(),
                    minimum_authority_epoch: 1,
                    maximum_authority_epoch: 9,
                    valid_from: 1,
                    expires_at: 100,
                    revoked_at: None,
                }],
            },
            &owner_trust,
        )
        .fixture("original selector verifier");
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("register-initial"),
                manifest: manifest.clone(),
            })
            .fixture("register actual manifest");
        write_candidate_payload(
            CreateOnlyArtifactFile::create(root.join("payload")).fixture("payload create"),
            &registry,
            &manifest.artifact_id,
            bytes,
        )
        .fixture("durable actual payload");
        Self {
            root,
            registry,
            manifest,
            owner_key,
            selector_key,
            owner_trust,
            selector,
        }
    }

    fn current(&self) -> (VerifiedCurrentRegistryViewV1, PathBuf) {
        let path = self
            .root
            .join(format!("snapshot-{}", NEXT.fetch_add(1, Ordering::Relaxed)));
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&path).fixture("snapshot create"),
            &self.registry,
            digest("storage binding"),
        )
        .fixture("durable actual snapshot");
        let mut signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: self.owner_trust.withdrawal_scope_digest,
            binding: receipt.binding,
            witness: RegistryHeadWitnessV1 {
                registry_id: self.owner_trust.registry_id.clone(),
                generation: Generation::new(receipt.records as u64).fixture("head generation"),
                head_digest: receipt.head_digest,
                predecessor_head_digest: Digest32::ZERO,
                authority_epoch: 1,
                signer_id: id("original-owner"),
                signing_key_digest: Digest32::of_bytes(&self.owner_key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: 80,
            },
            signature: [0; 64],
        };
        signed.signature = self.owner_key.sign(&signed.signing_bytes()).to_bytes();
        let view = ArtifactOwnerVerifierV1::new(self.owner_trust.clone())
            .fixture("original owner verifier")
            .verify_current_registry_view(
                File::open(&path).fixture("snapshot read FD"),
                receipt,
                &signed,
                &RegistryHeadRequirementV1 {
                    registry_id: self.owner_trust.registry_id.clone(),
                    minimum_generation: Generation::new(1).fixture("head floor"),
                    expected_predecessor_head_digest: Digest32::ZERO,
                    minimum_authority_epoch: 1,
                    now: 30,
                },
            )
            .fixture("authenticate CURRENT from actual snapshot");
        (view, path)
    }

    fn signed(&self, current: &VerifiedCurrentRegistryViewV1) -> SignedArtifactSelectionV1 {
        let m = &self.manifest;
        let mut signed = SignedArtifactSelectionV1 {
            selection_id: id("select-exact-initial-material"),
            artifact_id: m.artifact_id.clone(),
            registry_id: self.owner_trust.registry_id.clone(),
            withdrawal_scope_digest: self.owner_trust.withdrawal_scope_digest,
            registry_head_digest: current.receipt().head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: m.kind,
            artifact_generation: m.generation,
            predecessor_id: m.predecessor_id.clone(),
            content_digest: m.content_digest,
            objective_digest: m.objective_digest,
            support_digest: m.support_digest,
            compatibility_digest: m.compatibility_digest,
            encoded_size_bytes: m.encoded_size_bytes,
            selector_id: id("independent-selector"),
            selector_credential_digest: digest("selector credential"),
            signing_key_digest: Digest32::of_bytes(&self.selector_key.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: 20,
            expires_at: 80,
            signature: [0; 64],
        };
        signed.signature = self.selector_key.sign(&signed.signing_bytes()).to_bytes();
        signed
    }

    fn load(&self) -> Result<RevalidatingCandidate, ArtifactSelectionError> {
        let (current, snapshot) = self.current();
        let selected = self
            .selector
            .verify(&self.signed(&current), &current, /*now*/ 30)?;
        assert_eq!(selected.authority(), AuthorityPosture::DENY_ALL);
        load_selected_candidate(
            File::open(snapshot).fixture("snapshot"),
            File::open(self.root.join("payload")).fixture("payload"),
            selected,
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn actual_selected_zero_bytes_revalidate_and_cold_reopen_without_installation_authority() {
    let bytes = material();
    let fixture = Fixture::new(&bytes, manifest(&bytes));
    let mut loaded = fixture.load().fixture("selected initial material");
    let (current, _) = fixture.current();
    assert_eq!(
        loaded
            .with_current(current, /*now*/ 30, Digest32::of_bytes)
            .fixture("actual byte read"),
        Digest32::of_bytes(&bytes)
    );
    drop(loaded);
    let mut recovered = fixture
        .load()
        .fixture("same selection and original stored bytes reopened");
    let (current, _) = fixture.current();
    assert_eq!(
        recovered
            .with_current(current, /*now*/ 30, Digest32::of_bytes)
            .fixture("recovered byte read"),
        Digest32::of_bytes(&bytes)
    );
}

#[test]
fn nonzero_negative_zero_and_nonfinite_factors_are_rejected_after_real_selection() {
    for pattern in [
        1_f32.to_le_bytes(),
        (-0_f32).to_le_bytes(),
        f32::NAN.to_le_bytes(),
        f32::INFINITY.to_le_bytes(),
    ] {
        let mut bytes = material();
        let start = 8 + HEADER.len();
        bytes[start..start + 4].copy_from_slice(&pattern);
        let fixture = Fixture::new(&bytes, manifest(&bytes));
        assert!(matches!(
            fixture.load().fixture_error("forbidden actual factor"),
            ArtifactSelectionError::InitialGenesisMaterial
        ));
    }
}

fn replace_header(from: &str, to: &str) -> Vec<u8> {
    let header = String::from_utf8(HEADER.to_vec()).fixture("fixed UTF8 header");
    assert!(header.contains(from));
    let mut header = header.replacen(from, to, 1).into_bytes();
    header.resize(HEADER.len(), b' ');
    let mut bytes = (header.len() as u64).to_le_bytes().to_vec();
    bytes.extend_from_slice(&header);
    bytes.resize(bytes.len() + FACTOR_BYTES, 0);
    bytes
}

#[test]
fn duplicate_unknown_dtype_shape_offsets_and_profile_header_aliases_are_rejected() {
    let changes = [
        ("\"dtype\":\"F32\"", "\"dtype\":\"F32\",\"dtype\":\"F32\""),
        ("\"dtype\":\"F32\"", "\"dtype\":\"F16\""),
        ("q_proj.A", "q_proj.C"),
        ("[4,576]", "[4,575]"),
        ("[0,9216]", "[0,9215]"),
        ("[0,9216]", "[-1,9216]"),
        ("[0,9216]", "[0,999999999]"),
        ("[9216,18432]", "[0,9216]"),
        ("561414ae", "561414af"),
    ];
    for (from, to) in changes {
        let bytes = replace_header(from, to);
        let fixture = Fixture::new(&bytes, manifest(&bytes));
        assert!(matches!(
            fixture.load().fixture_error("noncanonical actual header"),
            ArtifactSelectionError::InitialGenesisMaterial
        ));
    }
}

#[test]
fn wrong_manifest_generation_kind_and_lengths_cannot_enter_the_new_profile() {
    let bytes = material();
    let mut changed_generation = manifest(&bytes);
    changed_generation.generation = Generation::new(2).fixture("derived generation");
    let mut changed_kind = manifest(&bytes);
    changed_kind.kind = ArtifactKind::Model;
    for changed in [changed_generation, changed_kind] {
        let fixture = Fixture::new(&bytes, changed);
        assert!(matches!(
            fixture.load().fixture_error("manifest shape"),
            ArtifactSelectionError::InitialGenesisMaterial
        ));
    }
    for bytes in [bytes[..bytes.len() - 1].to_vec(), [bytes, vec![0]].concat()] {
        let fixture = Fixture::new(&bytes, manifest(&bytes));
        assert!(matches!(
            fixture.load().fixture_error("actual length"),
            ArtifactSelectionError::InitialGenesisMaterial
        ));
    }
}

#[test]
fn original_selector_refuses_changed_tokenizer_profile_head_role_and_expired_evidence() {
    let bytes = material();
    let fixture = Fixture::new(&bytes, manifest(&bytes));
    let (current, _) = fixture.current();
    for change in ["tokenizer-profile", "head", "producer-role", "expiry"] {
        let mut signed = fixture.signed(&current);
        match change {
            "tokenizer-profile" => {
                signed.compatibility_digest = digest("substituted tokenizer/root profile")
            }
            "head" => signed.registry_head_digest = digest("different CURRENT head"),
            "producer-role" => signed.selector_id = fixture.manifest.producer_id.clone(),
            "expiry" => signed.expires_at = 29,
            _ => unreachable!(),
        }
        signed.signature = fixture
            .selector_key
            .sign(&signed.signing_bytes())
            .to_bytes();
        assert!(
            fixture
                .selector
                .verify(&signed, &current, /*now*/ 30)
                .is_err()
        );
    }
}

#[test]
fn newer_original_current_revocation_denies_the_loaded_initial_bytes() {
    let bytes = material();
    let mut fixture = Fixture::new(&bytes, manifest(&bytes));
    let mut loaded = fixture.load().fixture("initial selected material");
    fixture
        .registry
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("withdraw-initial"),
            artifact_id: fixture.manifest.artifact_id.clone(),
            evaluator_id: id("independent-withdrawal-owner"),
            reason_digest: digest("withdrawal reason"),
        }))
        .fixture("original registry revoke");
    let (current, _) = fixture.current();
    assert_eq!(
        loaded.with_current(current, /*now*/ 30, Digest32::of_bytes),
        Err(PinnedCandidateLoadError::Ineligible)
    );
}

#[test]
fn other_existing_profile_keeps_its_original_selected_loading_semantics() {
    let bytes = b"existing trained or other immutable artifact payload";
    let mut existing = manifest(bytes);
    existing.compatibility_digest = digest("existing compatibility profile");
    existing.generation = Generation::new(2).fixture("existing generation");
    let fixture = Fixture::new(bytes, existing);
    fixture.load().fixture("existing profile remains readable");
}

#[path = "selected_initial_smollm_tests.rs"]
mod selected_tests;
