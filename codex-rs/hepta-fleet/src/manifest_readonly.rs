//! Bounded read of one immutable registration; never opens the registry writer.
use crate::AgentManifest;
use crate::FleetRegistryError;
use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use std::io::Read;

const MAX_MANIFEST_BYTES: u64 = 1_048_576;

impl AgentManifest {
    pub fn read_registered(
        fleet_root: &HeptaFleetRoot,
        agent_id: &AgentId,
    ) -> Result<Self, FleetRegistryError> {
        let layout = fleet_root.layout().agent(agent_id);
        let path = layout.agent_config();
        // Reject symlinks in both the final file and its parent chain. An
        // administrative replacement while reading must not switch identities.
        if path.canonicalize()?.as_path() != path {
            return Err(FleetRegistryError::Corrupt(
                "registered manifest path is not physical and canonical".to_string(),
            ));
        }
        let before = std::fs::symlink_metadata(path)?;
        if !before.is_file() || before.file_type().is_symlink() {
            return Err(FleetRegistryError::Corrupt(
                "registered manifest is not a regular file".to_string(),
            ));
        }
        let file = std::fs::File::open(path)?;
        let opened = file.metadata()?;
        let current = std::fs::symlink_metadata(path)?;
        if !opened.is_file() || !current.is_file() || current.file_type().is_symlink() {
            return Err(FleetRegistryError::Corrupt(
                "registered manifest changed while opening".to_string(),
            ));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if before.dev() != opened.dev()
                || before.ino() != opened.ino()
                || current.dev() != opened.dev()
                || current.ino() != opened.ino()
            {
                return Err(FleetRegistryError::Corrupt(
                    "registered manifest identity changed while opening".to_string(),
                ));
            }
        }
        if opened.len() == 0 || opened.len() > MAX_MANIFEST_BYTES {
            return Err(FleetRegistryError::Corrupt(
                "registered manifest exceeds its bounded size".to_string(),
            ));
        }
        let mut bytes = Vec::new();
        file.take(MAX_MANIFEST_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes.is_empty() || bytes.len() as u64 > MAX_MANIFEST_BYTES {
            return Err(FleetRegistryError::Corrupt(
                "registered manifest exceeds its bounded size".to_string(),
            ));
        }
        let text = std::str::from_utf8(&bytes)
            .map_err(|error| FleetRegistryError::Corrupt(error.to_string()))?;
        let manifest: Self =
            toml::from_str(text).map_err(|error| FleetRegistryError::Corrupt(error.to_string()))?;
        manifest.validate(fleet_root)?;
        if &manifest.agent_id != agent_id {
            return Err(FleetRegistryError::Corrupt(
                "registered manifest principal differs from its directory".to_string(),
            ));
        }
        Ok(manifest)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::FleetRegistry;
    use crate::ResourceBudget;
    use crate::WorkspaceBinding;

    #[test]
    fn direct_manifest_read_preserves_registry_and_ignores_unrelated_peers() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = HeptaFleetRoot::parse(directory.path().join("fleet")).expect("root");
        let registry = FleetRegistry::initialize(root.clone()).expect("registry");
        let workspace = directory.path().join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
        let manifest = AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace, &root).expect("binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        registry.register(manifest.clone()).expect("register");
        let config = root.layout().agent(&agent).agent_config().to_path_buf();
        let bytes = std::fs::read(&config).expect("bytes");
        let modified = std::fs::metadata(&config)
            .expect("metadata")
            .modified()
            .expect("mtime");
        // A single-Agent read neither scans this peer nor cleans staging roots.
        let staging = root.layout().agents_root().join(".staging-unrelated");
        std::fs::create_dir(&staging).expect("staging");
        assert_eq!(
            AgentManifest::read_registered(&root, &agent).expect("read"),
            manifest
        );
        assert!(staging.exists());
        assert_eq!(std::fs::read(&config).expect("after"), bytes);
        assert_eq!(
            std::fs::metadata(config)
                .expect("after")
                .modified()
                .expect("mtime"),
            modified
        );
    }

    #[test]
    fn missing_manifest_does_not_create_a_registry() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = HeptaFleetRoot::parse(directory.path().join("missing")).expect("root");
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
        assert!(AgentManifest::read_registered(&root, &agent).is_err());
        assert!(!root.as_path().exists());
    }
}
