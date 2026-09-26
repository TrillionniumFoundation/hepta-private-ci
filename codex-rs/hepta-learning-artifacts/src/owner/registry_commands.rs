use codex_hepta_types::Digest32;

use crate::VerifiedCurrentRegistryViewV1;

use super::capability_validation::LearningArtifactHostActionV1;
use super::capability_validation::SignedLearningArtifactHostCommandV1;
use super::reference_host::LearningArtifactReferenceHostError;
use super::reference_host::LearningArtifactReferenceHostV1;
use super::reference_host::error_digest;
use super::transaction::digest_learning_artifact_current_view_request_v1;

impl LearningArtifactReferenceHostV1 {
    pub fn current_registry_view(
        &mut self,
        command: &SignedLearningArtifactHostCommandV1,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, LearningArtifactReferenceHostError> {
        let request_digest = digest_learning_artifact_current_view_request_v1(now);
        let verified = self.authorize(
            command,
            LearningArtifactHostActionV1::CurrentRegistryView,
            request_digest,
            now,
        )?;
        if let Err(error) = self.require_ready() {
            let digest = error_digest(&error);
            self.record_rejected(&verified, digest, now)?;
            return Err(error);
        }
        match self.service.current_registry_view(now) {
            Ok(view) => {
                let receipt = view.receipt();
                let mut bytes = b"hepta.learning-artifacts.host-current-view-result.v1".to_vec();
                bytes.extend_from_slice(receipt.binding.as_array());
                bytes.extend_from_slice(receipt.head_digest.as_array());
                bytes.extend_from_slice(receipt.file_digest.as_array());
                bytes.extend_from_slice(&(receipt.records as u64).to_be_bytes());
                bytes.extend_from_slice(&(receipt.encoded_bytes as u64).to_be_bytes());
                bytes.extend_from_slice(view.witness_digest().as_array());
                bytes.extend_from_slice(view.trust_digest().as_array());
                self.record_applied(&verified, Digest32::of_bytes(&bytes), now)?;
                Ok(view)
            }
            Err(error) => {
                let digest = error_digest(&error);
                self.record_rejected(&verified, digest, now)?;
                Err(error.into())
            }
        }
    }

    #[must_use]
    pub fn current_registry_view_request_digest(now: u64) -> Digest32 {
        digest_learning_artifact_current_view_request_v1(now)
    }
}
