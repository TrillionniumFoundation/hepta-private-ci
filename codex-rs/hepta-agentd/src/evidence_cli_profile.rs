//! Structural guard for the CLI's production-to-runtime hand-off.
//!
//! The current runtime selects its v2 descriptor path only for a direct child
//! of the registered Agent home. Never let explicit production mode reach its
//! legacy v1 branch. This check grants no trust: the runtime must still perform
//! owner-file, backend, signature, candidate, backup and snapshot admission.

use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

pub(crate) fn require_production_descriptor(
    home: &Path,
    descriptor: &Path,
) -> Result<(), &'static str> {
    if !home.is_absolute() || !descriptor.is_absolute() {
        return Err("production evidence descriptor and Agent home must be absolute");
    }
    if descriptor
        .components()
        .any(|part| matches!(part, Component::ParentDir | Component::CurDir))
        || descriptor.components().collect::<PathBuf>().as_os_str() != descriptor.as_os_str()
    {
        return Err("production evidence descriptor must be lexically canonical");
    }
    if descriptor.parent() != Some(home) || descriptor.file_name().is_none() {
        return Err(
            "production evidence descriptor must be a direct child of the registered Agent home; legacy recovery paths are forbidden",
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::require_production_descriptor;
    use std::path::Path;
    use std::path::PathBuf;

    fn home() -> PathBuf {
        if cfg!(windows) {
            PathBuf::from(r"C:\agent\home")
        } else {
            PathBuf::from("/agent/home")
        }
    }

    #[test]
    fn admits_only_the_structural_v2_route() {
        let home = home();
        assert!(
            require_production_descriptor(&home, &home.join("evidence-production.json")).is_ok()
        );
    }

    #[test]
    fn rejects_legacy_external_frontier_as_production_descriptor() {
        let home = home();
        let legacy = home.parent().unwrap().join("external/frontier.json");
        assert!(require_production_descriptor(&home, &legacy).is_err());
    }

    #[test]
    fn rejects_relative_descriptor() {
        assert!(
            require_production_descriptor(&home(), Path::new("evidence-production.json")).is_err()
        );
    }

    #[test]
    fn rejects_nested_descriptor_that_runtime_would_route_as_legacy() {
        let home = home();
        assert!(
            require_production_descriptor(&home, &home.join("nested/descriptor.json")).is_err()
        );
    }

    #[test]
    fn rejects_parent_alias() {
        let home = home();
        assert!(
            require_production_descriptor(&home, &home.join("../home/descriptor.json")).is_err()
        );
    }

    #[test]
    fn rejects_current_directory_alias() {
        let home = home();
        assert!(require_production_descriptor(&home, &home.join("./descriptor.json")).is_err());
    }

    #[test]
    fn rejects_home_itself() {
        let home = home();
        assert!(require_production_descriptor(&home, &home).is_err());
    }

    #[test]
    fn rejects_unregistered_relative_home() {
        assert!(
            require_production_descriptor(Path::new("home"), &home().join("descriptor.json"))
                .is_err()
        );
    }
}
