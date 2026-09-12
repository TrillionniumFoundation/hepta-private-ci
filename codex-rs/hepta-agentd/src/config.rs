use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AgentdError;

pub const HEPTA_AGENT_ID_ENV: &str = "HEPTA_AGENT_ID";
pub const HEPTA_AGENT_GENERATION_ENV: &str = "HEPTA_AGENT_GENERATION";
pub const HEPTA_AGENT_HOME_ENV: &str = "HEPTA_AGENT_HOME";
pub const HEPTA_AGENT_RUN_ROOT_ENV: &str = "HEPTA_AGENT_RUN_ROOT";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIdentity {
    pub agent_id: AgentId,
    pub layout: HeptaAgentLayout,
    pub spawn_generation: u64,
    pub fleet_root: PathBuf,
    pub workspace: PathBuf,
    pub resources: ResourceBudget,
    pub home_root: PathBuf,
    pub run_root: PathBuf,
    pub control_socket: PathBuf,
    pub app_server_socket: PathBuf,
}

pub struct AgentdConfig {
    identity: AgentdIdentity,
    registry: FleetRegistry,
    _writer_lock: File,
    authbus_trust_file: Option<PathBuf>,
}

impl AgentdConfig {
    pub fn from_process_environment() -> Result<Self, AgentdError> {
        let fleet_root = required_path(codex_hepta_paths::HEPTA_FLEET_ROOT_ENV)?;
        let agent_id = required_utf8(HEPTA_AGENT_ID_ENV)?;
        let spawn_generation = required_utf8(HEPTA_AGENT_GENERATION_ENV)?
            .parse::<u64>()
            .map_err(|_| {
                AgentdError::Invalid(format!(
                    "{HEPTA_AGENT_GENERATION_ENV} must be an unsigned integer"
                ))
            })?;
        let home_root = required_path(HEPTA_AGENT_HOME_ENV)?;
        let run_root = required_path(HEPTA_AGENT_RUN_ROOT_ENV)?;
        let codex_home = required_path("CODEX_HOME")?;
        let current_dir = std::env::current_dir()?;
        Self::load(
            fleet_root,
            AgentId::parse(agent_id).map_err(|error| AgentdError::Invalid(error.to_string()))?,
            spawn_generation,
            home_root,
            run_root,
            codex_home,
            current_dir,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn load(
        fleet_root: PathBuf,
        agent_id: AgentId,
        spawn_generation: u64,
        home_root: PathBuf,
        run_root: PathBuf,
        codex_home: PathBuf,
        current_dir: PathBuf,
    ) -> Result<Self, AgentdError> {
        if spawn_generation == 0 {
            return Err(AgentdError::Invalid(
                "spawn generation must be non-zero".to_string(),
            ));
        }
        let typed_fleet_root = HeptaFleetRoot::parse(fleet_root.clone())
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        require_canonical(&fleet_root, "fleet root")?;
        let registry = FleetRegistry::open_existing(typed_fleet_root)?;
        let record = registry
            .load()?
            .agent(&agent_id)
            .cloned()
            .ok_or_else(|| AgentdError::Invalid(format!("unknown fleet agent {agent_id}")))?;

        if record.lifecycle.lifecycle != AgentLifecycle::Starting
            || record.lifecycle.generation != spawn_generation
        {
            return Err(AgentdError::GenerationFenced(format!(
                "agent {agent_id} expected Starting generation {spawn_generation}, found {:?} generation {}",
                record.lifecycle.lifecycle, record.lifecycle.generation
            )));
        }
        require_exact_path(&home_root, record.layout.home_root(), "agent home")?;
        require_exact_path(&run_root, record.layout.run_root(), "agent run root")?;
        require_exact_path(&codex_home, record.layout.home_root(), "Codex home")?;
        let workspace = current_dir.canonicalize()?;
        if workspace != record.manifest.workspace.as_path() {
            return Err(AgentdError::Invalid(format!(
                "process workspace {} does not match manifest {}",
                workspace.display(),
                record.manifest.workspace.as_path().display()
            )));
        }

        let writer_lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(record.layout.writer_lock())?;
        writer_lock.try_lock().map_err(|error| {
            AgentdError::Invalid(format!(
                "agent {agent_id} already has a live writer lock: {error}"
            ))
        })?;
        let layout = record.layout;
        let control_socket = layout.agentd_control_socket().to_path_buf();
        let app_server_socket = layout.app_server_socket().to_path_buf();

        Ok(Self {
            identity: AgentdIdentity {
                agent_id,
                layout,
                spawn_generation,
                fleet_root,
                workspace,
                resources: record.manifest.resources,
                home_root,
                run_root,
                control_socket,
                app_server_socket,
            },
            registry,
            _writer_lock: writer_lock,
            authbus_trust_file: None,
        })
    }

    /// Explicit owner-managed public-key/route registry. No file is generated
    /// or trusted implicitly; the runtime validates and reloads it before use.
    pub fn with_authbus_trust_file(mut self, path: PathBuf) -> Self {
        self.authbus_trust_file = Some(path);
        self
    }

    pub(crate) fn authbus_trust_file(&self) -> Option<&Path> {
        self.authbus_trust_file.as_deref()
    }

    pub fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }

    pub(crate) fn into_parts(self) -> (AgentdIdentity, FleetRegistry, File) {
        (self.identity, self.registry, self._writer_lock)
    }
}

fn required_utf8(name: &str) -> Result<String, AgentdError> {
    let value = std::env::var_os(name)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| AgentdError::Invalid(format!("{name} is required")))?;
    value
        .into_string()
        .map_err(|_| AgentdError::Invalid(format!("{name} must be UTF-8")))
}

fn required_path(name: &str) -> Result<PathBuf, AgentdError> {
    let value: OsString = std::env::var_os(name)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| AgentdError::Invalid(format!("{name} is required")))?;
    Ok(PathBuf::from(value))
}

fn require_canonical(path: &Path, label: &str) -> Result<(), AgentdError> {
    let canonical = path.canonicalize()?;
    if canonical != path {
        return Err(AgentdError::Invalid(format!(
            "{label} must be canonical and symlink-free: {}",
            path.display()
        )));
    }
    Ok(())
}

fn require_exact_path(actual: &Path, expected: &Path, label: &str) -> Result<(), AgentdError> {
    require_canonical(actual, label)?;
    if actual != expected {
        return Err(AgentdError::Invalid(format!(
            "{label} {} does not match registered path {}",
            actual.display(),
            expected.display()
        )));
    }
    Ok(())
}

#[cfg(test)]
#[path = "config_tests.rs"]
mod tests;
