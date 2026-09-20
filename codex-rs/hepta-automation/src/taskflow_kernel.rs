//! Structural TaskFlow kernel qualification seam.
//!
//! The durable TaskFlow ledger already records an immutable transition chain,
//! but the base ledger intentionally keeps its mutation API small.  This
//! opt-in module supplies the next read-only slice: it derives a bounded graph
//! frontier and replays the durable transition payloads to verify that the
//! persisted projection still describes the same structural run.  It never
//! schedules work, invokes an activity/provider/model, or writes a row.

use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

use crate::AutomationStore;
use crate::TaskFlowDefinition;
use crate::TaskFlowError;
use crate::TaskFlowNodeKind;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowRun;
use crate::TaskFlowRunState;
use crate::TaskFlowTransition;
use crate::taskflow::load_taskflow_definition_tx;
use crate::taskflow::load_taskflow_run_tx;

/// This module is only compiled by an explicit qualification build.
pub const TASKFLOW_STRUCTURAL_QUALIFICATION_ENABLED: bool = true;
/// Structural replay is observation-only and has no external effect authority.
pub const TASKFLOW_STRUCTURAL_EFFECTS: bool = false;
/// No production caller is permitted to use this qualification seam.
pub const TASKFLOW_STRUCTURAL_PRODUCTION_CALLER: bool = false;
/// The existing automation scheduler remains the only wakeup owner.
pub const TASKFLOW_STRUCTURAL_SCHEDULER_AUTHORITY: bool = false;

const MAX_ID_BYTES: usize = 256;
/// A deterministic, read-only view of the graph frontier for one run.
///
/// `frontier_nodes` contains the sorted immediate successors of an active
/// current node.  Waiting, indeterminate, and terminal runs expose an empty
/// frontier so a caller cannot mistake this view for permission to execute.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TaskFlowFrontier {
    pub current_node: String,
    pub frontier_nodes: Vec<String>,
    pub blocked: bool,
    pub terminal: bool,
}

/// A read-only structural projection used by qualification callers.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TaskFlowStructuralPreview {
    pub run_id: String,
    pub revision: u64,
    pub state: TaskFlowRunState,
    pub current_node: String,
    pub frontier: TaskFlowFrontier,
}

/// Result of replaying one durable TaskFlow event chain.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TaskFlowReplayReport {
    pub run_id: String,
    pub event_count: u64,
    pub revision: u64,
    pub state: TaskFlowRunState,
    pub current_node: String,
    pub frontier: TaskFlowFrontier,
    /// Digest of the replayed structural result, suitable for local evidence
    /// binding.  It grants no authority and is not a production receipt.
    pub replay_digest: Sha256Digest,
}

impl TaskFlowDefinition {
    /// Derives the graph frontier without mutating the definition or a run.
    pub fn structural_frontier(
        &self,
        current_node: &str,
        state: TaskFlowRunState,
    ) -> Result<TaskFlowFrontier, TaskFlowError> {
        let (nodes, outgoing) = graph(self)?;
        let kind = nodes
            .get(current_node)
            .copied()
            .ok_or_else(|| corrupt("current node is not present in the TaskFlow definition"))?;
        let terminal = is_terminal(kind) || is_terminal_state(state);
        let blocked = terminal
            || matches!(
                state,
                TaskFlowRunState::Waiting | TaskFlowRunState::Indeterminate
            );
        let frontier_nodes = if blocked {
            Vec::new()
        } else if state == TaskFlowRunState::Queued {
            vec![current_node.to_string()]
        } else {
            outgoing.get(current_node).cloned().unwrap_or_default()
        };
        Ok(TaskFlowFrontier {
            current_node: current_node.to_string(),
            frontier_nodes,
            blocked,
            terminal,
        })
    }

    /// Returns a structural preview for a persisted run.
    pub fn structural_preview(
        &self,
        run: &TaskFlowRun,
    ) -> Result<TaskFlowStructuralPreview, TaskFlowError> {
        if run.workflow_id != self.workflow_id
            || run.workflow_version != self.version
            || run.definition_digest != self.definition_digest
        {
            return Err(corrupt("run is not bound to this TaskFlow definition"));
        }
        let frontier = self.structural_frontier(&run.current_node, run.state)?;
        Ok(TaskFlowStructuralPreview {
            run_id: run.run_id.clone(),
            revision: run.revision,
            state: run.state,
            current_node: run.current_node.clone(),
            frontier,
        })
    }
}

impl TaskFlowRun {
    /// Convenience wrapper around [`TaskFlowDefinition::structural_preview`].
    pub fn structural_preview(
        &self,
        definition: &TaskFlowDefinition,
    ) -> Result<TaskFlowStructuralPreview, TaskFlowError> {
        definition.structural_preview(self)
    }
}

