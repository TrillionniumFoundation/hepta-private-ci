//! Shared immutable read context. This owns neither a writer lease nor a fence.
use super::*;
pub(super) struct ArtifactOwnerReadContext<'a> {
    pub(super) root: &'a PathBuf,
    pub(super) verifier: &'a ArtifactOwnerVerifierV1,
    pub(super) required_current_head: &'a Option<SignedCurrentArtifactHeadV1>,
}

impl ArtifactOwnerReadContext<'_> {
    pub(super) fn current_registry_receipt(
        &self,
        current: &VerifiedCurrentArtifactHeadV1,
    ) -> Result<RegistrySnapshotReceipt, ArtifactOwnerHostError> {
        let mut matched: Option<RegistrySnapshotReceipt> = None;
        for checkpoint in records::all_checkpoints(self)? {
            if phase_code(checkpoint.phase)
                < phase_code(ArtifactPublicationPhaseV1::RegistryDurable)
            {
                continue;
            }
            let Some(registry_receipt) = checkpoint.registry_receipt else {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            };
            if registry_receipt.head_digest != current.signed.witness.head_digest
                || registry_receipt.binding != current.signed.binding
            {
                continue;
            }
            if let Some(witness_receipt) = checkpoint.witness_receipt
                && (witness_receipt.witness_digest != current.witness_digest
                    || witness_receipt.binding != current.signed.binding)
            {
                return Err(ArtifactOwnerHostError::CurrentHeadConflict);
            }
            match matched {
                Some(existing) if existing != registry_receipt => {
                    return Err(ArtifactOwnerHostError::IdentityConflict);
                }
                Some(_) => {}
                None => matched = Some(registry_receipt),
            }
        }
        matched.ok_or(ArtifactOwnerHostError::CheckpointMissing)
    }
    pub(super) fn registry_snapshot_path(&self, receipt: RegistrySnapshotReceipt) -> PathBuf {
        self.root.join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        ))
    }
    pub(super) fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        let current = self
            .discover_current_head(now)?
            .ok_or(ArtifactOwnerHostError::CurrentHeadContext)?;
        let receipt = self.current_registry_receipt(&current)?;
        let registry =
            read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))?, receipt)?;
        if registry.head_digest() != current.signed.witness.head_digest {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        self.validate_current_registry_inventory(&registry)?;
        let mut view = VerifiedCurrentRegistryViewV1::new(
            receipt,
            registry,
            current.witness_digest,
            current.trust_digest,
        );
        let signer = self
            .verifier
            .head_signers
            .get(&current.signed.witness.signer_id)
            .ok_or(ArtifactOwnerHostError::UnknownSigner)?;
        view.bind_use_window(
            crate::VerifiedCurrentRegistryUseWindowV1::from_verified_head(
                &current.signed.witness,
                signer,
                now,
            ),
        );
        Ok(view)
    }
    pub(super) fn recover_current_registry(
        &self,
        now: u64,
    ) -> Result<ArtifactRegistry, ArtifactOwnerHostError> {
        let Some(current) = self.discover_current_head(now)? else {
            let registry = ArtifactRegistry::new();
            self.validate_current_registry_inventory(&registry)?;
            return Ok(registry);
        };
        let receipt = self.current_registry_receipt(&current)?;
        let registry =
            read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))?, receipt)?;
        if registry.head_digest() != current.signed.witness.head_digest {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        self.validate_current_registry_inventory(&registry)?;
        Ok(registry)
    }
    pub(super) fn discover_current_head(
        &self,
        now: u64,
    ) -> Result<Option<VerifiedCurrentArtifactHeadV1>, ArtifactOwnerHostError> {
        let latest = self.discover_current_head_unanchored(now)?;
        if let Some(anchor) = &self.required_current_head {
            self.enforce_required_current_head(anchor, latest.as_ref())?;
        }
        Ok(latest)
    }
    pub(super) fn discover_current_head_unanchored(
        &self,
        now: u64,
    ) -> Result<Option<VerifiedCurrentArtifactHeadV1>, ArtifactOwnerHostError> {
        let mut records = Vec::new();
        for (index, entry) in fs::read_dir(self.root.join("heads"))?.enumerate() {
            if index >= MAX_HEAD_RECORDS * 2 {
                return Err(ArtifactOwnerHostError::Capacity);
            }
            let entry = entry?;
            let metadata = fs::symlink_metadata(entry.path())?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(ArtifactOwnerHostError::CurrentHeadContext);
            }
            if entry.path().extension().and_then(|value| value.to_str()) != Some("head") {
                continue;
            }
            if records.len() >= MAX_HEAD_RECORDS {
                return Err(ArtifactOwnerHostError::Capacity);
            }
            records.push(decode_signed_head(&read_small_record(
                &entry.path(),
                MAX_SMALL_RECORD_BYTES,
            )?)?);
        }
        if records.is_empty() {
            return Ok(None);
        }

        let mut by_predecessor: BTreeMap<Digest32, Vec<SignedCurrentArtifactHeadV1>> =
            BTreeMap::new();
        for record in records {
            by_predecessor
                .entry(record.witness.predecessor_head_digest)
                .or_default()
                .push(record);
        }
        let mut predecessor = self.verifier.trust.genesis_predecessor_head_digest;
        // Live floors may advance after a replacement head is published. The
        // signed historical chain remains replayable under its original keys,
        // while every link must still increase generation and retain epoch.
        let mut minimum_generation =
            Generation::new(1).map_err(|_| ArtifactOwnerHostError::InternalInvariant)?;
        let mut minimum_epoch = 1;
        let mut minimum_issued_at = 0;
        let mut consumed = 0usize;
        let mut latest = None;
        while let Some(candidates) = by_predecessor.remove(&predecessor) {
            if candidates.len() != 1 {
                return Err(ArtifactOwnerHostError::CurrentHeadFork);
            }
            let candidate = candidates
                .into_iter()
                .next()
                .ok_or(ArtifactOwnerHostError::InternalInvariant)?;
            if candidate.witness.issued_at < minimum_issued_at {
                return Err(ArtifactOwnerHostError::CurrentHeadContext);
            }
            let historical_requirement = RegistryHeadRequirementV1 {
                registry_id: self.verifier.trust.registry_id.clone(),
                minimum_generation,
                expected_predecessor_head_digest: predecessor,
                minimum_authority_epoch: minimum_epoch,
                now: candidate.witness.issued_at,
            };
            let verified =
                self.verifier
                    .verify_signed_head(&candidate, &historical_requirement, false)?;
            predecessor = candidate.witness.head_digest;
            if by_predecessor.contains_key(&predecessor) {
                minimum_generation = candidate
                    .witness
                    .generation
                    .next()
                    .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?;
            }
            minimum_epoch = candidate.witness.authority_epoch;
            minimum_issued_at = candidate.witness.issued_at;
            consumed += 1;
            latest = Some(verified);
        }
        if by_predecessor.values().any(|values| !values.is_empty()) {
            return Err(ArtifactOwnerHostError::CurrentHeadFork);
        }
        if consumed == 0 {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        let latest = latest.ok_or(ArtifactOwnerHostError::InternalInvariant)?;
        if latest.signed.witness.generation < self.verifier.trust.minimum_registry_generation
            || latest.signed.witness.authority_epoch < self.verifier.trust.minimum_authority_epoch
        {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        let signer = self
            .verifier
            .head_signers
            .get(&latest.signed.witness.signer_id)
            .ok_or(ArtifactOwnerHostError::UnknownSigner)?;
        verify_signer_context(
            signer,
            latest.signed.witness.signing_key_digest,
            latest.signed.witness.authority_epoch,
            latest.signed.witness.issued_at,
            now,
            true,
        )?;
        if now > latest.signed.witness.expires_at {
            return Err(ArtifactOwnerHostError::CurrentHeadExpired);
        }
        Ok(Some(latest))
    }
    pub(super) fn checkpoint_path(
        &self,
        operation_id: &StableId,
        phase: ArtifactPublicationPhaseV1,
    ) -> PathBuf {
        let operation_digest = Digest32::of_bytes(operation_id.as_str().as_bytes());
        self.root.join("transactions").join(format!(
            "{}-{}.checkpoint",
            operation_digest,
            phase_code(phase)
        ))
    }
    pub(super) fn signed_head_record_path(&self, signed: &SignedCurrentArtifactHeadV1) -> PathBuf {
        self.root.join("heads").join(format!(
            "{}-{}.head",
            signed.witness.generation.get(),
            Digest32::of_bytes(&signed.signing_bytes())
        ))
    }
    pub(super) fn enforce_required_current_head(
        &self,
        anchor: &SignedCurrentArtifactHeadV1,
        latest: Option<&VerifiedCurrentArtifactHeadV1>,
    ) -> Result<(), ArtifactOwnerHostError> {
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.verifier.trust.registry_id.clone(),
            minimum_generation: anchor.witness.generation,
            expected_predecessor_head_digest: anchor.witness.predecessor_head_digest,
            minimum_authority_epoch: anchor.witness.authority_epoch,
            now: anchor.witness.issued_at,
        };
        self.verifier
            .verify_signed_head(anchor, &requirement, false)?;
        let path = self.signed_head_record_path(anchor);
        if !path.is_file()
            || read_small_record(&path, MAX_SMALL_RECORD_BYTES)? != encode_signed_head(anchor)
        {
            return Err(ArtifactOwnerHostError::CurrentHeadRollback);
        }
        let latest = latest.ok_or(ArtifactOwnerHostError::CurrentHeadRollback)?;
        if latest.signed.witness.generation < anchor.witness.generation
            || (latest.signed.witness.generation == anchor.witness.generation
                && latest.signed.witness.head_digest != anchor.witness.head_digest)
        {
            return Err(ArtifactOwnerHostError::CurrentHeadRollback);
        }
        Ok(())
    }
}
