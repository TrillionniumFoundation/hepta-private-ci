//! Bind local publication recovery to operation identity in registry history.
//!
//! A checkpoint's hashes do not authenticate its operation identity by
//! themselves. The canonical owner registration commits the complete intent,
//! including operation ID, in the independently signed registry chain.

use super::*;

pub(super) fn validate_witness_receipt(
    signed: &SignedCurrentArtifactHeadV1,
    witness_digest: Digest32,
    receipt: RegistryHeadWitnessReceipt,
) -> Result<(), ArtifactOwnerHostError> {
    // The authenticated signed head commits every input to this canonical
    // encoding. A receipt must describe those bytes exactly even if the
    // separately persisted witness copy is no longer available.
    let encoded = encode_head_witness(&signed.witness, signed.binding)?;
    let expected = RegistryHeadWitnessReceipt {
        binding: signed.binding,
        witness_digest,
        file_digest: Digest32::of_bytes(&encoded),
        encoded_bytes: encoded.len(),
    };
    if receipt != expected {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    Ok(())
}

pub(super) fn validate_intent_record(
    record: &crate::ArtifactRecord,
    intent: &crate::ArtifactPublicationIntentV1,
) -> Result<(), ArtifactOwnerHostError> {
    let v2 = &intent.admission.validated_manifest.manifest;
    let expected = ArtifactManifest {
        artifact_id: v2.artifact_id.clone(),
        kind: v2.kind,
        generation: v2.generation,
        predecessor_id: v2.predecessor_ids.first().cloned(),
        content_digest: v2.bytes_digest,
        objective_digest: v2.objective_class_digest,
        support_digest: intent.admission.validated_manifest.manifest_digest,
        producer_id: v2.producer_id.clone(),
        compatibility_digest: v2.compatibility_digest,
        encoded_size_bytes: v2.encoded_size_bytes,
    };
    let ArtifactEvent::Register { event_id, manifest } = &record.event else {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    };
    if event_id.as_str() != format!("artifact-publication:{}", intent.intent_digest)
        || manifest != &expected
        || record.predecessor_chain_digest != intent.expected_registry_predecessor_head
    {
        return Err(ArtifactOwnerHostError::CheckpointMismatch);
    }
    Ok(())
}

impl LearningArtifactOwnerHost {
    pub(super) fn validate_checkpoint_registry(
        &self,
        checkpoint: &ArtifactOwnerPublicationCheckpointV1,
        registry: &ArtifactRegistry,
    ) -> Result<(), ArtifactOwnerHostError> {
        let record = registry
            .records()
            .last()
            .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?;
        self.validate_checkpoint_record(checkpoint, record)
    }

    fn validate_checkpoint_record(
        &self,
        checkpoint: &ArtifactOwnerPublicationCheckpointV1,
        record: &crate::ArtifactRecord,
    ) -> Result<(), ArtifactOwnerHostError> {
        let receipt = checkpoint
            .registry_receipt
            .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?;
        if receipt.head_digest != record.chain_digest
            || u64::try_from(receipt.records).ok() != Some(record.sequence.get())
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        validate_intent_record(
            record,
            &crate::ArtifactPublicationIntentV1 {
                operation_id: checkpoint.operation_id.clone(),
                admission: self.validate_checkpoint_admission(checkpoint)?,
                expected_registry_predecessor_head: checkpoint.expected_registry_predecessor_head,
                intent_digest: checkpoint.intent_digest,
            },
        )
    }

    pub(super) fn validate_current_registry_inventory(
        &self,
        registry: &ArtifactRegistry,
    ) -> Result<(), ArtifactOwnerHostError> {
        let by_head = registry
            .records()
            .iter()
            .map(|record| (record.chain_digest, record))
            .collect::<BTreeMap<_, _>>();
        let mut latest = BTreeMap::<StableId, ArtifactOwnerPublicationCheckpointV1>::new();
        for checkpoint in records::all_checkpoints(self)? {
            if latest
                .get(&checkpoint.operation_id)
                .is_none_or(|previous| phase_code(previous.phase) < phase_code(checkpoint.phase))
            {
                latest.insert(checkpoint.operation_id.clone(), checkpoint);
            }
        }
        let mut pending = None;
        for checkpoint in latest.into_values() {
            let Some(receipt) = checkpoint.registry_receipt else {
                continue;
            };
            if let Some(record) = by_head.get(&receipt.head_digest) {
                self.validate_checkpoint_record(&checkpoint, record)?;
            } else {
                // Every witnessed historical publication must remain in the
                // CURRENT prefix. Only the one unfinished RegistryDurable
                // operation can have a snapshot not yet exposed as CURRENT.
                if checkpoint.phase != ArtifactPublicationPhaseV1::RegistryDurable {
                    return Err(ArtifactOwnerHostError::CheckpointMismatch);
                }
                if checkpoint.expected_registry_predecessor_head
                    != registry.records().last().map_or(
                        self.verifier.trust.genesis_predecessor_head_digest,
                        |record| record.chain_digest,
                    )
                {
                    return Err(ArtifactOwnerHostError::RegistryPredecessorMismatch);
                }
                if pending.replace(checkpoint).is_some() {
                    return Err(ArtifactOwnerHostError::CurrentHeadConflict);
                }
            }
        }
        if let Some(checkpoint) = pending {
            let receipt = checkpoint
                .registry_receipt
                .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?;
            let pending_registry =
                read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))?, receipt)?;
            self.validate_checkpoint_registry(&checkpoint, &pending_registry)?;
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "owner_registry_replay_tests.rs"]
mod tests;
