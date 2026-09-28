//! Canonical intelligence product continuation from Agentd-owned run state.
//!
//! Canonical product capability requires a configured physical/learning
//! continuation. A runner/provider pair without that continuation is explicit
//! source-only compatibility mode and must not admit a half-closed canonical
//! run before falling back to the ordinary durable RunStart path.

use super::*;

impl AgentdState {
    /// Execute the complete canonical product path only when the configured
    /// provider also owns the physical/learning continuation. The continuation
    /// is resolved before seven-owner preparation or Agentd run admission so a
    /// source-only profile cannot publish `ContextAttached` and then stop at a
    /// misleading `canonical_ready` state.
    pub(crate) async fn start_canonical_intelligence_product_loop(
        &self,
        record: &RunStartRecordV1,
    ) -> Result<
        Option<(
            crate::AgentdIntelligenceAdmittedOutcomeV1,
            Option<crate::AgentdIntelligenceProductLoopReceiptV1>,
        )>,
        AgentdError,
    > {
        let continuation = match self.intelligence_invocation.get() {
            Some(provider) => match provider.product_continuation() {
                Some(value) => value,
                None => return Ok(None),
            },
            None => return Ok(None),
        };

        let Some(admitted) = self.start_canonical_intelligence(record).await? else {
            return Ok(None);
        };

        let product_loop = match &admitted {
            crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {
                prepared,
                run_receipt,
            } => Some(
                continuation
                    .continue_ready(prepared.clone(), run_receipt.clone())
                    .await?,
            ),
            crate::AgentdIntelligenceAdmittedOutcomeV1::Abstained
            | crate::AgentdIntelligenceAdmittedOutcomeV1::SlowPath => None,
        };

        Ok(Some((admitted, product_loop)))
    }
}
