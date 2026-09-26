use codex_hepta_types::Digest32;

use crate::ArtifactPublicationReceiptV1;
use crate::LearningArtifactPublishRequestV1;

use super::capability_validation::LearningArtifactHostActionV1;
use super::capability_validation::SignedLearningArtifactHostCommandV1;
use super::reconciliation::LearningArtifactHostLifecycleV1;
use super::reference_host::LearningArtifactReferenceHostError;
use super::reference_host::LearningArtifactReferenceHostV1;
use super::reference_host::error_digest;
use super::transaction::digest_learning_artifact_publish_request_v1;

impl LearningArtifactReferenceHostV1 {
    pub fn publish(
        &mut self,
        command: &SignedLearningArtifactHostCommandV1,
        request: LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactReferenceHostError> {
        let request_digest = digest_learning_artifact_publish_request_v1(&request);
        let verified = self.authorize(
            command,
            LearningArtifactHostActionV1::Publish,
            request_digest,
            request.now,
        )?;
        if let Err(error) = self.require_publishable(&request.operation_id) {
            let digest = error_digest(&error);
            self.record_rejected(&verified, digest, request.now)?;
            return Err(error);
        }
        let result = self.service.publish(request.clone());
        match result {
            Ok(receipt) => {
                if let Err(error) = self.durability.sync_publication(&self.root) {
                    self.lifecycle = LearningArtifactHostLifecycleV1::Faulted;
                    let digest = error_digest(&error);
                    self.record_indeterminate(&verified, digest, request.now)?;
                    return Err(error.into());
                }
                self.refresh_recovery_state();
                self.record_applied(&verified, receipt.state_digest, request.now)?;
                Ok(receipt)
            }
            Err(error) => {
                self.refresh_recovery_state();
                let digest = error_digest(&error);
                self.record_rejected(&verified, digest, request.now)?;
                Err(error.into())
            }
        }
    }

    #[must_use]
    pub fn publication_request_digest(
        request: &LearningArtifactPublishRequestV1,
    ) -> Digest32 {
        digest_learning_artifact_publish_request_v1(request)
    }
}
