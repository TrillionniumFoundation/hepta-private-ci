//! Final-use-authorized TaskFlow effect seam.
//!
//! This adapter deliberately owns no provider authority and no background executor. A caller
//! supplies an already-signed final-use grant and a concrete synchronous provider seam. The
//! adapter durably prepares/claims the step first, consumes the authority nonce immediately
//! before dispatch, and durably records the returned terminal/indeterminate observation.

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Serialize;

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowStepCommandResult;
use crate::TaskFlowStepCommandStatus;
use crate::TaskFlowStepObservation;
use crate::TaskFlowStepState;

pub const TASKFLOW_AUTHORIZED_EFFECT_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TaskFlowEffectIntent {
    pub schema_version: u32,
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub operation_id: String,
    pub subject_id: String,
    pub destination_id: String,
    pub scope_sha256: Sha256Digest,
    pub payload_sha256: Sha256Digest,
    pub deadline_ms: u64,
}

impl TaskFlowEffectIntent {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        run_id: impl Into<String>,
        step_id: impl Into<String>,
        attempt: u32,
        operation_id: impl Into<String>,
        subject_id: impl Into<String>,
        destination_id: impl Into<String>,
        scope_sha256: Sha256Digest,
        payload: &[u8],
        deadline_ms: u64,
    ) -> Result<Self, TaskFlowEffectError> {
        let intent = Self {
            schema_version: TASKFLOW_AUTHORIZED_EFFECT_SCHEMA_VERSION,
            run_id: run_id.into(),
            step_id: step_id.into(),
            attempt,
            operation_id: operation_id.into(),
            subject_id: subject_id.into(),
            destination_id: destination_id.into(),
            scope_sha256,
            payload_sha256: Sha256Digest::for_bytes(payload),
            deadline_ms,
        };
        intent.validate()?;
        Ok(intent)
    }

    pub fn digest(&self) -> Result<Sha256Digest, TaskFlowEffectError> {
        let bytes = serde_json::to_vec(self).map_err(|_| TaskFlowEffectError::Invalid)?;
        Ok(Sha256Digest::for_bytes(&bytes))
    }

    pub fn final_use_binding(&self) -> Result<FinalUseBinding, TaskFlowEffectError> {
        Ok(FinalUseBinding {
            subject_id: self.subject_id.clone(),
            destination_id: self.destination_id.clone(),
            request_sha256: digest_bytes(&self.digest()?)?,
            scope_sha256: digest_bytes(&self.scope_sha256)?,
            payload_sha256: digest_bytes(&self.payload_sha256)?,
        })
    }

    fn validate(&self) -> Result<(), TaskFlowEffectError> {
        if self.schema_version != TASKFLOW_AUTHORIZED_EFFECT_SCHEMA_VERSION
            || self.attempt == 0
            || self.run_id.is_empty()
            || self.step_id.is_empty()
            || self.operation_id.is_empty()
            || self.subject_id.is_empty()
            || self.destination_id.is_empty()
            || self.run_id.len() > 256
            || self.step_id.len() > 256
            || self.operation_id.len() > 256
            || self.subject_id.len() > 128
            || self.destination_id.len() > 128
            || self.deadline_ms == 0
        {
            return Err(TaskFlowEffectError::Invalid);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TaskFlowProviderOutcome {
    Succeeded,
    Failed,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskFlowProviderObservation {
    pub receipt_digest: Sha256Digest,
    pub outcome: TaskFlowProviderOutcome,
}

impl TaskFlowProviderObservation {
    pub fn new(receipt_digest: Sha256Digest, outcome: TaskFlowProviderOutcome) -> Self {
        Self {
            receipt_digest,
            outcome,
        }
    }
}

/// The actual provider boundary must be synchronous with final-use release so
/// revocation cannot race between the last authority check and dispatch. A
/// provider that cannot determine whether dispatch happened must return an
/// `Indeterminate` observation, not an error that could be blindly retried.
pub trait TaskFlowEffectProvider: Send + Sync {
    fn dispatch(&self, intent: &TaskFlowEffectIntent, payload: &[u8])
        -> TaskFlowProviderObservation;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum TaskFlowEffectError {
    #[error("invalid TaskFlow effect input")]
    Invalid,
    #[error("TaskFlow step state rejected the effect")]
    TaskFlow,
    #[error("final-use authority rejected the effect: {0}")]
    Authority(FinalUseError),
}

impl AutomationStore {
    #[allow(clippy::too_many_arguments)]
    pub async fn execute_authorized_taskflow_effect<P: TaskFlowEffectProvider>(
        &self,
        authority: &FinalUseAuthority,
        provider: &P,
        fence: &TaskFlowFence,
        signed_grant: &SignedFinalUseGrant,
        intent: &TaskFlowEffectIntent,
        payload: &[u8],
        now_ms: u64,
    ) -> Result<TaskFlowStepCommandResult, TaskFlowEffectError> {
        intent.validate()?;
        if now_ms >= intent.deadline_ms
            || Sha256Digest::for_bytes(payload) != intent.payload_sha256
        {
            return Err(TaskFlowEffectError::Invalid);
        }
        let intent_digest = intent.digest()?;
        let binding = intent.final_use_binding()?;

        let prepare_command = format!("effect:{}:prepare", intent.operation_id);
        let claim_command = format!("effect:{}:claim", intent.operation_id);
        self.prepare_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fence,
            &intent_digest,
            &intent.payload_sha256,
            &prepare_command,
            now_ms,
        )
        .await
        .map_err(map_taskflow_error)?;

        // A fully observed replay is safe without touching the one-use grant.
        if let Some(receipt) = self
            .read_taskflow_step(&intent.run_id, &intent.step_id, intent.attempt, fence)
            .await
            .map_err(map_taskflow_error)?
        {
            if receipt.intent_digest != intent_digest
                || receipt.payload_digest != intent.payload_sha256
            {
                return Err(TaskFlowEffectError::TaskFlow);
            }
            if matches!(
                receipt.state,
                TaskFlowStepState::Recorded | TaskFlowStepState::Reconciled
            ) {
                return Ok(TaskFlowStepCommandResult {
                    status: TaskFlowStepCommandStatus::AlreadyApplied,
                    receipt,
                });
            }
        }

        self.claim_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fence,
            &intent_digest,
            &intent.payload_sha256,
            &claim_command,
            now_ms,
        )
        .await
        .map_err(map_taskflow_error)?;

        // The nonce is durably consumed before the provider call. If the
        // process dies after this point, this operation cannot be blindly
        // repeated with the same grant.
        let token = authority
            .claim(signed_grant, &binding)
            .map_err(TaskFlowEffectError::Authority)?;
        let observation = authority
            .with_verified_use(token, &binding, || provider.dispatch(intent, payload))
            .map_err(TaskFlowEffectError::Authority)?;
        let step_observation = match observation.outcome {
            TaskFlowProviderOutcome::Succeeded => TaskFlowStepObservation::Succeeded,
            TaskFlowProviderOutcome::Failed => TaskFlowStepObservation::Failed,
            TaskFlowProviderOutcome::Indeterminate => TaskFlowStepObservation::Indeterminate,
        };
        let record_command = format!(
            "effect:{}:observe:{}",
            intent.operation_id,
            observation.receipt_digest.as_str()
        );
        self.record_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            fence,
            &intent_digest,
            &intent.payload_sha256,
            &record_command,
            &observation.receipt_digest,
            step_observation,
            now_ms,
        )
        .await
        .map_err(map_taskflow_error)
    }
}

fn digest_bytes(digest: &Sha256Digest) -> Result<[u8; 32], TaskFlowEffectError> {
    let value = digest.as_str().as_bytes();
    if value.len() != 64 {
        return Err(TaskFlowEffectError::Invalid);
    }
    let mut bytes = [0_u8; 32];
    for (index, chunk) in value.chunks_exact(2).enumerate() {
        let text = std::str::from_utf8(chunk).map_err(|_| TaskFlowEffectError::Invalid)?;
        bytes[index] =
            u8::from_str_radix(text, 16).map_err(|_| TaskFlowEffectError::Invalid)?;
    }
    Ok(bytes)
}

fn map_taskflow_error(_error: TaskFlowError) -> TaskFlowEffectError {
    TaskFlowEffectError::TaskFlow
}
