//! Private owner-root/bootstrap fixtures; no step claim or read authority.
//! This module exists only in the opt-in Automation unit-test compilation.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::SqlitePool;
use tempfile::TempDir;

use crate::AUTOMATION_SCHEMA_VERSION;
use crate::AutomationError;
use crate::AutomationStore;
use crate::TaskFlowCommand;
use crate::TaskFlowDefinition;
use crate::TaskFlowEdgeSpec;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowNodeKind;
use crate::TaskFlowNodeSpec;
use crate::TaskFlowRun;
use crate::TaskFlowRunState;
use crate::TaskFlowTransition;

const MARKER: &str = ".taskflow-qualification.json";
const STAGE: &str = "prepare_claim_v1";
const CLOCK_ORIGIN_MS: u64 = 1_000;
const RUN_ID: &str = "run00001";
const ACTIVITY: &str = "retrieval-choice";

// Exact definitions emitted by this fixture's root_schema.sql. Intentionally
// no SQL normalization: a weakened trigger or extra object must not be admitted.
const EXPECTED_SCHEMA: [(&str, &str, &str, Option<&str>); 12] = [
    (
        "index",
        "sqlite_autoindex_qualification_retrieval_choices_1",
        "qualification_retrieval_choices",
        None,
    ),
    (
        "index",
        "sqlite_autoindex_qualification_retrieval_choices_2",
        "qualification_retrieval_choices",
        None,
    ),
    (
        "index",
        "sqlite_autoindex_qualification_retrieval_claims_1",
        "qualification_retrieval_claims",
        None,
    ),
    (
        "table",
        "qualification_retrieval_binding",
        "qualification_retrieval_binding",
        Some(
            r#"CREATE TABLE qualification_retrieval_binding (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    format_version INTEGER NOT NULL CHECK (format_version = 1),
    stage TEXT NOT NULL CHECK (stage = 'prepare_claim_v1'),
    owner_agent_id TEXT NOT NULL,
    canonical_root TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    base_schema_version INTEGER NOT NULL CHECK (base_schema_version = 19),
    clock_origin_ms INTEGER NOT NULL CHECK (clock_origin_ms = 1000)
)"#,
        ),
    ),
    (
        "table",
        "qualification_retrieval_choices",
        "qualification_retrieval_choices",
        Some(
            r#"CREATE TABLE qualification_retrieval_choices (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    definition_digest TEXT NOT NULL,
    command_id TEXT NOT NULL,
    command_digest TEXT NOT NULL,
    command_bytes BLOB NOT NULL CHECK (length(command_bytes) <= 16384),
    native_command_digest TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt = 1),
    event_seq INTEGER NOT NULL CHECK (event_seq > 0),
    frozen_revision INTEGER NOT NULL CHECK (frozen_revision >= 0),
    bootstrap_event_seq INTEGER NOT NULL CHECK (bootstrap_event_seq > 0),
    PRIMARY KEY (owner_agent_id, run_id),
    UNIQUE (owner_agent_id, run_id, activation_id),
    FOREIGN KEY (owner_agent_id, run_id, definition_digest)
        REFERENCES taskflow_runs(owner_agent_id, run_id, definition_digest),
    FOREIGN KEY (owner_agent_id, run_id, step_id, attempt, event_seq)
        REFERENCES taskflow_step_outbox(owner_agent_id, run_id, step_id, attempt, event_seq)
)"#,
        ),
    ),
    (
        "table",
        "qualification_retrieval_claims",
        "qualification_retrieval_claims",
        Some(
            r#"CREATE TABLE qualification_retrieval_claims (
    owner_agent_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    command_digest TEXT NOT NULL,
    command_bytes BLOB NOT NULL CHECK (length(command_bytes) <= 16384),
    native_command_digest TEXT NOT NULL,
    step_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt = 1),
    event_seq INTEGER NOT NULL CHECK (event_seq > 0),
    PRIMARY KEY (owner_agent_id, run_id, activation_id),
    FOREIGN KEY (owner_agent_id, run_id, activation_id)
        REFERENCES qualification_retrieval_choices(owner_agent_id, run_id, activation_id),
    FOREIGN KEY (owner_agent_id, run_id, step_id, attempt, event_seq)
        REFERENCES taskflow_step_outbox(owner_agent_id, run_id, step_id, attempt, event_seq)
)"#,
        ),
    ),
    (
        "trigger",
        "qualification_binding_no_delete",
        "qualification_retrieval_binding",
        Some(
            r#"CREATE TRIGGER qualification_binding_no_delete
BEFORE DELETE ON qualification_retrieval_binding BEGIN
    SELECT RAISE(ABORT, 'qualification binding is immutable');
END"#,
        ),
    ),
    (
        "trigger",
        "qualification_binding_no_update",
        "qualification_retrieval_binding",
        Some(
            r#"CREATE TRIGGER qualification_binding_no_update
BEFORE UPDATE ON qualification_retrieval_binding BEGIN
    SELECT RAISE(ABORT, 'qualification binding is immutable');
END"#,
        ),
    ),
    (
        "trigger",
        "qualification_choices_no_delete",
        "qualification_retrieval_choices",
        Some(
            r#"CREATE TRIGGER qualification_choices_no_delete
BEFORE DELETE ON qualification_retrieval_choices BEGIN
    SELECT RAISE(ABORT, 'qualification choice is immutable');
END"#,
        ),
    ),
    (
        "trigger",
        "qualification_choices_no_update",
        "qualification_retrieval_choices",
        Some(
            r#"CREATE TRIGGER qualification_choices_no_update
BEFORE UPDATE ON qualification_retrieval_choices BEGIN
    SELECT RAISE(ABORT, 'qualification choice is immutable');
END"#,
        ),
    ),
    (
        "trigger",
        "qualification_claims_no_delete",
        "qualification_retrieval_claims",
        Some(
            r#"CREATE TRIGGER qualification_claims_no_delete
BEFORE DELETE ON qualification_retrieval_claims BEGIN
    SELECT RAISE(ABORT, 'qualification claim is immutable');
END"#,
        ),
    ),
    (
        "trigger",
        "qualification_claims_no_update",
        "qualification_retrieval_claims",
        Some(
            r#"CREATE TRIGGER qualification_claims_no_update
BEFORE UPDATE ON qualification_retrieval_claims BEGIN
    SELECT RAISE(ABORT, 'qualification claim is immutable');
END"#,
        ),
    ),
];

