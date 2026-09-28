//! Canonical intelligence product continuation from Agentd-owned run state.
//!
//! The existing `start_canonical_intelligence` method remains the sole owner of
//! seven-stage preparation plus run/context admission. This module can invoke a
//! host continuation only after that method has returned a `Ready` value whose
//! exact envelope is already frozen as `ContextAttached`.

use super::*;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct AgentdIntelligenceProductStartV1 {
    pub admitted: crate::AgentdIntelligenceAdmittedOutcomeV1,
    pub product_loop: Option<crate::AgentdIntelligenceProductLoopReceiptV1>,
}

impl AgentdState {
    /// Execute the configured canonical product continuation after the exact
    /// prepared run is already admitted. Absence of a continuation is explicit
    /// source-only compatibility mode and preserves the existing return value.
    pub(crate) async fn start_canonical_intelligence_product_loop(
        &self,
        record: &RunStartRecordV1,
    ) -> Result<Option<AgentdIntelligenceProductStartV1>, AgentdError> {
        let Some(admitted) = self.start_canonical_intelligence(record).await? else {
            return Ok(None);
        };

        let product_loop = match &admitted {
            crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {
                prepared,
                run_receipt,
            } => {
                let provider = self.intelligence_invocation.get().ok_or_else(|| {
                    AgentdError::Protocol(
                        "canonical intelligence provider disappeared after admission".to_string(),
                    )
                })?;
                match provider.product_continuation() {
                    Some(continuation) => Some(
                        continuation
                            .continue_ready(prepared.clone(), run_receipt.clone())
                            .await?,
                    ),
                    None => None,
                }
            }
            crate::AgentdIntelligenceAdmittedOutcomeV1::Abstained
            | crate::AgentdIntelligenceAdmittedOutcomeV1::SlowPath => None,
        };

        Ok(Some(AgentdIntelligenceProductStartV1 {
            admitted,
            product_loop,
        }))
    }
}
