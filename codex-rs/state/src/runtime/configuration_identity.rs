use super::SqliteConfig;
use super::StateRuntime;

impl StateRuntime {
    /// Match the exact configuration used to initialize this instance or its
    /// retained canonical configuration. This does not resolve new aliases or
    /// reopen the configured path: databases and dispatch locks remain bound
    /// to the canonical home captured during initialization.
    pub fn matches_sqlite_config(&self, requested: &SqliteConfig) -> bool {
        requested == &self.configured_sqlite || requested == &self.sqlite
    }
}
