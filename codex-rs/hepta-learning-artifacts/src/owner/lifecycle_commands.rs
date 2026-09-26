use codex_hepta_types::Digest32;

use crate::DatasetWithdrawalRegistry;

use super::bootstrap::persist_withdrawal_anchor;
use super::capability_validation::LearningArtifactHostActionV1;
use super::capability_validation::SignedLearningArtifactHostCommandV1;
use super::reconciliation::LearningArtifactHostLifecycleV1;
use super::reference_host::LearningArtifactReferenceHostError;
use super::reference_host::LearningArtifactReferenceHostV1;
use super::reference_host::error_digest;
use super::transaction::digest_learning_artifact_withdrawal_frontier_v1;

impl LearningArtifactReferenceHostV1 {
    pub fn install_withdrawal_frontier(
        &mut self,
        command: &SignedLearningArtifactHostCommandV1,
        next: DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<(), LearningArtifactReferenceHostError> {
        let request_digest = digest_learning_artifact_withdrawal_frontier_v1(&next);
        let verified = self.authorize(
            command,
            LearningArtifactHostActionV1::InstallWithdrawalFrontier,
            request_digest,
            now,
        )?;
        if let Err(error) = self.require_ready() {
            let digest = error_digest(&error);
            self.record_rejected(&verified, digest, now)?;
            return Err(error);
        }
        if let Err(error) = validate_monotonic_frontier(self.service.withdrawal_registry(), &next) {
            let digest = error_digest(&error);
            self.record_rejected(&verified, digest, now)?;
            return Err(error);
        }
        let receipt = match persist_withdrawal_anchor(
            &self.root,
            &self.control_root,
            &next,
            self.storage_binding,
            &self.durability,
        ) {
            Ok(receipt) => receipt,
            Err(error) => {
                self.lifecycle = LearningArtifactHostLifecycleV1::Faulted;
                let digest = error_digest(&error);
                self.record_indeterminate(&verified, digest, now)?;
                return Err(error);
            }
        };
        if let Err(error) = self.service.install_withdrawal_frontier(next) {
            self.lifecycle = LearningArtifactHostLifecycleV1::Faulted;
            let digest = error_digest(&error);
            self.record_indeterminate(&verified, digest, now)?;
            return Err(error.into());
        }
        self.withdrawal_receipt = receipt;
        let mut bytes = b"hepta.learning-artifacts.host-withdrawal-result.v1".to_vec();
        bytes.extend_from_slice(receipt.head_digest.as_array());
        bytes.extend_from_slice(receipt.file_digest.as_array());
        bytes.extend_from_slice(&(receipt.records as u64).to_be_bytes());
        self.record_applied(&verified, Digest32::of_bytes(&bytes), now)?;
        Ok(())
    }

    #[must_use]
    pub fn withdrawal_frontier_request_digest(
        registry: &DatasetWithdrawalRegistry,
    ) -> Digest32 {
        digest_learning_artifact_withdrawal_frontier_v1(registry)
    }
}

fn validate_monotonic_frontier(
    current: &DatasetWithdrawalRegistry,
    next: &DatasetWithdrawalRegistry,
) -> Result<(), LearningArtifactReferenceHostError> {
    if current.scope_digest() != next.scope_digest() {
        return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
    }
    let current = current.snapshot();
    let next = next.snapshot();
    if next.records().len() < current.records().len()
        || &next.records()[..current.records().len()] != current.records()
    {
        return Err(LearningArtifactReferenceHostError::WithdrawalAnchorConflict);
    }
    Ok(())
}
