use super::*;

use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture ID")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct Fixture {
    directory: TempDir,
    provider: PlasticityCurrentArtifactFilesV1,
    key: SigningKey,
    signed: SignedCurrentArtifactHeadV1,
    artifacts: ArtifactRegistry,
}

impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().expect("fixture directory");
        let mut artifacts = ArtifactRegistry::new();
        artifacts
            .append(ArtifactEvent::Register {
                event_id: id("registered"),
                manifest: ArtifactManifest {
                    artifact_id: id("baseline"),
                    kind: ArtifactKind::Model,
                    generation: Generation::new(1).expect("generation"),
                    predecessor_id: None,
                    content_digest: digest("payload"),
                    objective_digest: digest("objective"),
                    support_digest: digest("dataset"),
                    producer_id: id("model-producer"),
                    compatibility_digest: digest("compatibility"),
                    encoded_size_bytes: 7,
                },
            })
            .expect("register");
        let snapshot_path = directory.path().join("frozen.snapshot");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&snapshot_path).expect("create snapshot"),
            &artifacts,
            digest("binding"),
        )
        .expect("persist snapshot");
        let key = SigningKey::from_bytes(&[55; 32]);
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("independent-artifact-owner"),
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 2,
            valid_from: 1,
            expires_at: 100,
            revoked_at: None,
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: id("registry"),
            withdrawal_scope_digest: digest("withdrawal-scope"),
            minimum_registry_generation: Generation::new(1).expect("minimum generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        };
        let signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: trust.withdrawal_scope_digest,
            binding: receipt.binding,
            witness: RegistryHeadWitnessV1 {
                registry_id: trust.registry_id.clone(),
                generation: Generation::new(1).expect("generation"),
                head_digest: receipt.head_digest,
                predecessor_head_digest: Digest32::ZERO,
                authority_epoch: 1,
                signer_id: id("independent-artifact-owner"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: 90,
            },
            signature: [0; 64],
        };
        let provider = PlasticityCurrentArtifactFilesV1::new(
            snapshot_path,
            directory.path().join("CURRENT"),
            receipt,
            trust,
        )
        .expect("CURRENT provider");
        let mut fixture = Self {
            directory,
            provider,
            key,
            signed,
            artifacts,
        };
        fixture.publish();
        fixture
    }

    fn publish(&mut self) {
        self.signed.signature = self.key.sign(&self.signed.signing_bytes()).to_bytes();
        // Existing native artifact-owner disk format, independently signed.
        let signature = self
            .signed
            .signature
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let witness = &self.signed.witness;
        let bytes = format!(
            "HEPTA-ARTIFACT-CURRENT-HEAD-V1\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{signature}\n",
            self.signed.withdrawal_scope_digest,
            self.signed.binding,
            witness.registry_id,
            witness.generation.get(),
            witness.head_digest,
            witness.predecessor_head_digest,
            witness.authority_epoch,
            witness.signer_id,
            witness.signing_key_digest,
            witness.issued_at,
            witness.expires_at,
        );
        std::fs::write(&self.provider.current_head_path, bytes).expect("publish CURRENT");
    }
}

#[test]
fn independent_native_current_revalidates_exact_frozen_snapshot() {
    let fixture = Fixture::new();
    let view = fixture.provider.current(50).expect("authenticated CURRENT");
    assert_eq!(view.receipt(), fixture.provider.frozen_receipt);
    assert_eq!(
        fixture
            .provider
            .current(51)
            .expect("refresh CURRENT")
            .receipt(),
        view.receipt()
    );
    assert!(fixture.provider.current(91).is_err());
    std::fs::remove_file(&fixture.provider.current_head_path).expect("CURRENT unavailable");
    assert!(fixture.provider.current(51).is_err());
}

#[test]
fn changed_authenticated_current_fences_before_opening_old_snapshot() {
    let mut fixture = Fixture::new();
    fixture
        .artifacts
        .append(ArtifactEvent::Revoke(StateChange {
            event_id: id("revoked"),
            artifact_id: id("baseline"),
            evaluator_id: id("independent-withdrawal-owner"),
            reason_digest: digest("withdrawal"),
        }))
        .expect("revoke independently");
    fixture.signed.witness.predecessor_head_digest = fixture.provider.frozen_receipt.head_digest;
    fixture.signed.witness.head_digest = fixture.artifacts.snapshot().head_digest;
    fixture.signed.witness.generation = Generation::new(2).expect("new generation");
    fixture.publish();
    std::fs::remove_file(&fixture.provider.snapshot_path).expect("old snapshot unavailable");
    assert!(matches!(
        fixture.provider.current(50),
        Err(AgentdError::GenerationFenced(_))
    ));

    let mut bytes = std::fs::read(&fixture.provider.current_head_path).expect("signed CURRENT");
    let signature_byte = bytes.len() - 2;
    bytes[signature_byte] = if bytes[signature_byte] == b'0' {
        b'1'
    } else {
        b'0'
    };
    std::fs::write(&fixture.provider.current_head_path, bytes).expect("tamper CURRENT");
    assert!(matches!(
        fixture.provider.current(50),
        Err(AgentdError::Invalid(_))
    ));
}

#[test]
fn frozen_guard_rejects_different_scope_receipt_and_unavailable_current() {
    let mut fixture = Fixture::new();
    let receipt = fixture.provider.frozen_receipt;
    fixture.signed.binding = digest("another-storage-scope");
    fixture.publish();
    let provider = Arc::new(fixture.provider);
    let mut guard = FrozenPlasticityArtifactsV1::new(provider, receipt, &fixture.artifacts)
        .expect("bind frozen generation");
    assert!(matches!(
        guard.verify(50),
        Err(AgentdError::GenerationFenced(_))
    ));
    std::fs::remove_file(fixture.directory.path().join("CURRENT")).expect("remove CURRENT");
    assert!(guard.verify(50).is_err());
}

#[test]
fn frozen_generation_rejects_a_different_authenticated_owner_with_identical_bytes() {
    struct Views(std::sync::Mutex<std::collections::VecDeque<VerifiedCurrentRegistryViewV1>>);
    impl PlasticityCurrentArtifactsV1 for Views {
        fn current(&self, _now: u64) -> Result<VerifiedCurrentRegistryViewV1, AgentdError> {
            self.0
                .lock()
                .expect("view queue")
                .pop_front()
                .ok_or_else(|| AgentdError::Invalid("no CURRENT".to_string()))
        }
    }
    let first = Fixture::new();
    let mut foreign = Fixture::new();
    foreign.provider.trust.registry_id = id("foreign-registry");
    foreign.provider.verifier =
        ArtifactOwnerVerifierV1::new(foreign.provider.trust.clone()).expect("foreign verifier");
    foreign.signed.witness.registry_id = id("foreign-registry");
    foreign.publish();
    let a = first.provider.current(50).expect("owner A current");
    let b = foreign.provider.current(50).expect("owner B current");
    assert_eq!(a.receipt(), b.receipt());
    assert_ne!(a.trust_digest(), b.trust_digest());
    let provider = Arc::new(Views(std::sync::Mutex::new(
        std::collections::VecDeque::from([a, b]),
    )));
    let mut guard =
        FrozenPlasticityArtifactsV1::new(provider, first.provider.frozen_receipt, &first.artifacts)
            .expect("frozen generation");
    guard.verify(50).expect("initial owner");
    assert!(matches!(
        guard.verify(50),
        Err(AgentdError::GenerationFenced(_))
    ));
}
