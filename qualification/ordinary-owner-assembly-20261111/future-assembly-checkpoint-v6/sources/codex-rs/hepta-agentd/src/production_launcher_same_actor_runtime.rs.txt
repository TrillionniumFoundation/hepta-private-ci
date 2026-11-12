//! Exact original Android launch with an explicit phase shutdown owner.
//! The legacy Launch.run body is unchanged. Successful Runtime return only
//! creates custody of the actual still-live attachment; it is not a join or
//! a business-completion certificate.

use super::*;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_phase_gate::{CloseSameActorPhaseOnDrop, SameActorPhaseGate};

/// No public constructor, Clone or wire representation. Only the actual
/// run_with_shutdown Ok branch below constructs this owner. Keeping this
/// value retains the original Session/checkpoint/grants and Primary runtime.
pub(crate) struct OriginalSameActorRuntimeStopped {
    context: Arc<OriginalSameActorRootContext>,
    root_pidfd: OwnedFd,
    attachment: Option<crate::AgentdRootProductionAttachment>,
    device: Option<Arc<crate::AgentdAndroidTextDevice>>,
    mcp: Option<codex_app_server::ConfiguredMcpRuntime>,
    app_server: Arc<codex_app_server::OriginalAppServerOwnerCustody>,
    app_server_joined: codex_app_server::OriginalAppServerJoined,
    closing: CloseSameActorPhaseOnDrop,
}

/// The actual Runtime attachment remains owned after its four original
/// Root purposes were closed with the real seq1 permission. No File, Session,
/// device or MCP owner is dropped until the later full completion cleanup.
pub(crate) struct OriginalRuntimeRootPurposesRetired {
    stopped: OriginalSameActorRuntimeStopped,
}

impl OriginalRuntimeRootPurposesRetired {
    /// Capture the actual stopped owner before the first poll. Only the
    /// kernel Root-exit observation authorizes this terminal resource drop;
    /// the unchanged explicit MCP shutdown is actually awaited.
    pub(crate) fn release_original_after_root_exit(
        self,
        exited: &crate::same_actor_q24_deployment::OriginalRootProcessExited,
    ) -> impl std::future::Future<Output = Result<(), AgentdError>> + 'static {
        let checked = exited.require_original_cleanup_origin(
            self.stopped.context.identity(), self.stopped.context.gate(),
        );
        async move {
            let retained = self;
            // Even a failed cleanup provenance check still drives the
            // original fault shutdown; it cannot silently discard MCP work.
            let cleanup = retained.stopped.close_original_runtime_resources().await;
            match (checked, cleanup) {
                (Err(original), Err(cleanup)) => {
                    tracing::error!(error = %cleanup, "original Runtime cleanup also failed");
                    Err(original)
                }
                (Err(error), Ok(())) | (Ok(()), Err(error)) => Err(error),
                (Ok(()), Ok(())) => Ok(()),
            }
        }
    }

    pub(crate) fn require_original_origin(
        &self, identity: &AgentdIdentity, gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        self.stopped.require_original_origin(identity, gate)
    }
}

impl OriginalSameActorRuntimeStopped {
    pub(crate) fn require_original_origin(
        &self, identity: &AgentdIdentity, gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        if self.context.identity() != identity || !Arc::ptr_eq(self.context.gate(), gate)
            || self.attachment.is_none() || self.device.is_none() || self.mcp.is_none()
        {
            self.context.gate().close();
            return Err(runtime_refused("actual stopped Runtime custody differs"));
        }
        self.app_server_joined.require_original_custody(&self.app_server)
            .map_err(|error| AgentdError::Protocol(format!("original App Server join: {error}")))?;
        self.context.gate().require_open()?;
        crate::root_observation_stream::check_lifetime(&self.root_pidfd)
            .map_err(|error| AgentdError::Protocol(format!("original stopped Root lifetime: {error}")))
    }

    pub(crate) fn retire_original_root_purposes(
        self,
        intent: &crate::same_actor_q24_deployment::OriginalRootRetirementIntent,
    ) -> Result<OriginalRuntimeRootPurposesRetired, AgentdError> {
        self.require_original_origin(self.context.identity(), self.context.gate())?;
        intent.require_original_origin(self.context.identity(), self.context.gate())?;
        self.context.retire_original_runtime_purposes(intent)?;
        self.require_original_origin(self.context.identity(), self.context.gate())?;
        intent.require_original_origin(self.context.identity(), self.context.gate())?;
        Ok(OriginalRuntimeRootPurposesRetired { stopped: self })
    }

    /// Fault cleanup only. No Root retirement permission or natural Session
    /// completion is inferred from this operation.
    pub(super) async fn close_original_runtime_resources(mut self) -> Result<(), AgentdError> {
        self.context.gate().close();
        drop(self.attachment.take());
        if let Some(device) = self.device.take() { device.invalidate(); }
        let mcp = self.mcp.take()
            .ok_or_else(|| runtime_refused("actual Runtime MCP owner is missing"))?;
        codex_app_server::ConfiguredMcpRuntime::shutdown_original_owned(mcp).await.map_err(|error| {
            AgentdError::Protocol(format!("original Runtime MCP cleanup: {error}"))
        })?;
        // Keep the shared close responsibility armed, including cancellation.
        let _ = &self.closing;
        Ok(())
    }
}

impl Drop for OriginalSameActorRuntimeStopped {
    fn drop(&mut self) {
        self.context.gate().close();
        if let Some(device) = &self.device { device.invalidate(); }
        // Synchronous Drop requests failure and retains no false join claim.
        // The actual outer owner normally drives the explicit async cleanup.
    }
}

