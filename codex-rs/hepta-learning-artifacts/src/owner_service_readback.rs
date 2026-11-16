//! The service's exact-operation read path never invokes publication or resume.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerHost;
use crate::OriginalArtifactPublicationReadbackErrorV1;
use crate::OriginalArtifactPublicationReadbackV1;

impl LearningArtifactOwnerService {
    /// Read an already started original operation and its actual CURRENT.
    ///
    /// Retain the original operation and intent before dispatch. Missing or
    /// mismatched original bytes are errors, not permission to call publish.
    /// Pending phases remain pending. This leaves registry, withdrawal state
    /// and recovery_required unchanged and never completes an interrupted write.
    pub fn read_original_publication_current(
        &self,
        operation_id: &StableId,
        expected_intent_digest: Digest32,
    ) -> Result<OriginalArtifactPublicationReadbackV1, OriginalArtifactPublicationReadbackErrorV1>
    {
        let observed = LearningArtifactOwnerHost::read_original_publication_current(
            &self.host,
            operation_id,
            expected_intent_digest,
        )?;
        if observed.current().receipt().binding != self.storage_binding
            || Some(observed.checkpoint().withdrawal_scope_digest)
                != self.withdrawal_registry.scope_digest()
        {
            return Err(OriginalArtifactPublicationReadbackErrorV1::InvalidExpectation);
        }
        Ok(observed)
    }
}
