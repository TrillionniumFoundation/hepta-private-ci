//! Administrator inputs for two actual product binaries. This setup opens no
//! running HostAuthorityService and fabricates no published Initial or task cut.

use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;

use super::super::data;
use super::super::private_file;
use crate::DeploymentGrantPolicy;
use crate::HostAuthorityBindIdentity;
use crate::HostAuthorityBootstrap;
use crate::HostAuthorityConsumerConfig;
use crate::HostAuthorityConsumersConfig;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityServiceConfig;
use crate::HostAuthoritySocketPaths;
use crate::HostAuthorityWriterRegistration;
use crate::HostGenerationInitialDeploymentV1;
use crate::HostIssuerRecordProfile;
use crate::RootArtifactPublicationInputsV1;

pub(super) const LIFETIME_MS: u64 = 300_000;
// These are declared before A's first registration. The original writer must
// actually expire before recovery; its original issuer remains available to
// authorize the next registered incarnation without replacing its key/store.
const ORIGINAL_WRITER_LIFETIME_MS: u64 = 60_000;
const ORIGINAL_ISSUER_LIFETIME_MS: u64 = 1_200_000;

pub(super) struct OriginalRootInputs {
    pub(super) service: PathBuf,
    pub(super) registration: PathBuf,
    pub(super) initial: PathBuf,
    pub(super) source: PathBuf,
    pub(super) run_start: PathBuf,
    pub(super) authority: PathBuf,
    pub(super) current: PathBuf,
    pub(super) issuer: Value,
    pub(super) writer_proof: PathBuf,
}

impl OriginalRootInputs {
    pub(super) fn initialize(
        protected: &Path,
        runtime: &Path,
        required_bind: HostAuthorityBindIdentity,
        registered: &HostAuthorityRegisteredIdentity,
        binding: &FinalUseBinding,
        now: u64,
    ) -> anyhow::Result<Self> {
        let state = protected.join("authority");
        let bootstrap = protected.join("bootstrap.json");
        write_json(
            &bootstrap,
            &HostAuthorityBootstrap {
                schema_version: 1,
                required_bind: required_bind.clone(),
                signer_id: "ordinary-original-root".into(),
                // Root declares these exact destinations/scope before A.
                // Later C still needs its real Root publication admission;
                // policy data never changes the original issuer lease binding.
                policies: [
                    binding.destination_id.as_str(),
                    "agentd.cell-generation.replace-drained",
                    "agentd.cell-generation.next-task-same-model",
                ]
                .into_iter()
                .map(|destination| DeploymentGrantPolicy {
                    subject_id: binding.subject_id.clone(),
                    destination_id: destination.into(),
                    scope_sha256: binding.scope_sha256,
                    lifetime_ms: LIFETIME_MS,
                })
                .collect(),
                lease_id: "ordinary-original-root".into(),
                lease_binding: AuthorityLeaseBinding {
                    principal_id: binding.subject_id.clone(),
                    operation_class: "runtime.agentd.production_operation".into(),
                    destination_id: binding.destination_id.clone(),
                    scope_sha256: binding.scope_sha256,
                    payload_sha256: binding.payload_sha256,
                },
                lease_lifetime_ms: ORIGINAL_ISSUER_LIFETIME_MS,
            },
        )?;
        let initialized = crate::initialize_host_authority(&state, &bootstrap)?;
        let config = HostAuthorityServiceConfig {
            schema_version: 1,
            issuer_record_profile: HostIssuerRecordProfile::Standard,
            state_dir: state.clone(),
            required_bind,
            signer_id: initialized.signer_id.clone(),
            expected_verifying_key: initialized.verifying_key,
            lease_id: initialized.lease_id,
            lease_revision: initialized.lease_revision,
            writer: Some(HostAuthorityWriterRegistration {
                registered_agent_id: registered.agent_id.clone(),
                spawn_generation: registered.spawn_generation,
                owner_epoch: 1,
                local_lease_id: "ordinary-original-local-writer".into(),
                local_lease_generation: 1,
                authority_lease: AuthorityLease {
                    schema_version: 1,
                    lease_id: "ordinary-original-root-writer".into(),
                    revision: 1,
                    authority_epoch: 1,
                    binding: AuthorityLeaseBinding {
                        principal_id: registered.agent_id.to_string(),
                        operation_class: "runtime.agentd.production_writer".into(),
                        destination_id: "ordinary.original.cognitive-owner".into(),
                        scope_sha256: binding.scope_sha256,
                        payload_sha256: binding.payload_sha256,
                    },
                    issued_at_unix_ms: now,
                    expires_at_unix_ms: now
                        .checked_add(ORIGINAL_WRITER_LIFETIME_MS)
                        .ok_or_else(|| anyhow::anyhow!("original writer expiry overflow"))?,
                },
            }),
            checkpoint_state_dir: Some(state.join("checkpoint")),
            consumers: Some(HostAuthorityConsumersConfig {
                device: HostAuthorityConsumerConfig {
                    state_dir: state.join("device-consumer"),
                    owner_id: initialized.signer_id.clone(),
                },
                notes: HostAuthorityConsumerConfig {
                    state_dir: state.join("notes-consumer"),
                    owner_id: initialized.signer_id.clone(),
                },
            }),
            sockets: HostAuthoritySocketPaths {
                observation: runtime.join("obs.sock"),
                issuer: runtime.join("issuer.sock"),
                checkpoint: runtime.join("checkpoint.sock"),
                device_frontier: Some(runtime.join("device.sock")),
                notes_frontier: Some(runtime.join("notes.sock")),
            },
            peer_uid: 60001,
            peer_gid: 60001,
            timeout_ms: 500,
            lifetime_ms: LIFETIME_MS,
        };
        let service = protected.join("service.json");
        write_json(&service, &config)?;
        let original_proof = crate::register_host_writer_authorization(&service)?;
        let writer_proof = protected.join("original-writer-proof.json");
        write_json(&writer_proof, &original_proof)?;
        // The actual historical endpoint reads its independent retained cuts
        // from this registered Root state directory. Initial capture must use
        // this same declared directory; no test moves records after A exits.
        let current = state.clone();
        Ok(Self {
            service,
            registration: protected.join("original-spawn.json"),
            initial: protected.join("initial.json"),
            source: protected.join("source.json"),
            run_start: protected.join("run-start.json"),
            authority: state,
            current,
            writer_proof,
            issuer: json!({
                "key_id": initialized.signer_id,
                "verifying_key": initialized.verifying_key,
                "not_before_authority_epoch": 1,
                "not_after_authority_epoch": 1
            }),
        })
    }

