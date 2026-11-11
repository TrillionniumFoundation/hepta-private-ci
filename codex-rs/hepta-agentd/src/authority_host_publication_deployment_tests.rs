//! Exercised by the existing actual-UID0 broker parent. These are component
//! deployment files built from its real original owners, never test owners in
//! production or ordinary A/B/C evidence.

use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use super::*;
use super::data::*;

fn write_original_data(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

fn signer_data(signer: &TrustedArtifactSignerV1) -> SignerData {
    SignerData {
        id: signer.signer_id.to_string(), verifying_key: signer.verifying_key,
        minimum_authority_epoch: signer.minimum_authority_epoch,
        maximum_authority_epoch: signer.maximum_authority_epoch,
        valid_from: signer.valid_from, expires_at: signer.expires_at, revoked_at: signer.revoked_at,
    }
}

impl RootGenerationPublicationEnrollmentCapabilityV1 {
    pub(crate) fn component_original_deployment(
        self,
        directory: &Path,
        original_paths: &[PathBuf; 5],
        selector_trust: &ArtifactSelectionTrustV1,
        inputs: crate::RootGenerationPublicationEnrollmentV1,
    ) -> io::Result<(RootGenerationPublicationDeploymentV1, Vec<u8>)> {
        fs::create_dir(directory)?;
        fs::set_permissions(directory, fs::Permissions::from_mode(0o700))?;
        for (file, path) in [
            (&inputs.previous.journal, &original_paths[1]),
            (&inputs.previous.witness, &original_paths[2]),
            (&inputs.target.journal, &original_paths[3]),
            (&inputs.target.witness, &original_paths[4]),
        ] {
            let actual = file.metadata()?;
            let path = fs::metadata(path)?;
            assert_eq!((actual.dev(), actual.ino()), (path.dev(), path.ino()));
        }
        let artifacts = &inputs.artifacts;
        assert_eq!(
            ArtifactSelectionVerifierV1::new(selector_trust.clone(), &artifacts.trust)
                .map_err(io::Error::other)?.trust_digest(),
            artifacts.selector.trust_digest(),
        );
        let receipt = write_dataset_withdrawal_snapshot_beneath(
            directory, "withdrawal.snapshot", &artifacts.withdrawal_floor, artifacts.storage_binding,
        ).map_err(io::Error::other)?;
        let current = &artifacts.retained_current;
        let descriptor = DeploymentData {
            schema_version: 1,
            mode: match inputs.mode {
                crate::RootGenerationPublicationModeV1::Reserve => Mode::Reserve,
                crate::RootGenerationPublicationModeV1::Recover => Mode::Recover,
            },
            current_directory: original_paths[0].clone(),
            previous_journal: original_paths[1].clone(), previous_witness: original_paths[2].clone(),
            previous: ObserverData::from_original_observer(&inputs.previous.config),
            target_journal: original_paths[3].clone(), target_witness: original_paths[4].clone(),
            artifact_root: artifacts.root.clone(),
            owner_trust: OwnerTrustData {
                registry_id: artifacts.trust.registry_id.to_string(),
                withdrawal_scope: artifacts.trust.withdrawal_scope_digest.into_array(),
                minimum_registry_generation: artifacts.trust.minimum_registry_generation.get(),
                genesis_predecessor: artifacts.trust.genesis_predecessor_head_digest.into_array(),
                minimum_authority_epoch: artifacts.trust.minimum_authority_epoch,
                writer_signers: artifacts.trust.writer_signers.iter().map(signer_data).collect(),
                head_signers: artifacts.trust.head_signers.iter().map(signer_data).collect(),
            },
            retained_current: CurrentData {
                withdrawal_scope: current.withdrawal_scope_digest.into_array(), binding: current.binding.into_array(),
                registry_id: current.witness.registry_id.to_string(), generation: current.witness.generation.get(),
                head: current.witness.head_digest.into_array(), predecessor: current.witness.predecessor_head_digest.into_array(),
                authority_epoch: current.witness.authority_epoch, signer_id: current.witness.signer_id.to_string(),
                signing_key_digest: current.witness.signing_key_digest.into_array(),
                issued_at: current.witness.issued_at, expires_at: current.witness.expires_at, signature: current.signature.to_vec(),
            },
            storage_binding: artifacts.storage_binding.into_array(),
            withdrawal_file: directory.join("withdrawal.snapshot"),
            withdrawal: WithdrawalData {
                binding: receipt.binding.into_array(), scope: receipt.scope_digest.into_array(),
                head: receipt.head_digest.into_array(), file_digest: receipt.file_digest.into_array(),
                records: receipt.records, encoded_bytes: receipt.encoded_bytes,
            },
            selector_trust: SelectorTrustData {
                registry_id: selector_trust.registry_id.to_string(),
                withdrawal_scope: selector_trust.withdrawal_scope_digest.into_array(),
                minimum_authority_epoch: selector_trust.minimum_authority_epoch,
                selectors: selector_trust.selectors.iter().map(|signer| SignerData {
                    id: signer.selector_id.to_string(), verifying_key: signer.verifying_key,
                    minimum_authority_epoch: signer.minimum_authority_epoch,
                    maximum_authority_epoch: signer.maximum_authority_epoch,
                    valid_from: signer.valid_from, expires_at: signer.expires_at, revoked_at: signer.revoked_at,
                }).collect(),
            },
            consumer: inputs.consumer, consumer_state_root: inputs.consumer_state_root,
            issuer_keys: inputs.issuer_keys.iter().map(|key| IssuerKeyData {
                key_id: key.key_id.clone(), verifying_key: key.verifying_key,
                not_before_authority_epoch: key.not_before_authority_epoch,
                not_after_authority_epoch: key.not_after_authority_epoch,
            }).collect(),
            late_material: directory.join("material.json"), trigger: directory.join("trigger.json"),
        };
        let path = directory.join("deployment.json");
        write_original_data(&path, &serde_json::to_vec(&descriptor).map_err(io::Error::other)?)?;
        let material = RootGenerationPublicationDeploymentV1::encode_original_material(
            &inputs.target.config, &artifacts.signed_selection,
        )?;
        let decoded: LateMaterial = serde_json::from_slice(&material).map_err(io::Error::other)?;
        assert_eq!(decoded.selection.original_selection()?, artifacts.signed_selection);
        assert_eq!(decoded.target.generation, inputs.target.config.generation);
        for field in ["root_directory", "consumer", "owner_trust", "scope", "paths"] {
            let mut injected: serde_json::Value = serde_json::from_slice(&material).map_err(io::Error::other)?;
            injected.as_object_mut().expect("material object").insert(field.into(), serde_json::json!({}));
            assert!(serde_json::from_value::<LateMaterial>(injected).is_err());
        }
        let deployment = self.with_original_deployment(&path)?;
        let digest = Digest32::of_bytes(&material).to_string();
        let trigger = Trigger { session: deployment.session.clone(), material_digest: digest.clone() };
        deployment.require_original_trigger(&trigger)?;
        let mut previous = trigger.session.clone();
        previous.attempt = previous.attempt.checked_sub(1).expect("positive original attempt");
        assert!(deployment.require_original_trigger(&Trigger {
            session: previous, material_digest: digest.clone(),
        }).is_err());
        let mut previous = trigger.session.clone();
        previous.root_start_ticks = previous.root_start_ticks.checked_add(1).expect("component start ticks");
        assert!(deployment.require_original_trigger(&Trigger {
            session: previous, material_digest: digest,
        }).is_err());
        let stopped = AtomicBool::new(/*val*/ true);
        assert_eq!(deployment.require_waiting_session(&stopped, Instant::now() + Duration::from_secs(1))
            .expect_err("actual cancellation must reject").kind(), io::ErrorKind::Interrupted);
        let waiting = AtomicBool::new(/*val*/ false);
        assert_eq!(deployment.require_waiting_session(&waiting, Instant::now())
            .expect_err("late trigger must reject").kind(), io::ErrorKind::Interrupted);
        root_file_negatives(directory)?;
        deployment.require_deployment_files()?;
        assert!(!descriptor.late_material.exists());
        assert!(!descriptor.trigger.exists());
        Ok((deployment, material))
    }
}

impl RootGenerationPublicationDeploymentV1 {
    pub(crate) fn component_reject_previous_trigger(&self, path: &Path) -> io::Result<()> {
        let (original, bytes) = MetadataFile::open_metadata(path)?;
        let trigger: Trigger = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        assert_eq!(trigger.session.root_pid, self.session.root_pid);
        assert_eq!(trigger.session.root_boot_id, self.session.root_boot_id);
        assert_eq!(trigger.session.root_start_ticks, self.session.root_start_ticks);
        assert!(trigger.session.attempt < self.session.attempt);
        assert!(self.require_original_trigger(&trigger).is_err());
        original.require_metadata_unchanged()
    }

    /// Publish actual fixture data only after the child has completed the real
    /// learning checkpoint. The ordinary CLI obtains it from its trusted host.
    pub(crate) fn component_trigger_original(&self, material: &[u8]) -> io::Result<()> {
        write_original_data(&self.data.late_material, material)?;
        let trigger = Trigger {
            session: self.session.clone(), material_digest: Digest32::of_bytes(material).to_string(),
        };
        let bytes = serde_json::to_vec(&trigger).map_err(io::Error::other)?;
        write_original_data(&self.data.trigger, &bytes)?;
        assert!(write_original_data(&self.data.trigger, &bytes).is_err());
        Ok(())
    }
}

fn root_file_negatives(directory: &Path) -> io::Result<()> {
    let path = directory.join("file-pin-probe.json");
    write_original_data(&path, b"{\"original\":true}")?;
    let (original, _) = MetadataFile::open_metadata(&path)?;
    original.require_metadata_unchanged()?;
    let moved = directory.join("file-pin-old.json");
    fs::rename(&path, &moved)?;
    write_original_data(&path, b"{\"original\":true}")?;
    assert!(original.require_metadata_unchanged().is_err());
    fs::remove_file(&path)?;
    std::os::unix::fs::symlink(&moved, &path)?;
    assert!(MetadataFile::open_metadata(&path).is_err());
    fs::remove_file(&path)?;
    fs::hard_link(&moved, &path)?;
    assert!(MetadataFile::open_metadata(&path).is_err());
    fs::remove_file(&path)?;
    let mode_path = directory.join("metadata-mode-probe.json");
    write_original_data(&mode_path, b"{}")?;
    for mode in [0o4600, 0o2600, 0o1600, 0o640] {
        fs::set_permissions(&mode_path, fs::Permissions::from_mode(mode))?;
        assert!(MetadataFile::open_metadata(&mode_path).is_err());
    }
    fs::set_permissions(&mode_path, fs::Permissions::from_mode(0o600))?;
    MetadataFile::open_metadata(&mode_path)?;
    let parent = directory.join("parent-pin-probe");
    fs::create_dir(&parent)?;
    fs::set_permissions(&parent, fs::Permissions::from_mode(0o700))?;
    let path = parent.join("original.json");
    write_original_data(&path, b"{}")?;
    let (original, _) = MetadataFile::open_metadata(&path)?;
    fs::rename(&parent, directory.join("parent-pin-old"))?;
    fs::create_dir(&parent)?;
    fs::set_permissions(&parent, fs::Permissions::from_mode(0o700))?;
    write_original_data(&path, b"{}")?;
    assert!(original.require_metadata_unchanged().is_err());
    Ok(())
}
