//! Immutable revocation publication through the same owner, snapshot format,
//! signature authority and CURRENT chain as artifact admission.
use super::*;

const TRANSITION_MAGIC: &str = "HEPTA-ARTIFACT-REGISTRY-TRANSITION-V1";

impl LearningArtifactOwnerHost {
    /// Resolve bytes only from this fenced owner's live CURRENT, never from a
    /// caller-supplied snapshot. A historical signed selection must be renewed
    /// after CURRENT advances, even when the selected bytes have not changed.
    pub fn read_current_selected_payload(
        &self,
        selector: &crate::ArtifactSelectionVerifierV1,
        selection: &crate::SignedArtifactSelectionV1,
        now: u64,
    ) -> Result<(ArtifactManifest, Vec<u8>), ArtifactOwnerHostError> {
        let current = self.current_registry_view(now)?;
        let verified = selector
            .verify(selection, &current, now)
            .map_err(|_| ArtifactOwnerHostError::CurrentHeadConflict)?;
        let manifest = verified.manifest();
        self.read_registered_manifest(manifest, now)?;
        let path = self.root.join("payloads").join(format!(
            "{}-{}.bin",
            manifest.artifact_id, manifest.content_digest
        ));
        if fs::symlink_metadata(&path)?.file_type().is_symlink() {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        let bytes =
            read_candidate_payload(File::open(path)?, current.registry(), &manifest.artifact_id)?;
        Ok((manifest.clone(), bytes))
    }

    /// Commit one revocation under an independently signed next CURRENT head.
    /// The head is the commit point. Exact retries reconcile a crash after head
    /// publication; uncommitted snapshot/receipt files never become current.
    pub fn publish_revocation(
        &mut self,
        change: crate::StateChange,
        signed: &SignedCurrentArtifactHeadV1,
        now: u64,
    ) -> Result<RegistrySnapshotReceipt, ArtifactOwnerHostError> {
        self.require_current_writer(now)?;
        let current = self
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        if current.signed == *signed {
            let receipt = self
                .current_transition_receipt(&current)?
                .ok_or(ArtifactOwnerHostError::CurrentHeadConflict)?;
            let registry =
                read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))?, receipt)?;
            if registry.records().last().map(|r| &r.event) != Some(&ArtifactEvent::Revoke(change)) {
                return Err(ArtifactOwnerHostError::IdentityConflict);
            }
            return Ok(receipt);
        }
        if !self.recovery_required_operations()?.is_empty() {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.verifier.trust.registry_id.clone(),
            minimum_generation: current
                .signed
                .witness
                .generation
                .next()
                .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?,
            expected_predecessor_head_digest: current.signed.witness.head_digest,
            minimum_authority_epoch: current.signed.witness.authority_epoch,
            now,
        };
        self.verifier
            .verify_signed_head(signed, &requirement, true)?;
        if signed.binding != current.signed.binding {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let mut registry = self.recover_current_registry(now)?;
        let before = registry.records().len();
        registry.append(ArtifactEvent::Revoke(change))?;
        if registry.records().len() != before + 1
            || registry.records().last().map(|r| r.chain_digest) != Some(signed.witness.head_digest)
        {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let bytes = encode_snapshot(&registry, signed.binding)?;
        let receipt = RegistrySnapshotReceipt {
            binding: signed.binding,
            head_digest: signed.witness.head_digest,
            file_digest: Digest32::of_bytes(&bytes),
            records: registry.records().len(),
            encoded_bytes: bytes.len(),
        };
        let relative = PathBuf::from("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        ));
        match write_registry_snapshot_beneath(&self.root, &relative, &registry, signed.binding) {
            Ok(actual) if actual == receipt => {}
            Ok(_) => return Err(ArtifactOwnerHostError::CheckpointMismatch),
            Err(crate::ArtifactStorageError::AlreadyExists) => {
                read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))?, receipt)?;
            }
            Err(error) => return Err(error.into()),
        }
        sync_owner_directory(&self.root.join("registries"))?;
        let text = format!(
            "{TRANSITION_MAGIC}\n{}\n{}\n{}\n{}\n{}\n",
            receipt.binding,
            receipt.head_digest,
            receipt.file_digest,
            receipt.records,
            receipt.encoded_bytes
        );
        write_create_only_or_exact(&self.transition_path(receipt.head_digest), text.as_bytes())?;
        self.persist_signed_head_record(signed)?;
        let committed = self
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        if committed.signed != *signed {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        self.current_transition_receipt(&committed)?
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)
    }

    fn transition_path(&self, head: Digest32) -> PathBuf {
        self.root
            .join("transactions")
            .join(format!("{head}.registry-transition"))
    }

    pub(super) fn current_transition_receipt(
        &self,
        current: &VerifiedCurrentArtifactHeadV1,
    ) -> Result<Option<RegistrySnapshotReceipt>, ArtifactOwnerHostError> {
        let Some((receipt, registry)) =
            self.transition_registry(current.signed.witness.head_digest)?
        else {
            return Ok(None);
        };
        if receipt.binding != current.signed.binding
            || registry
                .records()
                .last()
                .map(|r| r.predecessor_chain_digest)
                != Some(current.signed.witness.predecessor_head_digest)
        {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        Ok(Some(receipt))
    }

    pub(super) fn transition_registry(
        &self,
        head: Digest32,
    ) -> Result<Option<(RegistrySnapshotReceipt, ArtifactRegistry)>, ArtifactOwnerHostError> {
        let path = self.transition_path(head);
        match fs::symlink_metadata(&path) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(e.into()),
            Ok(meta) if !meta.is_file() || meta.file_type().is_symlink() => {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            Ok(_) => {}
        }
        let bytes = read_small_record(&path, MAX_SMALL_RECORD_BYTES)?;
        let text =
            std::str::from_utf8(&bytes).map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?;
        let fields: Vec<_> = text.lines().collect();
        if fields.len() != 6 || fields[0] != TRANSITION_MAGIC {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        let receipt = RegistrySnapshotReceipt {
            binding: fields[1]
                .parse()
                .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?,
            head_digest: fields[2]
                .parse()
                .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?,
            file_digest: fields[3]
                .parse()
                .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?,
            records: fields[4]
                .parse()
                .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?,
            encoded_bytes: fields[5]
                .parse()
                .map_err(|_| ArtifactOwnerHostError::CheckpointMismatch)?,
        };
        if receipt.head_digest != head {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        let registry =
            read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))?, receipt)?;
        if !matches!(
            registry.records().last().map(|r| &r.event),
            Some(ArtifactEvent::Revoke(_))
        ) {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        Ok(Some((receipt, registry)))
    }
}
