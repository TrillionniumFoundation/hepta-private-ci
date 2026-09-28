//! Public product-safe methods over the durable intelligence learning host.
//!
//! These methods are the supported product surface for dispatch/reconciliation.
//! They acquire current wall-clock time inside Agentd and derive operation
//! identities from the sealed prepared run and immutable learning payload.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_operations::DurableOperationState;

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

    pub fn learning_scope_id_for(
        &self,
        prepared: &PreparedAgentdIntelligenceRunV1,
    ) -> Result<StableId, AgentdIntelligenceLearningErrorV1> {
        parse_id(&prepared.run_snapshot().run_id)
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

    /// Advance and inspect one exact durable operation. This method never treats
    /// enqueue, claim, dispatch or transport acknowledgement as ledger success.
    /// Only a persisted `Applied` terminal state returns `Acknowledged`.
    pub async fn settle_operation_current(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        maximum_steps: u32,
    ) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
        if maximum_steps == 0 || maximum_steps > MAX_RECONCILE_BATCH {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "operation settlement steps",
            ));
        }
        for _ in 0..maximum_steps {
            let record = self
                .operations
                .operation(scope_id, operation_id)
                .await?
                .ok_or_else(|| {
                    AgentdIntelligenceLearningErrorV1::Operation(
                        DurableOperationError::Missing(operation_id.clone()),
                    )
                })?;
            if record.state.is_terminal() {
                return terminal_receipt(record);
            }
            match record.state {
                DurableOperationState::Prepared => {
                    let _ = self.dispatch_next_current().await?;
                }
                DurableOperationState::Dispatching
                | DurableOperationState::Dispatched
                | DurableOperationState::Indeterminate => {
                    let _ = self
                        .reconcile_unsettled_current(maximum_steps)
                        .await?;
                }
                DurableOperationState::Applied
                | DurableOperationState::NotApplied
                | DurableOperationState::Quarantined => unreachable!(),
            }
        }

        let mut bytes = b"hepta.agentd.intelligence-learning-settlement-budget.v1\0".to_vec();
        push_id(&mut bytes, scope_id)?;
        push_id(&mut bytes, operation_id)?;
        bytes.extend_from_slice(&maximum_steps.to_be_bytes());
        Ok(AgentdIntelligenceLearningReceiptV1 {
            operation_id: operation_id.clone(),
            disposition: AgentdIntelligenceLearningDispositionV1::Indeterminate,
            evidence_digest: Digest32::of_bytes(&bytes),
            append: None,
        })
    }
}

fn terminal_receipt(
    record: codex_hepta_operations::DurableOperationRecord,
) -> Result<AgentdIntelligenceLearningReceiptV1, AgentdIntelligenceLearningErrorV1> {
    let evidence_digest = record.terminal_evidence_digest.ok_or(
        AgentdIntelligenceLearningErrorV1::Invalid("terminal operation evidence"),
    )?;
    let disposition = match record.state {
        DurableOperationState::Applied => AgentdIntelligenceLearningDispositionV1::Acknowledged,
        DurableOperationState::NotApplied => AgentdIntelligenceLearningDispositionV1::Rejected,
        DurableOperationState::Quarantined => AgentdIntelligenceLearningDispositionV1::Revoked,
        _ => {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "nonterminal operation settlement",
            ));
        }
    };
    Ok(AgentdIntelligenceLearningReceiptV1 {
        operation_id: record.intent.operation_id,
        disposition,
        evidence_digest,
        append: None,
    })
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
