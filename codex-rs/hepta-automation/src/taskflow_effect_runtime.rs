use std::future::Future;
use std::pin::Pin;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;

use crate::AutomationStore;
use crate::AutomationTaskId;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowStepCommandStatus;
use crate::TaskFlowStepObservation;
use crate::TaskFlowStepReceipt;

pub type TaskFlowEffectFuture<'a> =
    Pin<Box<dyn Future<Output = TaskFlowProviderObservation> + Send + 'a>>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskFlowAuthorizedDispatch {
    pub task_id: AutomationTaskId,
    pub occurrence: u64,
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub operation_id: String,
    pub provider_id: String,
    pub fence: TaskFlowFence,
    pub intent_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub binding: FinalUseBinding,
    pub signed_grant: SignedFinalUseGrant,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskFlowProviderRequest {
    pub task_id: AutomationTaskId,
    pub occurrence: u64,
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub operation_id: String,
    pub provider_id: String,
    pub intent_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub binding: FinalUseBinding,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskFlowProviderObservation {
    pub receipt_digest: Sha256Digest,
    pub observation: TaskFlowStepObservation,
    pub detail: Option<String>,
}

pub trait TaskFlowEffectProvider: Send + Sync {
    /// Dispatches one already-authorized operation. The non-serializable token
    /// must be consumed at the adapter's final-use seam. Any uncertainty after
    /// that seam must be returned as an indeterminate observation, never as a
    /// retryable error.
    fn dispatch(
        &self,
        token: VerifiedUseToken,
        request: TaskFlowProviderRequest,
    ) -> TaskFlowEffectFuture<'_>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TaskFlowAuthorizedDispatchResult {
    Observed(TaskFlowStepReceipt),
    NeedsReconciliation(TaskFlowStepReceipt),
}

#[derive(Debug, thiserror::Error)]
pub enum TaskFlowEffectRuntimeError {
    #[error("TaskFlow durable state rejected the operation: {0}")]
    TaskFlow(#[from] TaskFlowError),
    #[error("final-use authority rejected the operation: {0}")]
    FinalUse(#[from] FinalUseError),
    #[error("automation occurrence is not bound to this TaskFlow run")]
    OccurrenceBinding,
    #[error("final-use binding does not match provider or payload")]
    BindingMismatch,
    #[error("runtime command identifier is invalid")]
    CommandId,
    #[error("automation durable evidence write failed")]
    Automation,
}

impl AutomationStore {
    /// Durable step intent -> durable claim -> final-use verification ->
    /// provider dispatch -> durable observation. Replaying an already-applied
    /// claim never redispatches; it requires provider reconciliation instead.
    pub async fn dispatch_taskflow_step_with_final_use<P: TaskFlowEffectProvider>(
        &self,
        authority: &FinalUseAuthority,
        provider: &P,
        request: TaskFlowAuthorizedDispatch,
        now_ms: u64,
    ) -> Result<TaskFlowAuthorizedDispatchResult, TaskFlowEffectRuntimeError> {
        validate_dispatch_binding(&request)?;

        let occurrence = self
            .occurrence(request.task_id, request.occurrence)
            .await
            .map_err(|_| TaskFlowEffectRuntimeError::Automation)?
            .ok_or(TaskFlowEffectRuntimeError::OccurrenceBinding)?;
        if occurrence.taskflow_run_id.as_deref() != Some(request.run_id.as_str()) {
            return Err(TaskFlowEffectRuntimeError::OccurrenceBinding);
        }

        let prepare_command = command_id(&request.operation_id, "prepare")?;
        let claim_command = command_id(&request.operation_id, "claim")?;
        let record_command = command_id(&request.operation_id, "record")?;

        let prepared = self
            .prepare_taskflow_step(
                &request.run_id,
                &request.step_id,
                request.attempt,
                &request.fence,
                &request.intent_digest,
                &request.payload_digest,
                &prepare_command,
                now_ms,
            )
            .await?;
        if prepared.receipt.run_id != request.run_id
            || prepared.receipt.step_id != request.step_id
            || prepared.receipt.intent_digest != request.intent_digest
            || prepared.receipt.payload_digest != request.payload_digest
        {
            return Err(TaskFlowEffectRuntimeError::OccurrenceBinding);
        }

        let claimed = self
            .claim_taskflow_step(
                &request.run_id,
                &request.step_id,
                request.attempt,
                &request.fence,
                &request.intent_digest,
                &request.payload_digest,
                &claim_command,
                now_ms,
            )
            .await?;

        if claimed.status == TaskFlowStepCommandStatus::AlreadyApplied {
            return Ok(TaskFlowAuthorizedDispatchResult::NeedsReconciliation(
                claimed.receipt,
            ));
        }

        let token = authority.claim(&request.signed_grant, &request.binding)?;
        let provider_request = TaskFlowProviderRequest {
            task_id: request.task_id,
            occurrence: request.occurrence,
            run_id: request.run_id.clone(),
            step_id: request.step_id.clone(),
            attempt: request.attempt,
            operation_id: request.operation_id.clone(),
            provider_id: request.provider_id.clone(),
            intent_digest: request.intent_digest.clone(),
            payload_digest: request.payload_digest.clone(),
            binding: request.binding.clone(),
        };
        let observation = provider.dispatch(token, provider_request).await;

        let recorded = self
            .record_taskflow_step(
                &request.run_id,
                &request.step_id,
                request.attempt,
                &request.fence,
                &request.intent_digest,
                &request.payload_digest,
                &record_command,
                &observation.receipt_digest,
                observation.observation,
                now_ms,
            )
            .await?;

        let observation_name = match observation.observation {
            TaskFlowStepObservation::Succeeded => "succeeded",
            TaskFlowStepObservation::Failed => "failed",
            TaskFlowStepObservation::Indeterminate => "indeterminate",
        };
        self.record_provider_observation(
            request.task_id,
            request.occurrence,
            &request.provider_id,
            &request.operation_id,
            observation_name,
            request.payload_digest.as_str(),
            now_ms,
            observation.detail.as_deref(),
        )
        .await
        .map_err(|_| TaskFlowEffectRuntimeError::Automation)?;

        if observation.observation == TaskFlowStepObservation::Indeterminate {
            self.mark_occurrence_indeterminate(
                request.task_id,
                request.occurrence,
                now_ms,
                "provider_outcome_indeterminate",
            )
            .await
            .map_err(|_| TaskFlowEffectRuntimeError::Automation)?;
            Ok(TaskFlowAuthorizedDispatchResult::NeedsReconciliation(
                recorded.receipt,
            ))
        } else {
            Ok(TaskFlowAuthorizedDispatchResult::Observed(recorded.receipt))
        }
    }
}

fn command_id(operation_id: &str, suffix: &str) -> Result<String, TaskFlowEffectRuntimeError> {
    if operation_id.is_empty()
        || operation_id.len() > 240
        || operation_id.bytes().any(|byte| byte < 0x20)
    {
        return Err(TaskFlowEffectRuntimeError::CommandId);
    }
    let command = format!("{operation_id}:{suffix}");
    if command.len() > 256 {
        return Err(TaskFlowEffectRuntimeError::CommandId);
    }
    Ok(command)
}

fn validate_dispatch_binding(
    request: &TaskFlowAuthorizedDispatch,
) -> Result<(), TaskFlowEffectRuntimeError> {
    if request.provider_id.is_empty()
        || request.operation_id.is_empty()
        || request.binding.destination_id != request.provider_id
        || request.binding.payload_sha256 != digest_bytes(&request.payload_digest)?
    {
        return Err(TaskFlowEffectRuntimeError::BindingMismatch);
    }
    Ok(())
}

fn digest_bytes(digest: &Sha256Digest) -> Result<[u8; 32], TaskFlowEffectRuntimeError> {
    let bytes = digest.as_str().as_bytes();
    if bytes.len() != 64 {
        return Err(TaskFlowEffectRuntimeError::BindingMismatch);
    }
    let mut out = [0_u8; 32];
    for (index, slot) in out.iter_mut().enumerate() {
        let high = hex_nibble(bytes[index * 2])?;
        let low = hex_nibble(bytes[index * 2 + 1])?;
        *slot = (high << 4) | low;
    }
    Ok(out)
}

fn hex_nibble(value: u8) -> Result<u8, TaskFlowEffectRuntimeError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(TaskFlowEffectRuntimeError::BindingMismatch),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn digest_binding_decodes_exact_sha256_bytes() {
        let digest = Sha256Digest::parse("11".repeat(32)).expect("digest");
        assert_eq!(digest_bytes(&digest).expect("bytes"), [0x11; 32]);
    }

    #[test]
    fn command_ids_are_bounded() {
        assert!(command_id(&"x".repeat(250), "claim").is_err());
        assert_eq!(
            command_id("operation-1", "record").expect("command"),
            "operation-1:record"
        );
    }
}
