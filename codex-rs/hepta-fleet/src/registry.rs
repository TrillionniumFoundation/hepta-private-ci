use std::collections::BTreeMap;
#[cfg(unix)]
use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetLayout;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AGENT_STATE_SCHEMA_VERSION;
use crate::AgentLifecycle;
use crate::AgentLifecycleState;
use crate::AgentManifest;
use crate::AgentReleaseState;
use crate::FleetRegistryError;
use crate::release::initialize_release_state;
use crate::release::load_release_state;

const LIFECYCLE_FILE_PREFIX: &str = "lifecycle-";
const LIFECYCLE_FILE_SUFFIX: &str = ".json";
static STAGING_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentRecord {
    pub manifest: AgentManifest,
    pub lifecycle: AgentLifecycleState,
    pub release_state: AgentReleaseState,
    pub layout: HeptaAgentLayout,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct FleetSnapshot {
    pub agents: BTreeMap<AgentId, AgentRecord>,
}

impl FleetSnapshot {
    pub fn agent(&self, agent_id: &AgentId) -> Option<&AgentRecord> {
        self.agents.get(agent_id)
    }
}

/// Durable registry for one supervisor. Agents never write this control model.
#[derive(Clone, Debug)]
pub struct FleetRegistry {
    layout: HeptaFleetLayout,
}

impl FleetRegistry {
    pub fn initialize(fleet_root: HeptaFleetRoot) -> Result<Self, FleetRegistryError> {
        let layout = fleet_root.layout();
        for directory in [
            layout.fleet_root().as_path(),
            layout.state_root(),
            layout.run_root(),
            layout.releases_root(),
            layout.agents_root(),
        ] {
            std::fs::create_dir_all(directory)?;
            validate_physical_directory(directory)?;
        }
        sync_directory(layout.fleet_root().as_path())?;
        Ok(Self { layout })
    }

    pub fn open_existing(fleet_root: HeptaFleetRoot) -> Result<Self, FleetRegistryError> {
        let registry = Self {
            layout: fleet_root.layout(),
        };
        for directory in [
            registry.layout.fleet_root().as_path(),
            registry.layout.state_root(),
            registry.layout.run_root(),
            registry.layout.releases_root(),
            registry.layout.agents_root(),
        ] {
            validate_physical_directory(directory)?;
        }
        registry.migrate_legacy_matrix_roots()?;
        registry.load()?;
        Ok(registry)
    }

    pub fn layout(&self) -> &HeptaFleetLayout {
        &self.layout
    }

    pub fn load(&self) -> Result<FleetSnapshot, FleetRegistryError> {
        let mut agents = BTreeMap::new();
        for entry in std::fs::read_dir(self.layout.agents_root())? {
            let entry = entry?;
            let file_name = entry.file_name();
            let name = file_name.to_str().ok_or_else(|| {
                FleetRegistryError::Corrupt("agent directory name is not UTF-8".to_string())
            })?;
            if name.starts_with(".staging-") {
                continue;
            }
            let agent_id = AgentId::parse(name)
                .map_err(|error| FleetRegistryError::Corrupt(error.to_string()))?;
            validate_physical_directory(&entry.path())?;
            let record = self.load_agent(&agent_id)?;
            if agents.insert(agent_id, record).is_some() {
                return Err(FleetRegistryError::Corrupt(
                    "duplicate agent identity in registry".to_string(),
                ));
            }
        }
        validate_workspace_isolation(&agents)?;
        Ok(FleetSnapshot { agents })
    }

    pub fn register(&self, manifest: AgentManifest) -> Result<AgentRecord, FleetRegistryError> {
        manifest.validate(self.layout.fleet_root())?;
        let snapshot = self.load()?;
        if snapshot.agent(&manifest.agent_id).is_some() {
            return Err(FleetRegistryError::AlreadyRegistered(manifest.agent_id));
        }
        validate_manifest_workspace(&manifest, &snapshot.agents)?;

        let staging_root = staging_root(self.layout.agents_root(), &manifest.agent_id);
        std::fs::create_dir(&staging_root)?;
        let registration = self.stage_registration(&staging_root, &manifest);
        if let Err(error) = registration {
            let _ = std::fs::remove_dir_all(&staging_root);
            return Err(error);
        }

        let final_root = self
            .layout
            .agent(&manifest.agent_id)
            .agent_root()
            .to_path_buf();
        if final_root.exists() {
            let _ = std::fs::remove_dir_all(&staging_root);
            return Err(FleetRegistryError::AlreadyRegistered(manifest.agent_id));
        }
        if let Err(error) = std::fs::rename(&staging_root, &final_root) {
            let _ = std::fs::remove_dir_all(&staging_root);
            return if error.kind() == ErrorKind::AlreadyExists {
                Err(FleetRegistryError::AlreadyRegistered(manifest.agent_id))
            } else {
                Err(error.into())
            };
        }
        sync_directory(self.layout.agents_root())?;
        self.load_agent(&manifest.agent_id)
    }

    /// One-time, fail-closed upgrade for Agent roots created before the Matrix
    /// companion geometry existed. New private directories are staged,
    /// fsynced, and renamed; existing paths must be physical directories and
    /// are only tightened to owner-only permissions.
    fn migrate_legacy_matrix_roots(&self) -> Result<(), FleetRegistryError> {
        for entry in std::fs::read_dir(self.layout.agents_root())? {
            let entry = entry?;
            let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
                return Err(FleetRegistryError::Corrupt(
                    "agent directory name is not UTF-8".to_string(),
                ));
            };
            if name.starts_with(".staging-") {
                continue;
            }
            let agent_id = AgentId::parse(&name)
                .map_err(|error| FleetRegistryError::Corrupt(error.to_string()))?;
            let layout = self.layout.agent(&agent_id);
            validate_physical_directory(layout.agent_root())?;
            migrate_private_directory(layout.agent_root(), "matrix")?;
            migrate_private_directory(layout.matrix_root(), "secrets")?;
            validate_private_directory(layout.matrix_root())?;
            validate_private_directory(layout.matrix_secrets_root())?;
        }
        Ok(())
    }

    pub fn compare_and_transition(
        &self,
        agent_id: &AgentId,
        expected_generation: u64,
        requested: AgentLifecycle,
    ) -> Result<AgentLifecycleState, FleetRegistryError> {
        let current = self.load_agent(agent_id)?.lifecycle;
        if current.generation != expected_generation {
            return Err(FleetRegistryError::StaleGeneration {
                agent_id: agent_id.clone(),
                expected: expected_generation,
                current: current.generation,
            });
        }
        let next = current.successor(requested)?;
        let layout = self.layout.agent(agent_id);
        match publish_lifecycle(layout.run_root(), &next)? {
            PublishOutcome::Published => Ok(next),
            PublishOutcome::AlreadyExists => {
                let actual = self.load_agent(agent_id)?.lifecycle.generation;
                Err(FleetRegistryError::StaleGeneration {
                    agent_id: agent_id.clone(),
                    expected: expected_generation,
                    current: actual,
                })
            }
        }
    }

    fn stage_registration(
        &self,
        staging_root: &Path,
        manifest: &AgentManifest,
    ) -> Result<(), FleetRegistryError> {
        for name in [
            "home",
            "run",
            "logs",
            "releases",
            "cognitive",
            "matrix",
            "automation",
        ] {
            std::fs::create_dir(staging_root.join(name))?;
        }
        let matrix_secrets_root = staging_root.join("matrix/secrets");
        std::fs::create_dir(&matrix_secrets_root)?;
        set_private_directory_permissions(&staging_root.join("matrix"))?;
        set_private_directory_permissions(&matrix_secrets_root)?;
        write_new_file(
            &staging_root.join("agent.toml"),
            toml::to_string(manifest)?.as_bytes(),
        )?;
        let initial = AgentLifecycleState::initial(manifest.agent_id.clone());
        write_new_file(
            &lifecycle_path(&staging_root.join("run"), initial.generation),
            &lifecycle_json(&initial)?,
        )?;
        sync_directory(&staging_root.join("run"))?;
        initialize_release_state(&staging_root.join("releases"), &manifest.agent_id)?;
        sync_directory(&staging_root.join("releases"))?;
        sync_directory(staging_root)
    }

    fn load_agent(&self, agent_id: &AgentId) -> Result<AgentRecord, FleetRegistryError> {
        let layout = self.layout.agent(agent_id);
        for directory in [
            layout.agent_root(),
            layout.home_root(),
            layout.run_root(),
            layout.logs_root(),
            layout.releases_root(),
            layout.cognitive_root(),
            layout.matrix_root(),
            layout.matrix_secrets_root(),
            layout.automation_root(),
        ] {
            validate_physical_directory(directory)?;
        }
        validate_private_directory(layout.matrix_root())?;
        validate_private_directory(layout.matrix_secrets_root())?;
        let manifest: AgentManifest = toml::from_str(&read_regular_file(layout.agent_config())?)
            .map_err(|error| {
                FleetRegistryError::Corrupt(format!("invalid agent manifest: {error}"))
            })?;
        manifest.validate(self.layout.fleet_root())?;
        if &manifest.agent_id != agent_id {
            return Err(FleetRegistryError::Corrupt(format!(
                "manifest identity {} differs from directory {agent_id}",
                manifest.agent_id
            )));
        }
        let lifecycle = load_lifecycle(layout.run_root(), agent_id)?;
        let release_state = load_release_state(layout.releases_root(), agent_id)?;
        Ok(AgentRecord {
            manifest,
            lifecycle,
            release_state,
            layout,
        })
    }
}

