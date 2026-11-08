//! Actual immutable publication and independent selection with test issuer keys.
//! The Model payload is a synthetic contract fixture, not trained qualification.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
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
    times: ArtifactTimes,
}

#[derive(Clone, Copy)]
struct ArtifactTimes {
    created: u64,
    observed: u64,
    expires: u64,
    selection_expires: u64,
}

impl ArtifactFiles {
    pub(super) fn new(root: &Path, manifest: &CellBackendManifestV2) -> anyhow::Result<Self> {
        Self::new_at(
            root,
            manifest,
            ArtifactTimes {
                created: 1,
                observed: NOW,
                expires: 10_000,
                selection_expires: 2_000,
            },
        )
    }

    pub(super) fn new_research(
        root: &Path,
        manifest: &CellBackendManifestV2,
        now: u64,
    ) -> anyhow::Result<Self> {
        let expires = now
            .checked_add(600_000)
            .ok_or_else(|| anyhow::anyhow!("research authority expiry overflow"))?;
        Self::new_at(
            root,
            manifest,
            ArtifactTimes {
                created: now,
                observed: now,
                expires,
                selection_expires: expires,
            },
        )
    }

    fn new_at(
        root: &Path,
        manifest: &CellBackendManifestV2,
        times: ArtifactTimes,
    ) -> anyhow::Result<Self> {
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
        let candidate = publish_candidate(&mut owner, manifest, &key, "selected-candidate", times)?;
        let current = owner.current_registry_view(times.observed)?;
        let verifier = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
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
            },
            &trust,
        )?;
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
            issued_at: times.observed,
            expires_at: times.selection_expires,
            signature: [0; 64],
        };
        selected.signature = selector.sign(&selected.signing_bytes()).to_bytes();
        Ok(Self {
            owner: Arc::new(Mutex::new(owner)),
            root: root.to_path_buf(),
            key,
            selector,
            selected,
            verifier,
            times,
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

    pub(super) fn publish_next_selection(
        &self,
        manifest: &CellBackendManifestV2,
        name: &str,
        now: u64,
    ) -> anyhow::Result<AgentdSelectedGenerationV1> {
        self.publish_next_selection_until(manifest, name, now, now + 1_000)
            .map(|(selection, _)| selection)
    }

    pub(super) fn publish_research_next_selection(
        &self,
        manifest: &CellBackendManifestV2,
        name: &str,
        now: u64,
    ) -> anyhow::Result<AgentdSelectedGenerationV1> {
        let expires = now
            .checked_add(90_000)
            .ok_or_else(|| anyhow::anyhow!("research selection expiry overflow"))?
            .min(self.times.selection_expires);
        anyhow::ensure!(now < expires, "research selection authority expired");
        let (selection, signed) =
            self.publish_next_selection_until(manifest, name, now, expires)?;
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(self.root.join("research-selected.json"))?;
        file.write_all(&research_selection_bytes(&signed)?)?;
        file.sync_all()?;
        File::open(&self.root)?.sync_all()?;
        Ok(selection)
    }

    pub(super) fn research_selection(
        &self,
        now: u64,
    ) -> anyhow::Result<AgentdSelectedGenerationV1> {
        let bytes = std::fs::read(self.root.join("research-selected.json"))?;
        let selected = research_selection_from_bytes(&bytes)?;
        let owner = self
            .owner
            .lock()
            .map_err(|_| anyhow::anyhow!("artifact owner poisoned"))?;
        load_selection(&owner, &self.root, self.verifier.clone(), selected, now)
    }

    fn publish_next_selection_until(
        &self,
        manifest: &CellBackendManifestV2,
        name: &str,
        now: u64,
        expires: u64,
    ) -> anyhow::Result<(AgentdSelectedGenerationV1, SignedArtifactSelectionV1)> {
        let mut owner = self
            .owner
            .lock()
            .map_err(|_| anyhow::anyhow!("artifact owner poisoned"))?;
        let candidate = publish_candidate(&mut owner, manifest, &self.key, name, self.times)?;
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
        selected.expires_at = expires;
        selected.signature = self.selector.sign(&selected.signing_bytes()).to_bytes();
        let verified = load_selection(
            &owner,
            &self.root,
            self.verifier.clone(),
            selected.clone(),
            now,
        )?;
        Ok((verified, selected))
    }

    pub(super) fn advance_current(&self, manifest: &CellBackendManifestV2) -> anyhow::Result<()> {
        let mut owner = self
            .owner
            .lock()
            .map_err(|_| anyhow::anyhow!("artifact owner poisoned"))?;
        publish_candidate(
            &mut owner,
            manifest,
            &self.key,
            "new-current-candidate",
            self.times,
        )?;
        Ok(())
    }

    pub(super) fn withdraw(&self) -> anyhow::Result<()> {
        let mut owner = self
            .owner
            .lock()
            .map_err(|_| anyhow::anyhow!("artifact owner poisoned"))?;
        let mut withdrawals = owner.withdrawal_registry().clone();
        withdrawals.append(DatasetWithdrawalNoticeV1 {
            notice_id: id("test-withdraw-source")?,
            dataset_digest: Digest32::of_bytes(b"test-dataset-source"),
            source_tombstone_digest: Digest32::of_bytes(b"test-tombstone"),
            authority_id: id("test-dataset-authority")?,
            credential_chain_digest: Digest32::of_bytes(b"test-withdrawal-credential"),
            signing_key_digest: Digest32::of_bytes(&self.key.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: self.times.observed,
        })?;
        owner.install_withdrawal_frontier(withdrawals)?;
        Ok(())
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
    name: &str,
    times: ArtifactTimes,
) -> anyhow::Result<ArtifactManifest> {
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
        signed_current_head: signed,
        expected_registry_predecessor_head: predecessor,
        now: times.observed,
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

// The original SignedArtifactSelectionV1 intentionally has no Serde admission.
// This test-only wire retains every original field, signing preimage and signed
// bytes. Recovery reconstructs that unverified type and immediately calls the
// original load_selection verifier; it never signs again or returns admission.
fn research_selection_bytes(signed: &SignedArtifactSelectionV1) -> anyhow::Result<Vec<u8>> {
    anyhow::ensure!(
        signed.artifact_kind == ArtifactKind::Model,
        "research selected payload must use the original Model kind"
    );
    Ok(serde_json::to_vec(&serde_json::json!({
        "schema":"hepta.research.original-signed-selection.v1",
        "selection_id":signed.selection_id.to_string(),"artifact_id":signed.artifact_id.to_string(),
        "registry_id":signed.registry_id.to_string(),"withdrawal_scope_digest":signed.withdrawal_scope_digest.to_string(),
        "registry_head_digest":signed.registry_head_digest.to_string(),"current_witness_digest":signed.current_witness_digest.to_string(),
        "current_trust_digest":signed.current_trust_digest.to_string(),"artifact_kind":"model",
        "artifact_generation":signed.artifact_generation.get(),"predecessor_id":signed.predecessor_id.as_ref().map(ToString::to_string),
        "content_digest":signed.content_digest.to_string(),"objective_digest":signed.objective_digest.to_string(),
        "support_digest":signed.support_digest.to_string(),"compatibility_digest":signed.compatibility_digest.to_string(),
        "encoded_size_bytes":signed.encoded_size_bytes,"selector_id":signed.selector_id.to_string(),
        "selector_credential_digest":signed.selector_credential_digest.to_string(),"signing_key_digest":signed.signing_key_digest.to_string(),
        "authority_epoch":signed.authority_epoch,"issued_at":signed.issued_at,"expires_at":signed.expires_at,
        "signature":signed.signature.as_slice(),"original_signing_bytes":signed.signing_bytes(),
    }))?)
}

fn research_selection_from_bytes(bytes: &[u8]) -> anyhow::Result<SignedArtifactSelectionV1> {
    anyhow::ensure!(bytes.len() <= 16384, "bounded retained research selection");
    let value: serde_json::Value = serde_json::from_slice(bytes)?;
    anyhow::ensure!(
        value.as_object().is_some_and(|object| object.len() == 24)
            && value["schema"] == "hepta.research.original-signed-selection.v1"
            && value["artifact_kind"] == "model",
        "closed research selection encoding"
    );
    let text = |field: &str| -> anyhow::Result<&str> {
        value[field]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("research selection string {field}"))
    };
    let number = |field: &str| -> anyhow::Result<u64> {
        value[field]
            .as_u64()
            .ok_or_else(|| anyhow::anyhow!("research selection number {field}"))
    };
    let signature: Vec<u8> = serde_json::from_value(value["signature"].clone())?;
    let signature: [u8; 64] = signature
        .try_into()
        .map_err(|_| anyhow::anyhow!("original selection signature length"))?;
    let selected = SignedArtifactSelectionV1 {
        selection_id: StableId::new(text("selection_id")?)?,
        artifact_id: StableId::new(text("artifact_id")?)?,
        registry_id: StableId::new(text("registry_id")?)?,
        withdrawal_scope_digest: text("withdrawal_scope_digest")?.parse()?,
        registry_head_digest: text("registry_head_digest")?.parse()?,
        current_witness_digest: text("current_witness_digest")?.parse()?,
        current_trust_digest: text("current_trust_digest")?.parse()?,
        artifact_kind: ArtifactKind::Model,
        artifact_generation: Generation::new(number("artifact_generation")?)?,
        predecessor_id: if value["predecessor_id"].is_null() {
            None
        } else {
            Some(StableId::new(text("predecessor_id")?)?)
        },
        content_digest: text("content_digest")?.parse()?,
        objective_digest: text("objective_digest")?.parse()?,
        support_digest: text("support_digest")?.parse()?,
        compatibility_digest: text("compatibility_digest")?.parse()?,
        encoded_size_bytes: number("encoded_size_bytes")?,
        selector_id: StableId::new(text("selector_id")?)?,
        selector_credential_digest: text("selector_credential_digest")?.parse()?,
        signing_key_digest: text("signing_key_digest")?.parse()?,
        authority_epoch: number("authority_epoch")?,
        issued_at: number("issued_at")?,
        expires_at: number("expires_at")?,
        signature,
    };
    let preimage: Vec<u8> = serde_json::from_value(value["original_signing_bytes"].clone())?;
    anyhow::ensure!(
        selected.signing_bytes() == preimage && research_selection_bytes(&selected)? == bytes,
        "retained selection fields/signature/preimage encoding differ"
    );
    Ok(selected)
}
