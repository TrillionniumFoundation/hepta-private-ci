use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

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
use crate::VerifiedFinalUseAuthority;
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DispatchState {
    Authorized,
    Observed,
    Indeterminate,
    NotAdmitted,
}

impl DispatchState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Authorized => "authorized",
            Self::Observed => "observed",
            Self::Indeterminate => "indeterminate",
            Self::NotAdmitted => "not_admitted",
        }
    }

    fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "authorized" => Ok(Self::Authorized),
            "observed" => Ok(Self::Observed),
            "indeterminate" => Ok(Self::Indeterminate),
            "not_admitted" => Ok(Self::NotAdmitted),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

#[derive(Clone, Debug)]
struct DispatchRecord {
    state: DispatchState,
    occurrence_id: String,
    run_id: String,
    step_id: String,
    attempt: u32,
    operation_id: String,
    intent_digest: Sha256Digest,
    payload_digest: Sha256Digest,
    authority_epoch: u64,
    verifier_receipt_digest: Sha256Digest,
    provider_receipt_digest: Option<Sha256Digest>,
    observation: Option<AutomationProviderObservation>,
}

/// Execute one provider-bearing TaskFlow step through the durable outbox.
///
/// The operation order is deliberately fixed:
/// prepare intent -> claim intent -> final-use verify -> durable dispatch
/// authorization -> provider dispatch -> durable provider outcome -> step
/// observation. A replay that finds an authorized dispatch without a durable
/// provider result treats the crash window as indeterminate and never invokes
/// the provider again.
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

    if matches!(
        current.state,
        TaskFlowStepState::Recorded | TaskFlowStepState::Reconciled
    ) {
        repair_occurrence_observation(store, &request, &current).await?;
        return Ok(DurableStepExecutionResult {
            step: current,
            provider_dispatched: false,
        });
    }
    if current.state != TaskFlowStepState::Claimed {
        return Err(AutomationError::Conflict);
    }

    if let Some(dispatch) = load_dispatch(store, &request).await? {
        validate_dispatch_binding(&dispatch, &request)?;
        return replay_dispatch(store, fence, &request, dispatch).await;
    }

    if request.authority.semantic_digest != request.intent_digest
        || request.authority.payload_digest != request.payload_digest
    {
        return Err(AutomationError::AccessDenied);
    }
    let verified =
        verify_final_use_authority(verifier, request.authority.clone(), request.now_ms).await?;
    persist_authorized_dispatch(store, &request, &verified).await?;

    let provider_request = ProviderDispatchRequest {
        occurrence_id: request.occurrence_id.clone(),
        run_id: request.run_id.clone(),
        step_id: request.step_id.clone(),
        attempt: request.attempt,
        operation_id: verified.operation_id().to_string(),
        intent_digest: request.intent_digest.clone(),
        payload_digest: request.payload_digest.clone(),
    };

    let provider_outcome = match provider.dispatch(provider_request, &verified).await {
        Ok(outcome) => outcome,
        Err(error) => {
            mark_dispatch_not_admitted(store, &request, request.now_ms).await?;
            return Err(error);
        }
    };

    let (receipt_digest, observation, state) = match provider_outcome {
        ProviderDispatchOutcome::Observed(receipt) => (
            receipt.receipt_digest,
            receipt.observation,
            DispatchState::Observed,
        ),
        ProviderDispatchOutcome::Indeterminate { observation_digest } => (
            observation_digest,
            AutomationProviderObservation::Indeterminate,
            DispatchState::Indeterminate,
        ),
    };
    persist_dispatch_outcome(
        store,
        &request,
        state,
        &receipt_digest,
        observation,
        request.now_ms,
    )
    .await?;

    let step =
        record_observation(store, fence, &request, &receipt_digest, observation).await?;
    Ok(DurableStepExecutionResult {
        step,
        provider_dispatched: true,
    })
}

