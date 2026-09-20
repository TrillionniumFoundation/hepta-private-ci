//! Qualification-only durable TaskFlow step outbox.
//!
//! The regular TaskFlow ledger records the run projection and its transition
//! chain.  It intentionally does not claim a provider/effect.  This module
//! adds the smallest durable seam needed by H3: one append-only, per-step
//! intent/receipt chain.  A prepared row is an outbox item; claim, observation
//! and reconciliation append receipts to that same chain.  No method here
//! invokes a provider, wakes a scheduler, or grants production authority.
//!
//! The table is created lazily by the explicitly opt-in qualification API.
//! This keeps the default automation schema/version unchanged while making the
//! qualification state durable across reopen.  Every read and mutation first
//! verifies the owner, run history, definition binding, event hash chain and
//! exact generation/fence tuple.

#![allow(
    clippy::too_many_arguments,
    reason = "the canonical step operation keeps every bound field explicit"
)]

use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowRun;
use crate::taskflow::load_taskflow_definition_tx;
use crate::taskflow::load_taskflow_run_tx;

/// This module is compiled and callable only by an explicit qualification
/// feature.  These constants are intentionally negative for all authority
/// surfaces.
pub const TASKFLOW_STEP_OUTBOX_QUALIFICATION_ENABLED: bool = true;
pub const TASKFLOW_STEP_OUTBOX_EFFECTS: bool = false;
pub const TASKFLOW_STEP_OUTBOX_PRODUCTION_CALLER: bool = false;
pub const TASKFLOW_STEP_OUTBOX_SCHEDULER_AUTHORITY: bool = false;

const STEP_SCHEMA_VERSION: u32 = 1;
const MAX_TEXT_BYTES: usize = 256;
const MAX_STEP_ATTEMPT: u32 = 1_000_000;
const ZERO_DIGEST: &str = "0000000000000000000000000000000000000000000000000000000000000000";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskFlowStepState {
    Prepared,
    Claimed,
    Recorded,
    Reconciled,
}

impl TaskFlowStepState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Prepared => "prepared",
            Self::Claimed => "claimed",
            Self::Recorded => "recorded",
            Self::Reconciled => "reconciled",
        }
    }

    fn parse(value: &str) -> Result<Self, TaskFlowError> {
        match value {
            "prepared" => Ok(Self::Prepared),
            "claimed" => Ok(Self::Claimed),
            "recorded" => Ok(Self::Recorded),
            "reconciled" => Ok(Self::Reconciled),
            _ => Err(corrupt("unknown TaskFlow step state")),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskFlowStepObservation {
    Succeeded,
    Failed,
    Indeterminate,
}

impl TaskFlowStepObservation {
    fn as_str(self) -> &'static str {
        match self {
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Indeterminate => "indeterminate",
        }
    }

    fn parse(value: &str) -> Result<Self, TaskFlowError> {
        match value {
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            "indeterminate" => Ok(Self::Indeterminate),
            _ => Err(corrupt("unknown TaskFlow step observation")),
        }
    }
}

/// The reconstructed state of one immutable `(run, step, attempt)` chain.
/// `receipt_digest` is an observed provider/evidence digest only; this type
/// never asserts that a provider accepted an effect.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TaskFlowStepReceipt {
    pub owner_agent_id: AgentId,
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub state: TaskFlowStepState,
    pub intent_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub fence: TaskFlowFence,
    pub event_seq: u64,
    pub last_command_id: String,
    pub receipt_digest: Option<Sha256Digest>,
    pub observation: Option<TaskFlowStepObservation>,
    pub final_outcome: Option<TaskFlowReconcileOutcome>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskFlowStepCommandStatus {
    Applied,
    AlreadyApplied,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TaskFlowStepCommandResult {
    pub status: TaskFlowStepCommandStatus,
    pub receipt: TaskFlowStepReceipt,
}

#[derive(Clone, Debug)]
struct StepEvent {
    event_seq: u64,
    event_kind: TaskFlowStepState,
    command_id: String,
    command_digest: String,
    intent_digest: String,
    payload_digest: String,
    receipt_digest: Option<String>,
    observation: Option<TaskFlowStepObservation>,
    final_outcome: Option<TaskFlowReconcileOutcome>,
    owner_id: String,
    owner_epoch: u64,
    generation: u64,
    fencing_token: String,
    previous_event_digest: String,
    event_digest: String,
    recorded_at_ms: u64,
}

#[derive(Serialize)]
struct OperationCanonical<'a> {
    schema_version: u32,
    operation: &'a str,
    owner_agent_id: &'a AgentId,
    run_id: &'a str,
    step_id: &'a str,
    attempt: u32,
    command_id: &'a str,
    intent_digest: &'a str,
    payload_digest: &'a str,
    owner_id: &'a str,
    owner_epoch: u64,
    generation: u64,
    fencing_token: &'a str,
    receipt_digest: Option<&'a str>,
    observation: Option<TaskFlowStepObservation>,
    final_outcome: Option<TaskFlowReconcileOutcome>,
    now_ms: u64,
}

#[derive(Serialize)]
struct EventCanonical<'a> {
    schema_version: u32,
    previous_event_digest: &'a str,
    owner_agent_id: &'a AgentId,
    run_id: &'a str,
    step_id: &'a str,
    attempt: u32,
    event_seq: u64,
    event_kind: TaskFlowStepState,
    command_id: &'a str,
    command_digest: &'a str,
    intent_digest: &'a str,
    payload_digest: &'a str,
    receipt_digest: Option<&'a str>,
    observation: Option<TaskFlowStepObservation>,
    final_outcome: Option<TaskFlowReconcileOutcome>,
    owner_id: &'a str,
    owner_epoch: u64,
    generation: u64,
    fencing_token: &'a str,
    recorded_at_ms: u64,
}

