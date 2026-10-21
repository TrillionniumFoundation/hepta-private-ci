//! Revocation uses the same named writer service and uncertain-I/O fence as
//! publication. An independently signed CURRENT authorizes the exact denial.
use super::*;
use crate::StateChange;

#[derive(Clone, Debug)]
pub struct LearningArtifactRevokeRequestV1 {
    pub operation_id: StableId,
    pub change: StateChange,
    pub signed_current_head: SignedCurrentArtifactHeadV1,
    pub expected_registry_predecessor_head: Digest32,
    pub now: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactRevocationReceiptV1 {
    pub operation_id: StableId,
    pub change: StateChange,
    pub registry_head_digest: Digest32,
    pub witness_digest: Digest32,
    pub state_digest: Digest32,
    pub acknowledged_at: u64,
    pub authority: AuthorityPosture,
}

impl LearningArtifactOwnerService {
    /// Append one irreversible registry Revoke and publish its authenticated
    /// CURRENT under the existing writer fence. Descendants become ineligible
    /// through the original registry lineage rules. This neither deletes
    /// material nor asserts an admission or release outcome.
    pub fn revoke(
        &mut self,
        request: LearningArtifactRevokeRequestV1,
    ) -> Result<ArtifactRevocationReceiptV1, LearningArtifactOwnerServiceError> {
        if let Some(blocked) = &self.recovery_required
            && blocked != &request.operation_id
        {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                blocked.clone(),
            ));
        }
        self.ensure_observation_guard()?;
        let operation_id = request.operation_id.clone();
        let fenced_retry = self.recovery_required.as_ref() == Some(&operation_id);
        let result = self.revoke_inner(&request);
        let result = match result {
            Ok(receipt) => {
                self.recovery_required = None;
                Ok(receipt)
            }
            Err(error) => {
                self.recovery_required = Some(operation_id.clone());
                let uncertain = matches!(
                    error,
                    LearningArtifactOwnerServiceError::Host(ArtifactOwnerHostError::Indeterminate)
                        | LearningArtifactOwnerServiceError::Host(ArtifactOwnerHostError::Storage(
                            crate::ArtifactStorageError::Indeterminate
                        ))
                );
                match self.host.recover_publication(&operation_id)? {
                    None if !uncertain && !fenced_retry => self.recovery_required = None,
                    Some(recovery)
                        if recovery.checkpoint.phase
                            == ArtifactPublicationPhaseV1::Acknowledged
                            && !uncertain
                            && !fenced_retry =>
                    {
                        self.recovery_required = None
                    }
                    Some(_) | None => {}
                }
                // An in-flight or uncertain write remains fenced. A rejected
                // request against an already-settled operation cannot turn a
                // known rejection into a new denial of service.
                Err(error)
            }
        };
        if self.recovery_required.is_none() {
            self.observation_guard = None;
        }
        result
    }

    fn revoke_inner(
        &mut self,
        request: &LearningArtifactRevokeRequestV1,
    ) -> Result<ArtifactRevocationReceiptV1, LearningArtifactOwnerServiceError> {
        if request.signed_current_head.binding != self.storage_binding
            || Some(request.signed_current_head.withdrawal_scope_digest)
                != self.withdrawal_registry.scope_digest()
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let predecessor = self
            .host
            .recover_registry_by_head(request.expected_registry_predecessor_head)?;
        let (checkpoint, _) = self.host.apply_revocation(
            request,
            &predecessor,
            self.withdrawal_registry.head_digest(),
        )?;
        // An acknowledged historical retry must not replace a newer in-memory
        // registry with its old staged snapshot.
        self.registry = self.host.recover_current_registry(request.now)?;
        let registry = checkpoint
            .registry_receipt
            .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
        let witness = checkpoint
            .witness_receipt
            .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
        Ok(ArtifactRevocationReceiptV1 {
            operation_id: checkpoint.operation_id,
            change: request.change.clone(),
            registry_head_digest: registry.head_digest,
            witness_digest: witness.witness_digest,
            state_digest: checkpoint.state_digest,
            acknowledged_at: checkpoint
                .acknowledged_at
                .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}