impl AgentdProductionLaunch {
    pub(super) async fn run_original_same_actor_with_shutdown(
        self,
        mut config: AgentdConfig,
        arg0_paths: Arg0DispatchPaths,
        context: Arc<OriginalSameActorRootContext>,
        stop: Arc<same_actor_phase::owner::OriginalPhaseRunControl>,
    ) -> Result<OriginalSameActorRuntimeStopped, AgentdError> {
        let mut closing = CloseSameActorPhaseOnDrop::new(context.gate());
        let identity = context.identity().clone();
        let gate = Arc::clone(context.gate());
        OriginalSameActorRootContext::require_current(&context)?;
        let root_pidfd = context.root_pidfd()?;
        config.require_root_learning_assembled()?;
        if config.identity() != context.identity() || self.initial_publication.is_some()
            || self.publication.is_some() || self.q24_model.is_some()
        {
            return Err(runtime_refused(
                "actual phase Runtime has unresolved original handoffs or identity",
            ));
        }
        let RuntimeInputs { primary, notes, notes_ui } = self.inputs;
        if notes_ui.is_some() {
            return Err(runtime_refused("phase Circuit profile forbids Notes UI"));
        }
        let PrimaryInputs::Android { server, environment, payload, deadline } = primary else {
            return Err(runtime_refused("phase requires the actual Android Primary"));
        };
        let app_server = stop.original_app_server_custody(&context)?;
        config.attach_original_app_server_custody(Arc::clone(&app_server))?;
        let mcp_custody = stop.original_mcp_custody(&context)?;
        let mut mcp: Option<codex_app_server::ConfiguredMcpRuntime> = None;
        let mut device: Option<Arc<crate::AgentdAndroidTextDevice>> = None;
        let mut attachment: Option<crate::AgentdRootProductionAttachment> = None;
        let result = async {
            let payload_json = inputs::read_payload(payload)?;
            let home = AbsolutePathBuf::from_absolute_path(&config.identity().home_root)
                .map_err(|error| AgentdError::Invalid(error.to_string()))?;
            let workspace = AbsolutePathBuf::from_absolute_path(&config.identity().workspace)
                .map_err(|error| AgentdError::Invalid(error.to_string()))?;
            let original = codex_app_server::initialize_configured_mcp_server_with_owned_shutdown(
                home, workspace, arg0_paths.clone(), &server, &environment,
                (remaining(deadline)?, context.gate().deadline().instant()), &mcp_custody,
            ).await.map_err(|error| {
                AgentdError::Protocol(format!("original Runtime MCP startup: {error}"))
            })?;
            mcp = Some(original);
            let original = mcp.as_ref().ok_or_else(|| {
                AgentdError::Protocol("original MCP startup handle disappeared".into())
            })?;
            let android = AgentdAndroidRuntimeInputs::from_mcp_binding(
                original.binding(), &server, &environment, tokio::runtime::Handle::current(),
                payload_json, deadline,
            ).await?;
            let (target, actual_device) = crate::prepare_android_runtime_target(android)?;
            device = Some(actual_device);
            let target: Arc<dyn FinalUseProductionOutboxTarget> = target;
            attachment = Some(crate::attach_root_production_operation_host_with_startup(
                &mut config, self.root, target, notes, Duration::from_millis(100), None,
            ).await?);
            remaining(deadline)?;
            OriginalSameActorRootContext::require_current(&context)?;
            // This exact original Runtime still owns ordinary readiness,
            // signed ingress, reconciliation and all original shutdown rules.
            crate::run_with_shutdown(config, arg0_paths, stop.wait_original_shutdown()).await?;
            let joined = codex_app_server::OriginalAppServerOwnerCustody::join_original_app_server(&app_server).await.map_err(|error| {
                AgentdError::Protocol(format!("original App Server owners did not join: {error}"))
            })?;
            codex_app_server::OriginalAppServerJoined::require_original_custody(&joined, &app_server).map_err(|error| {
                AgentdError::Protocol(format!("original App Server joined custody: {error}"))
            })?;
            context.gate().require_open()?;
            crate::root_observation_stream::check_lifetime(&root_pidfd)
                .map_err(|error| AgentdError::Protocol(format!("original stopped Root lifetime: {error}")))?;
            Ok::<_, AgentdError>(joined)
        }.await;
        let app_server_joined = match result {
            Ok(joined) => joined,
            Err(error) => {
            context.gate().close();
            codex_app_server::OriginalAppServerOwnerCustody::request_stop(&app_server);
            if let Err(cleanup) = codex_app_server::OriginalAppServerOwnerCustody::join_original_app_server(&app_server).await {
                tracing::error!(error = %cleanup, "original App Server cleanup also failed");
            }
            drop(attachment.take());
            if let Some(device) = device.take() { device.invalidate(); }
            if let Some(mcp) = mcp.take() {
                if let Err(cleanup) = codex_app_server::ConfiguredMcpRuntime::shutdown_original_owned(mcp).await {
                    tracing::error!(error = %cleanup, "original Runtime MCP cleanup also failed");
                }
            }
            return Err(error);
            }
        };
        let stopped = OriginalSameActorRuntimeStopped {
            context, root_pidfd, attachment, device, mcp, app_server, app_server_joined,
            closing: CloseSameActorPhaseOnDrop::new(&gate),
        };
        stopped.require_original_origin(&identity, &gate)?;
        closing.disarm();
        Ok(stopped)
    }
}

fn runtime_refused(message: &str) -> AgentdError {
    AgentdError::GenerationFenced(message.into())
}