impl AutomationStore {
    /// Prepare one immutable step intent.  The prepared row is the durable
    /// outbox item; no provider or scheduler is called.
    pub async fn prepare_taskflow_step(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepCommandResult, TaskFlowError> {
        validate_common(
            run_id,
            step_id,
            attempt,
            command_id,
            intent_digest,
            payload_digest,
        )?;
        validate_fence(self, fence)?;
        ensure_step_schema(self).await?;
        let mut tx = self.begin_step_tx().await?;
        let run = load_run(&mut tx, self, run_id).await?;
        let definition = load_definition(&mut tx, self, &run).await?;
        validate_step_node(&definition, step_id)?;
        let events = load_step_events(&mut tx, self, run_id, step_id, attempt).await?;
        let command_digest = operation_digest(
            "prepare",
            self.taskflow_owner_agent_id(),
            run_id,
            step_id,
            attempt,
            command_id,
            intent_digest.as_str(),
            payload_digest.as_str(),
            fence,
            /*receipt_digest*/ None,
            /*observation*/ None,
            /*final_outcome*/ None,
            now_ms,
        )?;
        if let Some(existing) = existing_command(&events, command_id, command_digest.as_str())? {
            let receipt = reconstruct_step(
                self.taskflow_owner_agent_id(),
                run_id,
                step_id,
                attempt,
                &events,
            )?;
            tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(TaskFlowStepCommandResult {
                status: TaskFlowStepCommandStatus::AlreadyApplied,
                receipt: receipt_with_seq(receipt, existing.event_seq),
            });
        }
        check_active_run_fence(&run, fence, now_ms)?;
        if !events.is_empty() {
            return Err(TaskFlowError::Conflict(
                "TaskFlow step intent is already bound to different bytes".to_string(),
            ));
        }
        let event = append_step_event(
            &mut tx,
            self,
            run_id,
            step_id,
            attempt,
            TaskFlowStepState::Prepared,
            command_id,
            command_digest.as_str(),
            intent_digest.as_str(),
            payload_digest.as_str(),
            /*receipt_digest*/ None,
            /*observation*/ None,
            /*final_outcome*/ None,
            fence,
            now_ms,
        )
        .await?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        Ok(TaskFlowStepCommandResult {
            status: TaskFlowStepCommandStatus::Applied,
            receipt: reconstruct_step(
                self.taskflow_owner_agent_id(),
                run_id,
                step_id,
                attempt,
                &[event],
            )?,
        })
    }

    /// Append the fenced claim receipt for a prepared step.  Replaying the
    /// same command is idempotent; a different command with the same id or a
    /// stale fence is rejected before any row is written.
    pub async fn claim_taskflow_step(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepCommandResult, TaskFlowError> {
        self.append_step_operation(
            "claim",
            run_id,
            step_id,
            attempt,
            fence,
            intent_digest,
            payload_digest,
            command_id,
            /*receipt_digest*/ None,
            /*observation*/ None,
            now_ms,
        )
        .await
    }

    /// Append an observed step outcome.  `Indeterminate` deliberately remains
    /// non-terminal and requires an explicit reconciliation receipt.
    pub async fn record_taskflow_step(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        command_id: &str,
        receipt_digest: &Sha256Digest,
        observation: TaskFlowStepObservation,
        now_ms: u64,
    ) -> Result<TaskFlowStepCommandResult, TaskFlowError> {
        self.append_step_operation(
            "record",
            run_id,
            step_id,
            attempt,
            fence,
            intent_digest,
            payload_digest,
            command_id,
            Some(receipt_digest),
            Some(observation),
            now_ms,
        )
        .await
    }

    /// Reconcile an indeterminate observation with an explicit terminal
    /// outcome.  This only records the caller's already-observed receipt; it
    /// never contacts a provider and never claims effect authority.
    pub async fn reconcile_taskflow_step(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        command_id: &str,
        receipt_digest: &Sha256Digest,
        outcome: TaskFlowReconcileOutcome,
        now_ms: u64,
    ) -> Result<TaskFlowStepCommandResult, TaskFlowError> {
        self.append_step_operation_with_outcome(
            "reconcile",
            run_id,
            step_id,
            attempt,
            fence,
            intent_digest,
            payload_digest,
            command_id,
            Some(receipt_digest),
            StepOperationResult::Outcome(outcome),
            now_ms,
        )
        .await
    }

    /// Read and verify one immutable step chain.  A historical terminal step
    /// may be read after lease expiry, but the supplied fence must still be
    /// exactly the fence that authored the chain.
    pub async fn read_taskflow_step(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
    ) -> Result<Option<TaskFlowStepReceipt>, TaskFlowError> {
        validate_common_without_digests(run_id, step_id, attempt, "read")?;
        validate_fence(self, fence)?;
        ensure_step_schema(self).await?;
        let mut tx = self.begin_step_tx().await?;
        let run = load_run(&mut tx, self, run_id).await?;
        let definition = load_definition(&mut tx, self, &run).await?;
        validate_step_node(&definition, step_id)?;
        let events = load_step_events(&mut tx, self, run_id, step_id, attempt).await?;
        if events.is_empty() {
            tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(None);
        }
        let receipt = reconstruct_step(
            self.taskflow_owner_agent_id(),
            run_id,
            step_id,
            attempt,
            &events,
        )?;
        check_historical_fence(&run, &receipt.fence, fence)?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        Ok(Some(receipt))
    }

    async fn append_step_operation(
        &self,
        operation: &str,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        command_id: &str,
        receipt_digest: Option<&Sha256Digest>,
        observation: Option<TaskFlowStepObservation>,
        now_ms: u64,
    ) -> Result<TaskFlowStepCommandResult, TaskFlowError> {
        validate_common(
            run_id,
            step_id,
            attempt,
            command_id,
            intent_digest,
            payload_digest,
        )?;
        validate_fence(self, fence)?;
        if operation != "claim" && operation != "record" {
            return Err(TaskFlowError::Invalid("unknown step operation".to_string()));
        }
        if operation == "claim" && (receipt_digest.is_some() || observation.is_some()) {
            return Err(TaskFlowError::Invalid(
                "claim carries no observation".to_string(),
            ));
        }
        if operation == "record" && (receipt_digest.is_none() || observation.is_none()) {
            return Err(TaskFlowError::Invalid(
                "record requires receipt and observation".to_string(),
            ));
        }
        self.append_step_operation_with_outcome(
            operation,
            run_id,
            step_id,
            attempt,
            fence,
            intent_digest,
            payload_digest,
            command_id,
            receipt_digest,
            StepOperationResult::from(observation),
            now_ms,
        )
        .await
    }

    async fn append_step_operation_with_outcome(
        &self,
        operation: &str,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        command_id: &str,
        receipt_digest: Option<&Sha256Digest>,
        outcome_or_observation: impl Into<StepOperationResult>,
        now_ms: u64,
    ) -> Result<TaskFlowStepCommandResult, TaskFlowError> {
        let operation_result = outcome_or_observation.into();
        let (observation, final_outcome) = operation_result.parts();
        validate_common(
            run_id,
            step_id,
            attempt,
            command_id,
            intent_digest,
            payload_digest,
        )?;
        validate_fence(self, fence)?;
        if operation == "reconcile" {
            if receipt_digest.is_none() || final_outcome.is_none() {
                return Err(TaskFlowError::Invalid(
                    "reconcile requires receipt and final outcome".to_string(),
                ));
            }
            if observation.is_some() {
                return Err(TaskFlowError::Invalid(
                    "reconcile carries no direct observation".to_string(),
                ));
            }
        }
        if operation == "claim" && (receipt_digest.is_some() || observation.is_some()) {
            return Err(TaskFlowError::Invalid(
                "claim carries no observation".to_string(),
            ));
        }
        if operation == "record" && (receipt_digest.is_none() || observation.is_none()) {
            return Err(TaskFlowError::Invalid(
                "record requires receipt and observation".to_string(),
            ));
        }
        if !matches!(operation, "claim" | "record" | "reconcile") {
            return Err(TaskFlowError::Invalid("unknown step operation".to_string()));
        }
        if let Some(receipt_digest) = receipt_digest {
            validate_digest(receipt_digest, "step receipt digest")?;
        }
        ensure_step_schema(self).await?;
        let mut tx = self.begin_step_tx().await?;
        let run = load_run(&mut tx, self, run_id).await?;
        let definition = load_definition(&mut tx, self, &run).await?;
        validate_step_node(&definition, step_id)?;
        let events = load_step_events(&mut tx, self, run_id, step_id, attempt).await?;
        let command_digest = operation_digest(
            operation,
            self.taskflow_owner_agent_id(),
            run_id,
            step_id,
            attempt,
            command_id,
            intent_digest.as_str(),
            payload_digest.as_str(),
            fence,
            receipt_digest.map(Sha256Digest::as_str),
            observation,
            final_outcome,
            now_ms,
        )?;
        if let Some(existing) = existing_command(&events, command_id, command_digest.as_str())? {
            let receipt = reconstruct_step(
                self.taskflow_owner_agent_id(),
                run_id,
                step_id,
                attempt,
                &events,
            )?;
            tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(TaskFlowStepCommandResult {
                status: TaskFlowStepCommandStatus::AlreadyApplied,
                receipt: receipt_with_seq(receipt, existing.event_seq),
            });
        }
        let current = events
            .last()
            .ok_or_else(|| TaskFlowError::Conflict("step intent is not prepared".to_string()))?;
        if current.intent_digest != intent_digest.as_str()
            || current.payload_digest != payload_digest.as_str()
        {
            return Err(TaskFlowError::Conflict(
                "step command is bound to different intent bytes".to_string(),
            ));
        }
        check_historical_fence(
            &run,
            &fence_from_event(self.taskflow_owner_agent_id(), current)?,
            fence,
        )?;
        match operation {
            "claim" => {
                check_active_run_fence(&run, fence, now_ms)?;
                if current.event_kind != TaskFlowStepState::Prepared {
                    return Err(invalid_step_transition("claim requires prepared state"));
                }
            }
            "record" => {
                check_run_identity_for_observation(&run, fence)?;
                if current.event_kind != TaskFlowStepState::Claimed {
                    return Err(invalid_step_transition("record requires claimed state"));
                }
            }
            "reconcile" => {
                check_run_identity_for_observation(&run, fence)?;
                if current.event_kind != TaskFlowStepState::Recorded
                    || current.observation != Some(TaskFlowStepObservation::Indeterminate)
                {
                    return Err(invalid_step_transition(
                        "reconcile requires an indeterminate recorded state",
                    ));
                }
            }
            _ => unreachable!("operation validated above"),
        }
        let state = match operation {
            "claim" => TaskFlowStepState::Claimed,
            "record" => TaskFlowStepState::Recorded,
            "reconcile" => TaskFlowStepState::Reconciled,
            _ => unreachable!(),
        };
        let event = append_step_event(
            &mut tx,
            self,
            run_id,
            step_id,
            attempt,
            state,
            command_id,
            command_digest.as_str(),
            intent_digest.as_str(),
            payload_digest.as_str(),
            receipt_digest.map(Sha256Digest::as_str),
            observation,
            final_outcome,
            fence,
            now_ms,
        )
        .await?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        let mut all_events = events;
        all_events.push(event);
        Ok(TaskFlowStepCommandResult {
            status: TaskFlowStepCommandStatus::Applied,
            receipt: reconstruct_step(
                self.taskflow_owner_agent_id(),
                run_id,
                step_id,
                attempt,
                &all_events,
            )?,
        })
    }

    async fn begin_step_tx(&self) -> Result<sqlx::Transaction<'_, sqlx::Sqlite>, TaskFlowError> {
        self.taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)
    }
}