enum PublishOutcome {
    Published,
    AlreadyExists,
}

fn publish_lifecycle(
    run_root: &Path,
    state: &AgentLifecycleState,
) -> Result<PublishOutcome, FleetRegistryError> {
    let final_path = lifecycle_path(run_root, state.generation);
    let temp_path = run_root.join(format!(
        ".lifecycle-{}-{}-{}.tmp",
        state.generation,
        std::process::id(),
        STAGING_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ));
    write_new_file(&temp_path, &lifecycle_json(state)?)?;
    let outcome = match std::fs::hard_link(&temp_path, &final_path) {
        Ok(()) => PublishOutcome::Published,
        Err(error) if error.kind() == ErrorKind::AlreadyExists => PublishOutcome::AlreadyExists,
        Err(error) => {
            let _ = std::fs::remove_file(&temp_path);
            return Err(error.into());
        }
    };
    let _ = std::fs::remove_file(temp_path);
    sync_directory(run_root)?;
    Ok(outcome)
}

fn load_lifecycle(
    run_root: &Path,
    agent_id: &AgentId,
) -> Result<AgentLifecycleState, FleetRegistryError> {
    let mut states = BTreeMap::new();
    for entry in std::fs::read_dir(run_root)? {
        let entry = entry?;
        let file_name = entry.file_name();
        let Some(name) = file_name.to_str() else {
            return Err(FleetRegistryError::Corrupt(
                "lifecycle filename is not UTF-8".to_string(),
            ));
        };
        if name.starts_with('.') || !name.starts_with(LIFECYCLE_FILE_PREFIX) {
            continue;
        }
        let generation = parse_lifecycle_generation(name)?;
        let state: AgentLifecycleState = serde_json::from_str(&read_regular_file(&entry.path())?)
            .map_err(|error| {
            FleetRegistryError::Corrupt(format!("invalid lifecycle state: {error}"))
        })?;
        if state.schema_version != AGENT_STATE_SCHEMA_VERSION
            || &state.agent_id != agent_id
            || state.generation != generation
        {
            return Err(FleetRegistryError::Corrupt(format!(
                "lifecycle state does not match agent {agent_id} generation {generation}"
            )));
        }
        states.insert(generation, state);
    }
    let mut previous: Option<AgentLifecycleState> = None;
    for (expected, (generation, state)) in states.iter().enumerate() {
        if *generation != expected as u64 {
            return Err(FleetRegistryError::Corrupt(
                "agent lifecycle generations are not contiguous".to_string(),
            ));
        }
        if expected == 0 && state != &AgentLifecycleState::initial(agent_id.clone()) {
            return Err(FleetRegistryError::Corrupt(
                "agent lifecycle history has an invalid initial state".to_string(),
            ));
        }
        if let Some(previous) = previous.as_ref()
            && !previous.lifecycle.can_transition_to(state.lifecycle)
        {
            return Err(FleetRegistryError::Corrupt(
                "agent lifecycle history contains an invalid transition".to_string(),
            ));
        }
        previous = Some(state.clone());
    }
    previous
        .ok_or_else(|| FleetRegistryError::Corrupt("agent lifecycle state is missing".to_string()))
}

