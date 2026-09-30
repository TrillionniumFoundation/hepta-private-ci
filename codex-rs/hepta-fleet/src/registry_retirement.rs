//! Retirement preserves an Agent's complete private history and identity.

use super::*;

const RETIRED_AGENTS_DIRECTORY: &str = "retired-agents";

impl FleetRegistry {
    /// Atomically archive a terminal Agent under the existing control owner.
    /// The Supervisor must first prove absence of owned/leased processes and
    /// unresolved mutations. This API never signals a child or erases data.
    pub fn retire_agent(
        &self,
        agent_id: &AgentId,
        expected_generation: u64,
    ) -> Result<PathBuf, FleetRegistryError> {
        let record = self.load_agent(agent_id)?;
        if record.lifecycle.generation != expected_generation {
            return Err(FleetRegistryError::StaleGeneration {
                agent_id: agent_id.clone(),
                expected: expected_generation,
                current: record.lifecycle.generation,
            });
        }
        if !matches!(
            record.lifecycle.lifecycle,
            AgentLifecycle::Stopped | AgentLifecycle::Failed
        ) {
            return Err(FleetRegistryError::Invalid(
                "retirement requires a terminal lifecycle".to_string(),
            ));
        }
        let archives = self.layout.state_root().join(RETIRED_AGENTS_DIRECTORY);
        match create_private_directory(&archives) {
            Ok(()) => sync_directory(self.layout.state_root())?,
            Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                validate_physical_directory(&archives)?;
                validate_private_directory(&archives)?;
            }
            Err(error) => return Err(error.into()),
        }
        let archived = archives.join(agent_id.as_str());
        match std::fs::symlink_metadata(&archived) {
            Ok(_) => return Err(FleetRegistryError::AlreadyRegistered(agent_id.clone())),
            Err(error) if error.kind() == ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        // A root-managed live Agent has group-read access for its workload.
        // Terminal history returns to private custody before publication. Sync
        // even if a previous attempt changed the mode but failed its barrier.
        set_private_directory_permissions(record.layout.agent_root())?;
        sync_directory(record.layout.agent_root())?;
        std::fs::rename(record.layout.agent_root(), &archived)?;
        sync_directory(&archives)?;
        sync_directory(self.layout.agents_root())?;
        Ok(archived)
    }

    /// Read the durable retirement location, including after a lost response.
    /// Archived workspace paths need not still exist; they are historical data,
    /// not a new workspace or execution admission.
    pub fn retired_agent_path(
        &self,
        agent_id: &AgentId,
    ) -> Result<Option<PathBuf>, FleetRegistryError> {
        let archives = self.layout.state_root().join(RETIRED_AGENTS_DIRECTORY);
        match std::fs::symlink_metadata(&archives) {
            Ok(_) => {
                validate_physical_directory(&archives)?;
                validate_private_directory(&archives)?;
            }
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        }
        let archived = archives.join(agent_id.as_str());
        match std::fs::symlink_metadata(&archived) {
            Ok(_) => {
                validate_physical_directory(&archived)?;
                validate_private_directory(&archived)?;
            }
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        }
        let manifest: AgentManifest =
            toml::from_str(&read_regular_file(&archived.join("agent.toml"))?).map_err(|error| {
                FleetRegistryError::Corrupt(format!("invalid archived manifest: {error}"))
            })?;
        if manifest.agent_id != *agent_id
            || manifest.schema_version != crate::AGENT_MANIFEST_SCHEMA_VERSION
        {
            return Err(FleetRegistryError::Corrupt(
                "archived Agent identity mismatch".to_string(),
            ));
        }
        Ok(Some(archived))
    }
}