async fn replay_dispatch(
    store: &AutomationStore,
    fence: &TaskFlowFence,
    request: &DurableStepExecutionRequest,
    dispatch: DispatchRecord,
) -> Result<DurableStepExecutionResult, AutomationError> {
    match dispatch.state {
        DispatchState::NotAdmitted => Err(AutomationError::Conflict),
        DispatchState::Authorized => {
            // The durable authorization proves the process reached the dispatch
            // boundary, but absence of a provider result cannot prove whether
            // the effect crossed the seam. Quarantine instead of redispatch.
            let uncertainty = dispatch_uncertainty_digest(&dispatch);
            persist_dispatch_outcome(
                store,
                request,
                DispatchState::Indeterminate,
                &uncertainty,
                AutomationProviderObservation::Indeterminate,
                request.now_ms,
            )
            .await?;
            let step = record_observation(
                store,
                fence,
                request,
                &uncertainty,
                AutomationProviderObservation::Indeterminate,
            )
            .await?;
            Ok(DurableStepExecutionResult {
                step,
                provider_dispatched: false,
            })
        }
        DispatchState::Observed | DispatchState::Indeterminate => {
            let receipt = dispatch
                .provider_receipt_digest
                .as_ref()
                .ok_or(AutomationError::Corrupt)?;
            let observation = dispatch.observation.ok_or(AutomationError::Corrupt)?;
            let step = record_observation(store, fence, request, receipt, observation).await?;
            Ok(DurableStepExecutionResult {
                step,
                provider_dispatched: false,
            })
        }
    }
}

async fn record_observation(
    store: &AutomationStore,
    fence: &TaskFlowFence,
    request: &DurableStepExecutionRequest,
    receipt_digest: &Sha256Digest,
    observation: AutomationProviderObservation,
) -> Result<TaskFlowStepReceipt, AutomationError> {
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
            receipt_digest,
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
            receipt_digest,
            observation,
            request.now_ms,
        )
        .await?;

    Ok(recorded.receipt)
}

async fn repair_occurrence_observation(
    store: &AutomationStore,
    request: &DurableStepExecutionRequest,
    step: &TaskFlowStepReceipt,
) -> Result<(), AutomationError> {
    if step.state != TaskFlowStepState::Recorded {
        return Ok(());
    }
    let (Some(receipt_digest), Some(observation)) = (&step.receipt_digest, step.observation) else {
        return Err(AutomationError::Corrupt);
    };
    let occurrence_observation = match observation {
        TaskFlowStepObservation::Succeeded => AutomationProviderObservation::Succeeded,
        TaskFlowStepObservation::Failed => AutomationProviderObservation::Failed,
        TaskFlowStepObservation::Indeterminate => AutomationProviderObservation::Indeterminate,
    };
    store
        .record_provider_observation(
            &request.occurrence_id,
            &request.run_id,
            &request.step_id,
            request.attempt,
            receipt_digest,
            occurrence_observation,
            request.now_ms,
        )
        .await?;
    Ok(())
}

