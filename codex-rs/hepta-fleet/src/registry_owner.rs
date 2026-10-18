//! Preserve predecessor control evidence while separating workload writes.

use super::*;

impl FleetRegistry {
    /// Migrate under the existing Supervisor kernel lock, before owner recovery.
    /// This is install/owner administration; an Agent must never call it. Each
    /// move is atomic and restartable, and no workload data is removed.
    pub fn migrate_owner_journals(&self) -> Result<(), FleetRegistryError> {
        create_owner_socket_directory(&self.layout)?;
        for entry in std::fs::read_dir(self.layout.agents_root())? {
            let entry = entry?;
            let name = entry.file_name();
            let name = name
                .to_str()
                .ok_or_else(|| FleetRegistryError::Corrupt("non-UTF-8 Agent directory".into()))?;
            if name.starts_with(".staging-") {
                continue;
            }
            let agent = AgentId::parse(name)
                .map_err(|error| FleetRegistryError::Corrupt(error.to_string()))?;
            let layout = self.layout.agent(&agent);
            validate_physical_directory(layout.agent_root())?;
            match create_private_directory(layout.owner_run_root()) {
                Ok(()) => sync_directory(layout.agent_root())?,
                Err(error) if error.kind() == ErrorKind::AlreadyExists => {
                    validate_physical_directory(layout.owner_run_root())?
                }
                Err(error) => return Err(error.into()),
            }
            for file in std::fs::read_dir(layout.run_root())? {
                let file = file?;
                let name = file.file_name();
                let Some(name_text) = name.to_str() else {
                    continue;
                };
                if !name_text.starts_with("supervisor-")
                    && !(name_text.starts_with("lifecycle-") && name_text.ends_with(".json"))
                {
                    continue;
                }
                let source = file.path();
                let metadata = std::fs::symlink_metadata(&source)?;
                if metadata.file_type().is_symlink()
                    || !(metadata.is_file()
                        || name_text == "supervisor-emergency-control" && metadata.is_dir())
                {
                    return Err(FleetRegistryError::Corrupt(
                        "legacy owner evidence must be physical".into(),
                    ));
                }
                let destination = layout.owner_run_root().join(name);
                match std::fs::symlink_metadata(&destination) {
                    Ok(_) => {
                        return Err(FleetRegistryError::Corrupt(
                            "conflicting legacy and current owner evidence".into(),
                        ));
                    }
                    Err(error) if error.kind() == ErrorKind::NotFound => {}
                    Err(error) => return Err(error.into()),
                }
                std::fs::rename(&source, &destination)?;
                sync_directory(layout.owner_run_root())?;
                sync_directory(layout.run_root())?;
            }
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "registry_owner_tests.rs"]
mod tests;
