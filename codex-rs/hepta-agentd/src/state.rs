include!("state_base.rs");

impl AgentdState {
    /// Roll back a canonical run that could not be committed to the already
    /// reserved runtime.codex queue. This is an in-process owner transition;
    /// it deliberately does not call Agentd's own UDS and therefore cannot be
    /// lost to control-socket saturation.
    pub(crate) fn cancel_run_internal(
        &self,
        run_id: &str,
        expected_revision: u64,
        reason: &str,
    ) -> Result<RunReceipt, AgentdError> {
        self.refresh_generation()?;
        let now_ms = unix_now_ms()?;
        let (_, receipt) = self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .cancel_run(now_ms, run_id, expected_revision, reason)
            .map_err(run_error)?;
        Ok(receipt)
    }

    /// Configuration and runtime availability are distinct. A canonical
    /// profile remains configured while its durable executor reconciles, but it
    /// is advertised and counted as ready only while the executor can admit a
    /// newly reserved schedule.
    pub(crate) fn canonical_intelligence_available(&self) -> bool {
        self.canonical_intelligence_enabled()
            && crate::ProcessRuntimeCodexExecutorV1::agentd_supervisor_status().admission_ready
    }
}