impl AutomationStore {
    /// Replays one already-durable TaskFlow event chain and checks its
    /// structural result against the stored projection.  This is a read-only
    /// qualification operation; concurrent mutation or any malformed history
    /// fails closed with [`TaskFlowError::Corrupt`].
    pub async fn replay_taskflow_structural(
        &self,
        run_id: &str,
    ) -> Result<TaskFlowReplayReport, TaskFlowError> {
        // Keep the run projection, immutable definition, and event rows in
        // one SQLite snapshot.  Calling the public readers separately would
        // let a concurrent writer commit between reads, producing a report
        // that was never a durable state (or, worse, validating a run against
        // a different definition version).  This is still read-only: a
        // malformed or racing history is rejected and the transaction is
        // rolled back on every error.
        let mut transaction = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let run = load_taskflow_run_tx(&mut transaction, self.taskflow_owner_agent_id(), run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("TaskFlow run does not exist".to_string()))?;
        let definition = load_taskflow_definition_tx(
            &mut transaction,
            self.taskflow_owner_agent_id(),
            &run.workflow_id,
            run.workflow_version,
        )
        .await?
        .ok_or_else(|| corrupt("TaskFlow definition is missing during replay"))?;
        let rows = sqlx::query(
            "SELECT event_seq, command_id, transition, payload_json, revision,
                    state_digest, recorded_at_ms
             FROM taskflow_events
             WHERE owner_agent_id = ? AND run_id = ?
             ORDER BY event_seq",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .fetch_all(&mut *transaction)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        // The query above must use the same transaction, not the pool, or the
        // snapshot guarantee is lost.  (The explicit transaction handle is
        // passed through sqlx's executor implementation.)
        let report = replay_rows(&run, &definition, &rows)?;
        transaction
            .commit()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        Ok(report)
    }
}

#[derive(Clone, Debug)]
struct ReplayState {
    state: TaskFlowRunState,
    revision: u64,
    current_node: String,
    cancel_requested: bool,
    wait_token: Option<String>,
    retry_at_ms: Option<u64>,
    terminal_reason: Option<String>,
}

type TaskFlowGraph = (
    BTreeMap<String, TaskFlowNodeKind>,
    BTreeMap<String, Vec<String>>,
);

fn replay_rows(
    run: &TaskFlowRun,
    definition: &TaskFlowDefinition,
    rows: &[sqlx::sqlite::SqliteRow],
) -> Result<TaskFlowReplayReport, TaskFlowError> {
    let (_, outgoing) = graph(definition)?;
    let mut state = ReplayState {
        state: TaskFlowRunState::Queued,
        revision: 0,
        current_node: definition.entry_node.clone(),
        cancel_requested: false,
        wait_token: None,
        retry_at_ms: None,
        terminal_reason: None,
    };
    for (index, row) in rows.iter().enumerate() {
        let expected_seq =
            u64::try_from(index + 1).map_err(|_| corrupt("event sequence overflow"))?;
        let event_seq = to_u64(
            row.try_get("event_seq")
                .map_err(|_| corrupt("event sequence column"))?,
        )?;
        if event_seq != expected_seq {
            return Err(corrupt("TaskFlow replay event sequence has a gap"));
        }
        let revision = to_u64(
            row.try_get("revision")
                .map_err(|_| corrupt("event revision column"))?,
        )?;
        let expected_revision = state
            .revision
            .checked_add(1)
            .ok_or_else(|| corrupt("TaskFlow replay revision overflow"))?;
        if revision != expected_revision {
            return Err(corrupt("TaskFlow replay revision is not contiguous"));
        }
        let command_id: String = row
            .try_get("command_id")
            .map_err(|_| corrupt("event command id column"))?;
        let transition: String = row
            .try_get("transition")
            .map_err(|_| corrupt("event transition column"))?;
        let payload: String = row
            .try_get("payload_json")
            .map_err(|_| corrupt("event payload column"))?;
        let state_digest: String = row
            .try_get("state_digest")
            .map_err(|_| corrupt("event state digest column"))?;
        validate_digest(&state_digest, "event state digest")?;
        let recorded_at_ms = to_u64(
            row.try_get("recorded_at_ms")
                .map_err(|_| corrupt("event recorded timestamp column"))?,
        )?;

        if index == 0 {
            if transition != "run_created"
                || command_id != "taskflow:create"
                || payload != "{}"
                || revision != 1
            {
                return Err(corrupt("TaskFlow replay does not start with run_created"));
            }
        } else if transition == "lease_claimed" {
            if command_id != "taskflow:claim" || payload != "{}" {
                return Err(corrupt("TaskFlow lease replay envelope is malformed"));
            }
        } else {
            let parsed: TaskFlowTransition = serde_json::from_str(&payload)
                .map_err(|_| corrupt("TaskFlow transition payload is invalid"))?;
            if transition_name(&parsed) != transition {
                return Err(corrupt("TaskFlow transition name does not match payload"));
            }
            apply_replay_transition(&mut state, &outgoing, &parsed, recorded_at_ms)?;
        }
        state.revision = revision;
    }
    if rows.is_empty() {
        return Err(corrupt("TaskFlow replay has no event history"));
    }
    if state.revision != run.revision
        || state.state != run.state
        || state.current_node != run.current_node
        || state.cancel_requested != run.cancel_requested
        || state.wait_token != run.wait_token
        || state.retry_at_ms != run.retry_at_ms
        || state.terminal_reason != run.terminal_reason
    {
        return Err(corrupt(
            "TaskFlow structural replay diverges from projection",
        ));
    }
    let frontier = definition.structural_frontier(&state.current_node, state.state)?;
    let event_count = u64::try_from(rows.len()).map_err(|_| corrupt("event count overflow"))?;
    let mut report = TaskFlowReplayReport {
        run_id: run.run_id.clone(),
        event_count,
        revision: state.revision,
        state: state.state,
        current_node: state.current_node,
        frontier,
        replay_digest: Sha256Digest::for_bytes(b"uncomputed-taskflow-replay"),
    };
    let digest_view = ReplayDigestView {
        run_id: &report.run_id,
        event_count: report.event_count,
        revision: report.revision,
        state: report.state,
        current_node: &report.current_node,
        frontier: &report.frontier,
    };
    let bytes = serde_json::to_vec(&digest_view)
        .map_err(|_| corrupt("TaskFlow replay digest serialization failed"))?;
    report.replay_digest = Sha256Digest::for_bytes(&bytes);
    Ok(report)
}

#[derive(Serialize)]
struct ReplayDigestView<'a> {
    run_id: &'a str,
    event_count: u64,
    revision: u64,
    state: TaskFlowRunState,
    current_node: &'a str,
    frontier: &'a TaskFlowFrontier,
}