fn validate_workspace_isolation(
    agents: &BTreeMap<AgentId, AgentRecord>,
) -> Result<(), FleetRegistryError> {
    for (agent_id, record) in agents {
        validate_manifest_workspace(&record.manifest, agents).map_err(|error| match error {
            FleetRegistryError::WorkspaceConflict {
                registered_agent_id,
                ..
            } => FleetRegistryError::WorkspaceConflict {
                agent_id: agent_id.clone(),
                registered_agent_id,
            },
            other => other,
        })?;
    }
    Ok(())
}

fn validate_manifest_workspace(
    manifest: &AgentManifest,
    agents: &BTreeMap<AgentId, AgentRecord>,
) -> Result<(), FleetRegistryError> {
    for (registered_id, record) in agents {
        if registered_id == &manifest.agent_id {
            continue;
        }
        let candidate = manifest.workspace.as_path();
        let registered = record.manifest.workspace.as_path();
        if candidate.starts_with(registered) || registered.starts_with(candidate) {
            return Err(FleetRegistryError::WorkspaceConflict {
                agent_id: manifest.agent_id.clone(),
                registered_agent_id: registered_id.clone(),
            });
        }
    }
    Ok(())
}

fn parse_lifecycle_generation(name: &str) -> Result<u64, FleetRegistryError> {
    let value = name
        .strip_prefix(LIFECYCLE_FILE_PREFIX)
        .and_then(|value| value.strip_suffix(LIFECYCLE_FILE_SUFFIX))
        .filter(|value| value.len() == 20 && value.bytes().all(|byte| byte.is_ascii_digit()))
        .ok_or_else(|| {
            FleetRegistryError::Corrupt(format!("invalid lifecycle filename {name:?}"))
        })?;
    value
        .parse()
        .map_err(|_| FleetRegistryError::Corrupt(format!("invalid lifecycle generation {value}")))
}

