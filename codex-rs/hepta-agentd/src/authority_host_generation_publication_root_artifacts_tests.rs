//! Original Artifact owner and independently signed selection for the Root
//! broker component test. Keys/material here are explicit synthetic fixtures;
//! durable publication, reader verification and CURRENT are the real owners.

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

use crate::AgentdGenerationSelectionFilesV1;
use crate::AgentdSelectedGenerationV1;
use crate::RootArtifactPublicationInputsV1;

pub(super) struct Artifacts {
    owner: Arc<Mutex<LearningArtifactOwnerService>>,
    root: PathBuf,
    trust: ArtifactOwnerTrustV1,
    retained_current: SignedCurrentArtifactHeadV1,
    selected: SignedArtifactSelectionV1,
    verifier: ArtifactSelectionVerifierV1,
    pub(super) selector_trust: ArtifactSelectionTrustV1,
}

#[derive(Clone, Copy)]
struct ArtifactTimes {
    created: u64,
    observed: u64,
    expires: u64,
    selection_expires: u64,
}

impl Artifacts {
    pub(super) fn new(root: &Path, manifest: &CellBackendManifestV2, now: u64) -> anyhow::Result<Self> {
        let times = ArtifactTimes {
            created: now, observed: now,
            expires: now.checked_add(600_000).ok_or_else(|| anyhow::anyhow!("expiry overflow"))?,
            selection_expires: now.checked_add(600_000).ok_or_else(|| anyhow::anyhow!("expiry overflow"))?,
        };
        let key = SigningKey::from_bytes(&[61; 32]);
        let selector = SigningKey::from_bytes(&[62; 32]);
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
            authority_domain_id: id("test-dataset-authority")?,
            registry_id: id("test-withdrawals")?,
            scope_id: id("test-cell-sources")?,
        });
        let scope = withdrawals
            .scope_digest()
            .ok_or_else(|| anyhow::anyhow!("missing scope"))?;
        let signer = TrustedArtifactSignerV1 {
            signer_id: id("test-artifact-authority")?,
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: times.created,
            expires_at: times.expires,
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
            issued_at: times.created,
            expires_at: times.expires,
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
            now: times.observed,
        })?;
        let (candidate, retained_current) = publish_candidate(&mut owner, manifest, &key, "selected-candidate", times)?;
        let current = owner.current_registry_view(times.observed)?;
        let selector_trust = ArtifactSelectionTrustV1 {
                registry_id: trust.registry_id.clone(),
                withdrawal_scope_digest: scope,
                minimum_authority_epoch: 1,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id("test-independent-selector")?,
                    verifying_key: selector.verifying_key().to_bytes(),
                    minimum_authority_epoch: 1,
                    maximum_authority_epoch: 1,
                    valid_from: times.created,
                    expires_at: times.expires,
                    revoked_at: None,
                }],
            };
        let verifier = ArtifactSelectionVerifierV1::new(selector_trust.clone(), &trust)?;
        let mut selected = SignedArtifactSelectionV1 {
            selection_id: id("test-generation-selection")?,
            artifact_id: candidate.artifact_id,
            registry_id: trust.registry_id.clone(),
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
            issued_at: times.observed,
            expires_at: times.selection_expires,
            signature: [0; 64],
        };
        selected.signature = selector.sign(&selected.signing_bytes()).to_bytes();
        Ok(Self {
            owner: Arc::new(Mutex::new(owner)),
            root: root.to_path_buf(),
            trust,
            retained_current,
            selected,
            verifier,
            selector_trust,
        })
    }


    pub(super) fn inputs(&self, now: u64) -> anyhow::Result<RootArtifactPublicationInputsV1> {
        let owner = self.owner.lock().map_err(|_| anyhow::anyhow!("original artifact owner poisoned"))?;
        let receipt = owner.current_registry_view(now)?.receipt();
        Ok(RootArtifactPublicationInputsV1 {
            root: self.root.clone(), trust: self.trust.clone(),
            retained_current: self.retained_current.clone(),
            storage_binding: Digest32::of_bytes(b"test-artifact-storage"),
            withdrawal_floor: owner.withdrawal_registry().clone(),
            selector: self.verifier.clone(), signed_selection: self.selected.clone(),
            files: AgentdGenerationSelectionFilesV1 {
                registry_snapshot: File::open(self.root.join("registries").join(format!(
                    "{}-{}.snapshot", receipt.head_digest, receipt.file_digest,
                )))?,
                payload: File::open(self.root.join("payloads").join(format!(
                    "{}-{}.bin", self.selected.artifact_id, self.selected.content_digest,
                )))?,
            },
        })
    }

    pub(super) fn selection(&self, now: u64) -> anyhow::Result<AgentdSelectedGenerationV1> {
        let input = self.inputs(now)?;
        let owner = self.owner.lock().map_err(|_| anyhow::anyhow!("original artifact owner poisoned"))?;
        Ok(AgentdSelectedGenerationV1::load(
            &owner, input.selector, input.signed_selection, input.files, now,
        )?)
    }
}

fn publish_candidate(
    owner: &mut LearningArtifactOwnerService,
    cell: &CellBackendManifestV2,
    key: &SigningKey,
    name: &str,
    times: ArtifactTimes,
) -> anyhow::Result<(ArtifactManifest, SignedCurrentArtifactHeadV1)> {
    let payload = serde_json::to_vec(cell)?;
    let manifest = LearningArtifactManifestV2 {
        artifact_id: id(name)?,
        kind: ArtifactKind::Model,
        generation: Generation::new(1)?,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![Digest32::of_bytes(b"test-dataset-source")],
        lineage_digests: vec![Digest32::from_array(cell.evolution.lineage)],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: Digest32::of_bytes(&payload),
        encoded_size_bytes: payload.len() as u64,
        training_code_digest: Digest32::from_array(cell.source_digest),
        runtime_tuple_digest: Digest32::from_array(cell.runtime_digest),
        device_profile_digest: Digest32::from_array(cell.device_digest),
        objective_class_digest: Digest32::of_bytes(b"test-generation-objective"),
        compatibility_digest: Digest32::from_array(cell.digest()?),
        schema_profile_digest: Digest32::from_array(cell.state_schema),
        normalization_digest: Digest32::of_bytes(b"test-normalization"),
        producer_id: id("test-producer")?,
        created_at: times.created,
        expires_at: times.expires,
    };
    let predecessor = owner.registry().snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(
        owner.withdrawal_registry(),
        owner.withdrawal_registry().head_digest(),
        manifest.clone(),
        times.observed,
    )?;
    let transaction = ArtifactPublicationTransactionV1::begin(
        id(name)?,
        admission.clone(),
        owner.withdrawal_registry(),
        owner.registry(),
        predecessor,
        times.observed,
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
        binding: Digest32::of_bytes(b"test-artifact-storage"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("test-learning-artifacts")?,
            generation: Generation::new(staged.records().len() as u64)?,
            head_digest: staged.snapshot().head_digest,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: id("test-artifact-authority")?,
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: times.observed,
            expires_at: times.expires,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let receipt = owner.publish(LearningArtifactPublishRequestV1 {
        operation_id: id(name)?,
        admission,
        payload,
        signed_current_head: signed.clone(),
        expected_registry_predecessor_head: predecessor,
        now: times.observed,
    })?;
    anyhow::ensure!(
        receipt.registry_head_digest == staged.snapshot().head_digest,
        "actual publication differs from signed preview"
    );
    Ok((candidate, signed))
}


fn id(value: &str) -> anyhow::Result<StableId> { Ok(StableId::new(value)?) }