fn apply_replay_transition(
    state: &mut ReplayState,
    outgoing: &BTreeMap<String, Vec<String>>,
    transition: &TaskFlowTransition,
    recorded_at_ms: u64,
) -> Result<(), TaskFlowError> {
    match transition {
        TaskFlowTransition::Start => {
            if state.state != TaskFlowRunState::Queued || state.cancel_requested {
                return Err(invalid_transition(
                    "start requires a non-cancelled queued run",
                ));
            }
            state.state = TaskFlowRunState::Running;
        }
        TaskFlowTransition::Wait { token, resume_node } => {
            if state.state != TaskFlowRunState::Running {
                return Err(invalid_transition("wait requires running state"));
            }
            validate_text(token, "wait token")?;
            if let Some(target) = resume_node {
                validate_text(target, "resume node")?;
                if !outgoing
                    .get(&state.current_node)
                    .is_some_and(|targets| targets.iter().any(|node| node == target))
                {
                    return Err(corrupt("TaskFlow wait resume node is not an outgoing edge"));
                }
                state.current_node = target.clone();
            }
            state.state = TaskFlowRunState::Waiting;
            state.wait_token = Some(token.clone());
        }
        TaskFlowTransition::Resume { token } => {
            if state.state != TaskFlowRunState::Waiting
                || state.wait_token.as_deref() != Some(token)
            {
                return Err(invalid_transition(
                    "resume token does not match waiting state",
                ));
            }
            validate_text(token, "resume token")?;
            state.wait_token = None;
            if state.cancel_requested {
                state.state = TaskFlowRunState::Cancelled;
                state.terminal_reason = Some("sticky_cancel".to_string());
            } else {
                state.state = TaskFlowRunState::Running;
            }
        }
        TaskFlowTransition::Retry { retry_at_ms } => {
            if !matches!(
                state.state,
                TaskFlowRunState::Running
                    | TaskFlowRunState::Failed
                    | TaskFlowRunState::RetryBackoff
            ) {
                return Err(invalid_transition("retry requires an active state"));
            }
            if *retry_at_ms < recorded_at_ms {
                return Err(corrupt("TaskFlow retry timestamp predates its event"));
            }
            state.state = TaskFlowRunState::RetryBackoff;
            state.retry_at_ms = Some(*retry_at_ms);
        }
        TaskFlowTransition::Cancel { reason } => {
            if is_terminal_state(state.state) {
                return Err(invalid_transition("terminal run cannot be cancelled"));
            }
            validate_text(reason, "cancel reason")?;
            state.cancel_requested = true;
            state.state = TaskFlowRunState::Cancelled;
            state.terminal_reason = Some(reason.clone());
        }
        TaskFlowTransition::Succeed { output_digest } => {
            if !matches!(
                state.state,
                TaskFlowRunState::Running | TaskFlowRunState::RetryBackoff
            ) || state.cancel_requested
            {
                return Err(invalid_transition(
                    "success requires an active non-cancelled state",
                ));
            }
            validate_digest(output_digest.as_str(), "output digest")?;
            state.state = TaskFlowRunState::Succeeded;
            state.terminal_reason = Some("activity_succeeded".to_string());
        }
        TaskFlowTransition::Fail { reason } => {
            if !matches!(
                state.state,
                TaskFlowRunState::Running
                    | TaskFlowRunState::RetryBackoff
                    | TaskFlowRunState::Waiting
            ) {
                return Err(invalid_transition("failure requires an active state"));
            }
            validate_text(reason, "failure reason")?;
            state.state = TaskFlowRunState::Failed;
            state.terminal_reason = Some(reason.clone());
        }
        TaskFlowTransition::Indeterminate { reason } => {
            if is_terminal_state(state.state) {
                return Err(invalid_transition(
                    "terminal run cannot become indeterminate",
                ));
            }
            validate_text(reason, "indeterminate reason")?;
            state.state = TaskFlowRunState::Indeterminate;
            state.terminal_reason = Some(reason.clone());
        }
        TaskFlowTransition::Reconcile {
            receipt_digest,
            outcome,
        } => {
            if state.state != TaskFlowRunState::Indeterminate {
                return Err(invalid_transition("reconcile requires indeterminate state"));
            }
            validate_digest(receipt_digest.as_str(), "reconciliation receipt")?;
            state.state = match outcome {
                TaskFlowReconcileOutcome::Succeeded => TaskFlowRunState::Succeeded,
                TaskFlowReconcileOutcome::Failed => TaskFlowRunState::Failed,
                TaskFlowReconcileOutcome::Cancelled => TaskFlowRunState::Cancelled,
            };
            state.terminal_reason = Some("explicit_reconciliation".to_string());
        }
    }
    Ok(())
}

