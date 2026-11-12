//! The private fresh-writer entrance for the independent HEAD protocol.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::ArtifactOwnerHostError;
use super::LearningArtifactOwnerHost;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::WithdrawalBoundArtifactAdmissionV3;

impl LearningArtifactOwnerHost {
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
