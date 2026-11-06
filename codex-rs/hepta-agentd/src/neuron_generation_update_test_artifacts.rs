//! Actual immutable publication and independent selection with test issuer keys.
//! The Model payload is a synthetic contract fixture, not trained qualification.

use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::files::NOW;
use crate::neuron_generation_update_selection::AgentdGenerationSelectionFilesV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

pub(super) struct ArtifactFiles {
    pub(super) owner: Arc<Mutex<LearningArtifactOwnerService>>,
    root: PathBuf,
    key: SigningKey,
    selector: SigningKey,
    selected: SignedArtifactSelectionV1,
    verifier: ArtifactSelectionVerifierV1,
}

impl ArtifactFiles {
    pub(super) fn new(root: &Path, manifest: &CellBackendManifestV2) -> anyhow::Result<Self> {
        let key = SigningKey::from_bytes(&[61; 32]);
        let selector = SigningKey::from_bytes(&[62; 32]);
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
            authority_domain_id: id("test-dataset-authority")?,
            registry_id: id("test-withdrawals")?,
            scope_id: id("test-cell-sources")?,
        });
        let scope = withdrawals.scope_digest().ok_or_else(|| anyhow::anyhow!("missing scope"))?;
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("test-artifact-authority")?,
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: 1,
            expires_at: 10_000,
            revoked_at: None,
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: id("test-learning-artifacts")?,
            withdrawal_scope_digest: scope,
            minimum_registry_generation: Generation::new(1)?,
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("test-writer-lease")?,
            producer_id: id("test-producer")?,
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: scope,
            signer_id: id("test-artifact-authority")?,
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: 1,
            expires_at: 10_000,
            signature: [0; 64],
        };
        lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
        let mut owner = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            root: root.to_path_buf(),
            trust: trust.clone(),
            writer_lease: lease,
            required_current_head: None,
            withdrawal_registry: withdrawals,
            storage_binding: Digest32::of_bytes(b"test-artifact-storage"),
            now: NOW,
        })?;
        let candidate = publish_candidate(&mut owner, manifest, &key, "selected-candidate")?;
        let current = owner.current_registry_view(NOW)?;
        let verifier = ArtifactSelectionVerifierV1::new(ArtifactSelectionTrustV1 {
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: scope,
            minimum_authority_epoch: 1,
            selectors: vec![TrustedArtifactSelectorV1 {
                selector_id: id("test-independent-selector")?,
                verifying_key: selector.verifying_key().to_bytes(),
                minimum_authority_epoch: 1,
                maximum_authority_epoch: 1,
                valid_from: 1,
                expires_at: 10_000,
                revoked_at: None,
            }],
        }, &trust)?;
        let mut selected = SignedArtifactSelectionV1 {
            selection_id: id("test-generation-selection")?,
            artifact_id: candidate.artifact_id,
            registry_id: trust.registry_id,
            withdrawal_scope_digest: scope,
            registry_head_digest: current.receipt().head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: candidate.kind,
            artifact_generation: candidate.generation,
            predecessor_id: candidate.predecessor_id,
            content_digest: candidate.content_digest,
            objective_digest: candidate.objective_digest,
            support_digest: candidate.support_digest,
            compatibility_digest: candidate.compatibility_digest,
            encoded_size_bytes: candidate.encoded_size_bytes,
            selector_id: id("test-independent-selector")?,
            selector_credential_digest: Digest32::of_bytes(b"test-selector-credential"),
            signing_key_digest: Digest32::of_bytes(&selector.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: NOW,
            expires_at: 2_000,
            signature: [0; 64],
        };
        selected.signature = selector.sign(&selected.signing_bytes()).to_bytes();
        Ok(Self { owner: Arc::new(Mutex::new(owner)), root: root.to_path_buf(), key, selector, selected, verifier })
    }

    pub(super) fn selection(&self, now: u64) -> anyhow::Result<AgentdSelectedGenerationV1> {
        let owner = self.owner.lock().map_err(|_| anyhow::anyhow!("artifact owner poisoned"))?;
        load_selection(&owner, &self.root, self.verifier.clone(), self.selected.clone(), now)
    }

    pub(super) fn publish_next_selection(&self, manifest: &CellBackendManifestV2, name: &str, now: u64) -> anyhow::Result<AgentdSelectedGenerationV1> {
        let mut owner = self.owner.lock().map_err(|_| anyhow::anyhow!("artifact owner poisoned"))?;
        let candidate = publish_candidate(&mut owner, manifest, &self.key, name)?;
        let current = owner.current_registry_view(now)?;
        let mut selected = self.selected.clone();
        selected.selection_id = id(&format!("selection-{name}"))?;
        selected.artifact_id = candidate.artifact_id;
        selected.registry_head_digest = current.receipt().head_digest;
        selected.current_witness_digest = current.witness_digest();
        selected.current_trust_digest = current.trust_digest();
        selected.artifact_kind = candidate.kind;
        selected.artifact_generation = candidate.generation;
        selected.predecessor_id = candidate.predecessor_id;
        selected.content_digest = candidate.content_digest;
        selected.objective_digest = candidate.objective_digest;
        selected.support_digest = candidate.support_digest;
        selected.compatibility_digest = candidate.compatibility_digest;
        selected.encoded_size_bytes = candidate.encoded_size_bytes;
        selected.issued_at = now;
        selected.expires_at = now + 1_000;
        selected.signature = self.selector.sign(&selected.signing_bytes()).to_bytes();
        load_selection(&owner, &self.root, self.verifier.clone(), selected, now)
    }

    pub(super) fn advance_current(&self, manifest: &CellBackendManifestV2) -> anyhow::Result<()> {
        let mut owner = self.owner.lock().map_err(|_| anyhow::anyhow!("artifact owner poisoned"))?;
        publish_candidate(&mut owner, manifest, &self.key, "new-current-candidate")?;
        Ok(())
    }

    pub(super) fn withdraw(&self) -> anyhow::Result<()> {
        let mut owner = self.owner.lock().map_err(|_| anyhow::anyhow!("artifact owner poisoned"))?;
        let mut withdrawals = owner.withdrawal_registry().clone();
        withdrawals.append(DatasetWithdrawalNoticeV1 {
            notice_id: id("test-withdraw-source")?,
            dataset_digest: Digest32::of_bytes(b"test-dataset-source"),
            source_tombstone_digest: Digest32::of_bytes(b"test-tombstone"),
            authority_id: id("test-dataset-authority")?,
            credential_chain_digest: Digest32::of_bytes(b"test-withdrawal-credential"),
            signing_key_digest: Digest32::of_bytes(&self.key.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: NOW,
        })?;
        owner.install_withdrawal_frontier(withdrawals)?;
        Ok(())
    }
}