#[derive(Debug, thiserror::Error)]
pub(crate) enum FixtureError {
    #[error("fixture store admission failed: {0}")]
    Store(#[from] AutomationError),
    #[error("fixture owner operation failed: {0}")]
    TaskFlow(#[from] TaskFlowError),
    #[error("fixture filesystem failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("fixture admission is invalid")]
    Invalid,
    #[error("fixture encoding exceeds its reviewed budget")]
    Budget,
    #[error("fixture fault injection")]
    Injected,
    #[error("fixture SQL failed: {0}")]
    Sql(#[from] sqlx::Error),
}

#[derive(Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct Marker {
    version: u32,
    stage: String,
    owner: String,
    root: String,
    correlation: String,
    clock_origin_ms: u64,
}

pub(crate) struct FixtureRootCapability {
    _directory: TempDir,
    root: PathBuf,
    root_text: String,
    owner: AgentId,
    correlation: String,
    initialized: AtomicBool,
    bootstrap_started: AtomicBool,
    clock: AtomicU64,
    activation: OnceLock<TaskFlowRun>,
    bootstrap_event_seq: OnceLock<u64>,
}

impl FixtureRootCapability {
    pub(crate) fn root(&self) -> &Path {
        &self.root
    }

    pub(crate) fn owner(&self) -> &AgentId {
        &self.owner
    }

    fn marker(&self) -> Marker {
        Marker {
            version: 1,
            stage: STAGE.to_owned(),
            owner: self.owner.as_str().to_owned(),
            root: self.root_text.clone(),
            correlation: self.correlation.clone(),
            clock_origin_ms: CLOCK_ORIGIN_MS,
        }
    }

    pub(crate) fn now_ms(&self) -> u64 {
        self.clock.load(Ordering::SeqCst)
    }

    fn advance_clock(&self, now_ms: u64) -> Result<(), FixtureError> {
        if now_ms > i64::MAX as u64 {
            return Err(FixtureError::Invalid);
        }
        self.clock
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |current| {
                (now_ms >= current).then_some(now_ms)
            })
            .map_err(|_| FixtureError::Invalid)?;
        Ok(())
    }
}

struct FixtureRoot {
    capability: Arc<FixtureRootCapability>,
}

struct FixtureConnection {
    // Ordinary Drop initiates pool cleanup before releasing the root capability.
    // Only explicit close().await proves that pool shutdown has completed.
    store: AutomationStore,
    capability: Arc<FixtureRootCapability>,
}

impl FixtureRoot {
    async fn new_synthetic(owner: AgentId) -> Result<Self, FixtureError> {
        let directory = tempfile::tempdir()?;
        let root = std::fs::canonicalize(directory.path())?;
        let root_text = root.to_str().ok_or(FixtureError::Invalid)?.to_owned();
        let capability = Arc::new(FixtureRootCapability {
            _directory: directory,
            root,
            root_text,
            owner,
            correlation: uuid::Uuid::now_v7().to_string(),
            initialized: AtomicBool::new(false),
            bootstrap_started: AtomicBool::new(false),
            clock: AtomicU64::new(CLOCK_ORIGIN_MS),
            activation: OnceLock::new(),
            bootstrap_event_seq: OnceLock::new(),
        });
        let marker = serde_json::to_vec(&capability.marker()).map_err(|_| FixtureError::Invalid)?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(capability.root.join(MARKER))?;
        file.write_all(&marker)?;
        file.sync_all()?;
        let store = AutomationStore::open_qualification_root(&capability).await?;
        let installed = install_binding(&store, &capability).await;
        store.taskflow_pool().close().await;
        installed?;
        capability.initialized.store(true, Ordering::SeqCst);
        Ok(Self { capability })
    }

