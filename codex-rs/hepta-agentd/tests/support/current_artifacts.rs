#![allow(clippy::unwrap_used)]
//! Test-only keys around the real durable artifact owner and independent selector.
use super::support::digest;
use super::support::id;
use codex_hepta_bellman_operator::TabularOperatorArtifactV1;
use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

pub(super) struct Artifacts {
    pub(super) owner: Arc<Mutex<LearningArtifactOwnerHost>>,
    pub(super) root: PathBuf,
    pub(super) selector: ArtifactSelectionVerifierV1,
    withdrawals: DatasetWithdrawalRegistry,
}

fn owner_trust(scope: Digest32) -> ArtifactOwnerTrustV1 {
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("artifact-owner"),
        verifying_key: SigningKey::from_bytes(&[9; 32]).verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 10,
        valid_from: 1,
        expires_at: 1000,
        revoked_at: None,
    };
    ArtifactOwnerTrustV1 {
        registry_id: id("terminal-artifacts"),
        withdrawal_scope_digest: scope,
        minimum_registry_generation: Generation::new(1).unwrap(),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    }
}

impl Artifacts {
    pub(super) fn open(root: &Path, required: Option<SignedCurrentArtifactHeadV1>) -> Self {
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
            authority_domain_id: id("dataset-authority"),
            registry_id: id("dataset-withdrawals"),
            scope_id: id("terminal-scope"),
        });
        let scope = withdrawals.scope_digest().unwrap();
        let trust = owner_trust(scope);
        let owner_key = SigningKey::from_bytes(&[9; 32]);
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("terminal-writer-lease"),
            producer_id: id("operator.native.owner"),
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: scope,
            signer_id: id("artifact-owner"),
            signing_key_digest: Digest32::of_bytes(&owner_key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: 10,
            expires_at: 1000,
            signature: [0; 64],
        };
        lease.signature = owner_key.sign(&lease.signing_bytes()).to_bytes();
        let selector = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: trust.registry_id.clone(),
                withdrawal_scope_digest: scope,
                minimum_authority_epoch: 1,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id("independent-selector"),
                    verifying_key: SigningKey::from_bytes(&[41; 32]).verifying_key().to_bytes(),
                    minimum_authority_epoch: 1,
                    maximum_authority_epoch: 10,
                    valid_from: 1,
                    expires_at: 1000,
                    revoked_at: None,
                }],
            },
            &trust,
        )
        .unwrap();
        let owner = match required {
            Some(head) => LearningArtifactOwnerHost::open_with_required_current_head(
                root, trust, lease, head, 50,
            ),
            None => LearningArtifactOwnerHost::open(root, trust, lease, 50),
        }
        .unwrap();
        Self {
            owner: Arc::new(Mutex::new(owner)),
            selector,
            withdrawals,
            root: root.to_path_buf(),
        }
    }

    fn sign_head(
        &self,
        previous: Digest32,
        next: Digest32,
        generation: Generation,
    ) -> SignedCurrentArtifactHeadV1 {
        let key = SigningKey::from_bytes(&[9; 32]);
        let mut signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: self.withdrawals.scope_digest().unwrap(),
            binding: digest("terminal-artifact-store"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("terminal-artifacts"),
                generation,
                head_digest: next,
                predecessor_head_digest: previous,
                authority_epoch: 1,
                signer_id: id("artifact-owner"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: 1000,
            },
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        signed
    }

    pub(super) fn publish(
        &self,
        artifact: &TabularOperatorArtifactV1,
        bytes: &[u8],
    ) -> SignedArtifactSelectionV1 {
        self.publish_with_manifest(artifact, bytes, |_| {})
    }

    pub(super) fn publish_with_manifest(
        &self,
        artifact: &TabularOperatorArtifactV1,
        bytes: &[u8],
        change: impl FnOnce(&mut LearningArtifactManifestV2),
    ) -> SignedArtifactSelectionV1 {
        let owner = self.owner.lock().unwrap();
        let mut registry = owner.recover_current_registry(50).unwrap();
        let previous = registry.snapshot().head_digest;
        let generation = owner
            .discover_current_head(50)
            .unwrap()
            .map_or(Generation::new(1).unwrap(), |h| {
                h.signed.witness.generation.next().unwrap()
            });
        let mut manifest = LearningArtifactManifestV2 {
            artifact_id: artifact.artifact_id.clone(),
            kind: ArtifactKind::Policy,
            generation: artifact.generation,
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![artifact.dataset_digest],
            lineage_digests: vec![artifact.artifact_digest],
            predecessor_ids: vec![],
            rollback_predecessor: None,
            bytes_digest: Digest32::of_bytes(bytes),
            encoded_size_bytes: bytes.len() as u64,
            training_code_digest: digest("terminal-cell-code"),
            runtime_tuple_digest: digest("native-read-only-profile"),
            device_profile_digest: digest("test-host"),
            objective_class_digest: artifact.objective_digest,
            compatibility_digest: artifact.training_profile_digest,
            schema_profile_digest: digest("terminal-recovery-bundle-v1"),
            normalization_digest: digest("reward-units"),
            producer_id: artifact.producer_id.clone(),
            created_at: 20,
            expires_at: 1000,
        };
        change(&mut manifest);
        let admission = admit_manifest_at_withdrawal_head_v3(
            &self.withdrawals,
            self.withdrawals.head_digest(),
            manifest,
            50,
        )
        .unwrap();
        let mut tx = owner
            .begin_publication(
                id(&format!("publish.{}", artifact.generation.get())),
                admission,
                &self.withdrawals,
                &registry,
                previous,
                50,
            )
            .unwrap();
        owner
            .stage_compatibility_registration(&tx, &mut registry, 50)
            .unwrap();
        owner
            .ensure_payload_durable(&mut tx, &registry, bytes, 50)
            .unwrap();
        owner
            .ensure_registry_durable(
                &mut tx,
                &registry,
                &self.withdrawals,
                digest("terminal-artifact-store"),
                50,
            )
            .unwrap();
        let signed = self.sign_head(previous, registry.snapshot().head_digest, generation);
        owner
            .ensure_witness_durable(&mut tx, &signed, &self.withdrawals, 50)
            .unwrap();
        owner.acknowledge(&mut tx, &self.withdrawals, 50).unwrap();
        drop(owner);
        self.select(&artifact.artifact_id)
    }

    pub(super) fn select(&self, artifact: &StableId) -> SignedArtifactSelectionV1 {
        let owner = self.owner.lock().unwrap();
        let current = owner.current_registry_view(50).unwrap();
        let registry = owner.recover_current_registry(50).unwrap();
        let m = registry.manifest(artifact).unwrap();
        let key = SigningKey::from_bytes(&[41; 32]);
        let mut selection = SignedArtifactSelectionV1 {
            selection_id: id(&format!("selected.{}", current.receipt().head_digest)),
            artifact_id: m.artifact_id.clone(),
            registry_id: id("terminal-artifacts"),
            withdrawal_scope_digest: self.withdrawals.scope_digest().unwrap(),
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
            selector_credential_digest: digest("selector-credential"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: 20,
            expires_at: 1000,
            signature: [0; 64],
        };
        selection.signature = key.sign(&selection.signing_bytes()).to_bytes();
        selection
    }

    pub(super) fn head(&self) -> SignedCurrentArtifactHeadV1 {
        self.owner
            .lock()
            .unwrap()
            .discover_current_head(50)
            .unwrap()
            .unwrap()
            .signed
    }

    pub(super) fn revoke(&self, artifact: &StableId) {
        let mut owner = self.owner.lock().unwrap();
        let current = owner.discover_current_head(50).unwrap().unwrap();
        let mut registry = owner.recover_current_registry(50).unwrap();
        let change = StateChange {
            event_id: id(&format!("revoke.{artifact}")),
            artifact_id: artifact.clone(),
            evaluator_id: id("artifact-owner"),
            reason_digest: digest("independent-review"),
        };
        registry
            .append(ArtifactEvent::Revoke(change.clone()))
            .unwrap();
        let signed = self.sign_head(
            current.signed.witness.head_digest,
            registry.snapshot().head_digest,
            current.signed.witness.generation.next().unwrap(),
        );
        let receipt = owner
            .publish_revocation(change.clone(), &signed, 50)
            .unwrap();
        assert_eq!(
            owner.publish_revocation(change, &signed, 50).unwrap(),
            receipt
        );
        assert!(
            !owner
                .recover_current_registry(50)
                .unwrap()
                .is_eligible(artifact)
        );
    }

    pub(super) fn payload_path(&self, selection: &SignedArtifactSelectionV1) -> PathBuf {
        self.root.join("payloads").join(format!(
            "{}-{}.bin",
            selection.artifact_id, selection.content_digest
        ))
    }
}