fn graph(definition: &TaskFlowDefinition) -> Result<TaskFlowGraph, TaskFlowError> {
    definition.validate()?;
    let nodes = definition
        .nodes
        .iter()
        .map(|node| (node.node_id.clone(), node.kind))
        .collect::<BTreeMap<_, _>>();
    let mut outgoing = nodes
        .keys()
        .cloned()
        .map(|node| (node, Vec::new()))
        .collect::<BTreeMap<_, _>>();
    for edge in &definition.edges {
        outgoing
            .get_mut(&edge.from)
            .ok_or_else(|| corrupt("TaskFlow edge source is missing"))?
            .push(edge.to.clone());
    }
    for targets in outgoing.values_mut() {
        targets.sort();
    }
    Ok((nodes, outgoing))
}

fn transition_name(transition: &TaskFlowTransition) -> &'static str {
    match transition {
        TaskFlowTransition::Start => "started",
        TaskFlowTransition::Wait { .. } => "waiting",
        TaskFlowTransition::Resume { .. } => "resumed",
        TaskFlowTransition::Retry { .. } => "retry_scheduled",
        TaskFlowTransition::Cancel { .. } => "cancelled",
        TaskFlowTransition::Succeed { .. } => "succeeded",
        TaskFlowTransition::Fail { .. } => "failed",
        TaskFlowTransition::Indeterminate { .. } => "indeterminate",
        TaskFlowTransition::Reconcile { .. } => "reconciled",
    }
}

fn is_terminal(kind: TaskFlowNodeKind) -> bool {
    matches!(
        kind,
        TaskFlowNodeKind::TerminalSuccess | TaskFlowNodeKind::TerminalFailure
    )
}

fn is_terminal_state(state: TaskFlowRunState) -> bool {
    matches!(
        state,
        TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
    )
}

fn validate_text(value: &str, label: &str) -> Result<(), TaskFlowError> {
    if value.is_empty() || value.len() > MAX_ID_BYTES || value.bytes().any(|byte| byte < 0x20) {
        return Err(corrupt(format!("{label} is malformed")));
    }
    Ok(())
}

fn validate_digest(value: &str, label: &str) -> Result<(), TaskFlowError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(corrupt(format!("{label} is malformed")));
    }
    Ok(())
}

fn to_u64(value: i64) -> Result<u64, TaskFlowError> {
    u64::try_from(value).map_err(|_| corrupt("negative integer in TaskFlow replay row"))
}

fn invalid_transition(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::InvalidTransition(message.into())
}

fn corrupt(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Corrupt(message.into())
}
