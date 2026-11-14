//! Isolated qualification issuers and real immutable artifact publication.
//! These public fixture keys certify no production trust or model quality.

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

use codex_hepta_agentd::AgentdGenerationSelectionFilesV1;
use codex_hepta_agentd::AgentdSelectedGenerationV1;

pub(super) struct ArtifactFiles {
    pub(super) owner: Arc<Mutex<LearningArtifactOwnerService>>,
    root: PathBuf,
    selected: SignedArtifactSelectionV1,
    verifier: ArtifactSelectionVerifierV1,
}

impl ArtifactFiles {
    pub(super) fn new(
        root: &Path,
        manifest: &CellBackendManifestV2,
        dataset: Digest32,
        now: u64,
    ) -> anyhow::Result<Self> {
        let key = SigningKey::from_bytes(&[61; 32]);
        let selector = SigningKey::from_bytes(&[62; 32]);
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
            authority_domain_id: id("qualification-dataset-authority")?,
            registry_id: id("qualification-withdrawals")?,
            scope_id: id("qualification-cell-sources")?,
        });
        let scope = withdrawals
            .scope_digest()
            .ok_or_else(|| anyhow::anyhow!("missing scope"))?;
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("qualification-artifact-authority")?,
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: now,
            expires_at: now + 900_000,
            revoked_at: None,
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: id("qualification-learning-artifacts")?,
            withdrawal_scope_digest: scope,
            minimum_registry_generation: Generation::new(1)?,
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("qualification-writer-lease")?,
            producer_id: id("qualification-producer")?,
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest: scope,
            signer_id: id("qualification-artifact-authority")?,
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: now,
            expires_at: now + 900_000,
            signature: [0; 64],
        };
        lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
        let mut owner = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            root: root.to_path_buf(),
            trust: trust.clone(),
            writer_lease: lease,
            required_current_head: None,
            withdrawal_registry: withdrawals,
            storage_binding: Digest32::of_bytes(b"qualification-artifact-storage"),
            now: now,
        })?;
        let candidate = publish_candidate(&mut owner, manifest, &key, dataset, now)?;
        let current = owner.current_registry_view(now)?;
        let verifier = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: trust.registry_id.clone(),
                withdrawal_scope_digest: scope,
                minimum_authority_epoch: 1,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id("qualification-independent-selector")?,
                    verifying_key: selector.verifying_key().to_bytes(),
                    minimum_authority_epoch: 1,
                    maximum_authority_epoch: 1,
                    valid_from: now,
                    expires_at: now + 900_000,
                    revoked_at: None,
                }],
            },
            &trust,
        )?;
        let mut selected = SignedArtifactSelectionV1 {
            selection_id: id("qualification-generation-selection")?,
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
            selector_id: id("qualification-independent-selector")?,
            selector_credential_digest: Digest32::of_bytes(b"qualification-selector-credential"),
            signing_key_digest: Digest32::of_bytes(&selector.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: now,
            expires_at: now + 900_000,
            signature: [0; 64],
        };
        selected.signature = selector.sign(&selected.signing_bytes()).to_bytes();
        Ok(Self {
            owner: Arc::new(Mutex::new(owner)),
            root: root.to_path_buf(),
            selected,
            verifier,
        })
    }

    pub(super) fn selection(&self, now: u64) -> anyhow::Result<AgentdSelectedGenerationV1> {
        let owner = self
            .owner
            .lock()
            .map_err(|_| anyhow::anyhow!("artifact owner poisoned"))?;
        load_selection(
            &owner,
            &self.root,
            self.verifier.clone(),
            self.selected.clone(),
            now,
        )
    }
}

