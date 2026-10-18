//! Install-time writes share the daemon's kernel ownership domain.

use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_paths::HeptaFleetRoot;

use crate::SupervisorError;
use crate::daemon::owner::SingleInstanceLock;

/// Perform administrator registration or release installation only while the
/// Supervisor is offline. The same owner-held lock inode serializes setup with
/// daemon startup; the closure cannot bypass a running lifecycle writer.
pub fn with_offline_fleet_registry<T>(
    fleet_root: HeptaFleetRoot,
    configure: impl FnOnce(&FleetRegistry) -> Result<T, FleetRegistryError>,
) -> Result<T, SupervisorError> {
    let _ownership = SingleInstanceLock::acquire(fleet_root.layout().supervisor_lock())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    registry.migrate_owner_journals()?;
    let registry = FleetRegistry::open_existing(fleet_root)?;
    Ok(configure(&registry)?)
}
