use std::ffi::OsString;
use std::path::Component;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::RegisteredRelease;
use codex_hepta_fleet::ReleaseId;
use serde::Deserialize;
use serde::Serialize;

use crate::SupervisorError;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentCommand {
    pub program: PathBuf,
    pub args: Vec<OsString>,
}

/// Immutable process command resolved from the fleet-owned release catalog.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentRelease {
    identity: ReleaseId,
    command: AgentCommand,
    matrixd_command: Option<AgentCommand>,
}

impl AgentRelease {
    pub fn new(
        identity: impl Into<String>,
        command: AgentCommand,
    ) -> Result<Self, SupervisorError> {
        let identity = ReleaseId::parse(identity.into())?;
        Ok(Self {
            identity,
            command,
            matrixd_command: None,
        })
    }

    pub fn with_matrixd(
        identity: impl Into<String>,
        command: AgentCommand,
        matrixd_command: AgentCommand,
    ) -> Result<Self, SupervisorError> {
        let identity = ReleaseId::parse(identity.into())?;
        Ok(Self {
            identity,
            command,
            matrixd_command: Some(matrixd_command),
        })
    }

    pub fn identity(&self) -> &str {
        self.identity.as_str()
    }

    pub fn command(&self) -> &AgentCommand {
        &self.command
    }

    pub fn matrixd_command(&self) -> Option<&AgentCommand> {
        self.matrixd_command.as_ref()
    }

    pub(crate) fn unversioned(command: AgentCommand) -> Result<Self, SupervisorError> {
        Self::new("unversioned", command)
    }

    pub(crate) fn release_id(&self) -> &ReleaseId {
        &self.identity
    }
}

impl TryFrom<RegisteredRelease> for AgentRelease {
    type Error = SupervisorError;

    fn try_from(release: RegisteredRelease) -> Result<Self, Self::Error> {
        let command = AgentCommand::new(
            release.program,
            release.args.into_iter().map(OsString::from).collect(),
        )?;
        let matrixd_command = release
            .matrixd
            .map(|program| {
                AgentCommand::new(
                    program.program,
                    program.args.into_iter().map(OsString::from).collect(),
                )
            })
            .transpose()?;
        Ok(Self {
            identity: release.release_id,
            command,
            matrixd_command,
        })
    }
}

