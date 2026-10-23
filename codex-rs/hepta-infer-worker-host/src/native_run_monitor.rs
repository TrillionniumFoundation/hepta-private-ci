//! Current-process tracking of the original Agentd intelligence handoff.
//!
//! This is not a durable run owner or cancellation permission. Every field is
//! checked against the original control receipt; the existing coordinator and
//! native dispatch journal retain their original responsibilities.

use codex_hepta_agentd::AgentCancellationDisposition;
use codex_hepta_agentd::AgentRunCancellation;
use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_types::Digest32;
use std::str::FromStr;

use super::NativeIntelligenceRunBinding;
use super::NativeWorkerConfig;

#[derive(Clone, Debug, Eq, PartialEq)]
struct RunBinding {
    run_id: String,
    context_digest: String,
    envelope_digest: String,
    authority_epoch: u64,
    generation: u64,
    fence_digest: String,
    deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct RetainedIntelligenceRun {
    binding: RunBinding,
    revision: u64,
}

pub(super) struct OwnerRunObservation<'a> {
    pub(super) owner: &'a AgentdClient,
    pub(super) intelligence: Option<&'a mut RetainedIntelligenceRun>,
}

#[derive(Debug, Eq, PartialEq)]
pub(super) enum RunObservation {
    Dispatched,
    Cancelling,
}

#[derive(Debug)]
pub(super) enum ObservationFailure {
    Existing(String),
    OwnerCancelling,
    RunUnresolved(String),
}

impl From<String> for ObservationFailure {
    fn from(reason: String) -> Self {
        Self::Existing(reason)
    }
}

impl ObservationFailure {
    pub(super) fn reason(&self) -> &str {
        match self {
            Self::Existing(reason) | Self::RunUnresolved(reason) => reason,
            Self::OwnerCancelling => "owning Agentd run is cancelling",
        }
    }
}

impl RetainedIntelligenceRun {
    pub(super) fn from_handoff(
        config: &NativeWorkerConfig,
        expected: &NativeIntelligenceRunBinding,
        receipt: AgentRunReceipt,
    ) -> Result<Self, String> {
        // Agentd's Running lifecycle is exactly spawn + 1. Keep the process
        // spawn for control requests, and retain the actual admitted run epoch.
        let generation = config
            .generation
            .checked_add(1)
            .ok_or("Agentd running generation overflow")?;
        let mut fence = b"hepta:agentd:objective-fence:v1\0".to_vec();
        fence.extend_from_slice(config.agent_id.as_str().as_bytes());
        fence.extend_from_slice(&config.generation.to_be_bytes());
        fence.extend_from_slice(&generation.to_be_bytes());
        if receipt.run_id != expected.run_id
            || receipt.revision != expected.expected_revision
            || receipt.revision == 0
            || receipt.phase != AgentRunPhase::ContextAttached
            || receipt.context_digest.as_deref() != Some(expected.context_digest.as_str())
            || receipt.compilation_receipt_digest.as_deref()
                != Some(expected.envelope_digest.as_str())
            || receipt.authority_epoch == 0
            || receipt.generation != generation
            || receipt.fence_digest != Digest32::of_bytes(&fence).to_string()
            || receipt.deadline_ms == 0
            || receipt.terminal_observed
            || receipt.cancel_reason.is_some()
            || receipt.cancel_ack_deadline_ms.is_some()
        {
            return Err("Agentd intelligence handoff is stale or mixed".to_string());
        }
        for digest in [&expected.context_digest, &expected.envelope_digest] {
            if Digest32::from_str(digest)
                .map_err(|_| "invalid intelligence handoff digest")?
                .is_zero()
            {
                return Err("zero intelligence handoff digest".to_string());
            }
        }
        Ok(Self {
            binding: RunBinding {
                run_id: receipt.run_id,
                context_digest: expected.context_digest.clone(),
                envelope_digest: expected.envelope_digest.clone(),
                authority_epoch: receipt.authority_epoch,
                generation: receipt.generation,
                fence_digest: receipt.fence_digest,
                deadline_ms: receipt.deadline_ms,
            },
            revision: receipt.revision,
        })
    }

    pub(super) fn run_id(&self) -> &str {
        &self.binding.run_id
    }

    pub(super) fn revision(&self) -> u64 {
        self.revision
    }

