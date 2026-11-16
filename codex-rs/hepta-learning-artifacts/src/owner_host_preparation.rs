//! The private fresh-writer entrance for the independent HEAD protocol.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::ArtifactOwnerHostError;
use super::LearningArtifactOwnerHost;
use super::checkpoint_from_snapshot;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::WithdrawalBoundArtifactAdmissionV3;

impl LearningArtifactOwnerHost {
    // A caller can construct a legacy transaction locally. Before any durable
    // effect, it must match the complete original checkpoint, including its
    // protocol-specific intent, phase/state and original writer lease. This
    // also prevents low-level host APIs from reviving a lost fresh continuation.
    pub(super) fn require_original_publication_checkpoint(
        &self,
        transaction: &ArtifactPublicationTransactionV1,
        phase: ArtifactPublicationPhaseV1,
    ) -> Result<(), ArtifactOwnerHostError> {
        if transaction.phase() != phase {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        let original = self
            .read_original_publication_checkpoint(&transaction.intent().operation_id)?
            .ok_or(ArtifactOwnerHostError::CheckpointMissing)?;
        // A legacy transaction may resume after the original host reopens
        // under a renewed valid writer lease. Match the saved phase against
        // its original lease, as resume_publication does; each caller has
        // already authenticated the current writer before reaching here.
        if original
            != checkpoint_from_snapshot(
                &transaction.snapshot(),
                original.original_writer_lease_digest,
            )
        {
            return Err(ArtifactOwnerHostError::CheckpointMismatch);
        }
        Ok(())
    }

    pub(crate) fn begin_original_registry_publication(
        &self,
        operation_id: StableId,
        admission: WithdrawalBoundArtifactAdmissionV3,
        withdrawals: &DatasetWithdrawalRegistry,
        registry: &ArtifactRegistry,
        predecessor: Digest32,
        now: u64,
    ) -> Result<ArtifactPublicationTransactionV1, ArtifactOwnerHostError> {
        let writer = self.require_current_writer(now)?;
        if admission.validated_manifest.manifest.producer_id != writer.producer_id
            || admission.withdrawal_scope_digest != self.verifier.trust.withdrawal_scope_digest
            || withdrawals.scope_digest() != Some(self.verifier.trust.withdrawal_scope_digest)
        {
            return Err(ArtifactOwnerHostError::WriterLeaseContext);
        }
        let transaction = ArtifactPublicationTransactionV1::begin_original_registry(
            operation_id,
            admission,
            withdrawals,
            registry,
            predecessor,
            now,
        )?;
        self.persist_checkpoint(&transaction)?;
        Ok(transaction)
    }
}
