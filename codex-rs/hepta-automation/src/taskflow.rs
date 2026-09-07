//! Agent-local, qualification-only TaskFlow definition and run ledger.
//!
//! This module is deliberately small and boring: it gives the H2 compiler and
//! H3 durable-kernel work a typed seam without creating a second scheduler or
//! an effect executor.  Definitions and transitions are immutable evidence in
//! the existing per-Agent automation SQLite database.  The existing
//! `AutomationScheduler` remains the only wakeup owner; callers must provide a
//! lease/generation fence for every run mutation.

#![allow(
    clippy::expect_used,
    reason = "validated graph maps are total by construction; invariant failures are programmer errors"
)]
#![allow(
    clippy::too_many_arguments,
    reason = "event digest framing keeps every authenticated field explicit"
)]

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fmt;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AutomationStore;

pub const TASKFLOW_SCHEMA_VERSION: u32 = 1;
pub const TASKFLOW_NAMESPACE: &str = "local_qualification_only";
pub const TASKFLOW_EXTERNAL_EFFECTS: bool = false;
pub const TASKFLOW_PRODUCTION_CALLER: bool = false;
pub const TASKFLOW_SCHEDULER_AUTHORITY: bool = false;

const MAX_ID_BYTES: usize = 256;
const MAX_NODES: usize = 256;
const MAX_EDGES: usize = 1_024;
const MAX_CAPABILITIES: usize = 256;
const ZERO_DIGEST: &str = "0000000000000000000000000000000000000000000000000000000000000000";

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum TaskFlowError {
    #[error("invalid TaskFlow input: {0}")]
    Invalid(String),
    #[error("TaskFlow owner or generation fence is stale")]
    StaleFence,
    #[error("TaskFlow state conflict: {0}")]
    Conflict(String),
    #[error("TaskFlow store is corrupt: {0}")]
    Corrupt(String),
    #[error("TaskFlow store is unavailable")]
    Unavailable,
    #[error("TaskFlow transition is not valid in the current state: {0}")]
    InvalidTransition(String),
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskFlowNodeKind {
    Activity,
    Wait,
    Effect,
    TerminalSuccess,
    TerminalFailure,
}

impl TaskFlowNodeKind {
    fn is_terminal(self) -> bool {
        matches!(self, Self::TerminalSuccess | Self::TerminalFailure)
    }
}

/// A deliberately constrained node contract.  Activity and Effect nodes are
/// represented only; this qualification ledger never invokes a callback.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TaskFlowNodeSpec {
    pub node_id: String,
    pub kind: TaskFlowNodeKind,
    pub capability: Option<String>,
    pub idempotency_template: Option<String>,
    pub recovery_path: bool,
    pub max_attempts: u32,
    pub wait_timeout_ms: Option<u64>,
}

impl TaskFlowNodeSpec {
    pub fn new(node_id: impl Into<String>, kind: TaskFlowNodeKind) -> Self {
        Self {
            node_id: node_id.into(),
            kind,
            capability: None,
            idempotency_template: None,
            recovery_path: true,
            max_attempts: 1,
            wait_timeout_ms: None,
        }
    }

    pub fn effect(
        node_id: impl Into<String>,
        capability: impl Into<String>,
        idempotency_template: impl Into<String>,
    ) -> Self {
        Self {
            node_id: node_id.into(),
            kind: TaskFlowNodeKind::Effect,
            capability: Some(capability.into()),
            idempotency_template: Some(idempotency_template.into()),
            recovery_path: true,
            max_attempts: 1,
            wait_timeout_ms: None,
        }
    }