    async fn connection(&self) -> Result<FixtureConnection, FixtureError> {
        let store = AutomationStore::open_qualification_root(&self.capability).await?;
        Ok(FixtureConnection {
            store,
            capability: Arc::clone(&self.capability),
        })
    }
}

impl FixtureConnection {
    async fn bootstrap_fixed_activity(&self) -> Result<TaskFlowRun, FixtureError> {
        check_root(
            self.capability.root(),
            self.store.owner_agent_id(),
            Some(&self.capability),
        )?;
        check_pool(
            self.store.taskflow_pool(),
            self.store.owner_agent_id(),
            Some(&self.capability),
        )
        .await?;
        if self
            .capability
            .bootstrap_started
            .swap(true, Ordering::SeqCst)
        {
            return Err(FixtureError::Invalid);
        }
        let fence = TaskFlowFence::new(
            self.capability.owner.clone(),
            "owner001",
            /*owner_epoch*/ 1,
            /*generation*/ 1,
            "fence001",
        )?;
        let definition = TaskFlowDefinition::new(
            "read0001",
            /*version*/ 1,
            ACTIVITY,
            vec![
                TaskFlowNodeSpec::new(ACTIVITY, TaskFlowNodeKind::Activity),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![
                TaskFlowEdgeSpec::new(ACTIVITY, "success"),
                TaskFlowEdgeSpec::new(ACTIVITY, "failure"),
            ],
            Vec::new(),
            Sha256Digest::for_bytes(b"retrieval-owner-bootstrap-v1"),
        )?;
        self.store
            .register_taskflow_definition(
                &definition,
                &fence,
                self.capability.clock.load(Ordering::SeqCst),
            )
            .await?;
        self.store
            .create_taskflow_run(
                RUN_ID,
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                "thread01",
                self.capability.clock.load(Ordering::SeqCst),
            )
            .await?;
        let claimed = self
            .store
            .claim_taskflow_run(
                RUN_ID,
                &fence,
                self.capability.clock.load(Ordering::SeqCst),
                /*lease_duration_ms*/ 1_000,
            )
            .await?;
        let command = TaskFlowCommand::new(
            RUN_ID,
            "start001",
            fence,
            claimed.revision,
            TaskFlowTransition::Start,
            self.capability.clock.load(Ordering::SeqCst),
        )?;
        self.store.apply_taskflow_command(&command).await?;
        let run = self
            .store
            .taskflow_run(RUN_ID)
            .await?
            .ok_or(FixtureError::Invalid)?;
        if run.state != TaskFlowRunState::Running || run.current_node != ACTIVITY {
            return Err(FixtureError::Invalid);
        }
        let replay = self.store.replay_taskflow_structural(RUN_ID).await?;
        if replay.revision != run.revision
            || replay.state != run.state
            || replay.current_node != run.current_node
        {
            return Err(FixtureError::Invalid);
        }
        self.capability
            .bootstrap_event_seq
            .set(replay.event_count)
            .map_err(|_| FixtureError::Invalid)?;
        self.capability
            .activation
            .set(run.clone())
            .map_err(|_| FixtureError::Invalid)?;
        Ok(run)
    }

    fn prepare_command(&self) -> Result<records::PhaseCommand, FixtureError> {
        records::PhaseCommand::prepare(&self.capability)
    }

    fn claim_command(
        &self,
        prepare: &records::PhaseCommand,
    ) -> Result<records::PhaseCommand, FixtureError> {
        prepare.claim(self.capability.now_ms())
    }

    async fn phase(
        &self,
        command: &records::PhaseCommand,
    ) -> Result<records::PhaseOutcome, FixtureError> {
        self.store
            .retrieval_phase_command(
                &self.capability,
                command,
                records::PhaseFault::None,
                /*before_write*/ None,
            )
            .await
    }

    async fn close(self) {
        self.store.taskflow_pool().close().await;
    }
}

pub(crate) fn check_root(
    root: &Path,
    owner: &AgentId,
    capability: Option<&FixtureRootCapability>,
) -> Result<(), AutomationError> {
    let marker_path = root.join(MARKER);
    let Some(capability) = capability else {
        return match std::fs::symlink_metadata(marker_path) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            _ => Err(AutomationError::Invalid),
        };
    };
    let regular_marker = std::fs::symlink_metadata(&marker_path)
        .map_err(|_| AutomationError::Corrupt)?
        .file_type()
        .is_file();
    if owner != &capability.owner
        || std::fs::canonicalize(root).map_err(|_| AutomationError::Invalid)? != capability.root
        || !regular_marker
    {
        return Err(AutomationError::Invalid);
    }
    let file = File::open(marker_path).map_err(|_| AutomationError::Corrupt)?;
    let mut bytes = Vec::new();
    file.take(2_049)
        .read_to_end(&mut bytes)
        .map_err(|_| AutomationError::Corrupt)?;
    if bytes.len() > 2_048 {
        return Err(AutomationError::Corrupt);
    }
    let marker: Marker = serde_json::from_slice(&bytes).map_err(|_| AutomationError::Corrupt)?;
    if marker != capability.marker() {
        return Err(AutomationError::Corrupt);
    }
    Ok(())
}

pub(crate) async fn check_pool(
    pool: &SqlitePool,
    owner: &AgentId,
    capability: Option<&FixtureRootCapability>,
) -> Result<(), AutomationError> {
    let mut connection = pool
        .acquire()
        .await
        .map_err(|_| AutomationError::Unavailable)?;
    check_connection(&mut connection, owner, capability).await
}

pub(crate) async fn check_connection(
    connection: &mut sqlx::SqliteConnection,
    owner: &AgentId,
    capability: Option<&FixtureRootCapability>,
) -> Result<(), AutomationError> {
    // Inspect only this fixture's binding objects/prefix, not the product schema.
    // Thirteen rows suffice to reject extras beyond this exact twelve-object set.
    let objects: Vec<(String, String, String, Option<String>)> = sqlx::query_as(
        "SELECT type, name, tbl_name, sql FROM sqlite_master
         WHERE tbl_name GLOB 'qualification_retrieval_*'
            OR name GLOB 'qualification_retrieval_*'
         ORDER BY type, name, tbl_name, sql LIMIT 13",
    )
    .fetch_all(&mut *connection)
    .await
    .map_err(|_| AutomationError::Corrupt)?;
    let Some(capability) = capability else {
        return if objects.is_empty() {
            Ok(())
        } else {
            Err(AutomationError::Invalid)
        };
    };
    if owner != &capability.owner {
        return Err(AutomationError::Invalid);
    }
    if !capability.initialized.load(Ordering::SeqCst) {
        return if objects.is_empty() {
            Ok(())
        } else {
            Err(AutomationError::Corrupt)
        };
    }
    let expected_objects: Vec<_> = EXPECTED_SCHEMA
        .iter()
        .map(|(kind, name, table, sql)| {
            (
                kind.to_string(),
                name.to_string(),
                table.to_string(),
                sql.map(str::to_owned),
            )
        })
        .collect();
    if objects != expected_objects {
        return Err(AutomationError::Corrupt);
    }
    let row: Option<(i64, String, String, String, String, i64, i64)> = sqlx::query_as(
        "SELECT format_version, stage, owner_agent_id, canonical_root, correlation_id,
                base_schema_version, clock_origin_ms
         FROM qualification_retrieval_binding WHERE singleton = 1",
    )
    .fetch_optional(&mut *connection)
    .await
    .map_err(|_| AutomationError::Corrupt)?;
    let expected = (
        1,
        STAGE.to_owned(),
        owner.as_str().to_owned(),
        capability.root_text.clone(),
        capability.correlation.clone(),
        i64::from(AUTOMATION_SCHEMA_VERSION),
        CLOCK_ORIGIN_MS as i64,
    );
    if row != Some(expected) {
        return Err(AutomationError::Corrupt);
    }
    Ok(())
}

async fn install_binding(
    store: &AutomationStore,
    capability: &FixtureRootCapability,
) -> Result<(), AutomationError> {
    let mut tx = store
        .taskflow_pool()
        .begin()
        .await
        .map_err(|_| AutomationError::Unavailable)?;
    sqlx::raw_sql(include_str!("root_schema.sql"))
        .execute(&mut *tx)
        .await
        .map_err(|_| AutomationError::Unavailable)?;
    sqlx::query(
        "INSERT INTO qualification_retrieval_binding
         (singleton, format_version, stage, owner_agent_id, canonical_root, correlation_id,
          base_schema_version, clock_origin_ms) VALUES (1, 1, ?, ?, ?, ?, ?, ?)",
    )
    .bind(STAGE)
    .bind(store.owner_agent_id().as_str())
    .bind(&capability.root_text)
    .bind(&capability.correlation)
    .bind(i64::from(AUTOMATION_SCHEMA_VERSION))
    .bind(CLOCK_ORIGIN_MS as i64)
    .execute(&mut *tx)
    .await
    .map_err(|_| AutomationError::Unavailable)?;
    tx.commit().await.map_err(|_| AutomationError::Unavailable)
}

pub(crate) mod budget;
mod encoding;
pub(crate) mod records;
#[cfg(test)]
mod tests;
