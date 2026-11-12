//! Preflight the sealed predecessor before a new CURRENT mutation. This check
//! exports no private writer, source grant or reconstructed completion token.

use super::*;

impl PublishedCircuitFeatureCompletionV1 {
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
