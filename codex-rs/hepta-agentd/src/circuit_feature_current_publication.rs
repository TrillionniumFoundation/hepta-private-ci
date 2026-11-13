//! Preflight the sealed predecessor before a new CURRENT mutation. This check
//! exports no private writer, source grant or reconstructed completion token.

use super::*;

impl PublishedCircuitFeatureCompletionV1 {
    /// A's process and writers have exited. The actual opaque historical Root
    /// receipt rereads Source, Cell, RunStart, Ledger and completed handoff on
    /// both sides of this conversion. This yields only their completed fact;
    /// the later CURRENT owner must independently admit the same predecessor.
    #[cfg(target_os = "linux")]
    pub(crate) fn read_original_historical_completion(
        original: &crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1,
        manifest: CellBackendManifestV2,
    ) -> Result<Self, AgentdError> {
        crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1::with_current_feature_read(
            original,
            |binding, source, receipt| {
                if manifest.digest().map_err(std::io::Error::other)?
                    != binding.manifest_digest()
                    || manifest.bundle_digest != source.bundle_digest().into_array()
                    || receipt.checkpoint_after != source.checkpoint_digest()
                    || source.input().scope.agent_id.as_str() != binding.scope().agent_id
                    || source.input().scope.cell_id.as_str() != binding.scope().cell_id
                    || source.input().scope.run_id.as_str() != binding.scope().run_id
                    || source.input().scope.principal_digest.into_array()
                        != binding.scope().principal_digest
                {
                    return Err(std::io::Error::other(
                        "original historical Feature completion differs",
                    ));
                }
                source.require_decision(&receipt).map_err(std::io::Error::other)?;
                let completed = Self {
                    binding: binding.clone(),
                    manifest,
                    source,
                    receipt,
                };
                completed
                    .require_publication_predecessor(binding)
                    .map_err(std::io::Error::other)?;
                Ok(completed)
            },
        )
        .map_err(invalid)
    }

    pub(crate) fn require_publication_predecessor(
        &self,
        expected: &CellGenerationOwnerBindingV1,
    ) -> Result<(), AgentdError> {
        if &self.binding != expected
            || self.manifest.digest().map_err(invalid)? != expected.manifest_digest()
            || self.manifest.bundle_digest != self.source.bundle_digest().into_array()
            || self.receipt.checkpoint_after != self.source.checkpoint_digest()
        {
            return Err(invalid("actual completed Feature predecessor differs"));
        }
        Ok(())
    }
}
