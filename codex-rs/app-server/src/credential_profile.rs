//! Startup-owned credential storage independent of runtime data isolation.

use std::io;
use std::sync::Arc;

use codex_core::config::Config;
use codex_login::AuthManager;
use codex_utils_absolute_path::AbsolutePathBuf;

pub(crate) async fn auth_manager_for_runtime(
    config: &Config,
    credential_profile_home: Option<&AbsolutePathBuf>,
) -> io::Result<Arc<AuthManager>> {
    let mut auth_config = config.clone();
    if let Some(home) = credential_profile_home {
        if !home.as_path().is_dir() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "credential profile home must be an existing directory",
            ));
        }
        // Only this auth-constructor view uses the profile. Thread state,
        // configuration, SQLite, plugins and rollout storage retain the
        // embedding runtime's original private home.
        auth_config.codex_home = home.clone();
    }
    AuthManager::shared_from_config(&auth_config, /*enable_codex_api_key_env*/ false)
        .await
        .map_err(io::Error::other)
}

#[cfg(test)]
#[path = "credential_profile_tests.rs"]
mod tests;
