//! Reconcile one actually failed native activation through the original owners.
//! An original Supervisor Failed transition is observed, never manufactured.

use super::*;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_supervisor::ProcessDriverError;
use std::os::fd::BorrowedFd;

#[path = "native_cpu_reentry_cut.rs"]
mod cut;
#[path = "native_cpu_reentry_fault.rs"]
mod fault;
pub(super) use fault::FailurePoint;

pub(super) struct PendingActivation {
    pub(super) spec: SpawnSpec,
    pub(super) peer: CognitiveCheckpointPeerLifetime,
    pub(super) server: Option<std::thread::JoinHandle<io::Result<()>>>,
    pub(super) fault: Option<FailurePoint>,
    pub(super) fault_observation: Option<serde_json::Value>,
}

impl Installation {
    pub(super) fn activate_image(
        &mut self,
        spec: &SpawnSpec,
        image: OwnerImage,
        owner: OwnedFd,
        deadline: u64,
    ) -> io::Result<Active> {
        if self.activation.is_some() {
            return Err(invalid(
                "previous actual activation has not been reconciled",
            ));
        }
        // This capture precedes every authority mutation. The original driver
        // retains its own child guard throughout this callback and kills/reaps
        // that exact child if any subsequent original owner operation fails.
        let peer = peer(image.pid, 60001)?;
        let retained = crate::RetainedCheckpointPublisher::capture(peer.clone()).map_err(error)?;
        self.activation = Some(PendingActivation {
            spec: spec.clone(),
            peer,
            server: None,
            fault: self.activation_fault.take(),
            fault_observation: None,
        });
        let result = self.activate_image_inner(spec, image, owner, deadline, retained);
        if result.is_ok() {
            self.activation = None;
        }
        result
    }

    fn retired_failed_activation(
        &mut self,
    ) -> io::Result<(
        crate::RetiredCheckpointPublisher,
        codex_hepta_fleet::AgentLifecycleState,
    )> {
        let failed = self
            .activation
            .as_mut()
            .ok_or_else(|| invalid("no actual failed activation was retained"))?;
        let record = self
            .fleet
            .load()
            .map_err(error)?
            .agent(&failed.spec.agent_id)
            .cloned()
            .ok_or_else(|| invalid("original failed Agent absent"))?;
        if record.lifecycle.lifecycle != codex_hepta_fleet::AgentLifecycle::Failed
            || failed.spec.generation.checked_add(1) != Some(record.lifecycle.generation)
            || failed.spec.fleet_root.as_path() != self.fleet.layout().fleet_root().as_path()
            || failed.spec.workspace.as_path() != record.manifest.workspace.as_path()
            || failed.spec.run_root.as_path() != record.layout.run_root()
            || failed.spec.control_socket.as_path() != record.layout.agentd_control_socket()
        {
            return Err(invalid(
                "original Supervisor did not retain this failed activation",
            ));
        }
        let retired =
            crate::RetiredCheckpointPublisher::observe(failed.peer.clone()).map_err(error)?;
        if let Some(server) = failed.server.take() {
            let result = server
                .join()
                .map_err(|_| invalid("failed original lane panicked"))?;
            if let Err(failure) = result {
                let diagnostic = failure.to_string().chars().take(512).collect::<String>();
                eprintln!(
                    "hepta-native: actual failed publisher {} lane termination: {diagnostic}",
                    failed.peer.pid
                );
            }
        }
        Ok((retired, record.lifecycle))
    }
}

/// A failed start is eligible for a different actual Process only after a
/// complete explicit original-owner reconciliation. A bounded repeated failure
/// remains an error; it is never converted to a healthy or drained receipt.
pub(super) fn start<F>(
    evidence: &mut evidence::Evidence,
    installation: &Arc<Mutex<Installation>>,
    active: &Arc<Mutex<Option<Active>>>,
    supervisor: &mut Supervisor<KernelInitialProcessDriver<F>>,
    agent: &AgentId,
    deadline: u64,
) -> io::Result<()>
where
    F: for<'fd> FnMut(
        &SpawnSpec,
        KernelInitialRole,
        BorrowedFd<'fd>,
    ) -> Result<(), ProcessDriverError>,
{
    const MAX_RECONCILED_FAILURES: usize = 2;
    for attempt in 0..=MAX_RECONCILED_FAILURES {
        remaining(deadline)?;
        let command = AgentCommand::new("/test/hepta-g2-owner", Vec::new()).map_err(error)?;
        let failure = match supervisor.start(agent, command, Instant::now()) {
            Ok(()) => return Ok(()),
            Err(failure) => failure,
        };
        let snapshot = supervisor
            .snapshot(agent)
            .ok_or_else(|| invalid("failed original Supervisor snapshot absent"))?;
        if attempt == MAX_RECONCILED_FAILURES
            || snapshot.active
            || snapshot.healthy
            || snapshot.runtime_generation.is_some()
            || snapshot.spawn_generation.is_some()
            || snapshot.process_system_id.is_some()
            || active.lock().map_err(error)?.is_some()
        {
            return Err(io::Error::other(format!(
                "native original start failed: {failure}"
            )));
        }
        let mut retained = installation.lock().map_err(error)?;
        if retained.activation.is_none() {
            return Err(io::Error::other(format!(
                "native start failed before an activation was captured: {failure}"
            )));
        }
        let observation = retained.prepare_failed_activation(deadline).map_err(|reconcile| {
            io::Error::new(reconcile.kind(), format!(
                "native original start failed ({failure}); explicit owner reconciliation failed: {reconcile}"
            ))
        })?;
        evidence.emit("activation_recovery_prepared", serde_json::json!({
            "failure":failure.to_string(), "reconciliation":observation,
            "supervisor":{"active":snapshot.active,"healthy":snapshot.healthy,
                "runtime_generation":snapshot.runtime_generation,"spawn_generation":snapshot.spawn_generation,
                "process_system_id":snapshot.process_system_id}
        }))?;
    }
    Err(invalid("native activation reconciliation bound reached"))
}