async fn load_dispatch(
    store: &AutomationStore,
    request: &DurableStepExecutionRequest,
) -> Result<Option<DispatchRecord>, AutomationError> {
    let row = sqlx::query(
        "SELECT state, occurrence_id, run_id, step_id, attempt, operation_id,
                intent_digest, payload_digest, authority_epoch,
                verifier_receipt_digest, provider_receipt_digest, observation
         FROM automation_effect_dispatches
         WHERE owner_agent_id = ? AND run_id = ? AND step_id = ? AND attempt = ?",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(&request.run_id)
    .bind(&request.step_id)
    .bind(i64::from(request.attempt))
    .fetch_optional(store.taskflow_pool())
    .await
    .map_err(|_| AutomationError::Unavailable)?;
    row.map(|row| dispatch_from_row(&row)).transpose()
}

async fn persist_authorized_dispatch(
    store: &AutomationStore,
    request: &DurableStepExecutionRequest,
    authority: &VerifiedFinalUseAuthority,
) -> Result<(), AutomationError> {
    let inserted = sqlx::query(
        "INSERT INTO automation_effect_dispatches (
             owner_agent_id, occurrence_id, run_id, step_id, attempt, operation_id,
             intent_digest, payload_digest, authority_epoch, verifier_receipt_digest,
             state, authorized_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'authorized', ?)",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(&request.occurrence_id)
    .bind(&request.run_id)
    .bind(&request.step_id)
    .bind(i64::from(request.attempt))
    .bind(authority.operation_id())
    .bind(request.intent_digest.as_str())
    .bind(request.payload_digest.as_str())
    .bind(to_i64(authority.authority_epoch())?)
    .bind(authority.verifier_receipt_digest().as_str())
    .bind(to_i64(request.now_ms)?)
    .execute(store.taskflow_pool())
    .await
    .map_err(|error| {
        if is_constraint(&error) {
            AutomationError::Conflict
        } else {
            AutomationError::Unavailable
        }
    })?;
    if inserted.rows_affected() != 1 {
        return Err(AutomationError::Conflict);
    }
    Ok(())
}

async fn persist_dispatch_outcome(
    store: &AutomationStore,
    request: &DurableStepExecutionRequest,
    state: DispatchState,
    receipt_digest: &Sha256Digest,
    observation: AutomationProviderObservation,
    observed_at_ms: u64,
) -> Result<(), AutomationError> {
    if !matches!(state, DispatchState::Observed | DispatchState::Indeterminate) {
        return Err(AutomationError::Invalid);
    }
    let updated = sqlx::query(
        "UPDATE automation_effect_dispatches
         SET state = ?, provider_receipt_digest = ?, observation = ?, observed_at_ms = ?
         WHERE owner_agent_id = ? AND run_id = ? AND step_id = ? AND attempt = ?
           AND state = 'authorized'",
    )
    .bind(state.as_str())
    .bind(receipt_digest.as_str())
    .bind(observation.as_str())
    .bind(to_i64(observed_at_ms)?)
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(&request.run_id)
    .bind(&request.step_id)
    .bind(i64::from(request.attempt))
    .execute(store.taskflow_pool())
    .await
    .map_err(|_| AutomationError::Unavailable)?;
    if updated.rows_affected() != 1 {
        // A replay may race the original writer. Accept only an exact durable
        // outcome; otherwise fail closed.
        let current = load_dispatch(store, request)
            .await?
            .ok_or(AutomationError::Corrupt)?;
        if current.state != state
            || current.provider_receipt_digest.as_ref() != Some(receipt_digest)
            || current.observation != Some(observation)
        {
            return Err(AutomationError::Conflict);
        }
    }
    Ok(())
}

async fn mark_dispatch_not_admitted(
    store: &AutomationStore,
    request: &DurableStepExecutionRequest,
    observed_at_ms: u64,
) -> Result<(), AutomationError> {
    let updated = sqlx::query(
        "UPDATE automation_effect_dispatches
         SET state = 'not_admitted', observed_at_ms = ?
         WHERE owner_agent_id = ? AND run_id = ? AND step_id = ? AND attempt = ?
           AND state = 'authorized'",
    )
    .bind(to_i64(observed_at_ms)?)
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(&request.run_id)
    .bind(&request.step_id)
    .bind(i64::from(request.attempt))
    .execute(store.taskflow_pool())
    .await
    .map_err(|_| AutomationError::Unavailable)?;
    if updated.rows_affected() != 1 {
        return Err(AutomationError::Conflict);
    }
    Ok(())
}

fn validate_dispatch_binding(
    dispatch: &DispatchRecord,
    request: &DurableStepExecutionRequest,
) -> Result<(), AutomationError> {
    if dispatch.occurrence_id != request.occurrence_id
        || dispatch.run_id != request.run_id
        || dispatch.step_id != request.step_id
        || dispatch.attempt != request.attempt
        || dispatch.operation_id != request.authority.operation_id
        || dispatch.intent_digest != request.intent_digest
        || dispatch.payload_digest != request.payload_digest
        || dispatch.authority_epoch != request.authority.authority_epoch
    {
        return Err(AutomationError::Conflict);
    }
    Ok(())
}

fn dispatch_from_row(row: &sqlx::sqlite::SqliteRow) -> Result<DispatchRecord, AutomationError> {
    Ok(DispatchRecord {
        state: DispatchState::parse(
            &row.try_get::<String, _>("state")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        occurrence_id: row
            .try_get("occurrence_id")
            .map_err(|_| AutomationError::Corrupt)?,
        run_id: row.try_get("run_id").map_err(|_| AutomationError::Corrupt)?,
        step_id: row.try_get("step_id").map_err(|_| AutomationError::Corrupt)?,
        attempt: u32::try_from(
            row.try_get::<i64, _>("attempt")
                .map_err(|_| AutomationError::Corrupt)?,
        )
        .map_err(|_| AutomationError::Corrupt)?,
        operation_id: row
            .try_get("operation_id")
            .map_err(|_| AutomationError::Corrupt)?,
        intent_digest: Sha256Digest::parse(
            row.try_get::<String, _>("intent_digest")
                .map_err(|_| AutomationError::Corrupt)?,
        )
        .map_err(|_| AutomationError::Corrupt)?,
        payload_digest: Sha256Digest::parse(
            row.try_get::<String, _>("payload_digest")
                .map_err(|_| AutomationError::Corrupt)?,
        )
        .map_err(|_| AutomationError::Corrupt)?,
        authority_epoch: to_u64(
            row.try_get("authority_epoch")
                .map_err(|_| AutomationError::Corrupt)?,
        )?,
        verifier_receipt_digest: Sha256Digest::parse(
            row.try_get::<String, _>("verifier_receipt_digest")
                .map_err(|_| AutomationError::Corrupt)?,
        )
        .map_err(|_| AutomationError::Corrupt)?,
        provider_receipt_digest: row
            .try_get::<Option<String>, _>("provider_receipt_digest")
            .map_err(|_| AutomationError::Corrupt)?
            .map(Sha256Digest::parse)
            .transpose()
            .map_err(|_| AutomationError::Corrupt)?,
        observation: row
            .try_get::<Option<String>, _>("observation")
            .map_err(|_| AutomationError::Corrupt)?
            .map(|value| parse_observation(&value))
            .transpose()?,
    })
}

fn dispatch_uncertainty_digest(dispatch: &DispatchRecord) -> Sha256Digest {
    let canonical = format!(
        "hepta.automation.dispatch-uncertainty.v1\n{}\n{}\n{}\n{}\n{}\n{}\n{}",
        dispatch.occurrence_id,
        dispatch.run_id,
        dispatch.step_id,
        dispatch.attempt,
        dispatch.operation_id,
        dispatch.verifier_receipt_digest.as_str(),
        dispatch.payload_digest.as_str(),
    );
    Sha256Digest::for_bytes(canonical.as_bytes())
}

fn parse_observation(value: &str) -> Result<AutomationProviderObservation, AutomationError> {
    match value {
        "succeeded" => Ok(AutomationProviderObservation::Succeeded),
        "failed" => Ok(AutomationProviderObservation::Failed),
        "indeterminate" => Ok(AutomationProviderObservation::Indeterminate),
        _ => Err(AutomationError::Corrupt),
    }
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

fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation())
}

fn to_i64(value: u64) -> Result<i64, AutomationError> {
    i64::try_from(value).map_err(|_| AutomationError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, AutomationError> {
    u64::try_from(value).map_err(|_| AutomationError::Corrupt)
}
