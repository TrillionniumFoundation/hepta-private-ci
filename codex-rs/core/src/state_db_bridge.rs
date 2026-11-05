use codex_rollout::state_db as rollout_state_db;
pub use codex_rollout::state_db::StateDbHandle;

use crate::config::Config;

/// Bind the caller's configuration to the home retained by its initial state runtime.
pub async fn init_state_db(config: &mut Config) -> Option<StateDbHandle> {
    let state_db = rollout_state_db::init(&*config).await?;
    config.sqlite = state_db.sqlite().clone();
    Some(state_db)
}

#[cfg(all(test, unix))]
#[path = "state_db_bridge_tests.rs"]
mod tests;