fn lifecycle_path(run_root: &Path, generation: u64) -> PathBuf {
    run_root.join(format!(
        "{LIFECYCLE_FILE_PREFIX}{generation:020}{LIFECYCLE_FILE_SUFFIX}"
    ))
}

fn lifecycle_json(state: &AgentLifecycleState) -> Result<Vec<u8>, FleetRegistryError> {
    let mut json = serde_json::to_vec(state)
        .map_err(|error| FleetRegistryError::Corrupt(format!("encode lifecycle state: {error}")))?;
    json.push(b'\n');
    Ok(json)
}

fn staging_root(agents_root: &Path, agent_id: &AgentId) -> PathBuf {
    agents_root.join(format!(
        ".staging-{agent_id}-{}-{}",
        std::process::id(),
        STAGING_SEQUENCE.fetch_add(1, Ordering::Relaxed)
    ))
}

fn write_new_file(path: &Path, contents: &[u8]) -> Result<(), FleetRegistryError> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(contents)?;
    file.sync_all()?;
    Ok(())
}

fn read_regular_file(path: &Path) -> Result<String, FleetRegistryError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(FleetRegistryError::Corrupt(format!(
            "control path is not a regular file: {}",
            path.display()
        )));
    }
    std::fs::read_to_string(path).map_err(Into::into)
}

fn validate_physical_directory(path: &Path) -> Result<(), FleetRegistryError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(FleetRegistryError::Corrupt(format!(
            "control path is not a physical directory: {}",
            path.display()
        )));
    }
    Ok(())
}

fn migrate_private_directory(parent: &Path, name: &str) -> Result<(), FleetRegistryError> {
    let final_path = parent.join(name);
    match std::fs::symlink_metadata(&final_path) {
        Ok(metadata) => {
            if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
                return Err(FleetRegistryError::Corrupt(format!(
                    "private Matrix path is not a physical directory: {}",
                    final_path.display()
                )));
            }
            set_private_directory_permissions(&final_path)?;
            sync_directory(parent)?;
            return Ok(());
        }
        Err(error) if error.kind() == ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }

    match create_private_directory(&final_path) {
        Ok(()) => {}
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            validate_physical_directory(&final_path)?;
            set_private_directory_permissions(&final_path)?;
        }
        Err(error) => return Err(error.into()),
    }
    sync_directory(parent)
}

#[cfg(unix)]
fn create_private_directory(path: &Path) -> std::io::Result<()> {
    use std::os::unix::fs::DirBuilderExt;

    let mut builder = std::fs::DirBuilder::new();
    builder.mode(0o700).create(path)
}

#[cfg(not(unix))]
fn create_private_directory(path: &Path) -> std::io::Result<()> {
    std::fs::create_dir(path)
}

#[cfg(unix)]
fn set_private_directory_permissions(path: &Path) -> Result<(), FleetRegistryError> {
    use std::os::unix::fs::PermissionsExt;

    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    Ok(())
}

#[cfg(not(unix))]
fn set_private_directory_permissions(_path: &Path) -> Result<(), FleetRegistryError> {
    Ok(())
}

#[cfg(unix)]
fn validate_private_directory(path: &Path) -> Result<(), FleetRegistryError> {
    use std::os::unix::fs::PermissionsExt;

    let mode = std::fs::symlink_metadata(path)?.permissions().mode();
    if mode & 0o077 != 0 || mode & 0o700 != 0o700 {
        return Err(FleetRegistryError::Corrupt(format!(
            "private Matrix directory has unsafe permissions: {}",
            path.display()
        )));
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_private_directory(path: &Path) -> Result<(), FleetRegistryError> {
    validate_physical_directory(path)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), FleetRegistryError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), FleetRegistryError> {
    Ok(())
}

#[cfg(test)]
#[path = "registry_tests.rs"]
mod tests;
