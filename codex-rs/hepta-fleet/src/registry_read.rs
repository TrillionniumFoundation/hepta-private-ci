//! Workload reads do not perform the Supervisor's global migration or audit.
use super::*;

impl FleetRegistry {
    /// Open this Agent's existing control record without migrating or loading peers.
    /// The Supervisor retains global registration and workspace isolation checks;
    /// callers must bind this fresh record to their immutable launch identity.
    pub fn open_existing_for_agent(
        fleet_root: HeptaFleetRoot,
        agent_id: &AgentId,
    ) -> Result<Self, FleetRegistryError> {
        let registry = Self::existing_layout(fleet_root)?;
        registry.load_agent(agent_id)?;
        Ok(registry)
    }

    /// Read the public registration metadata for one exact Agent. This does not
    /// read its private runtime or lifecycle state and is not launch authority.
    pub fn load_agent_manifest(
        &self,
        agent_id: &AgentId,
    ) -> Result<AgentManifest, FleetRegistryError> {
        let layout = self.layout.agent(agent_id);
        validate_physical_directory(layout.agent_root())?;
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
        Ok(manifest)
    }

    /// Discover registered layout candidates from the public directory names.
    /// Private peer state is checked by the federation owner at the actual read
    /// boundary; this list grants no access and cannot authorize a launch.
    pub fn registered_agent_layouts(&self) -> Result<Vec<HeptaAgentLayout>, FleetRegistryError> {
        let mut layouts = BTreeMap::new();
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
            layouts.insert(agent_id.clone(), self.layout.agent(&agent_id));
        }
        Ok(layouts.into_values().collect())
    }
}