    fn validate(&self, capabilities: &BTreeSet<String>) -> Result<(), TaskFlowError> {
        validate_text(&self.node_id, "node_id", /*max_bytes*/ 128)?;
        if self.max_attempts == 0 || self.max_attempts > 32 {
            return Err(invalid("max_attempts must be in 1..=32"));
        }
        if let Some(capability) = &self.capability {
            validate_text(capability, "node capability", MAX_ID_BYTES)?;
            if !capabilities.contains(capability) {
                return Err(invalid(format!(
                    "node {} requires an undeclared capability",
                    self.node_id
                )));
            }
        }
        if let Some(template) = &self.idempotency_template {
            validate_text(template, "idempotency template", MAX_ID_BYTES)?;
        }
        if self.kind == TaskFlowNodeKind::Effect
            && (self.capability.is_none()
                || self.idempotency_template.is_none()
                || !self.recovery_path)
        {
            return Err(invalid(format!(
                "effect node {} requires capability, idempotency, and recovery",
                self.node_id
            )));
        }
        if self.kind == TaskFlowNodeKind::Wait && !self.recovery_path {
            return Err(invalid(format!(
                "wait node {} has no recovery path",
                self.node_id
            )));
        }
        if self.kind.is_terminal()
            && (self.capability.is_some()
                || self.idempotency_template.is_some()
                || self.wait_timeout_ms.is_some())
        {
            return Err(invalid(format!(
                "terminal node {} carries execution fields",
                self.node_id
            )));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TaskFlowEdgeSpec {
    pub from: String,
    pub to: String,
}

impl TaskFlowEdgeSpec {
    pub fn new(from: impl Into<String>, to: impl Into<String>) -> Self {
        Self {
            from: from.into(),
            to: to.into(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TaskFlowDefinition {
    pub workflow_id: String,
    pub version: u32,
    pub entry_node: String,
    pub nodes: Vec<TaskFlowNodeSpec>,
    pub edges: Vec<TaskFlowEdgeSpec>,
    pub capability_set: Vec<String>,
    pub policy_digest: Sha256Digest,
    pub definition_digest: Sha256Digest,
}

impl TaskFlowDefinition {
    pub fn new(
        workflow_id: impl Into<String>,
        version: u32,
        entry_node: impl Into<String>,
        mut nodes: Vec<TaskFlowNodeSpec>,
        mut edges: Vec<TaskFlowEdgeSpec>,
        mut capability_set: Vec<String>,
        policy_digest: Sha256Digest,
    ) -> Result<Self, TaskFlowError> {
        nodes.sort_by(|left, right| left.node_id.cmp(&right.node_id));
        edges.sort_by(|left, right| {
            left.from
                .cmp(&right.from)
                .then_with(|| left.to.cmp(&right.to))
        });
        capability_set.sort();
        let mut definition = Self {
            workflow_id: workflow_id.into(),
            version,
            entry_node: entry_node.into(),
            nodes,
            edges,
            capability_set,
            policy_digest,
            definition_digest: Sha256Digest::for_bytes(b"uncomputed-taskflow-definition"),
        };
        definition.validate()?;
        definition.definition_digest = definition.compute_digest()?;
        Ok(definition)
    }

    pub fn validate(&self) -> Result<(), TaskFlowError> {
        validate_text(&self.workflow_id, "workflow_id", MAX_ID_BYTES)?;
        validate_text(&self.entry_node, "entry_node", /*max_bytes*/ 128)?;
        if self.version == 0 {
            return Err(invalid("workflow version must be non-zero"));
        }
        if self.nodes.is_empty() || self.nodes.len() > MAX_NODES {
            return Err(invalid("node count is outside the bounded limit"));
        }
        if self.edges.len() > MAX_EDGES {
            return Err(invalid("edge count exceeds the bounded limit"));
        }
        let policy = self.policy_digest.as_str();
        if policy.len() != 64
            || !policy
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        {
            return Err(invalid("policy digest must be lowercase sha256"));
        }
        let mut capabilities = BTreeSet::new();
        for capability in &self.capability_set {
            validate_text(capability, "capability", MAX_ID_BYTES)?;
            if !capabilities.insert(capability.clone()) {
                return Err(invalid("capability set contains a duplicate"));
            }
        }
        if capabilities.len() > MAX_CAPABILITIES {
            return Err(invalid("capability set exceeds the bounded limit"));
        }

        let mut nodes = BTreeMap::new();
        for node in &self.nodes {
            node.validate(&capabilities)?;
            if nodes.insert(node.node_id.clone(), node.kind).is_some() {
                return Err(invalid("workflow contains duplicate node ids"));
            }
        }
        if !nodes.contains_key(&self.entry_node) {
            return Err(invalid("entry node is not present"));
        }

        let mut outgoing: BTreeMap<String, Vec<String>> =
            nodes.keys().cloned().map(|key| (key, Vec::new())).collect();
        let mut incoming: BTreeMap<String, Vec<String>> =
            nodes.keys().cloned().map(|key| (key, Vec::new())).collect();
        for edge in &self.edges {
            validate_text(&edge.from, "edge source", /*max_bytes*/ 128)?;
            validate_text(&edge.to, "edge target", /*max_bytes*/ 128)?;
            if edge.from == edge.to {
                return Err(invalid("self-loop is not allowed"));
            }
            if !nodes.contains_key(&edge.from) || !nodes.contains_key(&edge.to) {
                return Err(invalid("edge references an unknown node"));
            }
            let targets = outgoing
                .get_mut(&edge.from)
                .expect("validated source node must exist");
            if targets.contains(&edge.to) {
                return Err(invalid("workflow contains duplicate edges"));
            }
            targets.push(edge.to.clone());
            incoming
                .get_mut(&edge.to)
                .expect("validated target node must exist")
                .push(edge.from.clone());
        }
        for (node_id, kind) in &nodes {
            let targets = outgoing
                .get(node_id)
                .expect("outgoing entry exists for every node");
            if kind.is_terminal() && !targets.is_empty() {
                return Err(invalid(format!(
                    "terminal node {node_id} has outgoing edges"
                )));
            }
            if !kind.is_terminal() && targets.is_empty() {
                return Err(invalid(format!(
                    "non-terminal node {node_id} has no successor"
                )));
            }
        }
        if !nodes
            .values()
            .any(|kind| *kind == TaskFlowNodeKind::TerminalSuccess)
            || !nodes
                .values()
                .any(|kind| *kind == TaskFlowNodeKind::TerminalFailure)
        {
            return Err(invalid("workflow needs success and failure terminal nodes"));
        }

        // Kahn's algorithm rejects hidden loops.  A loop is intentionally not
        // represented by this first durable slice; bounded retry is a node
        // policy, not a graph cycle.
        let mut indegree: BTreeMap<String, usize> = incoming
            .iter()
            .map(|(node, parents)| (node.clone(), parents.len()))
            .collect();
        let mut ready: BTreeSet<String> = indegree
            .iter()
            .filter(|(_, degree)| **degree == 0)
            .map(|(node, _)| node.clone())
            .collect();
        let mut consumed = 0_usize;
        while let Some(node) = ready.pop_first() {
            consumed += 1;
            for target in outgoing
                .get(&node)
                .expect("outgoing entry exists for every node")
            {
                let degree = indegree
                    .get_mut(target)
                    .expect("target degree exists for every edge");
                *degree -= 1;
                if *degree == 0 {
                    ready.insert(target.clone());
                }
            }
        }
        if consumed != nodes.len() {
            return Err(invalid("workflow graph contains a cycle"));
        }

        // Every node must be reachable from the entry and must have a path to
        // a terminal.  This catches detached recovery/failure branches before
        // a definition can enter the durable registry.
        let mut reachable = BTreeSet::from([self.entry_node.clone()]);
        let mut frontier = vec![self.entry_node.clone()];
        while let Some(node) = frontier.pop() {
            for target in outgoing
                .get(&node)
                .expect("outgoing entry exists for every node")
            {
                if reachable.insert(target.clone()) {
                    frontier.push(target.clone());
                }
            }
        }
        if reachable.len() != nodes.len() {
            return Err(invalid("workflow contains an unreachable node"));
        }
        let mut can_terminal: BTreeSet<String> = nodes
            .iter()
            .filter(|(_, kind)| kind.is_terminal())
            .map(|(node, _)| node.clone())
            .collect();
        let mut reverse_frontier: Vec<String> = can_terminal.iter().cloned().collect();
        while let Some(node) = reverse_frontier.pop() {
            for parent in incoming
                .get(&node)
                .expect("incoming entry exists for every node")
            {
                if can_terminal.insert(parent.clone()) {
                    reverse_frontier.push(parent.clone());
                }
            }
        }
        if can_terminal.len() != nodes.len() {
            return Err(invalid(
                "workflow has a node without a terminal recovery path",
            ));
        }
        if self.definition_digest != Sha256Digest::for_bytes(b"uncomputed-taskflow-definition")
            && self.definition_digest != self.compute_digest()?
        {
            return Err(TaskFlowError::Corrupt(
                "workflow definition digest does not match its canonical bytes".to_string(),
            ));
        }
        Ok(())
    }

    pub fn definition_digest(&self) -> &Sha256Digest {
        &self.definition_digest
    }

    fn compute_digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        let canonical = DefinitionCanonical {
            schema_version: TASKFLOW_SCHEMA_VERSION,
            workflow_id: &self.workflow_id,
            version: self.version,
            entry_node: &self.entry_node,
            nodes: &self.nodes,
            edges: &self.edges,
            capability_set: &self.capability_set,
            policy_digest: &self.policy_digest,
        };
        let bytes = serde_json::to_vec(&canonical).map_err(|error| {
            TaskFlowError::Corrupt(format!("definition serialization: {error}"))
        })?;
        Ok(Sha256Digest::for_bytes(&bytes))
    }

    fn canonical_json(&self) -> Result<String, TaskFlowError> {
        serde_json::to_string(self)
            .map_err(|error| TaskFlowError::Corrupt(format!("definition serialization: {error}")))
    }
}

#[derive(Serialize)]
struct DefinitionCanonical<'a> {
    schema_version: u32,
    workflow_id: &'a str,
    version: u32,
    entry_node: &'a str,
    nodes: &'a [TaskFlowNodeSpec],
    edges: &'a [TaskFlowEdgeSpec],
    capability_set: &'a [String],
    policy_digest: &'a Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TaskFlowDefinitionReceipt {
    pub workflow_id: String,
    pub version: u32,
    pub definition_digest: Sha256Digest,
    pub registered_generation: u64,
    pub inserted: bool,
}

/// The fence is supplied by the existing Agent-local owner.  It is never
/// minted by TaskFlow and carries no production authority.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TaskFlowFence {
    pub owner_agent_id: AgentId,
    pub owner_id: String,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: String,
}

impl TaskFlowFence {
    pub fn new(
        owner_agent_id: AgentId,
        owner_id: impl Into<String>,
        owner_epoch: u64,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<Self, TaskFlowError> {
        let fence = Self {
            owner_agent_id,
            owner_id: owner_id.into(),
            owner_epoch,
            generation,
            fencing_token: fencing_token.into(),
        };
        fence.validate()?;
        Ok(fence)
    }

    fn validate(&self) -> Result<(), TaskFlowError> {
        validate_text(&self.owner_id, "owner_id", MAX_ID_BYTES)?;
        validate_text(&self.fencing_token, "fencing_token", MAX_ID_BYTES)?;
        if self.owner_epoch == 0 || self.generation == 0 {
            return Err(invalid("owner epoch and generation must be non-zero"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskFlowRunState {
    Queued,
    Running,
    Waiting,
    RetryBackoff,
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

impl TaskFlowRunState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::Waiting => "waiting",
            Self::RetryBackoff => "retry_backoff",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::Indeterminate => "indeterminate",
        }
    }

    fn parse(value: &str) -> Result<Self, TaskFlowError> {
        match value {
            "queued" => Ok(Self::Queued),
            "running" => Ok(Self::Running),
            "waiting" => Ok(Self::Waiting),
            "retry_backoff" => Ok(Self::RetryBackoff),
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            "cancelled" => Ok(Self::Cancelled),
            "indeterminate" => Ok(Self::Indeterminate),
            _ => Err(corrupt(format!("unknown run state {value:?}"))),
        }
    }

    fn terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed | Self::Cancelled)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TaskFlowRun {
    pub owner_agent_id: AgentId,
    pub run_id: String,
    pub workflow_id: String,
    pub workflow_version: u32,
    pub definition_digest: Sha256Digest,
    pub thread_id: String,
    pub state: TaskFlowRunState,
    pub revision: u64,
    pub current_node: String,
    pub state_digest: Sha256Digest,
    pub owner_id: Option<String>,
    pub owner_epoch: Option<u64>,
    pub generation: Option<u64>,
    pub fencing_token: Option<String>,
    pub lease_expires_at_ms: Option<u64>,
    pub cancel_requested: bool,
    pub wait_token: Option<String>,
    pub retry_at_ms: Option<u64>,
    pub terminal_reason: Option<String>,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum TaskFlowTransition {
    Start,
    Wait {
        token: String,
        resume_node: Option<String>,
    },
    Resume {
        token: String,
    },
    Retry {
        retry_at_ms: u64,
    },
    Cancel {
        reason: String,
    },
    Succeed {
        output_digest: Sha256Digest,
    },
    Fail {
        reason: String,
    },
    /// Marks an unresolved activity outcome.  This is the only safe result
    /// for a crash/timeout boundary; it must be reconciled explicitly.
    Indeterminate {
        reason: String,
    },
    /// Reconciliation is explicit and receipt-bound.  It never calls a
    /// provider; the caller supplies the already-observed terminal outcome.
    Reconcile {
        receipt_digest: Sha256Digest,
        outcome: TaskFlowReconcileOutcome,
    },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskFlowReconcileOutcome {
    Succeeded,
    Failed,
    Cancelled,
}

#[derive(Clone, Debug, Serialize)]
pub struct TaskFlowCommand {
    pub run_id: String,
    pub command_id: String,
    pub fence: TaskFlowFence,
    pub expected_revision: u64,
    pub transition: TaskFlowTransition,
    pub now_ms: u64,
}

impl TaskFlowCommand {
    pub fn new(
        run_id: impl Into<String>,
        command_id: impl Into<String>,
        fence: TaskFlowFence,
        expected_revision: u64,
        transition: TaskFlowTransition,
        now_ms: u64,
    ) -> Result<Self, TaskFlowError> {
        let command = Self {
            run_id: run_id.into(),
            command_id: command_id.into(),
            fence,
            expected_revision,
            transition,
            now_ms,
        };
        validate_text(&command.run_id, "run_id", MAX_ID_BYTES)?;
        validate_text(&command.command_id, "command_id", MAX_ID_BYTES)?;
        command.fence.validate()?;
        Ok(command)
    }

    fn digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        let bytes = serde_json::to_vec(self)
            .map_err(|error| TaskFlowError::Corrupt(format!("command serialization: {error}")))?;
        Ok(Sha256Digest::for_bytes(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskFlowCommandStatus {
    Applied,
    AlreadyApplied,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TaskFlowCommandResult {
    pub status: TaskFlowCommandStatus,
    pub revision: u64,
    pub event_seq: u64,
    pub state: TaskFlowRunState,
    pub state_digest: Sha256Digest,
}

impl AutomationStore {
    /// Registers an immutable versioned definition.  A same-version exact
    /// replay is idempotent; a changed digest or a non-monotonic generation is
    /// rejected before any row is written.
    pub async fn register_taskflow_definition(
        &self,
        definition: &TaskFlowDefinition,
        fence: &TaskFlowFence,
        registered_at_ms: u64,
    ) -> Result<TaskFlowDefinitionReceipt, TaskFlowError> {
        definition.validate()?;
        self.validate_taskflow_fence(fence)?;
        let json = definition.canonical_json()?;
        let mut tx = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let existing = sqlx::query(
            "SELECT definition_digest, definition_json, registered_generation
             FROM taskflow_definitions
             WHERE owner_agent_id = ? AND workflow_id = ? AND version = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&definition.workflow_id)
        .bind(i64::from(definition.version))
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        if let Some(row) = existing {
            let digest: String = row
                .try_get("definition_digest")
                .map_err(|_| TaskFlowError::Corrupt("definition digest column".to_string()))?;
            let stored_json: String = row
                .try_get("definition_json")
                .map_err(|_| TaskFlowError::Corrupt("definition json column".to_string()))?;
            let generation = to_u64(row.try_get("registered_generation").map_err(|_| {
                TaskFlowError::Corrupt("definition generation column".to_string())
            })?)?;
            if digest != definition.definition_digest.as_str() || stored_json != json {
                return Err(TaskFlowError::Conflict(
                    "workflow version is already bound to another definition".to_string(),
                ));
            }
            tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(TaskFlowDefinitionReceipt {
                workflow_id: definition.workflow_id.clone(),
                version: definition.version,
                definition_digest: definition.definition_digest.clone(),
                registered_generation: generation,
                inserted: false,
            });
        }
        let max_generation: Option<i64> = sqlx::query_scalar(
            "SELECT MAX(registered_generation) FROM taskflow_definitions WHERE owner_agent_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        if max_generation.is_some_and(|value| fence.generation < to_u64(value).unwrap_or(u64::MAX))
        {
            return Err(TaskFlowError::StaleFence);
        }
        sqlx::query(
            "INSERT INTO taskflow_definitions (
                owner_agent_id, workflow_id, version, definition_digest,
                definition_json, registered_generation, registered_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&definition.workflow_id)
        .bind(i64::from(definition.version))
        .bind(definition.definition_digest.as_str())
        .bind(&json)
        .bind(to_i64(fence.generation)?)
        .bind(to_i64(registered_at_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(|error| {
            if is_constraint(&error) {
                TaskFlowError::Conflict("definition registration raced or duplicated".to_string())
            } else {
                TaskFlowError::Unavailable
            }
        })?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        Ok(TaskFlowDefinitionReceipt {
            workflow_id: definition.workflow_id.clone(),
            version: definition.version,
            definition_digest: definition.definition_digest.clone(),
            registered_generation: fence.generation,
            inserted: true,
        })
    }

    pub async fn taskflow_definition(
        &self,
        workflow_id: &str,
        version: u32,
    ) -> Result<Option<TaskFlowDefinition>, TaskFlowError> {
        validate_text(workflow_id, "workflow_id", MAX_ID_BYTES)?;
        let row = sqlx::query(
            "SELECT definition_json, definition_digest
             FROM taskflow_definitions
             WHERE owner_agent_id = ? AND workflow_id = ? AND version = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(workflow_id)
        .bind(i64::from(version))
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        let Some(row) = row else { return Ok(None) };
        let json: String = row
            .try_get("definition_json")
            .map_err(|_| TaskFlowError::Corrupt("definition json column".to_string()))?;
        let stored_digest: String = row
            .try_get("definition_digest")
            .map_err(|_| TaskFlowError::Corrupt("definition digest column".to_string()))?;
        let definition: TaskFlowDefinition = serde_json::from_str(&json)
            .map_err(|_| TaskFlowError::Corrupt("definition JSON is invalid".to_string()))?;
        verify_persisted_definition(&definition, &stored_digest)?;
        Ok(Some(definition))
    }

    /// Creates a queued run bound to one immutable definition.  Creation is
    /// idempotent by `(owner, run_id)` and writes the first event in the same
    /// transaction as the projection.
    pub async fn create_taskflow_run(
        &self,
        run_id: impl Into<String>,
        workflow_id: &str,
        workflow_version: u32,
        definition_digest: &Sha256Digest,
        thread_id: impl Into<String>,
        created_at_ms: u64,
    ) -> Result<TaskFlowRun, TaskFlowError> {
        let run_id = run_id.into();
        let thread_id = thread_id.into();
        validate_text(&run_id, "run_id", MAX_ID_BYTES)?;
        validate_text(workflow_id, "workflow_id", MAX_ID_BYTES)?;
        validate_text(&thread_id, "thread_id", MAX_ID_BYTES)?;
        validate_digest(definition_digest, "definition digest")?;
        let mut tx = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let definition_row = sqlx::query(
            "SELECT definition_json, definition_digest FROM taskflow_definitions
             WHERE owner_agent_id = ? AND workflow_id = ? AND version = ?
               AND definition_digest = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(workflow_id)
        .bind(i64::from(workflow_version))
        .bind(definition_digest.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?
        .ok_or_else(|| {
            TaskFlowError::Conflict("definition is not registered for this Agent".to_string())
        })?;
        let definition_json: String = definition_row
            .try_get("definition_json")
            .map_err(|_| TaskFlowError::Corrupt("definition json column".to_string()))?;
        let stored_definition_digest: String = definition_row
            .try_get("definition_digest")
            .map_err(|_| TaskFlowError::Corrupt("definition digest column".to_string()))?;
        let definition: TaskFlowDefinition =
            serde_json::from_str(&definition_json).map_err(|_| {
                TaskFlowError::Corrupt("registered definition JSON is invalid".to_string())
            })?;
        verify_persisted_definition(&definition, &stored_definition_digest)?;
        let existing =
            sqlx::query("SELECT * FROM taskflow_runs WHERE owner_agent_id = ? AND run_id = ?")
                .bind(self.taskflow_owner_agent_id().as_str())
                .bind(&run_id)
                .fetch_optional(&mut *tx)
                .await
                .map_err(|_| TaskFlowError::Unavailable)?;
        if let Some(row) = existing {
            let current = taskflow_run_from_row(&row, self.taskflow_owner_agent_id())?;
            if current.workflow_id != workflow_id
                || current.workflow_version != workflow_version
                || current.definition_digest != *definition_digest
                || current.thread_id != thread_id
            {
                return Err(TaskFlowError::Conflict(
                    "run id is bound to another definition/input".to_string(),
                ));
            }
            // An idempotent run creation is also a reopen boundary.  Do not
            // return a writable/replayable projection when its immutable
            // event history has been damaged since the opener verified it.
            verify_taskflow_event_chain_tx(&mut tx, &current).await?;
            tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(current);
        }
        let mut run = TaskFlowRun {
            owner_agent_id: self.taskflow_owner_agent_id().clone(),
            run_id: run_id.clone(),
            workflow_id: workflow_id.to_string(),
            workflow_version,
            definition_digest: definition_digest.clone(),
            thread_id,
            state: TaskFlowRunState::Queued,
            revision: 1,
            current_node: definition.entry_node.clone(),
            state_digest: Sha256Digest::for_bytes(b"uncomputed-taskflow-run"),
            owner_id: None,
            owner_epoch: None,
            generation: None,
            fencing_token: None,
            lease_expires_at_ms: None,
            cancel_requested: false,
            wait_token: None,
            retry_at_ms: None,
            terminal_reason: None,
            created_at_ms,
            updated_at_ms: created_at_ms,
        };
        run.state_digest = run.compute_state_digest()?;
        sqlx::query(
            "INSERT INTO taskflow_runs (
                owner_agent_id, run_id, workflow_id, workflow_version,
                definition_digest, thread_id, state, revision, current_node,
                state_digest, owner_id, owner_epoch, generation, fencing_token,
                lease_expires_at_ms, cancel_requested, wait_token, retry_at_ms,
                terminal_reason, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL, NULL, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&run.run_id)
        .bind(&run.workflow_id)
        .bind(i64::from(run.workflow_version))
        .bind(run.definition_digest.as_str())
        .bind(&run.thread_id)
        .bind(run.state.as_str())
        .bind(to_i64(run.revision)?)
        .bind(&run.current_node)
        .bind(run.state_digest.as_str())
        .bind(to_i64(run.created_at_ms)?)
        .bind(to_i64(run.updated_at_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(|error| if is_constraint(&error) { TaskFlowError::Conflict("run id raced or duplicated".to_string()) } else { TaskFlowError::Unavailable })?;
        append_taskflow_event(
            &mut tx,
            &run,
            "run_created",
            "taskflow:create",
            &Sha256Digest::for_bytes(b"taskflow:create"),
            "{}",
            ZERO_DIGEST,
        )
        .await?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        Ok(run)
    }

    pub async fn taskflow_run(&self, run_id: &str) -> Result<Option<TaskFlowRun>, TaskFlowError> {
        validate_text(run_id, "run_id", MAX_ID_BYTES)?;
        // Read the projection and its immutable event chain from one SQLite
        // snapshot.  Separate pool queries can observe a projection/event
        // pair that never existed durably when a writer commits between the
        // two reads.  The transaction is read-only and grants no scheduler or
        // effect authority.
        let mut transaction = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let run =
            load_taskflow_run_tx(&mut transaction, self.taskflow_owner_agent_id(), run_id).await?;
        transaction
            .commit()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        Ok(run)
    }

    /// Claims a single run's wakeup lease.  No background task is created;
    /// the caller remains responsible for invoking this method at a due wakeup.
    pub async fn claim_taskflow_run(
        &self,
        run_id: &str,
        fence: &TaskFlowFence,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<TaskFlowRun, TaskFlowError> {
        validate_text(run_id, "run_id", MAX_ID_BYTES)?;
        self.validate_taskflow_fence(fence)?;
        if lease_duration_ms == 0 {
            return Err(invalid("lease duration must be non-zero"));
        }
        let expires = now_ms
            .checked_add(lease_duration_ms)
            .ok_or_else(|| invalid("lease duration overflows timestamp"))?;
        let mut tx = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let row =
            sqlx::query("SELECT * FROM taskflow_runs WHERE owner_agent_id = ? AND run_id = ?")
                .bind(self.taskflow_owner_agent_id().as_str())
                .bind(run_id)
                .fetch_optional(&mut *tx)
                .await
                .map_err(|_| TaskFlowError::Unavailable)?
                .ok_or_else(|| {
                    TaskFlowError::Conflict("TaskFlow run does not exist".to_string())
                })?;
        let mut run = taskflow_run_from_row(&row, self.taskflow_owner_agent_id())?;
        // Lease replay/takeover must not extend a damaged append-only history.
        // Keep this audit in the same transaction as the projection update so
        // no concurrent writer can alter the chain between verification and
        // the eventual append.
        verify_taskflow_event_chain_tx(&mut tx, &run).await?;
        if run.state.terminal() {
            return Err(TaskFlowError::Conflict(
                "terminal TaskFlow run cannot be claimed".to_string(),
            ));
        }
        if run.state == TaskFlowRunState::Indeterminate {
            return Err(TaskFlowError::Conflict(
                "indeterminate TaskFlow run requires explicit reconciliation".to_string(),
            ));
        }
        if let Some(current_expires) = run.lease_expires_at_ms
            && current_expires > now_ms
        {
            if run.owner_id.as_deref() != Some(fence.owner_id.as_str())
                || run.owner_epoch != Some(fence.owner_epoch)
                || run.generation != Some(fence.generation)
                || run.fencing_token.as_deref() != Some(fence.fencing_token.as_str())
            {
                return Err(TaskFlowError::StaleFence);
            }
            return Ok(run);
        }
        if let Some(previous_generation) = run.generation
            && fence.generation <= previous_generation
        {
            return Err(TaskFlowError::StaleFence);
        }
        if let Some(previous_epoch) = run.owner_epoch
            && fence.owner_epoch < previous_epoch
        {
            return Err(TaskFlowError::StaleFence);
        }
        if run.cancel_requested {
            return Err(TaskFlowError::Conflict(
                "cancelled TaskFlow run cannot be claimed".to_string(),
            ));
        }
        run.owner_id = Some(fence.owner_id.clone());
        run.owner_epoch = Some(fence.owner_epoch);
        run.generation = Some(fence.generation);
        run.fencing_token = Some(fence.fencing_token.clone());
        run.lease_expires_at_ms = Some(expires);
        run.revision = run
            .revision
            .checked_add(1)
            .ok_or_else(|| corrupt("run revision overflow"))?;
        run.updated_at_ms = now_ms;
        run.state_digest = run.compute_state_digest()?;
        update_taskflow_run(&mut tx, &run, /*fence*/ None).await?;
        let previous = previous_event_digest(&mut tx, &run).await?;
        append_taskflow_event(
            &mut tx,
            &run,
            "lease_claimed",
            "taskflow:claim",
            &Sha256Digest::for_bytes(b"taskflow:claim"),
            "{}",
            &previous,
        )
        .await?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        Ok(run)
    }

    /// Applies one fenced CAS transition and appends its event atomically.
    pub async fn apply_taskflow_command(
        &self,
        command: &TaskFlowCommand,
    ) -> Result<TaskFlowCommandResult, TaskFlowError> {
        validate_text(&command.run_id, "run_id", MAX_ID_BYTES)?;
        validate_text(&command.command_id, "command_id", MAX_ID_BYTES)?;
        self.validate_taskflow_fence(&command.fence)?;
        let command_digest = command.digest()?;
        let mut tx = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let row =
            sqlx::query("SELECT * FROM taskflow_runs WHERE owner_agent_id = ? AND run_id = ?")
                .bind(self.taskflow_owner_agent_id().as_str())
                .bind(&command.run_id)
                .fetch_optional(&mut *tx)
                .await
                .map_err(|_| TaskFlowError::Unavailable)?
                .ok_or_else(|| {
                    TaskFlowError::Conflict("TaskFlow run does not exist".to_string())
                })?;
        let mut run = taskflow_run_from_row(&row, self.taskflow_owner_agent_id())?;
        // Validate the complete immutable history before command de-duplication
        // or any projection/event append.  A corrupt tail must never be
        // hidden behind `AlreadyApplied` or extended with a new event.
        verify_taskflow_event_chain_tx(&mut tx, &run).await?;
        let definition = load_taskflow_definition_tx(
            &mut tx,
            self.taskflow_owner_agent_id(),
            &run.workflow_id,
            run.workflow_version,
        )
        .await?
        .ok_or_else(|| corrupt("TaskFlow definition is missing during mutation"))?;
        if definition.definition_digest != run.definition_digest {
            return Err(corrupt(
                "TaskFlow run definition digest does not match registry",
            ));
        }
        if let Some(previous) = sqlx::query(
            "SELECT command_digest, revision, event_seq FROM taskflow_events
             WHERE owner_agent_id = ? AND run_id = ? AND command_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&command.run_id)
        .bind(&command.command_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?
        {
            let digest: String = previous
                .try_get("command_digest")
                .map_err(|_| TaskFlowError::Corrupt("command digest column".to_string()))?;
            if digest != command_digest.as_str() {
                return Err(TaskFlowError::Conflict(
                    "command id was reused with different bytes".to_string(),
                ));
            }
            let revision = to_u64(
                previous
                    .try_get("revision")
                    .map_err(|_| TaskFlowError::Corrupt("event revision column".to_string()))?,
            )?;
            let event_seq = to_u64(
                previous
                    .try_get("event_seq")
                    .map_err(|_| TaskFlowError::Corrupt("event sequence column".to_string()))?,
            )?;
            tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(TaskFlowCommandResult {
                status: TaskFlowCommandStatus::AlreadyApplied,
                revision,
                event_seq,
                state: run.state,
                state_digest: run.state_digest,
            });
        }
        let explicit_reconcile = run.state == TaskFlowRunState::Indeterminate
            && matches!(&command.transition, TaskFlowTransition::Reconcile { .. });
        if explicit_reconcile {
            // An indeterminate run retains its durable owner tuple, but its
            // lease may have expired while an external outcome was being
            // investigated. Reconciliation still requires that exact tuple;
            // the run is never claimable by a new generation.
            self.check_run_identity_fence(&run, &command.fence)?;
        } else {
            self.check_run_fence(&run, &command.fence, command.now_ms)?;
        }
        if command.expected_revision != run.revision {
            return Err(TaskFlowError::Conflict(format!(
                "expected revision {}, current {}",
                command.expected_revision, run.revision
            )));
        }
        let transition_name = transition_name(&command.transition);
        apply_transition(&mut run, &definition, &command.transition, command.now_ms)?;
        run.revision = run
            .revision
            .checked_add(1)
            .ok_or_else(|| corrupt("run revision overflow"))?;
        run.updated_at_ms = command.now_ms;
        run.state_digest = run.compute_state_digest()?;
        update_taskflow_run(&mut tx, &run, Some(&command.fence)).await?;
        let previous = previous_event_digest(&mut tx, &run).await?;
        let payload = serde_json::to_string(&command.transition).map_err(|error| {
            TaskFlowError::Corrupt(format!("transition serialization: {error}"))
        })?;
        let event_seq = append_taskflow_event(
            &mut tx,
            &run,
            transition_name,
            &command.command_id,
            &command_digest,
            &payload,
            &previous,
        )
        .await?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        Ok(TaskFlowCommandResult {
            status: TaskFlowCommandStatus::Applied,
            revision: run.revision,
            event_seq,
            state: run.state,
            state_digest: run.state_digest,
        })
    }

    fn validate_taskflow_fence(&self, fence: &TaskFlowFence) -> Result<(), TaskFlowError> {
        fence.validate()?;
        if fence.owner_agent_id != *self.taskflow_owner_agent_id() {
            return Err(TaskFlowError::StaleFence);
        }
        Ok(())
    }

    fn check_run_fence(
        &self,
        run: &TaskFlowRun,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<(), TaskFlowError> {
        self.check_run_identity_fence(run, fence)?;
        if run
            .lease_expires_at_ms
            .is_none_or(|expires| expires <= now_ms)
        {
            return Err(TaskFlowError::StaleFence);
        }
        Ok(())
    }

    fn check_run_identity_fence(
        &self,
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
}

impl TaskFlowRun {
    fn compute_state_digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        let view = RunDigestView {
            owner_agent_id: &self.owner_agent_id,
            run_id: &self.run_id,
            workflow_id: &self.workflow_id,
            workflow_version: self.workflow_version,
            definition_digest: &self.definition_digest,
            thread_id: &self.thread_id,
            state: self.state,
            revision: self.revision,
            current_node: &self.current_node,
            owner_id: self.owner_id.as_deref(),
            owner_epoch: self.owner_epoch,
            generation: self.generation,
            fencing_token: self.fencing_token.as_deref(),
            lease_expires_at_ms: self.lease_expires_at_ms,
            cancel_requested: self.cancel_requested,
            wait_token: self.wait_token.as_deref(),
            retry_at_ms: self.retry_at_ms,
            terminal_reason: self.terminal_reason.as_deref(),
            created_at_ms: self.created_at_ms,
            updated_at_ms: self.updated_at_ms,
        };
        let bytes = serde_json::to_vec(&view)
            .map_err(|error| TaskFlowError::Corrupt(format!("run serialization: {error}")))?;
        Ok(Sha256Digest::for_bytes(&bytes))
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

fn apply_transition(
    run: &mut TaskFlowRun,
    definition: &TaskFlowDefinition,
    transition: &TaskFlowTransition,
    now_ms: u64,
) -> Result<(), TaskFlowError> {
    match transition {
        TaskFlowTransition::Start => {
            if run.state != TaskFlowRunState::Queued {
                return Err(invalid_transition("start requires queued state"));
            }
            if run.cancel_requested {
                return Err(invalid_transition("cancelled run cannot start"));
            }
            run.state = TaskFlowRunState::Running;
        }
        TaskFlowTransition::Wait { token, resume_node } => {
            if run.state != TaskFlowRunState::Running {
                return Err(invalid_transition("wait requires running state"));
            }
            validate_text(token, "wait token", MAX_ID_BYTES)?;
            if let Some(node) = resume_node {
                validate_text(node, "resume node", /*max_bytes*/ 128)?;
                if node == &run.current_node {
                    return Err(invalid("wait resume node cannot equal current node"));
                }
                if !definition
                    .edges
                    .iter()
                    .any(|edge| edge.from == run.current_node && edge.to == *node)
                {
                    return Err(invalid_transition(
                        "wait resume node is not an outgoing edge",
                    ));
                }
                // The resume target is part of the durable state transition,
                // not merely a structural replay hint. Persisting it here
                // keeps the default writer and the opt-in replay seam on the
                // same graph-aware projection.
                run.current_node = node.clone();
            }
            run.state = TaskFlowRunState::Waiting;
            run.wait_token = Some(token.clone());
        }
        TaskFlowTransition::Resume { token } => {
            if run.state != TaskFlowRunState::Waiting || run.wait_token.as_deref() != Some(token) {
                return Err(invalid_transition(
                    "resume token does not match waiting run",
                ));
            }
            validate_text(token, "resume token", MAX_ID_BYTES)?;
            if run.cancel_requested {
                run.state = TaskFlowRunState::Cancelled;
                run.terminal_reason = Some("sticky_cancel".to_string());
                clear_lease(run);
            } else {
                run.state = TaskFlowRunState::Running;
            }
            run.wait_token = None;
        }
        TaskFlowTransition::Retry { retry_at_ms } => {
            if !matches!(
                run.state,
                TaskFlowRunState::Running
                    | TaskFlowRunState::Failed
                    | TaskFlowRunState::RetryBackoff
            ) {
                return Err(invalid_transition(
                    "retry requires running, failed, or retry-backoff state",
                ));
            }
            if *retry_at_ms < now_ms {
                return Err(invalid("retry timestamp is in the past"));
            }
            run.state = TaskFlowRunState::RetryBackoff;
            run.retry_at_ms = Some(*retry_at_ms);
        }
        TaskFlowTransition::Cancel { reason } => {
            if run.state.terminal() {
                return Err(invalid_transition("terminal run cannot be cancelled"));
            }
            validate_text(reason, "cancel reason", MAX_ID_BYTES)?;
            run.cancel_requested = true;
            run.state = TaskFlowRunState::Cancelled;
            run.terminal_reason = Some(reason.clone());
            clear_lease(run);
        }
        TaskFlowTransition::Succeed { output_digest } => {
            if !matches!(
                run.state,
                TaskFlowRunState::Running | TaskFlowRunState::RetryBackoff
            ) {
                return Err(invalid_transition(
                    "success requires running or retry-backoff state",
                ));
            }
            validate_digest(output_digest, "output digest")?;
            if run.cancel_requested {
                return Err(invalid_transition("sticky cancel rejects success"));
            }
            run.state = TaskFlowRunState::Succeeded;
            run.terminal_reason = Some("activity_succeeded".to_string());
            clear_lease(run);
        }
        TaskFlowTransition::Fail { reason } => {
            if !matches!(
                run.state,
                TaskFlowRunState::Running
                    | TaskFlowRunState::RetryBackoff
                    | TaskFlowRunState::Waiting
            ) {
                return Err(invalid_transition(
                    "failure requires a non-terminal active state",
                ));
            }
            validate_text(reason, "failure reason", MAX_ID_BYTES)?;
            run.state = TaskFlowRunState::Failed;
            run.terminal_reason = Some(reason.clone());
            clear_lease(run);
        }
        TaskFlowTransition::Indeterminate { reason } => {
            if run.state.terminal() {
                return Err(invalid_transition(
                    "terminal run cannot become indeterminate",
                ));
            }
            validate_text(reason, "indeterminate reason", MAX_ID_BYTES)?;
            run.state = TaskFlowRunState::Indeterminate;
            run.terminal_reason = Some(reason.clone());
            // Preserve the exact owner tuple as the reconciliation fence.
            // A new generation may not claim this run, and an expired lease
            // is accepted only by an explicit receipt-bound Reconcile command.
        }
        TaskFlowTransition::Reconcile {
            receipt_digest,
            outcome,
        } => {
            if run.state != TaskFlowRunState::Indeterminate {
                return Err(invalid_transition("reconcile requires indeterminate state"));
            }
            validate_digest(receipt_digest, "reconciliation receipt")?;
            run.state = match outcome {
                TaskFlowReconcileOutcome::Succeeded => TaskFlowRunState::Succeeded,
                TaskFlowReconcileOutcome::Failed => TaskFlowRunState::Failed,
                TaskFlowReconcileOutcome::Cancelled => TaskFlowRunState::Cancelled,
            };
            run.terminal_reason = Some("explicit_reconciliation".to_string());
            clear_lease(run);
        }
    }
    Ok(())
}

fn clear_lease(run: &mut TaskFlowRun) {
    run.owner_id = None;
    run.owner_epoch = None;
    run.generation = None;
    run.fencing_token = None;
    run.lease_expires_at_ms = None;
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

async fn update_taskflow_run(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    run: &TaskFlowRun,
    fence: Option<&TaskFlowFence>,
) -> Result<(), TaskFlowError> {
    let revision = to_i64(run.revision)?;
    let owner_epoch = run.owner_epoch.map(to_i64).transpose()?;
    let generation = run.generation.map(to_i64).transpose()?;
    let lease_expires_at_ms = run.lease_expires_at_ms.map(to_i64).transpose()?;
    let retry_at_ms = run.retry_at_ms.map(to_i64).transpose()?;
    let updated_at_ms = to_i64(run.updated_at_ms)?;
    let result = if let Some(fence) = fence {
        sqlx::query(
            "UPDATE taskflow_runs SET state = ?, revision = ?, current_node = ?, state_digest = ?,
             owner_id = ?, owner_epoch = ?, generation = ?, fencing_token = ?, lease_expires_at_ms = ?,
             cancel_requested = ?, wait_token = ?, retry_at_ms = ?, terminal_reason = ?, updated_at_ms = ?
             WHERE owner_agent_id = ? AND run_id = ?
               AND owner_id = ? AND owner_epoch = ? AND generation = ? AND fencing_token = ?",
        )
        .bind(run.state.as_str())
        .bind(revision)
        .bind(&run.current_node)
        .bind(run.state_digest.as_str())
        .bind(&run.owner_id)
        .bind(owner_epoch)
        .bind(generation)
        .bind(&run.fencing_token)
        .bind(lease_expires_at_ms)
        .bind(if run.cancel_requested { 1_i64 } else { 0_i64 })
        .bind(&run.wait_token)
        .bind(retry_at_ms)
        .bind(&run.terminal_reason)
        .bind(updated_at_ms)
        .bind(run.owner_agent_id.as_str())
        .bind(&run.run_id)
        .bind(&fence.owner_id)
        .bind(to_i64(fence.owner_epoch)?)
        .bind(to_i64(fence.generation)?)
        .bind(&fence.fencing_token)
        .execute(&mut **tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?
    } else {
        sqlx::query(
            "UPDATE taskflow_runs SET state = ?, revision = ?, current_node = ?, state_digest = ?,
             owner_id = ?, owner_epoch = ?, generation = ?, fencing_token = ?, lease_expires_at_ms = ?,
             cancel_requested = ?, wait_token = ?, retry_at_ms = ?, terminal_reason = ?, updated_at_ms = ?
             WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(run.state.as_str())
        .bind(revision)
        .bind(&run.current_node)
        .bind(run.state_digest.as_str())
        .bind(&run.owner_id)
        .bind(owner_epoch)
        .bind(generation)
        .bind(&run.fencing_token)
        .bind(lease_expires_at_ms)
        .bind(if run.cancel_requested { 1_i64 } else { 0_i64 })
        .bind(&run.wait_token)
        .bind(retry_at_ms)
        .bind(&run.terminal_reason)
        .bind(updated_at_ms)
        .bind(run.owner_agent_id.as_str())
        .bind(&run.run_id)
        .execute(&mut **tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?
    };
    if result.rows_affected() != 1 {
        return Err(TaskFlowError::StaleFence);
    }
    Ok(())
}

async fn previous_event_digest(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    run: &TaskFlowRun,
) -> Result<String, TaskFlowError> {
    sqlx::query_scalar::<_, String>(
        "SELECT event_digest FROM taskflow_events
         WHERE owner_agent_id = ? AND run_id = ? ORDER BY event_seq DESC LIMIT 1",
    )
    .bind(run.owner_agent_id.as_str())
    .bind(&run.run_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)
    .map(|value| value.unwrap_or_else(|| ZERO_DIGEST.to_string()))
}

async fn append_taskflow_event(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    run: &TaskFlowRun,
    transition: &str,
    command_id: &str,
    command_digest: &Sha256Digest,
    payload_json: &str,
    previous_digest: &str,
) -> Result<u64, TaskFlowError> {
    let previous_seq: Option<i64> = sqlx::query_scalar(
        "SELECT MAX(event_seq) FROM taskflow_events WHERE owner_agent_id = ? AND run_id = ?",
    )
    .bind(run.owner_agent_id.as_str())
    .bind(&run.run_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let event_seq = to_u64(previous_seq.unwrap_or(0))?
        .checked_add(1)
        .ok_or_else(|| corrupt("event sequence overflow"))?;
    let event_digest = event_digest(
        previous_digest,
        &run.run_id,
        event_seq,
        command_id,
        command_digest.as_str(),
        transition,
        payload_json,
        run.revision,
        run.state_digest.as_str(),
    )?;
    sqlx::query(
        "INSERT INTO taskflow_events (
            owner_agent_id, run_id, event_seq, command_id, command_digest,
            transition, payload_json, revision, state_digest, previous_event_digest,
            event_digest, owner_id, owner_epoch, generation, fencing_token, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(run.owner_agent_id.as_str())
    .bind(&run.run_id)
    .bind(to_i64(event_seq)?)
    .bind(command_id)
    .bind(command_digest.as_str())
    .bind(transition)
    .bind(payload_json)
    .bind(to_i64(run.revision)?)
    .bind(run.state_digest.as_str())
    .bind(previous_digest)
    .bind(event_digest.as_str())
    .bind(&run.owner_id)
    .bind(run.owner_epoch.map(to_i64).transpose()?)
    .bind(run.generation.map(to_i64).transpose()?)
    .bind(&run.fencing_token)
    .bind(to_i64(run.updated_at_ms)?)
    .execute(&mut **tx)
    .await
    .map_err(|error| {
        if is_constraint(&error) {
            TaskFlowError::Conflict("duplicate TaskFlow event".to_string())
        } else {
            TaskFlowError::Unavailable
        }
    })?;
    Ok(event_seq)
}

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
        let length =
            u64::try_from(part.len()).map_err(|_| corrupt("event part length overflow"))?;
        hasher.update(length.to_be_bytes());
        hasher.update(part);
    }
    Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
}

fn taskflow_run_from_row(
    row: &sqlx::sqlite::SqliteRow,
    expected_owner: &AgentId,
) -> Result<TaskFlowRun, TaskFlowError> {
    let owner = AgentId::parse(
        row.try_get::<String, _>("owner_agent_id")
            .map_err(|_| TaskFlowError::Corrupt("run owner column".to_string()))?,
    )
    .map_err(|_| corrupt("run owner is not a valid AgentId"))?;
    if &owner != expected_owner {
        return Err(TaskFlowError::StaleFence);
    }
    let digest = parse_digest(
        row.try_get::<String, _>("definition_digest")
            .map_err(|_| TaskFlowError::Corrupt("definition digest column".to_string()))?,
        "definition digest",
    )?;
    let state_digest = parse_digest(
        row.try_get::<String, _>("state_digest")
            .map_err(|_| TaskFlowError::Corrupt("state digest column".to_string()))?,
        "state digest",
    )?;
    let run = TaskFlowRun {
        owner_agent_id: owner,
        run_id: row
            .try_get("run_id")
            .map_err(|_| TaskFlowError::Corrupt("run id column".to_string()))?,
        workflow_id: row
            .try_get("workflow_id")
            .map_err(|_| TaskFlowError::Corrupt("workflow id column".to_string()))?,
        workflow_version: to_u32(
            row.try_get("workflow_version")
                .map_err(|_| TaskFlowError::Corrupt("workflow version column".to_string()))?,
        )?,
        definition_digest: digest,
        thread_id: row
            .try_get("thread_id")
            .map_err(|_| TaskFlowError::Corrupt("thread id column".to_string()))?,
        state: TaskFlowRunState::parse(
            &row.try_get::<String, _>("state")
                .map_err(|_| TaskFlowError::Corrupt("run state column".to_string()))?,
        )?,
        revision: to_u64(
            row.try_get("revision")
                .map_err(|_| TaskFlowError::Corrupt("run revision column".to_string()))?,
        )?,
        current_node: row
            .try_get("current_node")
            .map_err(|_| TaskFlowError::Corrupt("current node column".to_string()))?,
        state_digest,
        owner_id: row
            .try_get("owner_id")
            .map_err(|_| TaskFlowError::Corrupt("run owner id column".to_string()))?,
        owner_epoch: row
            .try_get::<Option<i64>, _>("owner_epoch")
            .map_err(|_| TaskFlowError::Corrupt("run owner epoch column".to_string()))?
            .map(to_u64)
            .transpose()?,
        generation: row
            .try_get::<Option<i64>, _>("generation")
            .map_err(|_| TaskFlowError::Corrupt("run generation column".to_string()))?
            .map(to_u64)
            .transpose()?,
        fencing_token: row
            .try_get("fencing_token")
            .map_err(|_| TaskFlowError::Corrupt("run fencing token column".to_string()))?,
        lease_expires_at_ms: row
            .try_get::<Option<i64>, _>("lease_expires_at_ms")
            .map_err(|_| TaskFlowError::Corrupt("run expiry column".to_string()))?
            .map(to_u64)
            .transpose()?,
        cancel_requested: row
            .try_get::<i64, _>("cancel_requested")
            .map_err(|_| TaskFlowError::Corrupt("run cancel column".to_string()))?
            != 0,
        wait_token: row
            .try_get("wait_token")
            .map_err(|_| TaskFlowError::Corrupt("run wait token column".to_string()))?,
        retry_at_ms: row
            .try_get::<Option<i64>, _>("retry_at_ms")
            .map_err(|_| TaskFlowError::Corrupt("run retry column".to_string()))?
            .map(to_u64)
            .transpose()?,
        terminal_reason: row
            .try_get("terminal_reason")
            .map_err(|_| TaskFlowError::Corrupt("run terminal reason column".to_string()))?,
        created_at_ms: to_u64(
            row.try_get("created_at_ms")
                .map_err(|_| TaskFlowError::Corrupt("run created column".to_string()))?,
        )?,
        updated_at_ms: to_u64(
            row.try_get("updated_at_ms")
                .map_err(|_| TaskFlowError::Corrupt("run updated column".to_string()))?,
        )?,
    };
    if run.state_digest != run.compute_state_digest()? {
        return Err(corrupt("TaskFlow run state digest mismatch"));
    }
    Ok(run)
}

const TASKFLOW_EVENT_CHAIN_QUERY: &str =
    "SELECT event_seq, command_id, command_digest, transition, payload_json,
            revision, state_digest, previous_event_digest, event_digest,
            owner_id, owner_epoch, generation, fencing_token
     FROM taskflow_events WHERE owner_agent_id = ? AND run_id = ? ORDER BY event_seq";

pub(crate) async fn verify_taskflow_event_chain_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    run: &TaskFlowRun,
) -> Result<(), TaskFlowError> {
    let rows = sqlx::query(TASKFLOW_EVENT_CHAIN_QUERY)
        .bind(run.owner_agent_id.as_str())
        .bind(&run.run_id)
        .fetch_all(&mut **tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
    verify_taskflow_event_rows(run, &rows)
}

/// Load and verify one TaskFlow definition inside a caller-owned read
/// transaction.  The transaction-scoped form is used by structural replay so
/// the immutable definition, run projection, and event chain all come from a
/// single SQLite snapshot.  It intentionally performs no mutation and grants
/// no scheduler or effect authority.
pub(crate) async fn load_taskflow_definition_tx(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    workflow_id: &str,
    version: u32,
) -> Result<Option<TaskFlowDefinition>, TaskFlowError> {
    validate_text(workflow_id, "workflow_id", MAX_ID_BYTES)?;
    if version == 0 {
        return Err(invalid("workflow version must be non-zero"));
    }
    let row = sqlx::query(
        "SELECT definition_json, definition_digest
         FROM taskflow_definitions
         WHERE owner_agent_id = ? AND workflow_id = ? AND version = ?",
    )
    .bind(owner.as_str())
    .bind(workflow_id)
    .bind(i64::from(version))
    .fetch_optional(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let Some(row) = row else { return Ok(None) };
    let json: String = row
        .try_get("definition_json")
        .map_err(|_| TaskFlowError::Corrupt("definition json column".to_string()))?;
    let stored_digest: String = row
        .try_get("definition_digest")
        .map_err(|_| TaskFlowError::Corrupt("definition digest column".to_string()))?;
    let definition: TaskFlowDefinition = serde_json::from_str(&json)
        .map_err(|_| TaskFlowError::Corrupt("definition JSON is invalid".to_string()))?;
    verify_persisted_definition(&definition, &stored_digest)?;
    Ok(Some(definition))
}

/// Load one TaskFlow run and verify its complete immutable event history while
/// holding the caller's transaction.  Keeping this operation transaction
/// scoped closes the replay race where a run projection and its event rows
/// could otherwise be observed from different snapshots.
pub(crate) async fn load_taskflow_run_tx(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    run_id: &str,
) -> Result<Option<TaskFlowRun>, TaskFlowError> {
    validate_text(run_id, "run_id", MAX_ID_BYTES)?;
    let row = sqlx::query("SELECT * FROM taskflow_runs WHERE owner_agent_id = ? AND run_id = ?")
        .bind(owner.as_str())
        .bind(run_id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
    let Some(row) = row else { return Ok(None) };
    let run = taskflow_run_from_row(&row, owner)?;
    verify_taskflow_event_chain_tx(tx, &run).await?;
    Ok(Some(run))
}

fn verify_taskflow_event_rows(
    run: &TaskFlowRun,
    rows: &[sqlx::sqlite::SqliteRow],
) -> Result<(), TaskFlowError> {
    if rows.is_empty() {
        return Err(corrupt("TaskFlow run has no event history"));
    }
    let mut previous = ZERO_DIGEST.to_string();
    let mut last_state = None;
    let mut last_revision = 0_u64;
    let mut maximum_owner_epoch = None;
    let mut maximum_generation = None;
    // Keep the lease tuple that owns the current contiguous event suffix.
    // Event fence columns are durable provenance, but are not part of the
    // legacy event digest.  Without this relation check a direct database
    // edit could replace an event's owner/token while leaving its hash-valid
    // payload untouched.  A new `lease_claimed` event is the only legal point
    // at which the tuple may change; takeover still permits a strictly newer
    // generation while historical events retain their prior tuple.
    let mut current_event_fence: Option<(String, u64, u64, String)> = None;
    for (index, row) in rows.iter().enumerate() {
        let expected_seq =
            u64::try_from(index + 1).map_err(|_| corrupt("event sequence overflow"))?;
        let event_seq = to_u64(
            row.try_get("event_seq")
                .map_err(|_| corrupt("event sequence column"))?,
        )?;
        if event_seq != expected_seq {
            return Err(corrupt("TaskFlow event sequence has a gap"));
        }
        let command_id: String = row
            .try_get("command_id")
            .map_err(|_| corrupt("event command id column"))?;
        let command_digest: String = row
            .try_get("command_digest")
            .map_err(|_| corrupt("event command digest column"))?;
        let transition: String = row
            .try_get("transition")
            .map_err(|_| corrupt("event transition column"))?;
        let payload: String = row
            .try_get("payload_json")
            .map_err(|_| corrupt("event payload column"))?;
        let revision = to_u64(
            row.try_get("revision")
                .map_err(|_| corrupt("event revision column"))?,
        )?;
        if revision < last_revision {
            return Err(corrupt("TaskFlow event revisions are not monotonic"));
        }
        let state_digest: String = row
            .try_get("state_digest")
            .map_err(|_| corrupt("event state digest column"))?;
        let owner_id: Option<String> = row
            .try_get("owner_id")
            .map_err(|_| corrupt("event owner id column"))?;
        let owner_epoch = row
            .try_get::<Option<i64>, _>("owner_epoch")
            .map_err(|_| corrupt("event owner epoch column"))?
            .map(to_u64)
            .transpose()?;
        let generation = row
            .try_get::<Option<i64>, _>("generation")
            .map_err(|_| corrupt("event generation column"))?
            .map(to_u64)
            .transpose()?;
        let fencing_token: Option<String> = row
            .try_get("fencing_token")
            .map_err(|_| corrupt("event fencing token column"))?;
        let has_fence = owner_id.is_some()
            || owner_epoch.is_some()
            || generation.is_some()
            || fencing_token.is_some();
        if has_fence {
            let owner_id = owner_id
                .as_deref()
                .ok_or_else(|| corrupt("TaskFlow event fence tuple is incomplete"))?;
            validate_text(owner_id, "event owner id", MAX_ID_BYTES)?;
            let owner_epoch =
                owner_epoch.ok_or_else(|| corrupt("TaskFlow event fence tuple is incomplete"))?;
            let generation =
                generation.ok_or_else(|| corrupt("TaskFlow event fence tuple is incomplete"))?;
            let fencing_token = fencing_token
                .as_deref()
                .ok_or_else(|| corrupt("TaskFlow event fence tuple is incomplete"))?;
            if owner_epoch == 0 || generation == 0 {
                return Err(corrupt("TaskFlow event fence contains zero epoch"));
            }
            if run.owner_epoch.is_some_and(|current| owner_epoch > current)
                || run.generation.is_some_and(|current| generation > current)
            {
                return Err(corrupt(
                    "TaskFlow event fence is newer than the run projection",
                ));
            }
            validate_text(fencing_token, "event fencing token", MAX_ID_BYTES)?;
            if maximum_owner_epoch.is_some_and(|previous| owner_epoch < previous)
                || maximum_generation.is_some_and(|previous| generation < previous)
            {
                return Err(corrupt("TaskFlow event fence regresses across generations"));
            }
            let event_fence = (
                owner_id.to_string(),
                owner_epoch,
                generation,
                fencing_token.to_string(),
            );
            if transition == "lease_claimed" {
                // A claim event is the sole lease-identity transition.  A
                // replay of an unexpired claim emits no event, while a
                // takeover must advance generation strictly.
                if let Some((_, previous_epoch, previous_generation, _)) =
                    current_event_fence.as_ref()
                {
                    if generation <= *previous_generation {
                        return Err(corrupt("TaskFlow lease claim generation does not advance"));
                    }
                    if owner_epoch < *previous_epoch {
                        return Err(corrupt("TaskFlow lease claim owner epoch regresses"));
                    }
                }
                current_event_fence = Some(event_fence);
            } else {
                // Every command/indeterminate event is written while the
                // lease is held.  Requiring the exact tuple prevents an
                // owner or fencing token from being swapped in-place while
                // preserving the old event digest.
                if current_event_fence.as_ref() != Some(&event_fence) {
                    return Err(corrupt("TaskFlow event fence does not match active lease"));
                }
            }
            maximum_owner_epoch = Some(maximum_owner_epoch.unwrap_or(0).max(owner_epoch));
            maximum_generation = Some(maximum_generation.unwrap_or(0).max(generation));
        } else {
            // `Resume` keeps its command/event name when sticky cancellation
            // converts the waiting run directly to terminal `Cancelled`.
            // That legacy shape is fence-less like the other terminal rows,
            // but it can only be the final row of a cancelled projection.
            let sticky_cancel_resume = transition == "resumed"
                && index == rows.len() - 1
                && run.state == TaskFlowRunState::Cancelled
                && run.cancel_requested;
            if !(matches!(
                transition.as_str(),
                "succeeded" | "failed" | "cancelled" | "reconciled"
            ) || index == 0 && transition == "run_created"
                || sticky_cancel_resume)
            {
                // Non-terminal transitions and lease claims must carry the fence
                // that authorized them.  Terminal events are intentionally
                // fence-less because the projection clears its lease atomically.
                return Err(corrupt("TaskFlow non-terminal event is missing fence"));
            }
        }
        let stored_previous: String = row
            .try_get("previous_event_digest")
            .map_err(|_| corrupt("event predecessor column"))?;
        if stored_previous != previous {
            return Err(corrupt("TaskFlow event predecessor digest mismatch"));
        }
        let stored_digest: String = row
            .try_get("event_digest")
            .map_err(|_| corrupt("event digest column"))?;
        let computed = event_digest(
            &previous,
            &run.run_id,
            event_seq,
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
        validate_digest_string(&state_digest, "event state digest")?;
        previous = stored_digest;
        last_state = Some(state_digest);
        last_revision = revision;
    }
    if last_revision != run.revision || last_state.as_deref() != Some(run.state_digest.as_str()) {
        return Err(corrupt("TaskFlow event tail does not match run projection"));
    }
    if let Some(owner_id) = run.owner_id.as_deref() {
        let expected_fence = (
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
        if current_event_fence.as_ref() != Some(&expected_fence) {
            return Err(corrupt(
                "TaskFlow event tail fence does not match run projection",
            ));
        }
    }
    Ok(())
}

/// Audits every TaskFlow row during automation-store open.  The regular
/// `taskflow_run` read path verifies only the requested run; an opener must
/// also reject foreign-owner rows and damaged definitions/runs that could be
/// hidden until a later, selective lookup.  All checks share one read
/// transaction so the snapshot is internally consistent.
pub(crate) async fn verify_taskflow_store(
    pool: &sqlx::SqlitePool,
    expected_owner: &AgentId,
) -> Result<(), TaskFlowError> {
    let mut tx = pool.begin().await.map_err(|_| TaskFlowError::Unavailable)?;

    let foreign_definitions: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_definitions WHERE owner_agent_id != ?")
            .bind(expected_owner.as_str())
            .fetch_one(&mut *tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
    let foreign_runs: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_runs WHERE owner_agent_id != ?")
            .bind(expected_owner.as_str())
            .fetch_one(&mut *tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
    let foreign_events: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_events WHERE owner_agent_id != ?")
            .bind(expected_owner.as_str())
            .fetch_one(&mut *tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
    if foreign_definitions != 0 || foreign_runs != 0 || foreign_events != 0 {
        return Err(TaskFlowError::StaleFence);
    }

    let definition_rows = sqlx::query(
        "SELECT workflow_id, version, definition_digest, definition_json,
                registered_generation, registered_at_ms
         FROM taskflow_definitions
         WHERE owner_agent_id = ? ORDER BY workflow_id, version",
    )
    .bind(expected_owner.as_str())
    .fetch_all(&mut *tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let mut definitions = BTreeMap::new();
    for row in definition_rows {
        let workflow_id: String = row
            .try_get("workflow_id")
            .map_err(|_| corrupt("TaskFlow definition workflow id column"))?;
        let version = to_u32(
            row.try_get("version")
                .map_err(|_| corrupt("TaskFlow definition version column"))?,
        )?;
        let stored_digest = parse_digest(
            row.try_get("definition_digest")
                .map_err(|_| corrupt("TaskFlow definition digest column"))?,
            "TaskFlow definition digest",
        )?;
        let json: String = row
            .try_get("definition_json")
            .map_err(|_| corrupt("TaskFlow definition JSON column"))?;
        let registered_generation = to_u64(
            row.try_get("registered_generation")
                .map_err(|_| corrupt("TaskFlow definition generation column"))?,
        )?;
        if registered_generation == 0 {
            return Err(corrupt(
                "TaskFlow definition registration generation is zero",
            ));
        }
        // Read the timestamp as well so a negative/directly tampered value is
        // rejected even when SQLite's CHECK constraints were bypassed.
        to_u64(
            row.try_get("registered_at_ms")
                .map_err(|_| corrupt("TaskFlow definition timestamp column"))?,
        )?;
        let definition: TaskFlowDefinition = serde_json::from_str(&json)
            .map_err(|_| corrupt("TaskFlow definition JSON is invalid"))?;
        definition.validate()?;
        if definition.workflow_id != workflow_id
            || definition.version != version
            || definition.definition_digest != stored_digest
        {
            return Err(corrupt("TaskFlow definition row key or digest mismatch"));
        }
        verify_persisted_definition(&definition, stored_digest.as_str())?;
        definitions.insert((workflow_id, version), stored_digest);
    }

    let run_rows = sqlx::query(
        "SELECT * FROM taskflow_runs
         WHERE owner_agent_id = ? ORDER BY run_id",
    )
    .bind(expected_owner.as_str())
    .fetch_all(&mut *tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    for row in run_rows {
        let run = taskflow_run_from_row(&row, expected_owner)?;
        let definition_digest = definitions
            .get(&(run.workflow_id.clone(), run.workflow_version))
            .ok_or_else(|| corrupt("TaskFlow run references a missing definition"))?;
        if definition_digest != &run.definition_digest {
            return Err(corrupt(
                "TaskFlow run definition digest does not match registry",
            ));
        }
        verify_taskflow_event_chain_tx(&mut tx, &run).await?;
    }
    tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
    Ok(())
}

fn validate_text(value: &str, label: &str, max_bytes: usize) -> Result<(), TaskFlowError> {
    if value.is_empty() || value.len() > max_bytes || value.bytes().any(|byte| byte < 0x20) {
        return Err(invalid(format!(
            "{label} must be non-empty, bounded, and printable"
        )));
    }
    Ok(())
}

fn validate_digest(digest: &Sha256Digest, label: &str) -> Result<(), TaskFlowError> {
    if digest.as_str().len() != 64
        || !digest
            .as_str()
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid(format!("{label} must be lowercase sha256")));
    }
    Ok(())
}

/// Validate a definition loaded from durable storage against its canonical
/// digest.  `TaskFlowDefinition::validate` intentionally accepts the
/// construction-time sentinel so `new` can compute a digest; that sentinel
/// must never be accepted as a persisted definition.  Checking only that the
/// JSON field equals the database column would otherwise allow a damaged row
/// whose two copies were changed to the same sentinel (or another
/// self-consistent, non-canonical value) to pass reopen and mutation paths.
fn verify_persisted_definition(
    definition: &TaskFlowDefinition,
    stored_digest: &str,
) -> Result<(), TaskFlowError> {
    definition.validate()?;
    let canonical_digest = definition.compute_digest()?;
    if definition.definition_digest != canonical_digest {
        return Err(corrupt(
            "persisted TaskFlow definition digest is not canonical",
        ));
    }
    if stored_digest != canonical_digest.as_str() {
        return Err(corrupt("definition row digest mismatch"));
    }
    Ok(())
}

fn parse_digest(value: String, label: &str) -> Result<Sha256Digest, TaskFlowError> {
    validate_digest_string(&value, label)?;
    Sha256Digest::parse(value).map_err(|_| corrupt(format!("{label} is malformed")))
}

fn validate_digest_string(value: &str, label: &str) -> Result<(), TaskFlowError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(corrupt(format!("{label} is malformed")));
    }
    Ok(())
}

fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value).map_err(|_| invalid("integer exceeds SQLite range"))
}

fn to_u64(value: i64) -> Result<u64, TaskFlowError> {
    u64::try_from(value).map_err(|_| corrupt("negative integer in TaskFlow row"))
}

fn to_u32(value: i64) -> Result<u32, TaskFlowError> {
    u32::try_from(value).map_err(|_| corrupt("invalid workflow version"))
}

fn invalid(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Invalid(message.into())
}

fn corrupt(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Corrupt(message.into())
}

fn invalid_transition(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::InvalidTransition(message.into())
}

fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation())
}

impl fmt::Display for TaskFlowCommandStatus {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Applied => "applied",
            Self::AlreadyApplied => "already_applied",
        })
    }
}
