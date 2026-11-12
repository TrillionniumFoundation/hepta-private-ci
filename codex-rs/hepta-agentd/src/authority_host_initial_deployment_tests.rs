//! Component assertions inside the existing actual UID0 Initial parent.
//! These files describe its original signed owners; they do not create
//! production keys, fabricate genesis, or count as ordinary task evidence.

use super::shared_data::*;
use super::*;
use codex_hepta_learning_artifacts::*;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;

fn write_initial_metadata(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

fn original_signer_data(signer: &TrustedArtifactSignerV1) -> SignerData {
    SignerData {
        id: signer.signer_id.to_string(),
        verifying_key: signer.verifying_key,
        minimum_authority_epoch: signer.minimum_authority_epoch,
        maximum_authority_epoch: signer.maximum_authority_epoch,
        valid_from: signer.valid_from,
        expires_at: signer.expires_at,
        revoked_at: signer.revoked_at,
    }
}

impl RootGenerationInitialDeploymentFilesV1 {
    pub(crate) fn component_initial_files(
        directory: &Path,
        original_paths: &[PathBuf; 3],
        operation: String,
        selector_description: &[u8],
        inputs: &crate::RootGenerationInitialEnrollmentV1,
    ) -> io::Result<Self> {
        for (file, path) in [
            (&inputs.target.journal, &original_paths[1]),
            (&inputs.target.witness, &original_paths[2]),
        ] {
            let actual = file.metadata()?;
            let path = fs::metadata(path)?;
            assert_eq!((actual.dev(), actual.ino()), (path.dev(), path.ino()));
        }
        let artifacts = &inputs.artifacts;
        let selector: SelectorTrustData =
            serde_json::from_slice(selector_description).map_err(io::Error::other)?;
        assert_eq!(
            selector.original_selector(&artifacts.trust)?.trust_digest(),
            artifacts.selector.trust_digest()
        );
        let receipt = write_dataset_withdrawal_snapshot_beneath(
            directory,
            "withdrawal.snapshot",
            &artifacts.withdrawal_floor,
            artifacts.storage_binding,
        )
        .map_err(io::Error::other)?;
        let current = &artifacts.retained_current;
        let descriptor = InitialDeploymentData {
            learning_trust: None,
            schema_version: 1,
            mode: inputs.mode,
            operation,
            current_directory: original_paths[0].clone(),
            target_journal: original_paths[1].clone(),
            target_witness: original_paths[2].clone(),
            target: ObserverData::from_original_observer(&inputs.target.config),
            artifact_root: artifacts.root.clone(),
            owner_trust: OwnerTrustData {
                registry_id: artifacts.trust.registry_id.to_string(),
                withdrawal_scope: artifacts.trust.withdrawal_scope_digest.into_array(),
                minimum_registry_generation: artifacts.trust.minimum_registry_generation.get(),
                genesis_predecessor: artifacts.trust.genesis_predecessor_head_digest.into_array(),
                minimum_authority_epoch: artifacts.trust.minimum_authority_epoch,
                writer_signers: artifacts
                    .trust
                    .writer_signers
                    .iter()
                    .map(original_signer_data)
                    .collect(),
                head_signers: artifacts
                    .trust
                    .head_signers
                    .iter()
                    .map(original_signer_data)
                    .collect(),
            },
            retained_current: CurrentData {
                withdrawal_scope: current.withdrawal_scope_digest.into_array(),
                binding: current.binding.into_array(),
                registry_id: current.witness.registry_id.to_string(),
                generation: current.witness.generation.get(),
                head: current.witness.head_digest.into_array(),
                predecessor: current.witness.predecessor_head_digest.into_array(),
                authority_epoch: current.witness.authority_epoch,
                signer_id: current.witness.signer_id.to_string(),
                signing_key_digest: current.witness.signing_key_digest.into_array(),
                issued_at: current.witness.issued_at,
                expires_at: current.witness.expires_at,
                signature: current.signature.to_vec(),
            },
            storage_binding: artifacts.storage_binding.into_array(),
            withdrawal_file: directory.join("withdrawal.snapshot"),
            withdrawal: WithdrawalData {
                binding: receipt.binding.into_array(),
                scope: receipt.scope_digest.into_array(),
                head: receipt.head_digest.into_array(),
                file_digest: receipt.file_digest.into_array(),
                records: receipt.records,
                encoded_bytes: receipt.encoded_bytes,
            },
            selector_trust: selector,
            selection: SelectionData::from_original_selection(&artifacts.signed_selection)?,
            consumer: inputs.consumer,
            consumer_state_root: inputs.consumer_state_root.clone(),
            issuer_keys: inputs
                .issuer_keys
                .iter()
                .map(|key| IssuerKeyData {
                    key_id: key.key_id.clone(),
                    verifying_key: key.verifying_key,
                    not_before_authority_epoch: key.not_before_authority_epoch,
                    not_after_authority_epoch: key.not_after_authority_epoch,
                })
                .collect(),
            trigger: directory.join("trigger.json"),
        };
        let bytes = serde_json::to_vec(&descriptor).map_err(io::Error::other)?;
        let decoded: InitialDeploymentData =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        assert_eq!(
            decoded.selection.original_selection()?,
            artifacts.signed_selection
        );
        assert_eq!(decoded.target.generation, inputs.target.config.generation);
        for field in [
            "previous",
            "previous_journal",
            "learning",
            "late_material",
            "scope_override",
        ] {
            let mut injected: serde_json::Value =
                serde_json::from_slice(&bytes).map_err(io::Error::other)?;
            injected
                .as_object_mut()
                .expect("original descriptor object")
                .insert(field.into(), serde_json::json!({}));
            assert!(serde_json::from_value::<InitialDeploymentData>(injected).is_err());
        }
        let path = directory.join("initial-deployment.json");
        write_initial_metadata(&path, &bytes)?;
        let files = Self::open_original_initial_deployment(&path)?;
        assert!(!files.data.trigger.exists());

        // Replacing an otherwise identical owned metadata file must not be
        // mistaken for the original retained descriptor. Probe only test files.
        let probe = directory.join("metadata-probe.json");
        write_initial_metadata(&probe, b"{}")?;
        let (original, _) = MetadataFile::open_metadata(&probe)?;
        fs::rename(&probe, directory.join("metadata-original.json"))?;
        write_initial_metadata(&probe, b"{}")?;
        assert!(original.require_metadata_unchanged().is_err());
        files.require_original_initial_files()?;
        Ok(files)
    }
}

impl RootGenerationInitialDeploymentV1 {
    pub(crate) fn component_trigger_initial(&self) -> io::Result<()> {
        let trigger = InitialTrigger {
            session: self.session.clone(),
        };
        self.require_initial_trigger(&trigger)?;
        let mut wrong = trigger.session.clone();
        wrong.purpose = "hepta.generation.learned-publication.wrong-purpose".into();
        assert!(
            self.require_initial_trigger(&InitialTrigger { session: wrong })
                .is_err()
        );
        let mut old = trigger.session.clone();
        old.attempt = old
            .attempt
            .checked_sub(1)
            .expect("positive Initial attempt");
        assert!(
            self.require_initial_trigger(&InitialTrigger { session: old })
                .is_err()
        );
        let mut old = trigger.session.clone();
        old.root_start_ticks = old
            .root_start_ticks
            .checked_add(1)
            .expect("component start ticks");
        assert!(
            self.require_initial_trigger(&InitialTrigger { session: old })
                .is_err()
        );
        let stopped = AtomicBool::new(/*val*/ true);
        assert_eq!(
            self.require_initial_wait(&stopped, Instant::now() + Duration::from_secs(1))
                .expect_err("cancelled Initial trigger must reject")
                .kind(),
            io::ErrorKind::Interrupted
        );
        let waiting = AtomicBool::new(/*val*/ false);
        assert_eq!(
            self.require_initial_wait(&waiting, Instant::now())
                .expect_err("late Initial trigger must reject")
                .kind(),
            io::ErrorKind::Interrupted
        );
        let bytes = serde_json::to_vec(&trigger).map_err(io::Error::other)?;
        write_initial_metadata(&self.files.data.trigger, &bytes)?;
        assert!(write_initial_metadata(&self.files.data.trigger, &bytes).is_err());
        Ok(())
    }
}
