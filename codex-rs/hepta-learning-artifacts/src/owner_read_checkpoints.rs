//! Read complete historical checkpoints without owning publication authority.
use super::*;
impl ArtifactOwnerReadContext<'_> {
    pub(super) fn recover_publication(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<ArtifactOwnerRecoveryV1>, ArtifactOwnerHostError> {
        let recovery = self.recover_checkpoint_chain(operation_id)?;
        if let Some(recovery) = &recovery
            && let Some(receipt) = recovery.checkpoint.registry_receipt
        {
            let registry =
                read_registry_snapshot(File::open(self.registry_snapshot_path(receipt))?, receipt)?;
            self.validate_checkpoint_registry(&recovery.checkpoint, &registry)?;
        }
        Ok(recovery)
    }
    pub(super) fn recover_checkpoint_chain(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<ArtifactOwnerRecoveryV1>, ArtifactOwnerHostError> {
        let mut latest = None;
        let mut missing_seen = false;
        let mut invariant = None;
        let mut recovered_admission: Option<WithdrawalBoundArtifactAdmissionV3> = None;
        for phase in ordered_phases() {
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
                checkpoint.withdrawal_head_digest,
                checkpoint.expected_registry_predecessor_head,
                checkpoint.original_writer_lease_digest,
            );
            if invariant.is_some_and(|value| value != key) {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            invariant = Some(key);
            let admission = match &recovered_admission {
                Some(admission) => admission.clone(),
                None => {
                    let admission = self.validate_checkpoint_admission(&checkpoint)?;
                    recovered_admission = Some(admission.clone());
                    admission
                }
            };
            records::validate_checkpoint(&checkpoint, admission, latest.as_ref())?;
            latest = Some(checkpoint);
        }
        Ok(latest.map(|checkpoint| ArtifactOwnerRecoveryV1 {
            requires_exact_snapshot: checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged,
            checkpoint,
            authority: AuthorityPosture::DENY_ALL,
        }))
    }
}