impl AgentCommand {
    pub fn new(program: impl Into<PathBuf>, args: Vec<OsString>) -> Result<Self, SupervisorError> {
        let program = program.into();
        let argument_bytes = args.iter().try_fold(0_usize, |total, argument| {
            total.checked_add(argument.to_string_lossy().len())
        });
        if !program.is_absolute()
            || !program
                .components()
                .any(|component| matches!(component, Component::Normal(_)))
            || program
                .components()
                .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
            || args.len() > 128
            || program.to_string_lossy().len() > 4_096
            || argument_bytes.is_none_or(|bytes| bytes > 65_536)
        {
            return Err(SupervisorError::Invalid(
                "agent command path and arguments exceed bounded local-process limits".to_string(),
            ));
        }
        Ok(Self { program, args })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SupervisorConfig {
    pub health_timeout: Duration,
    pub drain_timeout: Duration,
    pub stop_grace: Duration,
    pub event_capacity: usize,
    pub log_capacity: usize,
    pub max_log_bytes: usize,
    pub driver_poll_batch: usize,
}

impl SupervisorConfig {
    pub fn local_default() -> Self {
        Self {
            // A cold App Server start may need to hydrate its local runtime and
            // scan agent-owned configuration before the UDS health endpoint is
            // available. Keep this well above the observed debug/cold-start
            // time so the lifecycle controller does not kill a healthy agent.
            health_timeout: Duration::from_secs(60),
            drain_timeout: Duration::from_secs(30),
            stop_grace: Duration::from_secs(5),
            event_capacity: 128,
            log_capacity: 256,
            max_log_bytes: 4_096,
            driver_poll_batch: 64,
        }
    }

    pub(crate) fn validate(&self) -> Result<(), SupervisorError> {
        if self.health_timeout.is_zero()
            || self.drain_timeout.is_zero()
            || self.stop_grace.is_zero()
            || !(1..=4_096).contains(&self.event_capacity)
            || !(1..=16_384).contains(&self.log_capacity)
            || !(1..=65_536).contains(&self.max_log_bytes)
            || !(1..=1_024).contains(&self.driver_poll_batch)
        {
            return Err(SupervisorError::Invalid(
                "supervisor deadlines and buffer bounds must be finite and non-zero".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProcessIdentity {
    system_id: u64,
    incarnation: String,
}

impl ProcessIdentity {
    pub fn new(system_id: u64, incarnation: impl Into<String>) -> Result<Self, SupervisorError> {
        let incarnation = incarnation.into();
        if system_id == 0
            || incarnation.is_empty()
            || incarnation.len() > 128
            || !incarnation.is_ascii()
        {
            return Err(SupervisorError::Invalid(
                "process identity must have a non-zero system id and bounded ASCII incarnation"
                    .to_string(),
            ));
        }
        Ok(Self {
            system_id,
            incarnation,
        })
    }

    pub fn system_id(&self) -> u64 {
        self.system_id
    }

    pub(crate) fn incarnation(&self) -> &str {
        &self.incarnation
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProcessStream {
    Stdout,
    Stderr,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProcessLog {
    pub stream: ProcessStream,
    pub bytes: Vec<u8>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProcessExit {
    pub success: bool,
    pub code: Option<i32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SupervisorEventKind {
    Spawned,
    Healthy,
    Lifecycle(AgentLifecycle),
    DrainRequested,
    StopRequested,
    KillRequested,
    RestartQueued,
    UpgradeQueued { previous: String, target: String },
    UpgradeCommitted { previous: String, target: String },
    AutomaticRollbackQueued { failed: String, target: String },
    AutomaticRollbackCommitted { failed: String, restored: String },
    AutomaticRollbackFailed { failed: String, rollback: String },
    ExplicitRollbackQueued { previous: String, target: String },
    ExplicitRollbackCommitted { previous: String, target: String },
    Exited(ProcessExit),
    OrphanAdopted,
    OrphanMissing,
    OrphanRejected,
    MatrixSpawned,
    MatrixHealthy,
    MatrixStopRequested,
    MatrixKillRequested,
    MatrixExited(ProcessExit),
    MatrixOrphanAdopted,
    MatrixOrphanMissing,
    MatrixOrphanRejected,
    MatrixDegraded(String),
    GenerationFenced { runtime: u64, registry: u64 },
    DriverFault(String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SupervisorEvent {
    pub generation: u64,
    pub kind: SupervisorEventKind,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentFault {
    pub agent_id: AgentId,
    pub message: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct TickReport {
    pub faults: Vec<AgentFault>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentSupervisorSnapshot {
    pub active: bool,
    pub healthy: bool,
    pub runtime_generation: Option<u64>,
    pub spawn_generation: Option<u64>,
    pub process_system_id: Option<u64>,
    pub active_release: Option<String>,
    pub previous_release: Option<String>,
    pub release_change_pending: bool,
    pub matrix: MatrixSupervisorSnapshot,
    pub events: Vec<SupervisorEvent>,
    pub logs: Vec<ProcessLog>,
    pub(crate) control_revision: u64,
    pub(crate) restart_pending: bool,
    pub(crate) release_state_generation: u64,
    pub(crate) runtime_phase: Option<ControlRuntimePhase>,
    pub(crate) runtime_release: Option<String>,
    pub(crate) runtime_incarnation: Option<String>,
    pub(crate) runtime_fenced: bool,
    pub(crate) release_change: Option<ControlReleaseChange>,
    pub(crate) has_last_command: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ControlRuntimePhase {
    AwaitingHealth,
    Running,
    Draining,
    Stopping,
    Killing,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ControlReleaseChangePhase {
    WaitingForTargetExit,
    TargetStarting,
    AutomaticRollbackStarting,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct ControlReleaseChange {
    pub origin_release: String,
    pub target_release: String,
    pub prior_previous_release: Option<String>,
    pub phase: ControlReleaseChangePhase,
    pub explicit_rollback: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixSupervisorSnapshot {
    pub configured: bool,
    pub active: bool,
    pub healthy: bool,
    pub degraded: bool,
    pub process_system_id: Option<u64>,
    pub attached_agent_generation: Option<u64>,
    pub binding_revision: Option<u64>,
    pub restart_attempt: u32,
    pub last_error: Option<String>,
}
