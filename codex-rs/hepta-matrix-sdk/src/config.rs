use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_paths::HeptaAgentLayout;

pub const MIN_SYNC_TIMELINE_LIMIT: u16 = 1;
pub const MAX_SYNC_TIMELINE_LIMIT: u16 = 256;
pub const MIN_SYNC_TIMEOUT: Duration = Duration::from_secs(1);
pub const MAX_SYNC_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixSidecarConfig {
    pub binding: MatrixBindingV1,
    /// Stable authority generation for this per-Agent Matrix database.
    ///
    /// This is deliberately independent from the replaceable `agentd` spawn
    /// generation. A workspace Agent upgrade must not orphan a committed
    /// Matrix cursor, inbox admission, or stable outbox transaction.
    pub matrix_generation: u64,
    pub sync_timeline_limit: u16,
    pub sync_timeout: Duration,
}

impl MatrixSidecarConfig {
    pub fn validate(&self, layout: &HeptaAgentLayout) -> Result<(), MatrixSidecarConfigError> {
        self.binding
            .validate()
            .map_err(|_| MatrixSidecarConfigError::Invalid)?;
        if &self.binding.agent_id != layout.agent_id() {
            return Err(MatrixSidecarConfigError::WrongAgent);
        }
        if self.matrix_generation == 0
            || !(MIN_SYNC_TIMELINE_LIMIT..=MAX_SYNC_TIMELINE_LIMIT)
                .contains(&self.sync_timeline_limit)
            || !(MIN_SYNC_TIMEOUT..=MAX_SYNC_TIMEOUT).contains(&self.sync_timeout)
        {
            return Err(MatrixSidecarConfigError::Invalid);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixSdkPaths {
    root: PathBuf,
    state: PathBuf,
    cache: PathBuf,
    session: PathBuf,
}

impl MatrixSdkPaths {
    pub fn prepare(
        layout: &HeptaAgentLayout,
        config: &MatrixSidecarConfig,
    ) -> Result<Self, MatrixSidecarConfigError> {
        config.validate(layout)?;
        let root = layout.matrix_root().join("matrix-sdk-0.18");
        let state = root.join("state");
        let cache = root.join("cache");
        let session = root.join("session.json");
        create_private_directory(&root)?;
        create_private_directory(&state)?;
        create_private_directory(&cache)?;
        Ok(Self {
            root,
            state,
            cache,
            session,
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn state(&self) -> &Path {
        &self.state
    }

    pub fn cache(&self) -> &Path {
        &self.cache
    }

    /// The per-Agent authentication session, written with owner-only
    /// permissions and atomically replaced after a successful login.
    pub fn session(&self) -> &Path {
        &self.session
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MatrixSidecarConfigError {
    #[error("invalid Matrix sidecar configuration")]
    Invalid,
    #[error("Matrix binding belongs to a different workspace agent")]
    WrongAgent,
    #[error("Matrix sidecar path is unavailable")]
    Unavailable,
}

fn create_private_directory(path: &Path) -> Result<(), MatrixSidecarConfigError> {
    fs::create_dir_all(path).map_err(|_| MatrixSidecarConfigError::Unavailable)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        fs::set_permissions(path, fs::Permissions::from_mode(0o700))
            .map_err(|_| MatrixSidecarConfigError::Unavailable)?;
    }
    Ok(())
}
