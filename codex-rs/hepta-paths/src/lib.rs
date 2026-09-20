//! Typed paths for the Hepta live runtime.
//!
//! This crate owns path geometry only. It does not create state, migrate a
//! schema, or grant a caller permission to mutate an existing state root.

#![forbid(unsafe_code)]

mod fleet;

pub use fleet::HEPTA_FLEET_ROOT_ENV;
pub use fleet::HeptaAgentLayout;
pub use fleet::HeptaFleetLayout;
pub use fleet::HeptaFleetRoot;

use std::env;
use std::fmt;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;

pub const HEPTA_STATE_ROOT_ENV: &str = "HEPTA_STATE_ROOT";
pub const RUNTIME_DIRECTORY_NAME: &str = "runtime-v2";
pub const OUTCOMES_DATABASE_NAME: &str = "outcomes.sqlite3";
pub const PREFERENCES_DATABASE_NAME: &str = "preferences.sqlite3";
pub const RUNTIME_STATE_NAME: &str = "runtime-state.json";
pub const RUNTIME_INTEGRITY_KEY_NAME: &str = "runtime-integrity.key";
pub const PREFERENCE_INTEGRITY_KEY_NAME: &str = "preference-integrity.key";
pub const PREFERENCE_INGRESS_KEY_NAME: &str = "preference-ingress-auth.key";

/// A normalized, host-native absolute, non-root path for one Hepta state domain.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct HeptaStateRoot(PathBuf);

impl HeptaStateRoot {
    pub fn parse(path: impl Into<PathBuf>) -> Result<Self> {
        let path = path.into();
        validate_absolute_non_root(&path)
            .with_context(|| format!("validate {HEPTA_STATE_ROOT_ENV}"))?;
        Ok(Self(path))
    }

    pub fn from_env() -> Result<Self> {
        if let Some(path) = env::var_os(HEPTA_STATE_ROOT_ENV) {
            return Self::parse(path);
        }
        let home =
            env::var_os("HOME").context("HOME is required when HEPTA_STATE_ROOT is unset")?;
        Self::production_default(Path::new(&home))
    }

    pub fn production_default(home: &Path) -> Result<Self> {
        validate_absolute_non_root(home).context("validate home directory")?;
        Self::parse(home.join(".local/share/hepta-vnext/live-snapshot"))
    }

    pub fn as_path(&self) -> &Path {
        &self.0
    }

    pub fn layout(&self) -> HeptaStateLayout {
        HeptaStateLayout::new(self.clone())
    }
}

impl AsRef<Path> for HeptaStateRoot {
    fn as_ref(&self) -> &Path {
        self.as_path()
    }
}

impl fmt::Display for HeptaStateRoot {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.display().fmt(formatter)
    }
}

/// Exact paths used by the compatibility open-existing runtime seam.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HeptaStateLayout {
    state_root: HeptaStateRoot,
    runtime_root: PathBuf,
    keys_root: PathBuf,
}

impl HeptaStateLayout {
    pub fn new(state_root: HeptaStateRoot) -> Self {
        let runtime_root = state_root.as_path().join(RUNTIME_DIRECTORY_NAME);
        let keys_root = runtime_root.join("keys");
        Self {
            state_root,
            runtime_root,
            keys_root,
        }
    }

    pub fn state_root(&self) -> &HeptaStateRoot {
        &self.state_root
    }

    pub fn runtime_root(&self) -> &Path {
        &self.runtime_root
    }

    pub fn outcomes_database(&self) -> PathBuf {
        self.runtime_root.join(OUTCOMES_DATABASE_NAME)
    }

    pub fn preferences_database(&self) -> PathBuf {
        self.runtime_root.join(PREFERENCES_DATABASE_NAME)
    }

    pub fn runtime_state(&self) -> PathBuf {
        self.runtime_root.join(RUNTIME_STATE_NAME)
    }

    pub fn runtime_integrity_key(&self) -> PathBuf {
        self.keys_root.join(RUNTIME_INTEGRITY_KEY_NAME)
    }

    pub fn preference_integrity_key(&self) -> PathBuf {
        self.keys_root.join(PREFERENCE_INTEGRITY_KEY_NAME)
    }

    pub fn preference_ingress_key(&self) -> PathBuf {
        self.keys_root.join(PREFERENCE_INGRESS_KEY_NAME)
    }
}

fn validate_absolute_non_root(path: &Path) -> Result<()> {
    // A foreign absolute spelling may still be relative on this host. Runtime
    // callers use this PathBuf directly, so portable syntax is not sufficient.
    if !path.is_absolute()
        || !path
            .components()
            .any(|component| matches!(component, Component::Normal(_)))
    {
        anyhow::bail!("path must be absolute and must not be filesystem root");
    }
    let raw_path = path.as_os_str().to_string_lossy();
    if raw_path
        .split(['/', '\\'])
        .any(|component| matches!(component, "." | ".."))
        || path
            .components()
            .any(|component| matches!(component, Component::CurDir | Component::ParentDir))
    {
        anyhow::bail!("path must not contain current-directory or parent-directory components");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(unix)]
    #[test]
    fn production_default_uses_separate_vnext_snapshot_root() -> Result<()> {
        let root = HeptaStateRoot::production_default(Path::new("/Users/operator"))?;
        let layout = root.layout();
        assert_eq!(
            root.as_path(),
            Path::new("/Users/operator/.local/share/hepta-vnext/live-snapshot")
        );
        assert_eq!(
            layout.outcomes_database(),
            Path::new(
                "/Users/operator/.local/share/hepta-vnext/live-snapshot/runtime-v2/outcomes.sqlite3"
            )
        );
        assert_eq!(
            layout.preferences_database(),
            Path::new(
                "/Users/operator/.local/share/hepta-vnext/live-snapshot/runtime-v2/preferences.sqlite3"
            )
        );
        assert_eq!(
            layout.runtime_state(),
            Path::new(
                "/Users/operator/.local/share/hepta-vnext/live-snapshot/runtime-v2/runtime-state.json"
            )
        );
        Ok(())
    }

    #[cfg(windows)]
    #[test]
    fn production_layout_accepts_a_windows_absolute_home() -> Result<()> {
        let root = HeptaStateRoot::production_default(Path::new(r"C:\Users\operator"))?;
        assert_eq!(
            root.as_path(),
            Path::new(r"C:\Users\operator\.local\share\hepta-vnext\live-snapshot")
        );
        assert_eq!(
            root.layout().outcomes_database(),
            Path::new(
                r"C:\Users\operator\.local\share\hepta-vnext\live-snapshot\runtime-v2\outcomes.sqlite3"
            )
        );
        Ok(())
    }

    #[test]
    fn state_root_rejects_relative_root_and_parent_traversal() {
        assert!(HeptaStateRoot::parse("relative").is_err());
        #[cfg(unix)]
        {
            assert!(HeptaStateRoot::parse("/").is_err());
            assert!(HeptaStateRoot::parse("/tmp/../escape").is_err());
            assert!(HeptaStateRoot::parse("/tmp/./escape").is_err());
        }
        #[cfg(windows)]
        {
            assert!(HeptaStateRoot::parse(r"C:\").is_err());
            assert!(HeptaStateRoot::parse(r"C:\tmp\..\escape").is_err());
            assert!(HeptaStateRoot::parse(r"C:\tmp\.\escape").is_err());
        }
    }
}

#[cfg(test)]
#[path = "native_root_tests.rs"]
mod native_root_tests;
