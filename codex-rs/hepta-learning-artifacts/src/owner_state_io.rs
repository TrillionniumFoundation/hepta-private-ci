//! Snapshot and CURRENT-head I/O shared by owner state replay.

use super::*;

impl LearningArtifactOwnerHost {
    pub(super) fn verify_state_effects(
        &self,
        checkpoint: &StateCheckpoint,
    ) -> Result<(), ArtifactOwnerHostError> {
        if checkpoint.phase == StatePhase::Prepared {
            return Ok(());
        }
        read_registry_snapshot(
            File::open(self.registry_snapshot_path(checkpoint.registry_receipt))?,
            checkpoint.registry_receipt,
        )?;
        let predecessor = read_dataset_withdrawal_snapshot(
            File::open(self.root.join(storage::withdrawal_path(
                checkpoint.predecessor_withdrawal_receipt,
            )))?,
            checkpoint.predecessor_withdrawal_receipt,
        )?
        .snapshot();
        let next = read_dataset_withdrawal_snapshot(
            File::open(
                self.root
                    .join(storage::withdrawal_path(checkpoint.withdrawal_receipt)),
            )?,
            checkpoint.withdrawal_receipt,
        )?
        .snapshot();
        if next.records().len() < predecessor.records().len()
            || &next.records()[..predecessor.records().len()] != predecessor.records()
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        if checkpoint.phase == StatePhase::SnapshotsDurable {
            return Ok(());
        }
        let signed = &checkpoint.signed_head;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.verifier.trust.registry_id.clone(),
            minimum_generation: self.verifier.trust.minimum_registry_generation,
            expected_predecessor_head_digest: signed.witness.predecessor_head_digest,
            minimum_authority_epoch: self.verifier.trust.minimum_authority_epoch,
            now: signed.witness.issued_at,
        };
        let witness_path = self.root.join("witnesses").join(format!(
            "{}-{}.witness",
            signed.witness.generation.get(),
            checkpoint.witness_receipt.witness_digest
        ));
        if read_registry_head_witness(
            File::open(witness_path)?,
            checkpoint.witness_receipt,
            &requirement,
        )? != signed.witness
            || read_small_record(
                &self.signed_head_record_path(signed),
                MAX_SMALL_RECORD_BYTES,
            )? != encode_signed_head(signed)
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        Ok(())
    }

    pub(super) fn state_head_requirement(
        &self,
        signed: &SignedCurrentArtifactHeadV1,
        now: u64,
    ) -> Result<RegistryHeadRequirementV1, ArtifactOwnerHostError> {
        let current = self.discover_current_head(now)?;
        let (generation, epoch) = match current {
            Some(current) if current.signed == *signed => {
                (signed.witness.generation, signed.witness.authority_epoch)
            }
            Some(current)
                if current.signed.witness.head_digest == signed.witness.predecessor_head_digest =>
            {
                (
                    current
                        .signed
                        .witness
                        .generation
                        .next()
                        .map_err(|_| ArtifactOwnerHostError::CurrentHeadContext)?,
                    current.signed.witness.authority_epoch,
                )
            }
            Some(_) => return Err(ArtifactOwnerHostError::CurrentHeadConflict),
            None if signed.witness.predecessor_head_digest
                == self.verifier.trust.genesis_predecessor_head_digest =>
            {
                (
                    self.verifier.trust.minimum_registry_generation,
                    self.verifier.trust.minimum_authority_epoch,
                )
            }
            None => return Err(ArtifactOwnerHostError::CurrentHeadConflict),
        };
        Ok(RegistryHeadRequirementV1 {
            registry_id: self.verifier.trust.registry_id.clone(),
            minimum_generation: generation,
            expected_predecessor_head_digest: signed.witness.predecessor_head_digest,
            minimum_authority_epoch: epoch,
            now,
        })
    }

    pub(super) fn persist_state_snapshots(
        &self,
        checkpoint: &StateCheckpoint,
        registry: &ArtifactRegistry,
        withdrawal: &DatasetWithdrawalRegistry,
    ) -> Result<(), ArtifactOwnerHostError> {
        let registry_path = self.registry_snapshot_path(checkpoint.registry_receipt);
        let relative = registry_path
            .strip_prefix(&self.root)
            .map_err(|_| ArtifactOwnerHostError::PathBoundary)?;
        match write_registry_snapshot_beneath(
            &self.root,
            relative,
            registry,
            checkpoint.registry_receipt.binding,
        ) {
            Ok(receipt) if receipt == checkpoint.registry_receipt => {}
            Ok(_) => return Err(ArtifactOwnerHostError::CheckpointMismatch),
            Err(crate::ArtifactStorageError::AlreadyExists) => {
                read_registry_snapshot(File::open(&registry_path)?, checkpoint.registry_receipt)?;
            }
            Err(error) => return Err(error.into()),
        }
        recovery::synchronize_artifact_path(&registry_path)?;
        let relative = storage::withdrawal_path(checkpoint.withdrawal_receipt);
        match write_dataset_withdrawal_snapshot_beneath(
            &self.root,
            &relative,
            withdrawal,
            checkpoint.withdrawal_receipt.binding,
        ) {
            Ok(receipt) if receipt == checkpoint.withdrawal_receipt => {}
            Ok(_) => return Err(ArtifactOwnerHostError::CheckpointMismatch),
            Err(crate::ArtifactStorageError::AlreadyExists) => {
                read_dataset_withdrawal_snapshot(
                    File::open(self.root.join(&relative))?,
                    checkpoint.withdrawal_receipt,
                )?;
            }
            Err(error) => return Err(error.into()),
        }
        recovery::synchronize_artifact_path(&self.root.join(relative))?;
        Ok(())
    }

    pub(super) fn persist_state_witness(
        &self,
        checkpoint: &StateCheckpoint,
        signed: &SignedCurrentArtifactHeadV1,
        requirement: &RegistryHeadRequirementV1,
        now: u64,
    ) -> Result<(), ArtifactOwnerHostError> {
        let relative = PathBuf::from("witnesses").join(format!(
            "{}-{}.witness",
            signed.witness.generation.get(),
            checkpoint.witness_receipt.witness_digest
        ));
        match write_registry_head_witness_beneath(
            &self.root,
            &relative,
            &signed.witness,
            requirement,
            signed.binding,
        ) {
            Ok(receipt) if receipt == checkpoint.witness_receipt => {}
            Ok(_) => return Err(ArtifactOwnerHostError::CheckpointMismatch),
            Err(crate::ArtifactStorageError::AlreadyExists) => {
                let witness = read_registry_head_witness(
                    File::open(self.root.join(&relative))?,
                    checkpoint.witness_receipt,
                    requirement,
                )?;
                if witness != signed.witness {
                    return Err(ArtifactOwnerHostError::CurrentHeadConflict);
                }
            }
            Err(error) => return Err(error.into()),
        }
        recovery::synchronize_artifact_path(&self.root.join(relative))?;
        self.persist_signed_head_record(signed)?;
        if self.discover_current_head(now)?.map(|head| head.signed) != Some(signed.clone()) {
            return Err(ArtifactOwnerHostError::CurrentHeadConflict);
        }
        Ok(())
    }

    pub(super) fn validate_state_head(
        &self,
        request: &LearningArtifactStatePublishRequestV1,
        checkpoint: &StateCheckpoint,
    ) -> Result<(), ArtifactOwnerHostError> {
        let signed = &request.signed_current_head;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.verifier.trust.registry_id.clone(),
            minimum_generation: self.verifier.trust.minimum_registry_generation,
            expected_predecessor_head_digest: signed.witness.predecessor_head_digest,
            minimum_authority_epoch: self.verifier.trust.minimum_authority_epoch,
            now: signed.witness.issued_at,
        };
        let verified = self
            .verifier
            .verify_signed_head(signed, &requirement, false)?;
        if verified.witness_digest != checkpoint.witness_receipt.witness_digest
            || signed.binding != checkpoint.registry_receipt.binding
            || signed.witness.head_digest != checkpoint.registry_receipt.head_digest
            || read_small_record(
                &self.signed_head_record_path(signed),
                MAX_SMALL_RECORD_BYTES,
            )? != encode_signed_head(signed)
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        Ok(())
    }
}
