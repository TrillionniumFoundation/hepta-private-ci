//! Read original control data without migration or writer admission.

use super::FleetRegistry;
use super::FleetSnapshot;
use super::validate_physical_directory;
use crate::FleetRegistryError;
use codex_hepta_paths::HeptaFleetRoot;

impl FleetRegistry {
    /// Read the same complete registry snapshot as `load`, using only the
    /// already provisioned original paths. This does not migrate legacy data,
    /// create a directory, change permissions, or return a writable registry.
    /// Missing or unsafe original geometry remains an error.
    ///
    /// The caller must already have the original filesystem read permissions.
    /// This data is not a writer grant, peer admission, or retained owner.
    pub fn read_existing_snapshot(
        fleet_root: HeptaFleetRoot,
    ) -> Result<FleetSnapshot, FleetRegistryError> {
        let registry: FleetRegistry = Self {
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
        registry.load()
    }
}

#[cfg(test)]
#[path = "registry_readonly_tests.rs"]
mod tests;
