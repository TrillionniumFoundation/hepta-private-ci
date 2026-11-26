//! Shared original CURRENT and checkpoint recovery logic; no writer capability.
use super::*;

pub(super) struct CurrentArtifactStoreV1<'a> {
    pub root: &'a Path,
    pub verifier: &'a ArtifactOwnerVerifierV1,
    pub required_current_head: Option<&'a SignedCurrentArtifactHeadV1>,
}

impl CurrentArtifactStoreV1<'_> {
    pub(super) fn current_registry_receipt(
        &self,
        current: &VerifiedCurrentArtifactHeadV1,
    ) -> Result<RegistrySnapshotReceipt, ArtifactOwnerHostError> {
        let mut matched: Option<RegistrySnapshotReceipt> = None;
        for checkpoint in read_checkpoint_entries(self.root)? {
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
        let registry = read_registry_snapshot(
            owner_observation::open_regular_existing(
                &self.registry_snapshot_path(receipt),
                8 * 1024 * 1024,
            )?,
            receipt,
        )?;
        if registry.snapshot().head_digest != current.signed.witness.head_digest {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        Ok(VerifiedCurrentRegistryViewV1::new(
            receipt,
            registry,
            current.witness_digest,
            current.trust_digest,
            self.verifier.current_validity(&current.signed, now)?,
        ))
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
        for entry in bounded_entries(&self.root.join("heads"), MAX_HEAD_RECORDS)? {
            if records.len() >= MAX_HEAD_RECORDS {
                return Err(ArtifactOwnerHostError::Capacity);
            }
            let metadata = fs::symlink_metadata(entry.path())?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(ArtifactOwnerHostError::CurrentHeadContext);
            }
            if entry.path().extension().and_then(|value| value.to_str()) != Some("head") {
                return Err(ArtifactOwnerHostError::CurrentHeadContext);
            }
            let signed =
                decode_signed_head(&read_small_record(&entry.path(), MAX_SMALL_RECORD_BYTES)?)?;
            if entry.path() != self.signed_head_record_path(&signed) {
                return Err(ArtifactOwnerHostError::CurrentHeadContext);
            }
            records.push(signed);
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
        let mut minimum_generation = self.verifier.trust.minimum_registry_generation;
        let mut minimum_epoch = self.verifier.trust.minimum_authority_epoch;
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
            minimum_generation = candidate
                .witness
                .generation
                .next()
                .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?;
            minimum_epoch = candidate.witness.authority_epoch;
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
            minimum_authority_epoch: self.verifier.trust.minimum_authority_epoch,
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

    pub(super) fn recover_publication(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<ArtifactOwnerRecoveryV1>, ArtifactOwnerHostError> {
        let mut latest = None;
        let mut missing_seen = false;
        let mut invariant: Option<(Digest32, Digest32, Digest32, Digest32)> = None;
        for phase in ordered_phases() {
            if phase == ArtifactPublicationPhaseV1::PayloadDurable
                && latest.as_ref().is_some_and(
                    |checkpoint: &ArtifactOwnerPublicationCheckpointV1| {
                        checkpoint.revocation.is_some()
                    },
                )
            {
                continue; // Revocation publishes no payload; its explicit v2 phases skip this step.
            }
            let path = self.checkpoint_path(operation_id, phase);
            if !path.exists() {
                missing_seen = true;
                continue;
            }
            if missing_seen {
                return Err(ArtifactOwnerHostError::CheckpointGap);
            }
            let bytes = read_small_record(&path, MAX_SMALL_RECORD_BYTES)?;
            let checkpoint = decode_checkpoint(&bytes)?;
            if checkpoint.operation_id != *operation_id || checkpoint.phase != phase {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            let key = (
                checkpoint.intent_digest,
                checkpoint.admission_digest,
                checkpoint.withdrawal_scope_digest,
                checkpoint.expected_registry_predecessor_head,
            );
            if invariant.is_some_and(|value| value != key) {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            invariant = Some(key);
            latest = Some(checkpoint);
        }
        Ok(latest.map(|checkpoint| ArtifactOwnerRecoveryV1 {
            requires_exact_snapshot: checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged,
            checkpoint,
            authority: AuthorityPosture::DENY_ALL,
        }))
    }

    pub(super) fn recovery_required_operations(
        &self,
    ) -> Result<Vec<ArtifactOwnerPublicationCheckpointV1>, ArtifactOwnerHostError> {
        let mut latest: BTreeMap<StableId, ArtifactOwnerPublicationCheckpointV1> = BTreeMap::new();
        for checkpoint in read_checkpoint_entries(self.root)? {
            match latest.get(&checkpoint.operation_id) {
                Some(existing) if phase_code(existing.phase) >= phase_code(checkpoint.phase) => {}
                Some(_) | None => {
                    latest.insert(checkpoint.operation_id.clone(), checkpoint);
                }
            }
        }
        Ok(latest
            .into_values()
            .filter(|checkpoint| checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged)
            .collect())
    }
}
