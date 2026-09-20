use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use serde::Deserialize;
use serde::Serialize;

use crate::FleetRegistryError;

pub const AGENT_MANIFEST_SCHEMA_VERSION: u32 = 1;
pub const AGENT_STATE_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkspaceBinding {
    root: PathBuf,
}

impl WorkspaceBinding {
    pub fn new(
        path: impl Into<PathBuf>,
        fleet_root: &HeptaFleetRoot,
    ) -> Result<Self, FleetRegistryError> {
        let path = path.into();
        validate_absolute_normalized(&path, "workspace root")?;
        let canonical = path.canonicalize()?;
        if canonical != path {
            return Err(FleetRegistryError::Invalid(format!(
                "workspace root must be canonical and must not traverse a symlink: {}",
                path.display()
            )));
        }
        if !canonical.is_dir() {
            return Err(FleetRegistryError::Invalid(format!(
                "workspace root is not a directory: {}",
                canonical.display()
            )));
        }

        let fleet = fleet_root.as_path().canonicalize()?;
        if canonical.starts_with(&fleet) || fleet.starts_with(&canonical) {
            return Err(FleetRegistryError::Invalid(
                "workspace root must not overlap the fleet control root".to_string(),
            ));
        }
        Ok(Self { root: canonical })
    }

    pub fn as_path(&self) -> &Path {
        &self.root
    }

    pub(crate) fn validate(&self, fleet_root: &HeptaFleetRoot) -> Result<(), FleetRegistryError> {
        Self::new(self.root.clone(), fleet_root).map(|_| ())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceBudget {
    pub max_concurrent_turns: u16,
    pub memory_limit_mib: u32,
    pub max_tool_processes: u16,
    pub turn_queue_capacity: u32,
}

impl ResourceBudget {
    pub fn local_default() -> Self {
        Self {
            max_concurrent_turns: 2,
            memory_limit_mib: 4_096,
            max_tool_processes: 16,
            turn_queue_capacity: 256,
        }
    }

    pub(crate) fn validate(&self) -> Result<(), FleetRegistryError> {
        if !(1..=32).contains(&self.max_concurrent_turns)
            || !(128..=262_144).contains(&self.memory_limit_mib)
            || !(1..=128).contains(&self.max_tool_processes)
            || !(1..=4_096).contains(&self.turn_queue_capacity)
        {
            return Err(FleetRegistryError::Invalid(
                "resource budget exceeds supported local-agent bounds".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentManifest {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub workspace: WorkspaceBinding,
    pub resources: ResourceBudget,
}

impl AgentManifest {
    pub fn new(
        agent_id: AgentId,
        workspace: WorkspaceBinding,
        resources: ResourceBudget,
    ) -> Result<Self, FleetRegistryError> {
        resources.validate()?;
        Ok(Self {
            schema_version: AGENT_MANIFEST_SCHEMA_VERSION,
            agent_id,
            workspace,
            resources,
        })
    }

    pub(crate) fn validate(&self, fleet_root: &HeptaFleetRoot) -> Result<(), FleetRegistryError> {
        if self.schema_version != AGENT_MANIFEST_SCHEMA_VERSION {
            return Err(FleetRegistryError::Corrupt(format!(
                "unsupported agent manifest schema {}",
                self.schema_version
            )));
        }
        self.workspace.validate(fleet_root)?;
        self.resources.validate()
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentLifecycle {
    Stopped,
    Starting,
    Running,
    Draining,
    Failed,
}

impl AgentLifecycle {
    pub(crate) fn can_transition_to(self, next: Self) -> bool {
        matches!(
            (self, next),
            (Self::Stopped, Self::Starting)
                | (Self::Starting, Self::Running | Self::Failed | Self::Stopped)
                | (Self::Running, Self::Draining | Self::Failed)
                | (Self::Draining, Self::Stopped | Self::Failed)
                | (Self::Failed, Self::Starting | Self::Stopped)
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentLifecycleState {
    pub schema_version: u32,
    pub agent_id: AgentId,
    pub generation: u64,
    pub lifecycle: AgentLifecycle,
}

impl AgentLifecycleState {
    pub(crate) fn initial(agent_id: AgentId) -> Self {
        Self {
            schema_version: AGENT_STATE_SCHEMA_VERSION,
            agent_id,
            generation: 0,
            lifecycle: AgentLifecycle::Stopped,
        }
    }

    pub(crate) fn successor(&self, lifecycle: AgentLifecycle) -> Result<Self, FleetRegistryError> {
        if !self.lifecycle.can_transition_to(lifecycle) {
            return Err(FleetRegistryError::InvalidTransition {
                agent_id: self.agent_id.clone(),
                current: self.lifecycle,
                requested: lifecycle,
            });
        }
        let generation = self
            .generation
            .checked_add(1)
            .ok_or_else(|| FleetRegistryError::Corrupt("agent generation overflow".to_string()))?;
        Ok(Self {
            schema_version: AGENT_STATE_SCHEMA_VERSION,
            agent_id: self.agent_id.clone(),
            generation,
            lifecycle,
        })
    }
}

fn validate_absolute_normalized(path: &Path, label: &str) -> Result<(), FleetRegistryError> {
    if !path.is_absolute()
        || !path
            .components()
            .any(|component| matches!(component, Component::Normal(_)))
        || path
            .components()
            .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
    {
        return Err(FleetRegistryError::Invalid(format!(
            "{label} must be absolute, normalized, and non-root"
        )));
    }
    Ok(())
}
