//! Bounded startup verification for the durable TaskFlow ledger.
//!
//! The implementation remains in `taskflow.rs`. This wrapper preserves its
//! public API while replacing only the automation-store opener audit. Every
//! definition, run and event is still verified from one SQLite read snapshot,
//! but no retained collection is materialized without a fixed page bound.

#[path = "taskflow.rs"]
mod implementation;

pub use implementation::{
    TASKFLOW_COMPOSED_CALLER, TASKFLOW_EXTERNAL_EFFECTS, TASKFLOW_NAMESPACE,
    TASKFLOW_PRODUCTION_CALLER, TASKFLOW_SCHEDULER_AUTHORITY, TASKFLOW_SCHEMA_VERSION,
    TaskFlowCommand, TaskFlowCommandResult, TaskFlowCommandStatus, TaskFlowDefinition,
    TaskFlowDefinitionReceipt, TaskFlowEdgeSpec, TaskFlowError, TaskFlowFence, TaskFlowNodeKind,
    TaskFlowNodeSpec, TaskFlowReconcileOutcome, TaskFlowRun, TaskFlowRunState, TaskFlowTransition,
};
pub(crate) use implementation::{load_taskflow_definition_tx, load_taskflow_run_tx};

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

const TASKFLOW_VERIFY_PAGE_SIZE: usize = 256;
const TASKFLOW_VERIFY_PAGE_LIMIT: i64 = 256;
const MAX_ID_BYTES: usize = 256;
const ZERO_DIGEST: &str = "0000000000000000000000000000000000000000000000000000000000000000";

pub(crate) async fn verify_taskflow_store(
    pool: &sqlx::SqlitePool,
    expected_owner: &AgentId,
) -> Result<(), TaskFlowError> {
    let mut tx = pool.begin().await.map_err(|_| TaskFlowError::Unavailable)?;
    reject_foreign_rows(&mut tx, expected_owner).await?;
    verify_definition_pages(&mut tx, expected_owner).await?;
    verify_run_pages(&mut tx, expected_owner).await?;
    tx.commit().await.map_err(|_| TaskFlowError::Unavailable)
}

