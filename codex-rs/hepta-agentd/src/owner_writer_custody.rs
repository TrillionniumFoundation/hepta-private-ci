//! Keep the one original Registry file alive with original production handles.
//! This retains no identity, Registry, clock, grant or alternate authority.

use super::AgentdConfig;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityVerifier;
use std::fs::File;
use std::sync::Arc;

struct RegisteredWriterVerifier {
    // Original verifier/Root resources retire before this final File reference.
    inner: Arc<dyn ProductionAuthorityVerifier>,
    _writer_lock: Arc<File>,
}

impl ProductionAuthorityVerifier for RegisteredWriterVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        self.inner.verify(authority, expected_agent)
    }

    fn verify_sender_process_binding(
        &self,
        authority: &ProductionAuthorityLease,
        expected_agent: &AgentId,
        local_lease_id: &str,
        local_generation: u64,
        spawn_generation: u64,
    ) -> Result<(), String> {
        self.inner.verify_sender_process_binding(
            authority,
            expected_agent,
            local_lease_id,
            local_generation,
            spawn_generation,
        )
    }
}

impl AgentdConfig {
    pub(crate) fn retain_production_verifier(
        &self,
        inner: Arc<dyn ProductionAuthorityVerifier>,
    ) -> Arc<dyn ProductionAuthorityVerifier> {
        Arc::new(RegisteredWriterVerifier {
            inner,
            _writer_lock: Arc::clone(&self._writer_lock),
        })
    }
}
