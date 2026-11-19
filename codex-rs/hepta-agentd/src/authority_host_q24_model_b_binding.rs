//! Attach only the same registered learning backend's actual B custodian.
//! This retains no writable file and performs no B work or Model admission.

use super::*;
use crate::OriginalRootIndependentBEvaluationFilesV1;
use crate::authority_host_service::RegisteredHostLearningCheckpointV1;
use std::sync::Arc;

impl RegisteredHostLearningCheckpointV1 {
    pub(crate) fn attach_original_model_b(
        &mut self,
        original: Arc<OriginalRootIndependentBEvaluationFilesV1>,
    ) -> io::Result<()> {
        original.require_original_learning(self)?;
        let factory = self
            .q24_model
            .as_mut()
            .ok_or_else(|| io::Error::other("original Model factory absent"))?;
        if factory.original_b.is_some()
            || factory.profile.wire_schema() != 2
            || serde_json::to_vec(&factory.learning).map_err(io::Error::other)?
                != serde_json::to_vec(&self.profile).map_err(io::Error::other)?
        {
            return Err(io::Error::other(
                "original Model and B learning custody differs",
            ));
        }
        factory.original_b = Some(original);
        Ok(())
    }
}