    pub(super) fn initial_data(
        &self,
        identity: &crate::AgentdIdentity,
        deployment: &HostGenerationInitialDeploymentV1,
        target: &codex_hepta_neuron::CellGenerationObserverConfigV1,
        target_paths: [&Path; 2],
        transfer: &Value,
        artifacts: &RootArtifactPublicationInputsV1,
        data_directory: &Path,
        learning_trust: &Path,
    ) -> anyhow::Result<Value> {
        let withdrawal = codex_hepta_learning_artifacts::write_dataset_withdrawal_snapshot_beneath(
            data_directory,
            "original-withdrawal.snapshot",
            &artifacts.withdrawal_floor,
            artifacts.storage_binding,
        )?;
        let withdrawal_path = data_directory.join("original-withdrawal.snapshot");
        super::super::owned_mode(&withdrawal_path, 60001, 60001, 0o600)?;
        let value = json!({
            "learning_trust": learning_trust,
            "schema_version": 1, "mode": crate::RootGenerationInitialModeV1::Reserve,
            "operation": deployment.operation, "current_directory": self.current,
            "target_journal": target_paths[0], "target_witness": target_paths[1],
            "target": data::ObserverData::from_original_observer(target),
            "artifact_root": transfer["root"], "owner_trust": transfer["owner"],
            "retained_current": transfer["current"], "storage_binding": artifacts.storage_binding.into_array(),
            "withdrawal_file": withdrawal_path,
            "withdrawal": {
                "binding": withdrawal.binding.into_array(), "scope": withdrawal.scope_digest.into_array(),
                "head": withdrawal.head_digest.into_array(), "file_digest": withdrawal.file_digest.into_array(),
                "records": withdrawal.records, "encoded_bytes": withdrawal.encoded_bytes
            },
            "selector_trust": transfer["selector"], "selection": transfer["selected"],
            "consumer": crate::RootPublicationFinalUseConsumerV1::Device,
            "consumer_state_root": identity.layout.agent_root().join("final-use"),
            "issuer_keys": [self.issuer],
            "trigger": self.initial.with_file_name("unused-file-trigger.json")
        });
        // Decode the exact same public preimage the product main will consume.
        // Root later opens and authorizes its original files independently.
        crate::OriginalRootInitialLaunchDataV1::from_original_deployment_value(value.clone())?;
        write_json(&self.initial, &value)?;
        Ok(value)
    }
}

pub(super) fn write_json(path: &Path, value: &impl Serialize) -> anyhow::Result<()> {
    write_bytes(path, &serde_json::to_vec(value)?)
}

pub(super) fn write_bytes(path: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    let mut file = private_file(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    File::open(
        path.parent()
            .ok_or_else(|| anyhow::anyhow!("original file parent absent"))?,
    )?
    .sync_all()?;
    Ok(())
}
