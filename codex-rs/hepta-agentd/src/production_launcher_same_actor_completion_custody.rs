//! Actual outer-owner custody at construction and final cleanup.
//! These methods use the one precreated registry; no status or callback
//! can replace its concrete original handles or joined observations.

use super::*;

impl OriginalPhaseRunControl {
    /// The empty custody existed before the actual Startup future. Only the
    /// same received context may hand it to the one configured initializer.
    pub(in crate::production_launcher) fn original_mcp_custody(
        &self, context: &Arc<OriginalSameActorRootContext>,
    ) -> Result<Arc<codex_app_server::OriginalMcpRuntimeShutdown>, AgentdError> {
        let state = self.state.lock()
            .map_err(|_| refused("original Startup custody is poisoned"))?;
        if self.stopped.load(Ordering::Acquire)
            || !state.context.as_ref().and_then(Weak::upgrade)
                .is_some_and(|original| Arc::ptr_eq(&original, context))
            || !state.gate.as_ref().is_some_and(|gate| Arc::ptr_eq(gate, context.gate()))
        {
            SameActorPhaseGate::close(context.gate());
            return Err(refused("original MCP custody differs from the actual phase"));
        }
        context.gate().require_open()?;
        Ok(Arc::clone(&self.mcp))
    }

    pub(in crate::production_launcher) fn original_app_server_custody(
        &self, context: &Arc<OriginalSameActorRootContext>,
    ) -> Result<Arc<codex_app_server::OriginalAppServerOwnerCustody>, AgentdError> {
        let state = self.state.lock()
            .map_err(|_| refused("original Startup custody is poisoned"))?;
        if self.stopped.load(Ordering::Acquire)
            || !state.context.as_ref().and_then(Weak::upgrade)
                .is_some_and(|original| Arc::ptr_eq(&original, context))
            || !state.gate.as_ref().is_some_and(|gate| Arc::ptr_eq(gate, context.gate()))
        {
            SameActorPhaseGate::close(context.gate());
            return Err(refused("original App Server custody differs from the actual phase"));
        }
        context.gate().require_open()?;
        Ok(Arc::clone(&self.app_server))
    }

    pub(in super::super) fn original_circuit_custody(
        &self, context: &Arc<OriginalSameActorRootContext>,
    ) -> Result<Arc<OriginalCircuitOwnerCustody>, AgentdError> {
        let state = self.state.lock()
            .map_err(|_| refused("original Startup custody is poisoned"))?;
        if self.stopped.load(Ordering::Acquire)
            || !state.context.as_ref().and_then(Weak::upgrade)
                .is_some_and(|original| Arc::ptr_eq(&original, context))
        {
            SameActorPhaseGate::close(context.gate());
            return Err(refused("original Circuit custody differs from the actual phase"));
        }
        let custody = state.circuit.as_ref()
            .ok_or_else(|| refused("actual Circuit custody was not installed"))?;
        OriginalCircuitOwnerCustody::require_original_origin(
            custody, context.identity(), context.gate(),
        )?;
        Ok(Arc::clone(custody))
    }

    /// Cleanup-only cut after the same real Root pidfd has exited. The
    /// original Circuit job already joined naturally; remove this outer
    /// registry's remaining custody share without re-entering Current.
    pub(in super::super) fn release_original_circuit_after_root_exit(
        &self,
        circuit: &Arc<OriginalCircuitOwnerCustody>,
        exited: &crate::same_actor_q24_deployment::OriginalRootProcessExited,
        identity: &crate::AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        exited.require_original_cleanup_origin(identity, gate)?;
        let mut state = self.state.lock()
            .map_err(|_| refused("original Startup custody is poisoned"))?;
        if self.stopped.load(Ordering::Acquire)
            || state.identity.as_ref() != Some(identity)
            || !state.gate.as_ref().is_some_and(|original| Arc::ptr_eq(original, gate))
            || !state.circuit.as_ref().is_some_and(|original| Arc::ptr_eq(original, circuit))
        {
            return Err(refused("actual Circuit cleanup custody differs"));
        }
        let original = state.circuit.take();
        state.context.take();
        drop(state);
        drop(original);
        Ok(())
    }

    /// These exact registries existed before the public waiting future.
    /// Observe every owned handle even if another component reports failure.
    pub(in super::super) async fn finish_original_component_owners_after_root_exit(
        &self,
        exited: &crate::same_actor_q24_deployment::OriginalRootProcessExited,
        identity: &crate::AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(
        Arc<codex_app_server::OriginalMcpRuntimeShutdownObservation>,
        codex_app_server::OriginalAppServerJoined,
    ), AgentdError> {
        exited.require_original_cleanup_origin(identity, gate)?;
        let mut failure = None;
        if let Err(error) = self.consumers.join_and_release().await {
            save_original_failure(&mut failure, error);
        }
        let app_server = match self.app_server.join_original_app_server().await {
            Ok(joined) => match codex_app_server::OriginalAppServerJoined::require_original_custody(&joined, &self.app_server) {
                Ok(()) => Some(joined),
                Err(error) => {
                    save_original_failure(&mut failure, AgentdError::Protocol(
                        format!("original App Server cleanup custody: {error}"),
                    ));
                    None
                }
            },
            Err(error) => {
                save_original_failure(&mut failure, AgentdError::Protocol(
                    format!("original App Server final cleanup: {error}"),
                ));
                None
            }
        };
        let mcp = match self.mcp.stop_and_join_original_runtime().await {
            Ok(joined) => match codex_app_server::OriginalMcpRuntimeShutdownObservation::require_original_ready_runtime_joined(&joined) {
                Ok(()) => Some(joined),
                Err(error) => {
                    save_original_failure(&mut failure, AgentdError::Protocol(
                        format!("original MCP final cleanup custody: {error}"),
                    ));
                    None
                }
            },
            Err(error) => {
                save_original_failure(&mut failure, AgentdError::Protocol(
                    format!("original MCP final cleanup: {error}"),
                ));
                None
            }
        };
        if let Some(error) = failure { return Err(error); }
        exited.require_original_cleanup_origin(identity, gate)?;
        Ok((
            mcp.ok_or_else(|| refused("actual MCP cleanup observation is missing"))?,
            app_server.ok_or_else(|| refused("actual App Server cleanup observation is missing"))?,
        ))
    }

    pub(in super::super) fn require_original_completed_owners(
        &self,
        identity: &crate::AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
        mcp: &codex_app_server::OriginalMcpRuntimeShutdownObservation,
        app_server: &codex_app_server::OriginalAppServerJoined,
    ) -> Result<(), AgentdError> {
        let state = self.state.lock()
            .map_err(|_| refused("original Startup custody is poisoned"))?;
        if self.stopped.load(Ordering::Acquire)
            || self.cancellation.is_cancelled()
            || state.identity.as_ref() != Some(identity)
            || !state.gate.as_ref().is_some_and(|original| Arc::ptr_eq(original, gate))
            || state.context.is_some()
            || state.circuit.is_some()
        {
            return Err(refused("actual original final owner custody differs or was cancelled"));
        }
        mcp.require_original_ready_runtime_joined().map_err(|error| {
            AgentdError::Protocol(format!("original final MCP owners: {error}"))
        })?;
        app_server.require_original_custody(&self.app_server).map_err(|error| {
            AgentdError::Protocol(format!("original final App Server owners: {error}"))
        })
    }

}