#[derive(Clone, Copy)]
enum StepOperationResult {
    None,
    Observation(TaskFlowStepObservation),
    Outcome(TaskFlowReconcileOutcome),
}

impl StepOperationResult {
    fn parts(
        self,
    ) -> (
        Option<TaskFlowStepObservation>,
        Option<TaskFlowReconcileOutcome>,
    ) {
        match self {
            Self::None => (None, None),
            Self::Observation(value) => (Some(value), None),
            Self::Outcome(value) => (None, Some(value)),
        }
    }
}

impl From<Option<TaskFlowStepObservation>> for StepOperationResult {
    fn from(value: Option<TaskFlowStepObservation>) -> Self {
        value.map_or(Self::None, Self::Observation)
    }
}

impl From<TaskFlowReconcileOutcome> for StepOperationResult {
    fn from(value: TaskFlowReconcileOutcome) -> Self {
        Self::Outcome(value)
    }
}

async fn ensure_step_schema(store: &AutomationStore) -> Result<(), TaskFlowError> {
    // The schema is additive and deliberately qualification-only.  Keeping it
    // out of the default migrator avoids changing AUTOMATION_SCHEMA_VERSION or
    // existing production/open paths.
    sqlx::query(
        r#"CREATE TABLE IF NOT EXISTS taskflow_step_outbox (
            owner_agent_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            attempt INTEGER NOT NULL CHECK (attempt > 0 AND attempt <= 1000000),
            event_seq INTEGER NOT NULL CHECK (event_seq > 0),
            event_kind TEXT NOT NULL CHECK (
                event_kind IN ('prepared', 'claimed', 'recorded', 'reconciled')
            ),
            command_id TEXT NOT NULL,
            command_digest TEXT NOT NULL CHECK (
                length(command_digest) = 64 AND command_digest NOT GLOB '*[^0-9a-f]*'
            ),
            intent_digest TEXT NOT NULL CHECK (
                length(intent_digest) = 64 AND intent_digest NOT GLOB '*[^0-9a-f]*'
            ),
            payload_digest TEXT NOT NULL CHECK (
                length(payload_digest) = 64 AND payload_digest NOT GLOB '*[^0-9a-f]*'
            ),
            receipt_digest TEXT CHECK (
                receipt_digest IS NULL OR
                (length(receipt_digest) = 64 AND receipt_digest NOT GLOB '*[^0-9a-f]*')
            ),
            observation TEXT CHECK (
                observation IS NULL OR observation IN ('succeeded', 'failed', 'indeterminate')
            ),
            final_outcome TEXT CHECK (
                final_outcome IS NULL OR final_outcome IN ('succeeded', 'failed', 'cancelled')
            ),
            owner_id TEXT NOT NULL,
            owner_epoch INTEGER NOT NULL CHECK (owner_epoch > 0),
            generation INTEGER NOT NULL CHECK (generation > 0),
            fencing_token TEXT NOT NULL CHECK (length(fencing_token) BETWEEN 1 AND 256),
            previous_event_digest TEXT NOT NULL CHECK (
                length(previous_event_digest) = 64 AND
                previous_event_digest NOT GLOB '*[^0-9a-f]*'
            ),
            event_digest TEXT NOT NULL CHECK (
                length(event_digest) = 64 AND event_digest NOT GLOB '*[^0-9a-f]*'
            ),
            recorded_at_ms INTEGER NOT NULL CHECK (recorded_at_ms >= 0),
            PRIMARY KEY (owner_agent_id, run_id, step_id, attempt, event_seq),
            UNIQUE (owner_agent_id, command_id),
            FOREIGN KEY (owner_agent_id, run_id)
                REFERENCES taskflow_runs(owner_agent_id, run_id),
            CHECK (
                (event_kind IN ('prepared', 'claimed') AND
                    receipt_digest IS NULL AND observation IS NULL AND final_outcome IS NULL)
                OR
                (event_kind = 'recorded' AND
                    receipt_digest IS NOT NULL AND observation IS NOT NULL AND final_outcome IS NULL)
                OR
                (event_kind = 'reconciled' AND
                    receipt_digest IS NOT NULL AND observation IS NULL AND final_outcome IS NOT NULL)
            )
        )"#,
    )
    .execute(store.taskflow_pool())
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    sqlx::query(
        "CREATE TRIGGER IF NOT EXISTS taskflow_step_outbox_no_update
         BEFORE UPDATE ON taskflow_step_outbox
         BEGIN SELECT RAISE(ABORT, 'TaskFlow step outbox is append-only'); END",
    )
    .execute(store.taskflow_pool())
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    sqlx::query(
        "CREATE TRIGGER IF NOT EXISTS taskflow_step_outbox_no_delete
         BEFORE DELETE ON taskflow_step_outbox
         BEGIN SELECT RAISE(ABORT, 'TaskFlow step outbox is append-only'); END",
    )
    .execute(store.taskflow_pool())
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    sqlx::query(
        "CREATE INDEX IF NOT EXISTS taskflow_step_outbox_lookup
         ON taskflow_step_outbox(owner_agent_id, run_id, step_id, attempt, event_seq)",
    )
    .execute(store.taskflow_pool())
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    Ok(())
}

