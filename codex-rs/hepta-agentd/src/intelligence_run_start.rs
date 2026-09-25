//! Bind canonical computation to the already authenticated durable RunStart.
//! Never turn a computation budget into a fresh objective deadline, or replace
//! the selected artifact/body identities with a newly constructed facade hash.
use super::AgentdIntelligenceProductError;
use super::AgentdIntelligenceProductRunnerV1;
use super::PreparedAgentdIntelligenceRunV1;
use super::wall_clock_ms;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::RunSnapshot;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use std::sync::Arc;
use std::time::Duration;
use tokio::time::timeout;

impl AgentdIntelligenceProductRunnerV1 {
    /// The same bounded worker pool owns input-production work. A timed-out
    /// provider cannot release its permit while still doing blocking work.
    pub(crate) async fn build_invocation(
        &self,
        provider: Arc<dyn AgentdIntelligenceInvocationProviderV1>,
        identity: AgentdIdentity,
        record: RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        let snapshot =
            RunSnapshot::from_revalidated_run_start(&record).map_err(crate::state::run_error)?;
        let now = wall_clock_ms().map_err(|error| AgentdError::Protocol(error.to_string()))?;
        let remaining = snapshot
            .deadline_ms
            .min(record.authentication.expires_at_ms)
            .checked_sub(now)
            .filter(|value| *value > 0)
            .ok_or_else(|| {
                AgentdError::Invalid("RunStart expired before owner input production".to_string())
            })?;
        let mut worker = self
            .spawn_owner_work(move || {
                let invocation = provider.build(&identity, &record)?;
                invocation.validate(&identity, &record)?;
                Ok(invocation)
            })
            .map_err(|error| AgentdError::Protocol(error.to_string()))?;
        // Input preparation is bounded separately from the later seven-stage
        // computation, always within the durable objective/admission horizon.
        timeout(
            Duration::from_millis(remaining).min(crate::control_budget::OWNER_INPUT_TIMEOUT),
            &mut worker,
        )
        .await
        .map_err(|_| {
            worker.abort();
            AgentdError::Protocol("canonical owner input production timed out".to_string())
        })?
        .map_err(|_| AgentdError::Protocol("canonical owner input worker failed".to_string()))?
    }
}

impl PreparedAgentdIntelligenceRunV1 {
    /// Called only after the daemon has revalidated the original signed owner
    /// record. This is a projection/binding, not an authentication substitute.
    pub(crate) fn bind_revalidated_run_start(
        &mut self,
        record: &RunStartRecordV1,
        now_ms: u64,
    ) -> Result<(), AgentdIntelligenceProductError> {
        let snapshot = RunSnapshot::from_revalidated_run_start(record)
            .map_err(AgentdIntelligenceProductError::Run)?;
        if self.envelope.run_id != record.snapshot.run_id
            || self.envelope.objective_digest != record.snapshot.objective_digest
            || self.snapshot.objective_digest() != record.snapshot.objective_digest
            || self.snapshot.configuration_digest()
                != AgentdIntelligenceInvocationV1::configuration_digest(record)
            || self.snapshot.authority_epoch() != snapshot.authority_epoch
            || self.snapshot.body_generation().get() != snapshot.generation
            || self.run_snapshot.generation != snapshot.generation
            || self.run_snapshot.fence_digest != snapshot.fence_digest
            || now_ms >= snapshot.deadline_ms
            || now_ms >= record.authentication.expires_at_ms
        {
            return Err(AgentdIntelligenceProductError::RunStartBinding);
        }
        let dispatch_digest = Digest32::of_parts(&[
            b"hepta.agentd.intelligence-run-start-dispatch.v1\0",
            self.envelope.envelope_digest.as_array(),
            self.snapshot.digest().as_array(),
            record.authentication.signed_body_digest.as_array(),
            record.admission.admitted_source_digest.as_array(),
            record.runtime_body_digest.as_array(),
            record.snapshot.artifact_set_digest.as_array(),
            record.snapshot.fence_digest.as_array(),
            &snapshot.deadline_ms.to_be_bytes(),
        ]);
        let attachment = crate::AgentContextAttachment {
            run_id: snapshot.run_id.clone(),
            request_digest: snapshot.request_digest.clone(),
            objective_digest: snapshot.objective_digest.clone(),
            body_digest: snapshot.body_digest.clone(),
            artifact_set_digest: snapshot.artifact_set_digest.clone(),
            authority_epoch: snapshot.authority_epoch,
            generation: snapshot.generation,
            fence_digest: snapshot.fence_digest.clone(),
            deadline_ms: snapshot.deadline_ms,
            context_digest: self.context_attachment.context_digest.clone(),
            compilation_receipt_digest: self.context_attachment.compilation_receipt_digest.clone(),
        };
        self.run_snapshot = snapshot.into();
        self.context_attachment = attachment;
        self.dispatch_proposal_digest = dispatch_digest;
        Ok(())
    }
}
