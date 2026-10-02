//! Companion recovery keeps pure diagnostics separate from exact-owner
//! containment. Denial cannot grant serving metadata or hide a binding fault.

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_matrix_protocol::matrix_binding_digest;

use crate::AgentRelease;
use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::lease::MatrixProcessLease;
use crate::runtime::AgentSlot;
use crate::runtime::bounded_message;
use crate::runtime::driver_error;

impl<D: ProcessDriver> Supervisor<D> {
    pub(super) fn contain_denied_matrix_owner(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        lease: &MatrixProcessLease,
    ) -> Result<(), SupervisorError> {
        // Complete independent pure checks before the one containment attempt.
        // Extra failures remain bounded diagnostics, never another signal.
        let mut faults = assess_denied(&self.registry, agent_id, record, slot, lease).into_iter();
        let fault = faults.next();
        for error in faults {
            slot.event(
                record.lifecycle.generation,
                SupervisorEventKind::DriverFault(bounded_message(error.to_string())),
            );
        }
        let termination = self.kill_matrix_now(agent_id, slot);
        if let Some(error) = fault {
            if let Err(signal) = termination {
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::DriverFault(bounded_message(signal.to_string())),
                );
            }
            return Err(error);
        }
        termination
    }
}

fn assess_denied<P: ManagedProcess>(
    registry: &FleetRegistry,
    agent_id: &AgentId,
    record: &AgentRecord,
    slot: &AgentSlot<P>,
    lease: &MatrixProcessLease,
) -> Vec<SupervisorError> {
    let initialization = match slot
        .matrix
        .runtime
        .as_ref()
        .and_then(|runtime| runtime.process.initialization_failure().map(str::to_owned))
    {
        Some(error) => Err(driver_error(agent_id, ProcessDriverError::new(error))),
        None => Ok(()),
    };
    let binding = validate_binding(record, agent_id, lease);
    let catalog = registry
        .resolve_release(agent_id, &lease.release_id)
        .map_err(SupervisorError::from)
        .and_then(AgentRelease::try_from)
        .and_then(|release| {
            if release.release_id() != &lease.release_id
                || release.matrixd_command().is_none()
                || slot
                    .runtime
                    .as_ref()
                    .is_some_and(|runtime| runtime.release_id != lease.release_id)
            {
                return Err(SupervisorError::CorruptLease(
                    "Matrix lease release is not the active companion bundle".to_string(),
                ));
            }
            Ok(())
        });
    [initialization, binding, catalog]
        .into_iter()
        .filter_map(Result::err)
        .collect()
}

pub(super) fn validate_binding(
    record: &AgentRecord,
    agent_id: &AgentId,
    lease: &MatrixProcessLease,
) -> Result<(), SupervisorError> {
    let binding = super::load_binding(record, agent_id)?.ok_or_else(|| {
        SupervisorError::CorruptLease("Matrix lease exists without a public binding".to_string())
    })?;
    if binding.revision != lease.binding_revision {
        return Err(SupervisorError::CorruptLease(
            "Matrix lease binding revision is stale".to_string(),
        ));
    }
    let digest = matrix_binding_digest(&binding)
        .map_err(|error| SupervisorError::CorruptLease(error.to_string()))?;
    if digest != lease.binding_digest {
        return Err(SupervisorError::CorruptLease(
            "Matrix lease binding digest is stale".to_string(),
        ));
    }
    Ok(())
}