async fn load_run<'a>(
    tx: &mut sqlx::Transaction<'a, sqlx::Sqlite>,
    store: &AutomationStore,
    run_id: &str,
) -> Result<TaskFlowRun, TaskFlowError> {
    load_taskflow_run_tx(tx, store.taskflow_owner_agent_id(), run_id)
        .await?
        .ok_or_else(|| TaskFlowError::Conflict("TaskFlow run does not exist".to_string()))
}

async fn load_definition<'a>(
    tx: &mut sqlx::Transaction<'a, sqlx::Sqlite>,
    store: &AutomationStore,
    run: &TaskFlowRun,
) -> Result<crate::TaskFlowDefinition, TaskFlowError> {
    load_taskflow_definition_tx(
        tx,
        store.taskflow_owner_agent_id(),
        &run.workflow_id,
        run.workflow_version,
    )
    .await?
    .ok_or_else(|| corrupt("TaskFlow definition is missing"))
}

async fn load_step_events(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    run_id: &str,
    step_id: &str,
    attempt: u32,
) -> Result<Vec<StepEvent>, TaskFlowError> {
    let rows = sqlx::query(
        "SELECT event_seq, event_kind, command_id, command_digest,
                intent_digest, payload_digest, receipt_digest, observation,
                final_outcome, owner_id, owner_epoch, generation, fencing_token,
                previous_event_digest, event_digest, recorded_at_ms
         FROM taskflow_step_outbox
         WHERE owner_agent_id = ? AND run_id = ? AND step_id = ? AND attempt = ?
         ORDER BY event_seq",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(run_id)
    .bind(step_id)
    .bind(i64::from(attempt))
    .fetch_all(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let mut events = Vec::with_capacity(rows.len());
    for row in rows {
        let event_kind = TaskFlowStepState::parse(
            row.try_get::<String, _>("event_kind")
                .map_err(|_| corrupt("step event kind column"))?
                .as_str(),
        )?;
        let observation = row
            .try_get::<Option<String>, _>("observation")
            .map_err(|_| corrupt("step observation column"))?
            .map(|value| TaskFlowStepObservation::parse(&value))
            .transpose()?;
        let final_outcome = row
            .try_get::<Option<String>, _>("final_outcome")
            .map_err(|_| corrupt("step final outcome column"))?
            .map(|value| parse_final_outcome(&value))
            .transpose()?;
        let event = StepEvent {
            event_seq: to_u64(row.try_get("event_seq").map_err(|_| corrupt("step seq"))?)?,
            event_kind,
            command_id: row
                .try_get("command_id")
                .map_err(|_| corrupt("step command id"))?,
            command_digest: row
                .try_get("command_digest")
                .map_err(|_| corrupt("step command digest"))?,
            intent_digest: row
                .try_get("intent_digest")
                .map_err(|_| corrupt("step intent digest"))?,
            payload_digest: row
                .try_get("payload_digest")
                .map_err(|_| corrupt("step payload digest"))?,
            receipt_digest: row
                .try_get("receipt_digest")
                .map_err(|_| corrupt("step receipt digest"))?,
            observation,
            final_outcome,
            owner_id: row
                .try_get("owner_id")
                .map_err(|_| corrupt("step owner id"))?,
            owner_epoch: to_u64(
                row.try_get("owner_epoch")
                    .map_err(|_| corrupt("step owner epoch"))?,
            )?,
            generation: to_u64(
                row.try_get("generation")
                    .map_err(|_| corrupt("step generation"))?,
            )?,
            fencing_token: row
                .try_get("fencing_token")
                .map_err(|_| corrupt("step fencing token"))?,
            previous_event_digest: row
                .try_get("previous_event_digest")
                .map_err(|_| corrupt("step predecessor"))?,
            event_digest: row
                .try_get("event_digest")
                .map_err(|_| corrupt("step digest"))?,
            recorded_at_ms: to_u64(
                row.try_get("recorded_at_ms")
                    .map_err(|_| corrupt("step timestamp"))?,
            )?,
        };
        events.push(event);
    }
    verify_step_events(
        store.taskflow_owner_agent_id(),
        run_id,
        step_id,
        attempt,
        &events,
    )?;
    Ok(events)
}

async fn append_step_event(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    run_id: &str,
    step_id: &str,
    attempt: u32,
    event_kind: TaskFlowStepState,
    command_id: &str,
    command_digest: &str,
    intent_digest: &str,
    payload_digest: &str,
    receipt_digest: Option<&str>,
    observation: Option<TaskFlowStepObservation>,
    final_outcome: Option<TaskFlowReconcileOutcome>,
    fence: &TaskFlowFence,
    recorded_at_ms: u64,
) -> Result<StepEvent, TaskFlowError> {
    let previous_event_digest = sqlx::query_scalar::<_, String>(
        "SELECT event_digest FROM taskflow_step_outbox
         WHERE owner_agent_id = ? AND run_id = ? AND step_id = ? AND attempt = ?
         ORDER BY event_seq DESC LIMIT 1",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(run_id)
    .bind(step_id)
    .bind(i64::from(attempt))
    .fetch_optional(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?
    .unwrap_or_else(|| ZERO_DIGEST.to_string());
    let previous_seq = sqlx::query_scalar::<_, Option<i64>>(
        "SELECT MAX(event_seq) FROM taskflow_step_outbox
         WHERE owner_agent_id = ? AND run_id = ? AND step_id = ? AND attempt = ?",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(run_id)
    .bind(step_id)
    .bind(i64::from(attempt))
    .fetch_one(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let event_seq = to_u64(previous_seq.unwrap_or(0))?
        .checked_add(1)
        .ok_or_else(|| corrupt("step event sequence overflow"))?;
    let event_digest = event_digest(
        &previous_event_digest,
        store.taskflow_owner_agent_id(),
        run_id,
        step_id,
        attempt,
        event_seq,
        event_kind,
        command_id,
        command_digest,
        intent_digest,
        payload_digest,
        receipt_digest,
        observation,
        final_outcome,
        fence,
        recorded_at_ms,
    )?;
    sqlx::query(
        "INSERT INTO taskflow_step_outbox (
            owner_agent_id, run_id, step_id, attempt, event_seq, event_kind,
            command_id, command_digest, intent_digest, payload_digest,
            receipt_digest, observation, final_outcome, owner_id, owner_epoch,
            generation, fencing_token, previous_event_digest, event_digest,
            recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(run_id)
    .bind(step_id)
    .bind(i64::from(attempt))
    .bind(to_i64(event_seq)?)
    .bind(event_kind.as_str())
    .bind(command_id)
    .bind(command_digest)
    .bind(intent_digest)
    .bind(payload_digest)
    .bind(receipt_digest)
    .bind(observation.map(TaskFlowStepObservation::as_str))
    .bind(final_outcome.map(final_outcome_str))
    .bind(&fence.owner_id)
    .bind(to_i64(fence.owner_epoch)?)
    .bind(to_i64(fence.generation)?)
    .bind(&fence.fencing_token)
    .bind(&previous_event_digest)
    .bind(event_digest.as_str())
    .bind(to_i64(recorded_at_ms)?)
    .execute(&mut **tx)
    .await
    .map_err(|error| {
        if is_constraint(&error) {
            TaskFlowError::Conflict("duplicate or conflicting step command".to_string())
        } else {
            TaskFlowError::Unavailable
        }
    })?;
    Ok(StepEvent {
        event_seq,
        event_kind,
        command_id: command_id.to_string(),
        command_digest: command_digest.to_string(),
        intent_digest: intent_digest.to_string(),
        payload_digest: payload_digest.to_string(),
        receipt_digest: receipt_digest.map(str::to_string),
        observation,
        final_outcome,
        owner_id: fence.owner_id.clone(),
        owner_epoch: fence.owner_epoch,
        generation: fence.generation,
        fencing_token: fence.fencing_token.clone(),
        previous_event_digest,
        event_digest: event_digest.as_str().to_string(),
        recorded_at_ms,
    })
}

fn verify_step_events(
    owner: &AgentId,
    run_id: &str,
    step_id: &str,
    attempt: u32,
    events: &[StepEvent],
) -> Result<(), TaskFlowError> {
    if events.is_empty() {
        return Ok(());
    }
    let mut previous = ZERO_DIGEST.to_string();
    let mut command_ids = BTreeSet::new();
    let mut state = None;
    let mut bound_intent: Option<String> = None;
    let mut bound_payload: Option<String> = None;
    let mut bound_fence = None;
    for (index, event) in events.iter().enumerate() {
        let expected_seq = u64::try_from(index + 1).map_err(|_| corrupt("step seq overflow"))?;
        if event.event_seq != expected_seq {
            return Err(corrupt("TaskFlow step event sequence has a gap"));
        }
        if !command_ids.insert(event.command_id.clone()) {
            return Err(corrupt("TaskFlow step command id is duplicated"));
        }
        validate_digest_str(&event.command_digest, "step command digest")?;
        validate_digest_str(&event.intent_digest, "step intent digest")?;
        validate_digest_str(&event.payload_digest, "step payload digest")?;
        if let Some(value) = &event.receipt_digest {
            validate_digest_str(value, "step receipt digest")?;
        }
        validate_text(&event.command_id, "step command id")?;
        validate_text(&event.owner_id, "step owner id")?;
        validate_text(&event.fencing_token, "step fencing token")?;
        if event.owner_epoch == 0 || event.generation == 0 {
            return Err(corrupt("step event fence has zero epoch or generation"));
        }
        if event.previous_event_digest != previous {
            return Err(corrupt("TaskFlow step predecessor digest mismatch"));
        }
        let computed = event_digest(
            &previous,
            owner,
            run_id,
            step_id,
            attempt,
            event.event_seq,
            event.event_kind,
            &event.command_id,
            &event.command_digest,
            &event.intent_digest,
            &event.payload_digest,
            event.receipt_digest.as_deref(),
            event.observation,
            event.final_outcome,
            &TaskFlowFence {
                owner_agent_id: owner.clone(),
                owner_id: event.owner_id.clone(),
                owner_epoch: event.owner_epoch,
                generation: event.generation,
                fencing_token: event.fencing_token.clone(),
            },
            event.recorded_at_ms,
        )?;
        if event.event_digest != computed.as_str() {
            return Err(corrupt("TaskFlow step event digest mismatch"));
        }
        if bound_intent
            .as_ref()
            .is_some_and(|value| value != &event.intent_digest)
            || bound_payload
                .as_ref()
                .is_some_and(|value| value != &event.payload_digest)
        {
            return Err(corrupt("TaskFlow step digest binding changes mid-chain"));
        }
        bound_intent = Some(event.intent_digest.clone());
        bound_payload = Some(event.payload_digest.clone());
        let fence_tuple = (
            event.owner_id.clone(),
            event.owner_epoch,
            event.generation,
            event.fencing_token.clone(),
        );
        if bound_fence
            .as_ref()
            .is_some_and(|value| value != &fence_tuple)
        {
            return Err(corrupt("TaskFlow step fence changes mid-chain"));
        }
        bound_fence = Some(fence_tuple);
        state = Some(match (state, event.event_kind) {
            (None, TaskFlowStepState::Prepared) => TaskFlowStepState::Prepared,
            (Some(TaskFlowStepState::Prepared), TaskFlowStepState::Claimed) => {
                TaskFlowStepState::Claimed
            }
            (Some(TaskFlowStepState::Claimed), TaskFlowStepState::Recorded) => {
                if event.receipt_digest.is_none() || event.observation.is_none() {
                    return Err(corrupt("recorded step event lacks observation receipt"));
                }
                TaskFlowStepState::Recorded
            }
            (Some(TaskFlowStepState::Recorded), TaskFlowStepState::Reconciled) => {
                if event.observation.is_some()
                    || event.final_outcome.is_none()
                    || events[index - 1].observation != Some(TaskFlowStepObservation::Indeterminate)
                {
                    return Err(corrupt("reconciled step event is not receipt-bound"));
                }
                TaskFlowStepState::Reconciled
            }
            (Some(TaskFlowStepState::Prepared), TaskFlowStepState::Prepared)
            | (Some(TaskFlowStepState::Claimed), TaskFlowStepState::Claimed)
            | (Some(TaskFlowStepState::Recorded), TaskFlowStepState::Recorded)
            | (Some(TaskFlowStepState::Reconciled), _)
            | (_, TaskFlowStepState::Prepared) => {
                return Err(corrupt("TaskFlow step transition sequence is invalid"));
            }
            _ => return Err(corrupt("TaskFlow step transition sequence is invalid")),
        });
        previous = event.event_digest.clone();
    }
    Ok(())
}

fn reconstruct_step(
    owner: &AgentId,
    run_id: &str,
    step_id: &str,
    attempt: u32,
    events: &[StepEvent],
) -> Result<TaskFlowStepReceipt, TaskFlowError> {
    verify_step_events(owner, run_id, step_id, attempt, events)?;
    let last = events
        .last()
        .ok_or_else(|| corrupt("TaskFlow step chain is empty"))?;
    let fence = TaskFlowFence::new(
        owner.clone(),
        last.owner_id.clone(),
        last.owner_epoch,
        last.generation,
        last.fencing_token.clone(),
    )?;
    let observation = events.iter().rev().find_map(|event| event.observation);
    let final_outcome = events.iter().rev().find_map(|event| event.final_outcome);
    Ok(TaskFlowStepReceipt {
        owner_agent_id: owner.clone(),
        run_id: run_id.to_string(),
        step_id: step_id.to_string(),
        attempt,
        state: last.event_kind,
        intent_digest: Sha256Digest::parse(last.intent_digest.clone())
            .map_err(|_| corrupt("step intent digest parse"))?,
        payload_digest: Sha256Digest::parse(last.payload_digest.clone())
            .map_err(|_| corrupt("step payload digest parse"))?,
        fence,
        event_seq: last.event_seq,
        last_command_id: last.command_id.clone(),
        receipt_digest: last
            .receipt_digest
            .as_ref()
            .map(|value| Sha256Digest::parse(value.clone()))
            .transpose()
            .map_err(|_| corrupt("step receipt digest parse"))?,
        observation,
        final_outcome,
    })
}

fn receipt_with_seq(mut receipt: TaskFlowStepReceipt, event_seq: u64) -> TaskFlowStepReceipt {
    receipt.event_seq = event_seq;
    receipt
}

fn existing_command<'a>(
    events: &'a [StepEvent],
    command_id: &str,
    command_digest: &str,
) -> Result<Option<&'a StepEvent>, TaskFlowError> {
    let Some(event) = events.iter().find(|event| event.command_id == command_id) else {
        return Ok(None);
    };
    if event.command_digest != command_digest {
        return Err(TaskFlowError::Conflict(
            "step command id was reused with different bytes".to_string(),
        ));
    }
    Ok(Some(event))
}

fn operation_digest(
    operation: &str,
    owner_agent_id: &AgentId,
    run_id: &str,
    step_id: &str,
    attempt: u32,
    command_id: &str,
    intent_digest: &str,
    payload_digest: &str,
    fence: &TaskFlowFence,
    receipt_digest: Option<&str>,
    observation: Option<TaskFlowStepObservation>,
    final_outcome: Option<TaskFlowReconcileOutcome>,
    now_ms: u64,
) -> Result<Sha256Digest, TaskFlowError> {
    let canonical = OperationCanonical {
        schema_version: STEP_SCHEMA_VERSION,
        operation,
        owner_agent_id,
        run_id,
        step_id,
        attempt,
        command_id,
        intent_digest,
        payload_digest,
        owner_id: &fence.owner_id,
        owner_epoch: fence.owner_epoch,
        generation: fence.generation,
        fencing_token: &fence.fencing_token,
        receipt_digest,
        observation,
        final_outcome,
        now_ms,
    };
    let bytes = serde_json::to_vec(&canonical)
        .map_err(|_| corrupt("step operation serialization failed"))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn event_digest(
    previous_event_digest: &str,
    owner_agent_id: &AgentId,
    run_id: &str,
    step_id: &str,
    attempt: u32,
    event_seq: u64,
    event_kind: TaskFlowStepState,
    command_id: &str,
    command_digest: &str,
    intent_digest: &str,
    payload_digest: &str,
    receipt_digest: Option<&str>,
    observation: Option<TaskFlowStepObservation>,
    final_outcome: Option<TaskFlowReconcileOutcome>,
    fence: &TaskFlowFence,
    recorded_at_ms: u64,
) -> Result<Sha256Digest, TaskFlowError> {
    let canonical = EventCanonical {
        schema_version: STEP_SCHEMA_VERSION,
        previous_event_digest,
        owner_agent_id,
        run_id,
        step_id,
        attempt,
        event_seq,
        event_kind,
        command_id,
        command_digest,
        intent_digest,
        payload_digest,
        receipt_digest,
        observation,
        final_outcome,
        owner_id: &fence.owner_id,
        owner_epoch: fence.owner_epoch,
        generation: fence.generation,
        fencing_token: &fence.fencing_token,
        recorded_at_ms,
    };
    let bytes =
        serde_json::to_vec(&canonical).map_err(|_| corrupt("step event serialization failed"))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn validate_common(
    run_id: &str,
    step_id: &str,
    attempt: u32,
    command_id: &str,
    intent_digest: &Sha256Digest,
    payload_digest: &Sha256Digest,
) -> Result<(), TaskFlowError> {
    validate_common_without_digests(run_id, step_id, attempt, command_id)?;
    validate_digest(intent_digest, "step intent digest")?;
    validate_digest(payload_digest, "step payload digest")
}

fn validate_common_without_digests(
    run_id: &str,
    step_id: &str,
    attempt: u32,
    command_id: &str,
) -> Result<(), TaskFlowError> {
    validate_text(run_id, "run id")?;
    validate_text(step_id, "step id")?;
    validate_text(command_id, "step command id")?;
    if attempt == 0 || attempt > MAX_STEP_ATTEMPT {
        return Err(TaskFlowError::Invalid(
            "step attempt is outside bounded range".to_string(),
        ));
    }
    Ok(())
}

fn validate_fence(store: &AutomationStore, fence: &TaskFlowFence) -> Result<(), TaskFlowError> {
    if fence.owner_agent_id != *store.taskflow_owner_agent_id() {
        return Err(TaskFlowError::StaleFence);
    }
    validate_text(&fence.owner_id, "owner id")?;
    validate_text(&fence.fencing_token, "fencing token")?;
    if fence.owner_epoch == 0 || fence.generation == 0 {
        return Err(TaskFlowError::Invalid(
            "fence epoch and generation must be non-zero".to_string(),
        ));
    }
    Ok(())
}

fn validate_step_node(
    definition: &crate::TaskFlowDefinition,
    step_id: &str,
) -> Result<(), TaskFlowError> {
    let node = definition
        .nodes
        .iter()
        .find(|node| node.node_id == step_id)
        .ok_or_else(|| TaskFlowError::Conflict("step is not in TaskFlow definition".to_string()))?;
    if matches!(
        node.kind,
        crate::TaskFlowNodeKind::TerminalSuccess | crate::TaskFlowNodeKind::TerminalFailure
    ) {
        return Err(TaskFlowError::Invalid(
            "terminal node cannot own a step outbox".to_string(),
        ));
    }
    Ok(())
}

fn check_active_run_fence(
    run: &TaskFlowRun,
    fence: &TaskFlowFence,
    now_ms: u64,
) -> Result<(), TaskFlowError> {
    check_run_identity_for_observation(run, fence)?;
    if run
        .lease_expires_at_ms
        .is_none_or(|expires| expires <= now_ms)
    {
        return Err(TaskFlowError::StaleFence);
    }
    Ok(())
}

fn check_run_identity_for_observation(
    run: &TaskFlowRun,
    fence: &TaskFlowFence,
) -> Result<(), TaskFlowError> {
    if run.owner_id.as_deref() != Some(fence.owner_id.as_str())
        || run.owner_epoch != Some(fence.owner_epoch)
        || run.generation != Some(fence.generation)
        || run.fencing_token.as_deref() != Some(fence.fencing_token.as_str())
    {
        return Err(TaskFlowError::StaleFence);
    }
    Ok(())
}

fn check_historical_fence(
    run: &TaskFlowRun,
    event_fence: &TaskFlowFence,
    supplied: &TaskFlowFence,
) -> Result<(), TaskFlowError> {
    if event_fence.owner_agent_id != supplied.owner_agent_id
        || event_fence.owner_id != supplied.owner_id
        || event_fence.owner_epoch != supplied.owner_epoch
        || event_fence.generation != supplied.generation
        || event_fence.fencing_token != supplied.fencing_token
    {
        return Err(TaskFlowError::StaleFence);
    }
    // If the run is still leased, its current tuple must remain the same.  A
    // terminal run clears the lease but keeps the historical step readable.
    if !matches!(
        run.state,
        crate::TaskFlowRunState::Succeeded
            | crate::TaskFlowRunState::Failed
            | crate::TaskFlowRunState::Cancelled
    ) {
        check_run_identity_for_observation(run, supplied)?;
    }
    Ok(())
}

fn fence_from_event(owner: &AgentId, event: &StepEvent) -> Result<TaskFlowFence, TaskFlowError> {
    TaskFlowFence::new(
        owner.clone(),
        event.owner_id.clone(),
        event.owner_epoch,
        event.generation,
        event.fencing_token.clone(),
    )
}

fn parse_final_outcome(value: &str) -> Result<TaskFlowReconcileOutcome, TaskFlowError> {
    match value {
        "succeeded" => Ok(TaskFlowReconcileOutcome::Succeeded),
        "failed" => Ok(TaskFlowReconcileOutcome::Failed),
        "cancelled" => Ok(TaskFlowReconcileOutcome::Cancelled),
        _ => Err(corrupt("unknown TaskFlow step final outcome")),
    }
}

fn final_outcome_str(value: TaskFlowReconcileOutcome) -> &'static str {
    match value {
        TaskFlowReconcileOutcome::Succeeded => "succeeded",
        TaskFlowReconcileOutcome::Failed => "failed",
        TaskFlowReconcileOutcome::Cancelled => "cancelled",
    }
}

fn to_u64(value: i64) -> Result<u64, TaskFlowError> {
    u64::try_from(value).map_err(|_| corrupt("negative integer in step outbox"))
}

fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value).map_err(|_| TaskFlowError::Invalid("integer overflow".to_string()))
}

fn validate_text(value: &str, label: &str) -> Result<(), TaskFlowError> {
    if value.is_empty() || value.len() > MAX_TEXT_BYTES || value.bytes().any(|byte| byte < 0x20) {
        return Err(TaskFlowError::Invalid(format!(
            "{label} must be non-empty, bounded, and printable"
        )));
    }
    Ok(())
}

fn validate_digest(value: &Sha256Digest, label: &str) -> Result<(), TaskFlowError> {
    validate_digest_str(value.as_str(), label)
}

fn validate_digest_str(value: &str, label: &str) -> Result<(), TaskFlowError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(corrupt(format!("{label} is malformed")));
    }
    Ok(())
}

fn invalid_step_transition(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::InvalidTransition(message.into())
}

fn corrupt(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Corrupt(message.into())
}

fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation() || database.is_foreign_key_violation() || database.is_check_violation())
}