    pub(super) fn validate_receipt(&self, receipt: &AgentRunReceipt) -> Result<(), String> {
        if receipt.run_id != self.binding.run_id
            || receipt.context_digest.as_deref() != Some(self.binding.context_digest.as_str())
            || receipt.compilation_receipt_digest.as_deref()
                != Some(self.binding.envelope_digest.as_str())
            || receipt.authority_epoch != self.binding.authority_epoch
            || receipt.generation != self.binding.generation
            || receipt.fence_digest != self.binding.fence_digest
            || receipt.deadline_ms != self.binding.deadline_ms
            || receipt.revision < self.revision
            || receipt.terminal_observed
                != matches!(
                    receipt.phase,
                    AgentRunPhase::Cancelled | AgentRunPhase::Succeeded | AgentRunPhase::Failed
                )
        {
            return Err(
                "Agentd run observation lost the retained intelligence binding".to_string(),
            );
        }
        Ok(())
    }

    pub(super) fn accept_dispatch(&mut self, receipt: &AgentRunReceipt) -> Result<(), String> {
        self.validate_receipt(receipt)?;
        if receipt.phase != AgentRunPhase::Dispatched
            || receipt.idempotent
            || self.revision.checked_add(1) != Some(receipt.revision)
            || receipt.cancel_reason.is_some()
            || receipt.cancel_ack_deadline_ms.is_some()
        {
            return Err("Agentd did not newly commit this exact intelligence dispatch".to_string());
        }
        self.revision = receipt.revision;
        Ok(())
    }

    pub(super) fn observe(
        &mut self,
        receipt: Option<AgentRunReceipt>,
    ) -> Result<RunObservation, String> {
        let receipt = receipt.ok_or("bound Agentd run projection is missing")?;
        self.validate_receipt(&receipt)?;
        match receipt.phase {
            AgentRunPhase::Dispatched
                if receipt.revision == self.revision
                    && receipt.cancel_reason.is_none()
                    && receipt.cancel_ack_deadline_ms.is_none() =>
            {
                Ok(RunObservation::Dispatched)
            }
            AgentRunPhase::Cancelling
                if self.revision.checked_add(1) == Some(receipt.revision)
                    && valid_cancel_reason(receipt.cancel_reason.as_deref())
                    && receipt
                        .cancel_ack_deadline_ms
                        .is_some_and(|value| value != 0) =>
            {
                self.revision = receipt.revision;
                Ok(RunObservation::Cancelling)
            }
            // Even a terminal coordinator projection does not supply the
            // original App Server's thread/turn correlation witness.
            AgentRunPhase::Admitted
            | AgentRunPhase::ContextAttached
            | AgentRunPhase::Dispatched
            | AgentRunPhase::Cancelling
            | AgentRunPhase::Cancelled
            | AgentRunPhase::Succeeded
            | AgentRunPhase::Failed
            | AgentRunPhase::Indeterminate => {
                Err("bound Agentd run requires terminal reconciliation".to_string())
            }
        }
    }

    pub(super) fn accept_cancellation(
        &mut self,
        cancellation: &AgentRunCancellation,
    ) -> Result<(), String> {
        let receipt = &cancellation.receipt;
        self.validate_receipt(receipt)?;
        let accepted = match cancellation.disposition {
            AgentCancellationDisposition::CancellingAfterDispatch => {
                receipt.phase == AgentRunPhase::Cancelling
                    && self.revision.checked_add(1) == Some(receipt.revision)
                    && valid_cancel_reason(receipt.cancel_reason.as_deref())
                    && receipt
                        .cancel_ack_deadline_ms
                        .is_some_and(|value| value != 0)
            }
            AgentCancellationDisposition::AlreadyTerminal => {
                receipt.terminal_observed && receipt.revision > self.revision
            }
            // This tracker is created before the one logical dispatch and is
            // used for cancellation only after that dispatch was acknowledged.
            AgentCancellationDisposition::CancelledBeforeDispatch => false,
        };
        if !accepted {
            return Err("Agentd cancellation lost the dispatched run boundary".to_string());
        }
        self.revision = receipt.revision;
        Ok(())
    }
}

fn valid_cancel_reason(reason: Option<&str>) -> bool {
    reason.is_some_and(|value| {
        !value.trim().is_empty() && value.len() <= 512 && !value.as_bytes().contains(&0)
    })
}

#[cfg(test)]
#[path = "native_run_monitor_tests.rs"]
mod tests;
