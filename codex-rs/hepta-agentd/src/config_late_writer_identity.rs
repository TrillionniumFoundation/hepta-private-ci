//! Read-only comparison data for the explicit late-writer CLI entry.
//! This does not open a writer, create Config, rotate a lease or admit a peer.
//! The original sealed handoff and Config loader independently recheck all data.

use super::*;

#[derive(Clone)]
struct OriginalStartingIdentityInput {
    fleet_root: PathBuf,
    agent_id: AgentId,
    spawn_generation: u64,
    home_root: PathBuf,
    run_root: PathBuf,
    codex_home: PathBuf,
    current_dir: PathBuf,
}

pub(crate) fn read_original_late_writer_starting_identity()
-> Result<(AgentdIdentity, CognitiveRetrievalMode), AgentdError> {
    let mode = cognitive_retrieval_mode_from_process_environment()?;
    let input = OriginalStartingIdentityInput {
        fleet_root: required_path(codex_hepta_paths::HEPTA_FLEET_ROOT_ENV)?,
        agent_id: AgentId::parse(required_utf8(HEPTA_AGENT_ID_ENV)?)
            .map_err(|error| AgentdError::Invalid(error.to_string()))?,
        spawn_generation: required_utf8(HEPTA_AGENT_GENERATION_ENV)?
            .parse::<u64>()
            .map_err(|_| {
                AgentdError::Invalid(format!(
                    "{HEPTA_AGENT_GENERATION_ENV} must be an unsigned integer"
                ))
            })?,
        home_root: required_path(HEPTA_AGENT_HOME_ENV)?,
        run_root: required_path(HEPTA_AGENT_RUN_ROOT_ENV)?,
        codex_home: required_path("CODEX_HOME")?,
        current_dir: std::env::current_dir()?,
    };
    Ok((input.read_expected_starting_identity()?, mode))
}

impl OriginalStartingIdentityInput {
    fn read_expected_starting_identity(&self) -> Result<AgentdIdentity, AgentdError> {
        if self.spawn_generation == 0 {
            return Err(AgentdError::Invalid(
                "spawn generation must be non-zero".into(),
            ));
        }
        let typed_root = HeptaFleetRoot::parse(self.fleet_root.clone())
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        require_canonical(&self.fleet_root, "fleet root")?;
        let snapshot = FleetRegistry::read_existing_snapshot(typed_root)?;
        let record = snapshot.agent(&self.agent_id).cloned().ok_or_else(|| {
            AgentdError::Invalid(format!("unknown fleet agent {}", self.agent_id))
        })?;
        if record.lifecycle.lifecycle != AgentLifecycle::Starting
            || record.lifecycle.generation != self.spawn_generation
        {
            return Err(AgentdError::GenerationFenced(format!(
                "agent {} expected Starting generation {}, found {:?} generation {}",
                self.agent_id,
                self.spawn_generation,
                record.lifecycle.lifecycle,
                record.lifecycle.generation
            )));
        }
        require_exact_path(&self.home_root, record.layout.home_root(), "agent home")?;
        require_exact_path(&self.run_root, record.layout.run_root(), "agent run root")?;
        require_exact_path(&self.codex_home, record.layout.home_root(), "Codex home")?;
        let workspace = self.current_dir.canonicalize()?;
        if workspace != record.manifest.workspace.as_path() {
            return Err(AgentdError::Invalid(format!(
                "process workspace {} does not match manifest {}",
                workspace.display(),
                record.manifest.workspace.as_path().display()
            )));
        }
        let layout = record.layout;
        let control_socket = layout.agentd_control_socket().to_path_buf();
        let app_server_socket = layout.app_server_socket().to_path_buf();
        Ok(AgentdIdentity {
            agent_id: self.agent_id.clone(),
            layout,
            spawn_generation: self.spawn_generation,
            fleet_root: self.fleet_root.clone(),
            workspace,
            resources: record.manifest.resources,
            home_root: self.home_root.clone(),
            run_root: self.run_root.clone(),
            control_socket,
            app_server_socket,
        })
    }
}

#[cfg(test)]
#[path = "config_late_writer_identity_tests.rs"]
mod tests;
