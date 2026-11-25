use super::*;

// The original health/drain protocol is shared by ordinary spawned children
// and kernel-initial children. Only the process custody mechanism differs.
#[cfg(target_os = "linux")]
impl UnixManagedProcess {
    pub(crate) fn from_kernel_initial_spawn(
        spec: &SpawnSpec,
        child: crate::kernel_initial::KernelInitialChild,
    ) -> Result<Self, ProcessDriverError> {
        Self::from_kernel_initial(
            AgentHealthProbeIdentity::from_spawn(spec, child.pid()),
            child,
        )
    }

    pub(crate) fn from_kernel_initial_adoption(
        spec: &AdoptSpec,
        child: crate::kernel_initial::KernelInitialChild,
    ) -> Result<Self, ProcessDriverError> {
        Self::from_kernel_initial(
            AgentHealthProbeIdentity::from_adopt(spec, child.pid()),
            child,
        )
    }

    fn from_kernel_initial(
        agent_control: AgentHealthProbeIdentity,
        child: crate::kernel_initial::KernelInitialChild,
    ) -> Result<Self, ProcessDriverError> {
        let health_probe = HealthProbe::spawn(HealthProbeIdentity::Agentd(agent_control.clone()))?;
        let (_sender, logs) = std::sync::mpsc::sync_channel(1);
        Ok(Self {
            handle: UnixProcessHandle::KernelInitial(child),
            logs,
            health_probe,
            agent_control: Some(agent_control),
            drain_requested: false,
            next_drain_request_id: 1,
        })
    }
}

#[cfg(target_os = "linux")]
pub(crate) fn prove_kernel_initial_adoption(spec: &AdoptSpec, process_id: u32) -> bool {
    prove_adoption_identity(&HealthProbeIdentity::Agentd(
        AgentHealthProbeIdentity::from_adopt(spec, process_id),
    ))
}
