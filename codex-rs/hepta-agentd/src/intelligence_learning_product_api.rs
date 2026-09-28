//! Public product-safe methods over the durable intelligence learning host.
//!
//! These methods are the supported product surface for dispatch/reconciliation.
//! They acquire current wall-clock time inside Agentd and derive operation
//! identities from the sealed prepared run and immutable learning payload.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::*;

impl AgentdIntelligenceLearningHostV1 {
    pub async fn dispatch_next_current(
        &self,
    ) -> Result<Option<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1>
    {
        self.dispatch_next_at(current_validation_time()?).await
    }

    pub async fn reconcile_unsettled_current(
        &self,
        limit: u32,
    ) -> Result<Vec<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1> {
        self.reconcile_unsettled_at(limit, current_validation_time()?)
            .await
    }

    pub fn decision_operation_id_for(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        episode_id: &StableId,
    ) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
        let snapshot = prepared.run_snapshot();
        decision_operation_id(
            &parse_id(&snapshot.run_id)?,
            episode_id.as_str(),
            intelligence_run_snapshot_digest_v1(prepared)?,
            prepared.envelope.decision.decision_digest,
        )
    }

    pub fn outcome_operation_id_for(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
        request: &AgentdIntelligenceOutcomeAppendV1,
    ) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
        let snapshot = prepared.run_snapshot();
        let physical_binding = intelligence_physical_terminal_binding_digest_v1(
            prepared,
            &request.run_receipt,
            request.provider_terminal_digest,
        )?;
        outcome_operation_id(
            &parse_id(&snapshot.run_id)?,
            request.outcome.outcome_id.as_str(),
            physical_binding,
        )
    }
}

fn current_validation_time() -> Result<u64, AgentdIntelligenceLearningErrorV1> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdIntelligenceLearningErrorV1::Invalid("learning validation clock"))?
        .as_millis();
    u64::try_from(millis)
        .ok()
        .filter(|value| *value != 0)
        .ok_or(AgentdIntelligenceLearningErrorV1::Invalid(
            "learning validation clock",
        ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn product_validation_clock_is_current_and_nonzero() {
        assert!(current_validation_time().expect("clock") > 0);
    }
}
