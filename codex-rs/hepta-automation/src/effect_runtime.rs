use codex_hepta_contracts::Sha256Digest;

use crate::AutomationEffectProvider;
use crate::AutomationError;
use crate::AutomationProviderObservation;
use crate::AutomationStore;
use crate::FinalUseAuthorityRequest;
use crate::FinalUseAuthorityVerifier;
use crate::ProviderDispatchOutcome;
use crate::ProviderDispatchRequest;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowStepObservation;
use crate::TaskFlowStepReceipt;
use crate::TaskFlowStepState;
use crate::verify_final_use_authority;

#[derive(Clone, Debug)]
pub struct DurableStepExecutionRequest {
    pub occurrence_id: String,
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub intent_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub authority: FinalUseAuthorityRequest,
    pub command_id_prefix: String,
    pub now_ms: u64,
}

#[derive(Clone, Debug)]
pub struct DurableStepExecutionResult {
    pub step: TaskFlowStepReceipt,
    pub provider_dispatched: bool,
}

/// Execute one provider-bearing TaskFlow step through the durable outbox.
///
/// The operation order is deliberately fixed:
/// prepare intent -> claim intent -> final-use verify -> provider dispatch ->
/// durable observation. If the provider result is unknown, that fact is
/// recorded as indeterminate and this method never retries the provider.
/// Replaying an already-recorded step returns the durable receipt without
/// dispatching again.
pub async fn execute_durable_taskflow_step<V, P>(
    store: &AutomationStore,
    fence: &TaskFlowFence,
    verifier: &V,
    provider: &P,
    request: DurableStepExecutionRequest,
) -> Result<DurableStepExecutionResult, AutomationError>
where
    V: FinalUseAuthorityVerifier + ?Sized,
    P: AutomationEffectProvider + ?Sized,
{
    validate_request(&request)?;

    let occurrence = store
        .causal_occurrence(&request.occurrence_id)
        .await?
        .ok_or(AutomationError::Conflict)?;
    if occurrence.taskflow_run_id.as_deref() != Some(request.run_id.as_str()) {
        return Err(AutomationError::Conflict);
    }

    let prepare_command = format!("{}:prepare", request.command_id_prefix);
    store
        .prepare_taskflow_step(
            &request.run_id,
            &request.step_id,
            request.attempt,
            fence,
            &request.intent_digest,
            &request.payload_digest,
            &prepare_command,
            request.now_ms,
        )
        .await
        .map_err(map_taskflow_error)?;

    let claim_command = format!("{}:claim", request.command_id_prefix);
    store
        .claim_taskflow_step(
            &request.run_id,
            &request.step_id,
            request.attempt,
            fence,
            &request.intent_digest,
            &request.payload_digest,
            &claim_command,
            request.now_ms,
        )
        .await
        .map_err(map_taskflow_error)?;

    let current = store
        .read_taskflow_step(
            &request.run_id,
            &request.step_id,
            request.attempt,
            fence,
        )
        .await
        .map_err(map_taskflow_error)?
        .ok_or(AutomationError::Corrupt)?;

    if matches!(current.state, TaskFlowStepState::Recorded | TaskFlowStepState::Reconciled) {
        return Ok(DurableStepExecutionResult {
            step: current,
            provider_dispatched: false,
        });
    }
    if current.state != TaskFlowStepState::Claimed {
        return Err(AutomationError::Conflict);
    }

    if request.authority.semantic_digest != request.intent_digest
        || request.authority.payload_digest != request.payload_digest
    {
        return Err(AutomationError::AccessDenied);
    }
    let verified =
        verify_final_use_authority(verifier, request.authority.clone(), request.now_ms).await?;

    let provider_request = ProviderDispatchRequest {
        occurrence_id: request.occurrence_id.clone(),
        run_id: request.run_id.clone(),
        step_id: request.step_id.clone(),
        attempt: request.attempt,
        operation_id: verified.operation_id().to_string(),
        intent_digest: request.intent_digest.clone(),
        payload_digest: request.payload_digest.clone(),
    };

    let (receipt_digest, observation) = match provider.dispatch(provider_request, &verified).await? {
        ProviderDispatchOutcome::Observed(receipt) => {
            (receipt.receipt_digest, receipt.observation)
        }
        ProviderDispatchOutcome::Indeterminate { observation_digest } => (
            observation_digest,
            AutomationProviderObservation::Indeterminate,
        ),
    };

    let step_observation = match observation {
        AutomationProviderObservation::Succeeded => TaskFlowStepObservation::Succeeded,
        AutomationProviderObservation::Failed => TaskFlowStepObservation::Failed,
        AutomationProviderObservation::Indeterminate => TaskFlowStepObservation::Indeterminate,
    };

    let record_command = format!("{}:record", request.command_id_prefix);
    let recorded = store
        .record_taskflow_step(
            &request.run_id,
            &request.step_id,
            request.attempt,
            fence,
            &request.intent_digest,
            &request.payload_digest,
            &record_command,
            &receipt_digest,
            step_observation,
            request.now_ms,
        )
        .await
        .map_err(map_taskflow_error)?;

    store
        .record_provider_observation(
            &request.occurrence_id,
            &request.run_id,
            &request.step_id,
            request.attempt,
            &receipt_digest,
            observation,
            request.now_ms,
        )
        .await?;

    Ok(DurableStepExecutionResult {
        step: recorded.receipt,
        provider_dispatched: true,
    })
}

fn validate_request(request: &DurableStepExecutionRequest) -> Result<(), AutomationError> {
    if request.occurrence_id.is_empty()
        || request.run_id.is_empty()
        || request.step_id.is_empty()
        || request.attempt == 0
        || request.command_id_prefix.is_empty()
    {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

fn map_taskflow_error(error: TaskFlowError) -> AutomationError {
    match error {
        TaskFlowError::Unavailable => AutomationError::Unavailable,
        TaskFlowError::StaleFence => AutomationError::AccessDenied,
        TaskFlowError::Invalid(_) => AutomationError::Invalid,
        TaskFlowError::Conflict(_) | TaskFlowError::InvalidTransition(_) => {
            AutomationError::Conflict
        }
        TaskFlowError::Corrupt(_) => AutomationError::Corrupt,
    }
}