async fn reject_foreign_rows(
    tx: &mut Transaction<'_, Sqlite>,
    expected_owner: &AgentId,
) -> Result<(), TaskFlowError> {
    for table in ["taskflow_definitions", "taskflow_runs", "taskflow_events"] {
        let query = format!("SELECT COUNT(*) FROM {table} WHERE owner_agent_id != ?");
        let count: i64 = sqlx::query_scalar(&query)
            .bind(expected_owner.as_str())
            .fetch_one(&mut **tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        if count != 0 {
            return Err(TaskFlowError::StaleFence);
        }
    }
    Ok(())
}

async fn verify_definition_pages(
    tx: &mut Transaction<'_, Sqlite>,
    expected_owner: &AgentId,
) -> Result<(), TaskFlowError> {
    let mut cursor: Option<(String, i64)> = None;
    loop {
        let rows = if let Some((workflow_id, version)) = cursor.as_ref() {
            sqlx::query(
                "SELECT workflow_id, version, registered_generation, registered_at_ms
                 FROM taskflow_definitions
                 WHERE owner_agent_id = ?
                   AND (workflow_id > ? OR (workflow_id = ? AND version > ?))
                 ORDER BY workflow_id, version LIMIT ?",
            )
            .bind(expected_owner.as_str())
            .bind(workflow_id)
            .bind(workflow_id)
            .bind(*version)
            .bind(TASKFLOW_VERIFY_PAGE_LIMIT)
            .fetch_all(&mut **tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
        } else {
            sqlx::query(
                "SELECT workflow_id, version, registered_generation, registered_at_ms
                 FROM taskflow_definitions
                 WHERE owner_agent_id = ?
                 ORDER BY workflow_id, version LIMIT ?",
            )
            .bind(expected_owner.as_str())
            .bind(TASKFLOW_VERIFY_PAGE_LIMIT)
            .fetch_all(&mut **tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
        };
        if rows.is_empty() {
            return Ok(());
        }
        for row in &rows {
            let workflow_id: String = required(row, "workflow_id")?;
            validate_text(&workflow_id, "workflow id")?;
            let version_raw: i64 = required(row, "version")?;
            let version = to_u32(version_raw)?;
            let generation = to_u64(required(row, "registered_generation")?)?;
            if generation == 0 {
                return Err(corrupt(
                    "TaskFlow definition registration generation is zero",
                ));
            }
            to_u64(required(row, "registered_at_ms")?)?;
            load_taskflow_definition_tx(tx, expected_owner, &workflow_id, version)
                .await?
                .ok_or_else(|| corrupt("TaskFlow definition disappeared inside read snapshot"))?;
            cursor = Some((workflow_id, version_raw));
        }
        if rows.len() < TASKFLOW_VERIFY_PAGE_SIZE {
            return Ok(());
        }
    }
}

async fn verify_run_pages(
    tx: &mut Transaction<'_, Sqlite>,
    expected_owner: &AgentId,
) -> Result<(), TaskFlowError> {
    let mut cursor: Option<String> = None;
    loop {
        let rows = if let Some(run_id) = cursor.as_ref() {
            sqlx::query(
                "SELECT * FROM taskflow_runs
                 WHERE owner_agent_id = ? AND run_id > ?
                 ORDER BY run_id LIMIT ?",
            )
            .bind(expected_owner.as_str())
            .bind(run_id)
            .bind(TASKFLOW_VERIFY_PAGE_LIMIT)
            .fetch_all(&mut **tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
        } else {
            sqlx::query(
                "SELECT * FROM taskflow_runs
                 WHERE owner_agent_id = ? ORDER BY run_id LIMIT ?",
            )
            .bind(expected_owner.as_str())
            .bind(TASKFLOW_VERIFY_PAGE_LIMIT)
            .fetch_all(&mut **tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
        };
        if rows.is_empty() {
            return Ok(());
        }
        for row in &rows {
            let run = run_from_row(row, expected_owner)?;
            let definition = load_taskflow_definition_tx(
                tx,
                expected_owner,
                &run.workflow_id,
                run.workflow_version,
            )
            .await?
            .ok_or_else(|| corrupt("TaskFlow run references a missing definition"))?;
            if definition.definition_digest != run.definition_digest {
                return Err(corrupt(
                    "TaskFlow run definition digest does not match registry",
                ));
            }
            verify_event_pages(tx, &run).await?;
            cursor = Some(run.run_id);
        }
        if rows.len() < TASKFLOW_VERIFY_PAGE_SIZE {
            return Ok(());
        }
    }
}

async fn verify_event_pages(
    tx: &mut Transaction<'_, Sqlite>,
    run: &TaskFlowRun,
) -> Result<(), TaskFlowError> {
    let maximum: Option<i64> = sqlx::query_scalar(
        "SELECT MAX(event_seq) FROM taskflow_events
         WHERE owner_agent_id = ? AND run_id = ?",
    )
    .bind(run.owner_agent_id.as_str())
    .bind(&run.run_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let maximum = maximum
        .ok_or_else(|| corrupt("TaskFlow run has no event history"))
        .and_then(to_u64)?;
    if maximum == 0 {
        return Err(corrupt("TaskFlow event sequence starts at zero"));
    }
    let mut verifier = EventVerifier::new(maximum);
    let mut cursor = 0_i64;
    loop {
        let rows = sqlx::query(
            "SELECT event_seq, command_id, command_digest, transition, payload_json,
                    revision, state_digest, previous_event_digest, event_digest,
                    owner_id, owner_epoch, generation, fencing_token
             FROM taskflow_events
             WHERE owner_agent_id = ? AND run_id = ? AND event_seq > ?
             ORDER BY event_seq LIMIT ?",
        )
        .bind(run.owner_agent_id.as_str())
        .bind(&run.run_id)
        .bind(cursor)
        .bind(TASKFLOW_VERIFY_PAGE_LIMIT)
        .fetch_all(&mut **tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        if rows.is_empty() {
            break;
        }
        for row in &rows {
            cursor = to_i64(verifier.verify_row(run, row)?)?;
        }
        if rows.len() < TASKFLOW_VERIFY_PAGE_SIZE {
            break;
        }
    }
    verifier.finish(run)
}

struct EventVerifier {
    maximum: u64,
    next: u64,
    previous: String,
    last_state: Option<String>,
    last_revision: u64,
    maximum_owner_epoch: Option<u64>,
    maximum_generation: Option<u64>,
    current_fence: Option<(String, u64, u64, String)>,
}

impl EventVerifier {
    fn new(maximum: u64) -> Self {
        Self {
            maximum,
            next: 1,
            previous: ZERO_DIGEST.to_string(),
            last_state: None,
            last_revision: 0,
            maximum_owner_epoch: None,
            maximum_generation: None,
            current_fence: None,
        }
    }

    fn verify_row(
        &mut self,
        run: &TaskFlowRun,
        row: &sqlx::sqlite::SqliteRow,
    ) -> Result<u64, TaskFlowError> {
        let seq = to_u64(required(row, "event_seq")?)?;
        if seq != self.next {
            return Err(corrupt("TaskFlow event sequence has a gap"));
        }
        let command_id: String = required(row, "command_id")?;
        let command_digest: String = required(row, "command_digest")?;
        let transition: String = required(row, "transition")?;
        let payload: String = required(row, "payload_json")?;
        let revision = to_u64(required(row, "revision")?)?;
        if revision < self.last_revision {
            return Err(corrupt("TaskFlow event revisions are not monotonic"));
        }
        let state_digest: String = required(row, "state_digest")?;
        let owner_id: Option<String> = optional(row, "owner_id")?;
        let owner_epoch = optional::<i64>(row, "owner_epoch")?.map(to_u64).transpose()?;
        let generation = optional::<i64>(row, "generation")?.map(to_u64).transpose()?;
        let token: Option<String> = optional(row, "fencing_token")?;
        let has_fence = owner_id.is_some()
            || owner_epoch.is_some()
            || generation.is_some()
            || token.is_some();
        if has_fence {
            let owner_id = owner_id
                .as_deref()
                .ok_or_else(|| corrupt("TaskFlow event fence tuple is incomplete"))?;
            validate_text(owner_id, "event owner id")?;
            let owner_epoch =
                owner_epoch.ok_or_else(|| corrupt("TaskFlow event fence tuple is incomplete"))?;
            let generation =
                generation.ok_or_else(|| corrupt("TaskFlow event fence tuple is incomplete"))?;
            let token = token
                .as_deref()
                .ok_or_else(|| corrupt("TaskFlow event fence tuple is incomplete"))?;
            validate_text(token, "event fencing token")?;
            if owner_epoch == 0 || generation == 0 {
                return Err(corrupt("TaskFlow event fence contains zero epoch"));
            }
            if run.owner_epoch.is_some_and(|value| owner_epoch > value)
                || run.generation.is_some_and(|value| generation > value)
                || self
                    .maximum_owner_epoch
                    .is_some_and(|value| owner_epoch < value)
                || self
                    .maximum_generation
                    .is_some_and(|value| generation < value)
            {
                return Err(corrupt("TaskFlow event fence regresses or exceeds projection"));
            }
            let fence = (
                owner_id.to_string(),
                owner_epoch,
                generation,
                token.to_string(),
            );
            if transition == "lease_claimed" {
                if let Some((_, previous_epoch, previous_generation, _)) =
                    self.current_fence.as_ref()
                {
                    if generation <= *previous_generation || owner_epoch < *previous_epoch {
                        return Err(corrupt("TaskFlow lease claim fence does not advance"));
                    }
                }
                self.current_fence = Some(fence);
            } else if self.current_fence.as_ref() != Some(&fence) {
                return Err(corrupt("TaskFlow event fence does not match active lease"));
            }
            self.maximum_owner_epoch = Some(self.maximum_owner_epoch.unwrap_or(0).max(owner_epoch));
            self.maximum_generation = Some(self.maximum_generation.unwrap_or(0).max(generation));
        } else {
            let sticky_cancel_resume = transition == "resumed"
                && seq == self.maximum
                && run.state == TaskFlowRunState::Cancelled
                && run.cancel_requested;
            if !(matches!(
                transition.as_str(),
                "succeeded"
                    | "failed"
                    | "cancelled"
                    | "reconciled"
                    | "requeued_proven_absent"
                    | "cancelled_proven_absent"
            ) || seq == 1 && transition == "run_created"
                || sticky_cancel_resume)
            {
                return Err(corrupt("TaskFlow non-terminal event is missing fence"));
            }
        }
        let stored_previous: String = required(row, "previous_event_digest")?;
        if stored_previous != self.previous {
            return Err(corrupt("TaskFlow event predecessor digest mismatch"));
        }
        let stored_digest: String = required(row, "event_digest")?;
        let computed = event_digest(
            &self.previous,
            &run.run_id,
            seq,
            &command_id,
            &command_digest,
            &transition,
            &payload,
            revision,
            &state_digest,
        )?;
        if stored_digest != computed.as_str() {
            return Err(corrupt("TaskFlow event digest mismatch"));
        }
        parse_digest(state_digest.clone(), "event state digest")?;
        self.previous = stored_digest;
        self.last_state = Some(state_digest);
        self.last_revision = revision;
        self.next = seq
            .checked_add(1)
            .ok_or_else(|| corrupt("event sequence overflow"))?;
        Ok(seq)
    }

    fn finish(self, run: &TaskFlowRun) -> Result<(), TaskFlowError> {
        if self.next
            != self
                .maximum
                .checked_add(1)
                .ok_or_else(|| corrupt("event sequence overflow"))?
        {
            return Err(corrupt("TaskFlow event sequence has a gap"));
        }
        if self.last_revision != run.revision
            || self.last_state.as_deref() != Some(run.state_digest.as_str())
        {
            return Err(corrupt("TaskFlow event tail does not match run projection"));
        }
        if let Some(owner_id) = run.owner_id.as_deref() {
            let expected = (
                owner_id.to_string(),
                run.owner_epoch
                    .ok_or_else(|| corrupt("TaskFlow run owner epoch is missing"))?,
                run.generation
                    .ok_or_else(|| corrupt("TaskFlow run generation is missing"))?,
                run.fencing_token
                    .as_deref()
                    .ok_or_else(|| corrupt("TaskFlow run fencing token is missing"))?
                    .to_string(),
            );
            if self.current_fence.as_ref() != Some(&expected) {
                return Err(corrupt("TaskFlow event tail fence does not match run projection"));
            }
        }
        Ok(())
    }
}

fn run_from_row(
    row: &sqlx::sqlite::SqliteRow,
    expected_owner: &AgentId,
) -> Result<TaskFlowRun, TaskFlowError> {
    let owner = AgentId::parse(required::<String>(row, "owner_agent_id")?)
        .map_err(|_| corrupt("run owner is not a valid AgentId"))?;
    if &owner != expected_owner {
        return Err(TaskFlowError::StaleFence);
    }
    let run = TaskFlowRun {
        owner_agent_id: owner,
        run_id: required(row, "run_id")?,
        workflow_id: required(row, "workflow_id")?,
        workflow_version: to_u32(required(row, "workflow_version")?)?,
        definition_digest: parse_digest(required(row, "definition_digest")?, "definition digest")?,
        thread_id: required(row, "thread_id")?,
        state: parse_state(&required::<String>(row, "state")?)?,
        revision: to_u64(required(row, "revision")?)?,
        current_node: required(row, "current_node")?,
        state_digest: parse_digest(required(row, "state_digest")?, "state digest")?,
        owner_id: optional(row, "owner_id")?,
        owner_epoch: optional::<i64>(row, "owner_epoch")?.map(to_u64).transpose()?,
        generation: optional::<i64>(row, "generation")?.map(to_u64).transpose()?,
        fencing_token: optional(row, "fencing_token")?,
        lease_expires_at_ms: optional::<i64>(row, "lease_expires_at_ms")?
            .map(to_u64)
            .transpose()?,
        cancel_requested: required::<i64>(row, "cancel_requested")? != 0,
        wait_token: optional(row, "wait_token")?,
        retry_at_ms: optional::<i64>(row, "retry_at_ms")?.map(to_u64).transpose()?,
        terminal_reason: optional(row, "terminal_reason")?,
        created_at_ms: to_u64(required(row, "created_at_ms")?)?,
        updated_at_ms: to_u64(required(row, "updated_at_ms")?)?,
    };
    if run.state_digest != compute_state_digest(&run)? {
        return Err(corrupt("TaskFlow run state digest mismatch"));
    }
    Ok(run)
}

fn parse_state(value: &str) -> Result<TaskFlowRunState, TaskFlowError> {
    match value {
        "queued" => Ok(TaskFlowRunState::Queued),
        "running" => Ok(TaskFlowRunState::Running),
        "waiting" => Ok(TaskFlowRunState::Waiting),
        "retry_backoff" => Ok(TaskFlowRunState::RetryBackoff),
        "succeeded" => Ok(TaskFlowRunState::Succeeded),
        "failed" => Ok(TaskFlowRunState::Failed),
        "cancelled" => Ok(TaskFlowRunState::Cancelled),
        "indeterminate" => Ok(TaskFlowRunState::Indeterminate),
        _ => Err(corrupt(format!("unknown run state {value:?}"))),
    }
}

#[derive(Serialize)]
struct RunDigestView<'a> {
    owner_agent_id: &'a AgentId,
    run_id: &'a str,
    workflow_id: &'a str,
    workflow_version: u32,
    definition_digest: &'a Sha256Digest,
    thread_id: &'a str,
    state: TaskFlowRunState,
    revision: u64,
    current_node: &'a str,
    owner_id: Option<&'a str>,
    owner_epoch: Option<u64>,
    generation: Option<u64>,
    fencing_token: Option<&'a str>,
    lease_expires_at_ms: Option<u64>,
    cancel_requested: bool,
    wait_token: Option<&'a str>,
    retry_at_ms: Option<u64>,
    terminal_reason: Option<&'a str>,
    created_at_ms: u64,
    updated_at_ms: u64,
}

fn compute_state_digest(run: &TaskFlowRun) -> Result<Sha256Digest, TaskFlowError> {
    let view = RunDigestView {
        owner_agent_id: &run.owner_agent_id,
        run_id: &run.run_id,
        workflow_id: &run.workflow_id,
        workflow_version: run.workflow_version,
        definition_digest: &run.definition_digest,
        thread_id: &run.thread_id,
        state: run.state,
        revision: run.revision,
        current_node: &run.current_node,
        owner_id: run.owner_id.as_deref(),
        owner_epoch: run.owner_epoch,
        generation: run.generation,
        fencing_token: run.fencing_token.as_deref(),
        lease_expires_at_ms: run.lease_expires_at_ms,
        cancel_requested: run.cancel_requested,
        wait_token: run.wait_token.as_deref(),
        retry_at_ms: run.retry_at_ms,
        terminal_reason: run.terminal_reason.as_deref(),
        created_at_ms: run.created_at_ms,
        updated_at_ms: run.updated_at_ms,
    };
    let bytes = serde_json::to_vec(&view)
        .map_err(|error| corrupt(format!("run serialization: {error}")))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

#[allow(clippy::too_many_arguments)]
fn event_digest(
    previous: &str,
    run_id: &str,
    event_seq: u64,
    command_id: &str,
    command_digest: &str,
    transition: &str,
    payload_json: &str,
    revision: u64,
    state_digest: &str,
) -> Result<Sha256Digest, TaskFlowError> {
    let mut hasher = Sha256::new();
    for part in [
        previous.as_bytes(),
        run_id.as_bytes(),
        &event_seq.to_be_bytes(),
        command_id.as_bytes(),
        command_digest.as_bytes(),
        transition.as_bytes(),
        payload_json.as_bytes(),
        &revision.to_be_bytes(),
        state_digest.as_bytes(),
    ] {
        let length = u64::try_from(part.len())
            .map_err(|_| corrupt("event part length overflow"))?;
        hasher.update(length.to_be_bytes());
        hasher.update(part);
    }
    Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
}

fn required<T>(row: &sqlx::sqlite::SqliteRow, name: &str) -> Result<T, TaskFlowError>
where
    for<'r> T: sqlx::Decode<'r, Sqlite> + sqlx::Type<Sqlite>,
{
    row.try_get(name)
        .map_err(|_| corrupt(format!("TaskFlow {name} column")))
}

fn optional<T>(row: &sqlx::sqlite::SqliteRow, name: &str) -> Result<Option<T>, TaskFlowError>
where
    for<'r> T: sqlx::Decode<'r, Sqlite> + sqlx::Type<Sqlite>,
{
    row.try_get(name)
        .map_err(|_| corrupt(format!("TaskFlow {name} column")))
}

fn validate_text(value: &str, label: &str) -> Result<(), TaskFlowError> {
    if value.is_empty() || value.len() > MAX_ID_BYTES || value.bytes().any(|byte| byte < 0x20) {
        return Err(corrupt(format!("{label} is invalid")));
    }
    Ok(())
}

fn parse_digest(value: String, label: &str) -> Result<Sha256Digest, TaskFlowError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(corrupt(format!("{label} is malformed")));
    }
    Sha256Digest::parse(value).map_err(|_| corrupt(format!("{label} is malformed")))
}

fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value).map_err(|_| corrupt("integer exceeds SQLite range"))
}

fn to_u64(value: i64) -> Result<u64, TaskFlowError> {
    u64::try_from(value).map_err(|_| corrupt("negative integer in TaskFlow row"))
}

fn to_u32(value: i64) -> Result<u32, TaskFlowError> {
    u32::try_from(value).map_err(|_| corrupt("invalid workflow version"))
}

fn corrupt(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Corrupt(message.into())
}