fn load_selection(owner: &LearningArtifactOwnerService, root: &Path, verifier: ArtifactSelectionVerifierV1, selected: SignedArtifactSelectionV1, now: u64) -> anyhow::Result<AgentdSelectedGenerationV1> {
    let receipt = owner.current_registry_view(now)?.receipt();
    let registry = root.join("registries").join(format!("{}-{}.snapshot", receipt.head_digest, receipt.file_digest));
    let payload = root.join("payloads").join(format!("{}-{}.bin", selected.artifact_id, selected.content_digest));
    Ok(AgentdSelectedGenerationV1::load(owner, verifier, selected, AgentdGenerationSelectionFilesV1 {
        registry_snapshot: File::open(registry)?, payload: File::open(payload)?,
    }, now)?)
}

fn publish_candidate(owner: &mut LearningArtifactOwnerService, cell: &CellBackendManifestV2, key: &SigningKey, name: &str) -> anyhow::Result<ArtifactManifest> {
    let payload = serde_json::to_vec(cell)?;
    let manifest = LearningArtifactManifestV2 {
        artifact_id: id(name)?, kind: ArtifactKind::Model, generation: Generation::new(1)?,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![Digest32::of_bytes(b"test-dataset-source")],
        lineage_digests: vec![Digest32::from_array(cell.evolution.lineage)],
        predecessor_ids: Vec::new(), rollback_predecessor: None,
        bytes_digest: Digest32::of_bytes(&payload), encoded_size_bytes: payload.len() as u64,
        training_code_digest: Digest32::from_array(cell.source_digest),
        runtime_tuple_digest: Digest32::from_array(cell.runtime_digest),
        device_profile_digest: Digest32::from_array(cell.device_digest),
        objective_class_digest: Digest32::of_bytes(b"test-generation-objective"),
        compatibility_digest: Digest32::from_array(cell.digest()?),
        schema_profile_digest: Digest32::from_array(cell.state_schema),
        normalization_digest: Digest32::of_bytes(b"test-normalization"),
        producer_id: id("test-producer")?, created_at: 1, expires_at: 10_000,
    };
    let predecessor = owner.registry().snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(owner.withdrawal_registry(), owner.withdrawal_registry().head_digest(), manifest.clone(), NOW)?;
    let transaction = ArtifactPublicationTransactionV1::begin(id(name)?, admission.clone(), owner.withdrawal_registry(), owner.registry(), predecessor, NOW)?;
    // The fixture issuer previews the same public Register event that the real
    // owner stages. Only Service::publish supplies durable CURRENT evidence.
    let candidate = ArtifactManifest {
        artifact_id: manifest.artifact_id, kind: manifest.kind, generation: manifest.generation,
        predecessor_id: None, content_digest: manifest.bytes_digest,
        objective_digest: manifest.objective_class_digest,
        support_digest: admission.validated_manifest.manifest_digest,
        producer_id: manifest.producer_id, compatibility_digest: manifest.compatibility_digest,
        encoded_size_bytes: manifest.encoded_size_bytes,
    };
    let mut staged = owner.registry().clone();
    staged.append(ArtifactEvent::Register {
        event_id: id(&format!("artifact-publication:{}", transaction.intent().intent_digest))?,
        manifest: candidate.clone(),
    })?;
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: admission.withdrawal_scope_digest,
        binding: Digest32::of_bytes(b"test-artifact-storage"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("test-learning-artifacts")?, generation: Generation::new(staged.records().len() as u64)?,
            head_digest: staged.snapshot().head_digest, predecessor_head_digest: predecessor,
            authority_epoch: 1, signer_id: id("test-artifact-authority")?,
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: NOW, expires_at: 10_000,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let receipt = owner.publish(LearningArtifactPublishRequestV1 {
        operation_id: id(name)?, admission, payload, signed_current_head: signed,
        expected_registry_predecessor_head: predecessor, now: NOW,
    })?;
    anyhow::ensure!(receipt.registry_head_digest == staged.snapshot().head_digest, "actual publication differs from signed preview");
    Ok(candidate)
}

fn id(value: &str) -> anyhow::Result<StableId> {
    Ok(StableId::new(value.to_owned())?)
}
