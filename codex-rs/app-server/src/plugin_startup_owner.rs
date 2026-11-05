//! App-server lifetime owner for its actual curated plugin startup thread.
//! This covers orderly shutdown and Rust drops, not SIGKILL or host crashes.

use codex_core_plugins::PluginsManager;
use std::sync::Arc;

pub(crate) struct PluginStartupOwner {
    manager: Arc<PluginsManager>,
}

impl PluginStartupOwner {
    pub(crate) fn new(manager: Arc<PluginsManager>) -> Self {
        Self { manager }
    }

    pub(crate) fn cancel(&self) {
        self.manager.cancel_curated_startup_sync();
    }

    pub(crate) fn shutdown(&self) {
        if let Err(error) = self.manager.shutdown_curated_startup_sync() {
            tracing::warn!("curated plugin startup owner could not complete shutdown: {error}");
        }
    }
}

impl Drop for PluginStartupOwner {
    fn drop(&mut self) {
        self.shutdown();
    }
}
