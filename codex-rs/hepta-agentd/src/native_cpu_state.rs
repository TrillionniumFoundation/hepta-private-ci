//! Explicit native CPU readiness over the original registered Agentd state.
use super::*;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdResponse;

impl AgentdState<NativeCpuRuntimeOwners> {
    pub(crate) fn check_native_cpu_authority(&self) -> Result<(), AgentdError> {
        let root = self.native_cpu_root.get().ok_or_else(|| {
            AgentdError::Invalid("native CPU owner has no original Root session".into())
        })?;
        let host = self.production_operations.get().ok_or_else(|| {
            AgentdError::Invalid("native CPU owner has no recovered original writer".into())
        })?;
        let writer = host.writer();
        if writer.authority() != &root.authority()
            || writer.owner_agent_id() != &self.identity.agent_id
            || host.spawn_generation() != self.identity.spawn_generation
            || host.destination_count() != 1
            || writer.checkpoint_fenced()
            || !host.has_destination(codex_hepta_memory::HOS2_DESTINATION_V1)
        {
            return Err(AgentdError::GenerationFenced(
                "native CPU original owner is fenced".into(),
            ));
        }
        root.verifier()
            .verify_sender_process_binding(
                writer.authority(),
                &self.identity.agent_id,
                writer.lease_id(),
                writer.generation(),
                self.identity.spawn_generation,
            )
            .map_err(AgentdError::GenerationFenced)
    }

    pub(crate) fn native_cpu_admission_open(&self) -> Result<bool, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        Ok(runtime.lifecycle == AgentLifecycle::Running
            && runtime.native_cpu_ready
            && runtime.admission_open
            && !runtime.fenced)
    }

    pub(crate) fn require_native_cpu_admission(&self) -> Result<(), AgentdError> {
        self.check_native_cpu_authority()?;
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.lifecycle != AgentLifecycle::Running
            || !runtime.native_cpu_ready
            || !runtime.admission_open
            || runtime.fenced
        {
            return Err(AgentdError::GenerationFenced(
                "native CPU owner is not admitting work".into(),
            ));
        }
        Ok(())
    }

    async fn request_native_cpu_drain(
        &self,
    ) -> Result<codex_hepta_agent_protocol::DrainSnapshot, AgentdError> {
        self.refresh_generation()?;
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            if runtime.lifecycle != AgentLifecycle::Draining || runtime.fenced {
                return Err(AgentdError::GenerationFenced(
                    "native drain requires the original Supervisor Draining generation".into(),
                ));
            }
        }
        let ingress = self
            .native_cpu_ingress
            .get()
            .ok_or_else(|| AgentdError::Invalid("native admission gate missing".into()))?;
        ingress.close();
        self.mark_draining()?;
        let host = self
            .production_operations
            .get()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        self.drain_snapshot(ingress.blockers(host).await?)
    }

    pub(crate) fn mark_native_cpu_ready(&self) -> Result<(), AgentdError> {
        self.check_native_cpu_authority()?;
        self.refresh_generation()?;
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        if !runtime.critical_stores_ready || runtime.fenced {
            return Err(AgentdError::GenerationFenced(
                "native CPU prerequisites are unavailable".into(),
            ));
        }
        runtime.native_cpu_ready = true;
        runtime.required_ports_ready = true;
        runtime.admission_open = runtime.lifecycle == AgentLifecycle::Running;
        Ok(())
    }

    pub(crate) async fn native_cpu_response(
        &self,
        request_id: u64,
        spawn_generation: u64,
        method: AgentdMethod,
    ) -> Result<AgentdResponse, AgentdError> {
        if spawn_generation != self.identity.spawn_generation {
            return Err(AgentdError::GenerationFenced(
                "native CPU request belongs to another process generation".into(),
            ));
        }
        self.check_native_cpu_authority()?;
        self.refresh_generation()?;
        let (generation, lifecycle, ready, critical, revocation, ports, admission, fenced) = {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            (
                runtime.current_generation,
                runtime.lifecycle,
                runtime.native_cpu_ready,
                runtime.critical_stores_ready,
                runtime.revocation_ready,
                runtime.required_ports_ready,
                runtime.admission_open,
                runtime.fenced,
            )
        };
        let payload = match method {
            AgentdMethod::Capabilities => AgentdPayload::Capabilities(
                crate::AgentdCapabilitySet::new(vec![
                    crate::AgentdCapability::new(
                        "hepta.native.cpu.owner",
                        /*major*/ 1,
                        /*minor*/ 0,
                    )
                    .map_err(AgentdError::Protocol)?,
                ])
                .map_err(AgentdError::Protocol)?,
            ),
            AgentdMethod::Health => AgentdPayload::Health(crate::HealthSnapshot {
                promotion_ready: matches!(
                    lifecycle,
                    AgentLifecycle::Starting | AgentLifecycle::Running
                ) && ready
                    && critical
                    && revocation
                    && ports
                    && !fenced,
                ready: lifecycle == AgentLifecycle::Running
                    && ready
                    && critical
                    && revocation
                    && ports
                    && admission
                    && !fenced,
                fenced,
                lifecycle,
                process_id: std::process::id(),
                workspace: self.identity.workspace.clone(),
                home_root: self.identity.home_root.clone(),
                run_root: self.identity.run_root.clone(),
            }),
            AgentdMethod::Lifecycle => AgentdPayload::Lifecycle(crate::LifecycleSnapshot {
                lifecycle,
                app_server_ready: false,
                fenced,
            }),
            AgentdMethod::Readiness => AgentdPayload::Readiness(crate::ReadinessSnapshot {
                critical_stores_ready: critical,
                revocation_ready: revocation,
                required_ports_ready: ports,
                admission_open: admission,
            }),
            AgentdMethod::Drain => AgentdPayload::Drain(self.request_native_cpu_drain().await?),
            _ => {
                return Err(AgentdError::Invalid(
                    "method is outside the native CPU lifecycle profile".into(),
                ));
            }
        };
        self.check_native_cpu_authority()?;
        Ok(AgentdResponse {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            agent_id: self.identity.agent_id.clone(),
            spawn_generation: self.identity.spawn_generation,
            current_generation: generation,
            payload,
        })
    }
}