fn load_selection(
    owner: &LearningArtifactOwnerService,
    root: &Path,
    verifier: ArtifactSelectionVerifierV1,
    selected: SignedArtifactSelectionV1,
    now: u64,
) -> anyhow::Result<AgentdSelectedGenerationV1> {
    let receipt = owner.current_registry_view(now)?.receipt();
    let registry = root.join("registries").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest
    ));
    let payload = root.join("payloads").join(format!(
        "{}-{}.bin",
        selected.artifact_id, selected.content_digest
    ));
    Ok(AgentdSelectedGenerationV1::load(
        owner,
        verifier,
        selected,
        AgentdGenerationSelectionFilesV1 {
            registry_snapshot: File::open(registry)?,
            payload: File::open(payload)?,
        },
        now,
    )?)
}

fn publish_candidate(
    owner: &mut LearningArtifactOwnerService,
    cell: &CellBackendManifestV2,
    key: &SigningKey,
    dataset: Digest32,
    now: u64,
) -> anyhow::Result<ArtifactManifest> {
    let name = "qualification-v13-selected-model";
    let payload = serde_json::to_vec(cell)?;
    let manifest = LearningArtifactManifestV2 {
        artifact_id: id(name)?,
        kind: ArtifactKind::Model,
        generation: Generation::new(1)?,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![dataset],
        lineage_digests: vec![Digest32::from_array(cell.evolution.lineage)],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: Digest32::of_bytes(&payload),
        encoded_size_bytes: payload.len() as u64,
        training_code_digest: Digest32::from_array(cell.source_digest),
        runtime_tuple_digest: Digest32::from_array(cell.runtime_digest),
        device_profile_digest: Digest32::from_array(cell.device_digest),
        objective_class_digest: Digest32::of_bytes(b"qualification-generation-objective"),
        compatibility_digest: Digest32::from_array(cell.digest()?),
        schema_profile_digest: Digest32::from_array(cell.state_schema),
        normalization_digest: Digest32::of_bytes(b"qualification-normalization"),
        producer_id: id("qualification-producer")?,
        created_at: now,
        expires_at: now + 900_000,
    };
    let predecessor = owner.registry().snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(
        owner.withdrawal_registry(),
        owner.withdrawal_registry().head_digest(),
        manifest.clone(),
        now,
    )?;
    let transaction = ArtifactPublicationTransactionV1::begin(
        id(name)?,
        admission.clone(),
        owner.withdrawal_registry(),
        owner.registry(),
        predecessor,
        now,
    )?;
    // The fixture issuer previews the same public Register event that the real
    // owner stages. Only Service::publish supplies durable CURRENT evidence.
    let candidate = ArtifactManifest {
        artifact_id: manifest.artifact_id,
        kind: manifest.kind,
        generation: manifest.generation,
        predecessor_id: None,
        content_digest: manifest.bytes_digest,
        objective_digest: manifest.objective_class_digest,
        support_digest: admission.validated_manifest.manifest_digest,
        producer_id: manifest.producer_id,
        compatibility_digest: manifest.compatibility_digest,
        encoded_size_bytes: manifest.encoded_size_bytes,
    };
    let mut staged = owner.registry().clone();
    staged.append(ArtifactEvent::Register {
        event_id: id(&format!(
            "artifact-publication:{}",
            transaction.intent().intent_digest
        ))?,
        manifest: candidate.clone(),
    })?;
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: admission.withdrawal_scope_digest,
        binding: Digest32::of_bytes(b"qualification-artifact-storage"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("qualification-learning-artifacts")?,
            generation: Generation::new(staged.records().len() as u64)?,
            head_digest: staged.snapshot().head_digest,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: id("qualification-artifact-authority")?,
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: now,
            expires_at: now + 900_000,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let receipt = owner.publish(LearningArtifactPublishRequestV1 {
        operation_id: id(name)?,
        admission,
        payload,
        signed_current_head: signed,
        expected_registry_predecessor_head: predecessor,
        now: now,
    })?;
    anyhow::ensure!(
        receipt.registry_head_digest == staged.snapshot().head_digest,
        "actual publication differs from signed preview"
    );
    Ok(candidate)
}

fn id(value: &str) -> anyhow::Result<StableId> {
    Ok(StableId::new(value.to_owned())?)
}
